# generate_startercode

Automatische Erzeugung von Startercode- und Solution-Branches aus einem gemeinsamen main-Branch.

Das Repository ist jetzt als uv-Projekt aufgebaut, enthält Tests und nutzt GitHub Actions fuer pre-commit, Tests und automatische Releases mit Semantic Release.

## Installation (uv)

1. uv installieren: https://docs.astral.sh/uv/
2. Abhaengigkeiten installieren:

```bash
uv sync --extra dev
```

3. Optional pre-commit Hooks installieren:

```bash
uv run pre-commit install --install-hooks
```

## Lokale Nutzung

### transform.py

```bash
uv run python transform.py --target solution --repo-root /pfad/zum/repo
uv run python transform.py --target startercode --repo-root /pfad/zum/repo
```

### sync_issue.py

```bash
uv run python sync_issue.py
```

Hinweis: Fuer sync_issue.py werden die GitLab-Umgebungsvariablen erwartet, insbesondere GITLAB_TOKEN, CI_SERVER_URL und CI_PROJECT_PATH.

## Neueste Release-Version herunterladen

Die Skripte koennen aus dem neuesten GitHub Release-Tag geladen werden (statt von main):

```bash
LATEST_TAG=$(curl -fsSL https://api.github.com/repos/obcode/generate_startercode/releases/latest | python3 -c "import json,sys; print(json.load(sys.stdin)['tag_name'])")
export GENERATE_STARTERCODE_VERSION="${LATEST_TAG#v}"

curl -fsSL "https://raw.githubusercontent.com/obcode/generate_startercode/${LATEST_TAG}/transform.py" -o /tmp/transform.py
curl -fsSL "https://raw.githubusercontent.com/obcode/generate_startercode/${LATEST_TAG}/sync_issue.py" -o /tmp/sync_issue.py
```

## Ersatz fuer bestehende GitLab CI Nutzung

Wenn du bisher in deinem GitLab-Projekt direkt von main geladen hast, ersetze das durch einen Download aus dem neuesten GitHub Release-Tag.

Die folgende .gitlab-ci Konfiguration ist der direkte Ersatz fuer deinen bisherigen Flow:

```yaml
# ── Issue syncen ──────────────────────────────────────────────
sync-issue:
  stage: sync
  image: ${CI_DEPENDENCY_PROXY_DIRECT_GROUP_IMAGE_PREFIX}/library/python:3.12-bookworm
  script:
    - set -eu
    - pip install "python-gitlab[graphql]" --quiet
    - LATEST_TAG=$(curl -fsSL https://api.github.com/repos/obcode/generate_startercode/releases/latest | python3 -c "import json,sys; print(json.load(sys.stdin)['tag_name'])")
    - export GENERATE_STARTERCODE_VERSION="${LATEST_TAG#v}"
    - echo "[sync-issue] Using release ${LATEST_TAG}"
    - curl -fsSL "https://raw.githubusercontent.com/obcode/generate_startercode/${LATEST_TAG}/sync_issue.py" -o /tmp/sync_issue.py
    - python /tmp/sync_issue.py
  rules:
    - if: '$CI_COMMIT_BRANCH == "main"'
      changes:
        - Aufgabenstellung/*
        - .gitlab/ci/teacher.yml
        - .gitlab-ci.yml

# ── Branches generieren ───────────────────────────────────────
publish-branches:
  stage: publish
  image: ${CI_DEPENDENCY_PROXY_DIRECT_GROUP_IMAGE_PREFIX}/library/python:3.12-bookworm
  before_script:
    - set -eu
    - pip install pyyaml --quiet
    - git config user.email "ci@gitlab"
    - git config user.name "CI"
    - git remote set-url origin "https://oauth2:${GITLAB_TOKEN}@${CI_SERVER_HOST}/${CI_PROJECT_PATH}.git"
  script:
    - LATEST_TAG=$(curl -fsSL https://api.github.com/repos/obcode/generate_startercode/releases/latest | python3 -c "import json,sys; print(json.load(sys.stdin)['tag_name'])")
    - export GENERATE_STARTERCODE_VERSION="${LATEST_TAG#v}"
    - echo "[publish-branches] Download transform.py from release ${LATEST_TAG}"
    - curl -fsSL "https://raw.githubusercontent.com/obcode/generate_startercode/${LATEST_TAG}/transform.py" -o /tmp/transform.py
    - echo "[publish-branches] Run target=solution"
    - python /tmp/transform.py --target solution --repo-root "$CI_PROJECT_DIR" --config .gitlab/ci/config.yml --no-skip-ci
    - echo "[publish-branches] Run target=startercode"
    - python /tmp/transform.py --target startercode --repo-root "$CI_PROJECT_DIR" --config .gitlab/ci/config.yml --no-skip-ci
  rules:
    - if: '$CI_COMMIT_BRANCH == "main"'
      changes:
        - "src/**/*.py"
        - "tests/**/*.py"
        - "src/**/*.go"
        - .gitlab/ci/config.yml
        - .gitlab/ci/teacher.yml
        - .gitlab-ci.yml
```

