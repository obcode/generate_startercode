#!/usr/bin/env python3
"""
Generiert solution- und startercode-Branches aus main.

Verwendung:
  python .gitlab/ci/transform.py --target solution
  python .gitlab/ci/transform.py --target startercode

Marker im Quellcode
-------------------
  # SOLUTION_BEGIN
  <Block>
  # SOLUTION_END
      → solution:    Block-Inhalt bleibt, Marker-Zeilen werden entfernt
      → startercode: Gesamter Block (inkl. Marker) wird entfernt

  # SOLUTION_BEGIN raise NotImplementedError
  <Block>
  # SOLUTION_END
      → solution:    Block-Inhalt bleibt, Marker-Zeilen werden entfernt
      → startercode: Block wird durch die angegebene Replacement-Zeile ersetzt

Unterstützte Kommentar-Präfixe: # (Python) und // (Go, Rust, …)
"""

import argparse
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import yaml  # type: ignore

ROOT = Path(__file__).resolve().parent.parent
CI_DIR = ROOT / ".gitlab" / "ci"

RX_BEGIN = re.compile(r"^(\s*)(?:#|//)\s*SOLUTION_BEGIN(?:\s+(.+?))?\s*$")
RX_END = re.compile(r"^\s*(?:#|//)\s*SOLUTION_END\s*$")

TEXT_SUFFIXES = {
    ".py",
    ".go",
    ".rs",
    ".js",
    ".ts",
    ".java",
    ".c",
    ".cpp",
    ".h",
    ".md",
    ".yml",
    ".yaml",
    ".toml",
    ".txt",
    ".sh",
    ".json",
    ".html",
    ".css",
    ".rst",
    ".tex",
}


