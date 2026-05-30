#!/usr/bin/env python3
"""Generiert solution- und startercode-Branches aus main.

Verwendung:
    python .gitlab/ci/transform.py --target solution
    python .gitlab/ci/transform.py --target startercode
        python .gitlab/ci/transform.py --target startercode --config .gitlab/ci/config.yml
        python /tmp/transform.py --target startercode --repo-root /pfad/zum/repo

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
import os
import re
import shutil
import subprocess
import tempfile
import tomllib
from importlib.metadata import PackageNotFoundError, version as pkg_version
from pathlib import Path


VERSION_ENV_VAR = "GENERATE_STARTERCODE_VERSION"


def _resolve_version() -> str:
    """Liest die Version aus CI, Paket-Metadaten oder pyproject.toml."""
    env_version = os.environ.get(VERSION_ENV_VAR, "").strip()
    if env_version:
        return env_version.removeprefix("v")

    try:
        return pkg_version("generate-startercode")
    except PackageNotFoundError:
        pass

    pyproject = Path(__file__).resolve().parent / "pyproject.toml"
    if pyproject.exists():
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        return str(data.get("project", {}).get("version", "0.0.0"))
    return "0.0.0"


__version__ = _resolve_version()

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


def git_tracked_files(repo_root: Path) -> list[Path]:
    """Gibt alle von Git getrackten Dateien zurück (keine gitignorierten Dateien)."""
    result = subprocess.run(
        ["git", "ls-files", "--cached"],
        capture_output=True,
        text=True,
        cwd=repo_root,
    )
    return [repo_root / p for p in result.stdout.splitlines() if p]


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


def _prepare_publish_repo(target: str, repo_root: Path) -> Path:
    repo_tmp = Path(tempfile.mkdtemp(prefix=f"transform_repo_{target}_"))
    origin_url = subprocess.run(
        ["git", "remote", "get-url", "origin"],
        capture_output=True,
        text=True,
        cwd=repo_root,
        check=True,
    ).stdout.strip()

    subprocess.run(
        ["git", "clone", "--quiet", str(repo_root), str(repo_tmp)],
        check=True,
    )
    subprocess.run(
        ["git", "remote", "set-url", "origin", origin_url],
        cwd=repo_tmp,
        check=True,
    )

    for key in ("user.email", "user.name"):
        value = _git_config_value(key, repo_root)
        if value is not None:
            subprocess.run(["git", "config", key, value], cwd=repo_tmp, check=True)

    return repo_tmp


def build(target: str, cfg: dict, skip_ci: bool, repo_root: Path) -> None:
    tcfg = cfg.get(target, {})
    remove_paths = set(tcfg.get("remove_paths", []))

    # Nur git-tracked Dateien transformieren – gitignorierte Verzeichnisse
    # (.uv-cache, .venv, __pycache__ etc.) werden automatisch ausgelassen.
    tracked = git_tracked_files(repo_root)

    # tmp-Verzeichnis AUSSERHALB des Repos → kein rekursives rglob-Problem
    tmp = Path(tempfile.mkdtemp(prefix=f"transform_{target}_"))
    try:
        for fpath in tracked:
            rel = fpath.relative_to(repo_root)
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

        repo_tmp = _prepare_publish_repo(target, repo_root)
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
            commit_message = f"chore: generate {target}"
            if skip_ci:
                commit_message += " [skip ci]"
            subprocess.run(
                [
                    "git",
                    "commit",
                    "--allow-empty",
                    "-m",
                    commit_message,
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
    import yaml  # type: ignore

    parser = argparse.ArgumentParser(
        description="Generiert solution/startercode-Branches."
    )
    parser.add_argument(
        "--version", action="version", version=f"transform.py {__version__}"
    )
    parser.add_argument("--target", choices=["solution", "startercode"], required=True)
    parser.add_argument(
        "--repo-root",
        default=str(Path.cwd()),
        help="Pfad zum Repository-Root (Default: aktuelles Arbeitsverzeichnis).",
    )
    parser.add_argument(
        "--config",
        default=".gitlab/ci/config.yml",
        help="Pfad zur YAML-Konfiguration (Default: .gitlab/ci/config.yml).",
    )
    parser.add_argument(
        "--no-skip-ci",
        action="store_true",
        help="Fuegt kein '[skip ci]' zur Commit-Message hinzu.",
    )
    args = parser.parse_args()

    print(f"transform.py v{__version__} gestartet  target={args.target}", flush=True)
    repo_root = Path(args.repo_root).resolve()
    config_path = Path(args.config)
    if not config_path.is_absolute():
        config_path = repo_root / config_path
    cfg = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    build(args.target, cfg, skip_ci=not args.no_skip_ci, repo_root=repo_root)
    print(f"✓ Branch '{args.target}' erfolgreich erzeugt und gepusht.")


if __name__ == "__main__":
    main()