Hinweis: Dafuer muss mindestens ein GitHub Release vorhanden sein. Die zusaetzliche Umgebungsvariable GENERATE_STARTERCODE_VERSION sorgt dafuer, dass das heruntergeladene Einzel-Skript auch ohne lokales pyproject die richtige Release-Version anzeigt. Falls noch kein Release existiert, initial einmalig gegen einen festen Tag laden (zum Beispiel v1.0.0) oder kurzzeitig gegen main.

## Konfiguration: .gitlab/ci/config.yml

Die Datei `.gitlab/ci/config.yml` steuert, was pro Target (solution/startercode) in den generierten Branch uebernommen wird. Code-Transformationen (SOLUTION_BEGIN/END-Marker) sind direkt im Quellcode definiert – hier werden nur Pfad-Entfernungen, Datei-Patches und Post-Process-Kommandos konfiguriert.

### Vollstaendiges Beispiel

```yaml
# .gitlab/ci/config.yml

solution:
  remove_paths:
    - Aufgabenstellung
    - .gitlab/ci
  patch_files:
    .gitlab-ci.yml:
      remove_line_containing:
        - ".gitlab/ci/teacher.yml"
        - "include:"
  postprocess_commands:
    - uvx ruff check --select I --fix .
    - uvx ruff format .

startercode:
  remove_paths:
    - Aufgabenstellung
    - .gitlab/ci
  patch_files:
    .gitlab-ci.yml:
      remove_line_containing:
        - ".gitlab/ci/teacher.yml"
        - "include:"
  postprocess_commands:
    - uvx ruff check --select I --fix .
    - uvx ruff format .
```

### remove_paths

Liste von Pfaden (Dateien oder Verzeichnisse), die im generierten Branch komplett entfernt werden. Pfade sind relativ zum Repository-Root.

```yaml
solution:
  remove_paths:
    - Aufgabenstellung        # ganzes Verzeichnis
    - .gitlab/ci              # Unterverzeichnis
    - src/secret_tests.py     # einzelne Datei
```

### patch_files

Ermoeglicht es, einzelne Dateien im generierten Branch zeilenweise zu veraendern. Aktuell unterstuetzte Operation: `remove_line_containing` – entfernt alle Zeilen, die den angegebenen Teilstring enthalten.

```yaml
solution:
  patch_files:
    .gitlab-ci.yml:
      remove_line_containing:
        - ".gitlab/ci/teacher.yml"   # entfernt jede Zeile, die diesen String enthaelt
        - "include:"
    README.md:
      remove_line_containing:
        - "SOLUTION_ONLY"
```

### postprocess_commands

Shell-Kommandos, die nach allen anderen Transformationen im generierten Tree ausgefuehrt werden, bevor der Branch committed wird. Nuetzlich, um Formatter oder Linter nach der Marker-Entfernung auszufuehren.

**Python/Ruff:**

```yaml
solution:
  postprocess_commands:
    - uvx ruff check --select I --fix .
    - uvx ruff format .
```

**Go:**

```yaml
solution:
  postprocess_commands:
    - find . -name "*.go" -exec goimports -w {} +
    - gofmt -w .
```

Hinweis: `goimports` benoetigt `go install golang.org/x/tools/cmd/goimports@latest` in der CI-Umgebung. Falls nur Formatierung benoetigt wird, reicht `gofmt`.

## GitHub Actions

### CI Workflow

Datei: .github/workflows/ci.yml

Fuehrt bei Push auf main und bei Pull Requests aus:

- pre-commit auf allen Dateien
- pytest Testsuite
- Semantic Release Dry-Run bei Pull Requests (`--print`)
- Semantic Release auf main, aber nur wenn pre-commit und Tests erfolgreich sind

### Release Workflow

Datei: .github/workflows/release.yml

Optionaler manueller Workflow (`workflow_dispatch`) fuer Release-Experimente.

## Versionierung ohne harte Einzelwerte

Die Skripte lesen ihre Version nicht mehr aus einem manuell gepflegten, festen Wert.
Stattdessen wird die Version aus den Paket-Metadaten bzw. aus pyproject.toml aufgeloest.
Die Version in pyproject.toml wird durch Semantic Release gepflegt.

## Tests

Die Tests liegen unter tests/ und koennen lokal mit uv ausgefuehrt werden:

```bash
uv run pytest
```

## Pre-commit

Die bestehende Datei .pre-commit-config.yaml bleibt aktiv und wird in CI ausgefuehrt.

Manuell ausfuehren:

```bash
uv run pre-commit run --all-files
```