def git_tracked_files() -> list[Path]:
    """Gibt alle von Git getrackten Dateien zurück (keine gitignorierten Dateien)."""
    result = subprocess.run(
        ["git", "ls-files", "--cached"],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    return [ROOT / p for p in result.stdout.splitlines() if p]


def transform_source(text: str, target: str) -> str:
    lines = text.splitlines(keepends=True)
    out: list[str] = []
    i = 0
    while i < len(lines):
        m = RX_BEGIN.match(lines[i])
        if m:
            indent = m.group(1)
            replacement = m.group(2)  # None wenn kein Replacement angegeben
            block: list[str] = []
            i += 1
            while i < len(lines) and not RX_END.match(lines[i]):
                block.append(lines[i])
                i += 1
            if i < len(lines):
                i += 1  # SOLUTION_END überspringen

            if target == "solution":
                out.extend(block)  # Inhalt behalten, Marker entfernt
            else:  # startercode
                if replacement is not None:
                    out.append(indent + replacement + "\n")
                # else: Block komplett entfernen
        else:
            out.append(lines[i])
            i += 1
    result = "".join(out)
    result = re.sub(
        r"\n{4,}", "\n\n\n", result
    )  # max. 3 aufeinanderfolgende Leerzeilen
    return result.lstrip("\n")


def apply_patch_files(patch_cfg: dict, root: Path) -> None:
    for rel_path, patches in patch_cfg.items():
        fpath = root / rel_path
        if not fpath.exists():
            continue
        text = fpath.read_text(encoding="utf-8")
        for pattern in patches.get("remove_line_containing", []):
            text = (
                "\n".join(line for line in text.splitlines() if pattern not in line)
                + "\n"
            )
        fpath.write_text(text, encoding="utf-8")


def _normalize_rel_path(path: str) -> str:
    """Normalisiert relative Pfade aus der Config für konsistente Vergleiche."""
    return Path(path.strip().rstrip("/")).as_posix()


def _is_removed(rel: Path, remove_paths: set[str]) -> bool:
    rel_posix = rel.as_posix()
    for raw in remove_paths:
        candidate = _normalize_rel_path(raw)
        if not candidate:
            continue
        if rel_posix == candidate or rel_posix.startswith(candidate + "/"):
            return True
    return False


def _git_config_value(key: str, cwd: Path) -> str | None:
    result = subprocess.run(
        ["git", "config", "--get", key],
        capture_output=True,
        text=True,
        cwd=cwd,
        check=False,
    )
    value = result.stdout.strip()
    return value or None


def _prepare_publish_repo(target: str) -> Path:
    repo_tmp = Path(tempfile.mkdtemp(prefix=f"transform_repo_{target}_"))
    origin_url = subprocess.run(
        ["git", "remote", "get-url", "origin"],
        capture_output=True,
        text=True,
        cwd=ROOT,
        check=True,
    ).stdout.strip()

    subprocess.run(["git", "clone", "--quiet", str(ROOT), str(repo_tmp)], check=True)
    subprocess.run(
        ["git", "remote", "set-url", "origin", origin_url],
        cwd=repo_tmp,
        check=True,
    )

    for key in ("user.email", "user.name"):
        value = _git_config_value(key, ROOT)
        if value is not None:
            subprocess.run(["git", "config", key, value], cwd=repo_tmp, check=True)

    return repo_tmp


def build(target: str, cfg: dict) -> None:
    tcfg = cfg.get(target, {})
    remove_paths = set(tcfg.get("remove_paths", []))

    # Nur git-tracked Dateien transformieren – gitignorierte Verzeichnisse
    # (.uv-cache, .venv, __pycache__ etc.) werden automatisch ausgelassen.
    tracked = git_tracked_files()

    # tmp-Verzeichnis AUSSERHALB des Repos → kein rekursives rglob-Problem
    tmp = Path(tempfile.mkdtemp(prefix=f"transform_{target}_"))
    try:
        for fpath in tracked:
            rel = fpath.relative_to(ROOT)
            # .gitlab/ci selbst nicht in den Branch kopieren
            if rel.parts[0:2] == (".gitlab", "ci"):
                continue
            if _is_removed(rel, remove_paths):
                continue
            dest = tmp / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            if fpath.suffix in TEXT_SUFFIXES:
                text = fpath.read_text(encoding="utf-8")
                dest.write_text(transform_source(text, target), encoding="utf-8")
            else:
                shutil.copy2(fpath, dest)

        apply_patch_files(tcfg.get("patch_files", {}), tmp)

        repo_tmp = _prepare_publish_repo(target)
        try:
            orphan = f"_gen_{target}"
            subprocess.run(
                ["git", "checkout", "--orphan", orphan],
                cwd=repo_tmp,
                check=True,
            )
            # Working Tree leeren, damit ausgeschlossene Pfade
            # nicht aus main "stehenbleiben".
            subprocess.run(
                ["git", "rm", "-rf", "."],
                cwd=repo_tmp,
                capture_output=True,
                check=True,
            )
            # Auch untracked Artefakte entfernen (z. B. aus vorherigen CI-Schritten).
            subprocess.run(
                ["git", "clean", "-fdx"],
                cwd=repo_tmp,
                capture_output=True,
                check=True,
            )

            for fpath in tmp.rglob("*"):
                if fpath.is_file():
                    rel = fpath.relative_to(tmp)
                    dest = repo_tmp / rel
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(fpath, dest)

            subprocess.run(["git", "add", "-A"], cwd=repo_tmp, check=True)
            subprocess.run(
                [
                    "git",
                    "commit",
                    "--allow-empty",
                    "-m",
                    f"chore: generate {target} [skip ci]",
                ],
                cwd=repo_tmp,
                check=True,
            )
            subprocess.run(
                ["git", "push", "origin", f"HEAD:{target}", "--force"],
                cwd=repo_tmp,
                check=True,
            )
        finally:
            shutil.rmtree(repo_tmp, ignore_errors=True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generiert solution/startercode-Branches."
    )
    parser.add_argument("--target", choices=["solution", "startercode"], required=True)
    args = parser.parse_args()

    cfg = yaml.safe_load((CI_DIR / "config.yml").read_text(encoding="utf-8"))
    build(args.target, cfg)
    print(f"✓ Branch '{args.target}' erfolgreich erzeugt und gepusht.")


if __name__ == "__main__":
    main()
