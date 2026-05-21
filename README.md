# generate_startercode

Automatische Erzeugung von **Startercode** und **Solution**-Branches aus einem gemeinsamen `main`-Branch für GitLab CI/CD.

## Zweck

Bei der Betreuung von Programmierblättern möchte man:

1. **Einen Branch mit Musterlösung** (`solution`) – mit vollständigem Code
2. **Einen Branch mit Startcode** (`startercode`) – mit Lücken/Platzhaltern für Studierende

Dieses Projekt enthält zwei Python-Scripts, die diese Branches **automatisch aus `main` erzeugen**:

- `transform.py`: Code-Transformation (Marker → Lücken/Platzhalter)
- `sync_issue.py`: Synchronisiert GitLab-Issues aus einer Markdown-Datei

---

## Quickstart

### 1. In deinem GitLab-Repo

Integriere die Scripts über GitLab CI in die Datei `.gitlab/ci/teacher.yml`:

```yaml
# .gitlab/ci/teacher.yml
# ── Issue syncen ──────────────────────────────────────────────
sync-issue:
  stage: sync
  image: python:3.12-bookworm
  script:
    - pip install "python-gitlab[graphql]" --quiet
    - curl -s https://github.com/obcode/generate_startercode/raw/refs/heads/main/sync_issue.py -o /tmp/sync_issue.py
    - python /tmp/sync_issue.py
  rules:
    - if: '$CI_COMMIT_BRANCH == "main"'
      changes:
        - Aufgabenstellung/*

# ── Branches generieren ───────────────────────────────────────
publish-branches:
  stage: publish
  image: python:3.12-bookworm
  before_script:
    - pip install pyyaml --quiet
    - git config user.email "ci@gitlab"
    - git config user.name "CI"
    - git remote set-url origin "https://oauth2:${GITLAB_TOKEN}@${CI_SERVER_HOST}/${CI_PROJECT_PATH}.git"
  script:
    - |
      curl -s https://github.com/obcode/generate_startercode/raw/refs/heads/main/transform.py -o /tmp/transform.py
      for TARGET in solution startercode; do
        python /tmp/transform.py --target "$TARGET"
      done
  rules:
    - if: '$CI_COMMIT_BRANCH == "main"'
      changes:
        - "src/**"
        - "tests/**"
```

### 1.1 Include in `.gitlab-ci.yml`

Damit `teacher.yml` überhaupt ausgeführt wird, muss es in deiner `.gitlab-ci.yml` eingebunden sein:

```yaml
include:
  - local: ".gitlab/ci/teacher.yml"
```

Hinweis: In den generierten Branches (`solution`/`startercode`) wird diese Include-Zeile durch `config.yml` wieder entfernt.

### 2. Konfigurationsdatei

Erstelle `.gitlab/ci/config.yml` im selben Verzeichnis:

```yaml
# .gitlab/ci/config.yml
solution:
  remove_paths:
    - Aufgabenstellung
    - .gitlab/ci
  patch_files:
    .gitlab-ci.yml:
      remove_line_containing:
        - "include:"
        - ".gitlab/ci/teacher.yml"

startercode:
  remove_paths:
    - Aufgabenstellung
    - .gitlab/ci
  patch_files:
    .gitlab-ci.yml:
      remove_line_containing:
        - "include:"
        - ".gitlab/ci/teacher.yml"
```

### 3. Marker im Code

Nutze Marker in deinem Quellcode, um festzulegen, was in `startercode` erscheint:

```python
def aufgabe(x: float) -> float:
    """Berechnet etwas."""
    # SOLUTION_BEGIN raise NotImplementedError
    return x * 2
    # SOLUTION_END
```

- **`solution`**: Code bleibt, Marker-Kommentare werden entfernt
- **`startercode`**: Code wird durch `raise NotImplementedError` ersetzt

### 4. Issues und Task-Hierarchie aus Markdown

Erstelle `Aufgabenstellung/Aufgabe.md`:

```markdown
# Aufgabenstellung

Implementiere eine Funktion, die ...
```

`sync_issue.py` erzeugt/aktualisiert daraus das Haupt-Work-Item **"Aufgabenstellung"** (Typ: Issue).

Zusätzlich kannst du Task-Dateien anlegen:

- `Aufgabenstellung/Task1.md`
- `Aufgabenstellung/Task2.md`
- ...

Für jede `TaskN.md` wird ein Work-Item **"Aufgabe N"** (Typ: Task) erzeugt oder aktualisiert und als **Child** unter das Haupt-Issue gehängt.

---

## Wie es funktioniert

### `transform.py`

**Input:** Ein Git-Repo (beliebige Sprachen) mit Marker-Kommentaren
**Output:** Zwei neue Branches (`solution`, `startercode`) mit transformiertem Code

Unterstützte Marker:
- `# SOLUTION_BEGIN` / `# SOLUTION_END` (Python)
- `// SOLUTION_BEGIN` / `// SOLUTION_END` (Go, Rust, JS, …)

Optionales Replacement:
- `# SOLUTION_BEGIN raise NotImplementedError` → startercode-Version wird durch den Text nach `BEGIN` ersetzt

### `sync_issue.py`

Liest `Aufgabenstellung/Aufgabe.md` und erzeugt/aktualisiert einen GitLab-Issue mit dem Inhalt.

Zusätzlich scannt das Script `Aufgabenstellung/TaskN.md`:

- Titel wird aus der Dateinummer gebildet: `Task3.md` -> `Aufgabe 3`
- Typ ist `Task`
- Der Task wird als Child unter dem Issue `Aufgabenstellung` verknüpft

Erfordert eine CI-Variable `GITLAB_TOKEN` mit Scope `api`.

---

## Marker-Syntax

### Beispiel 1: Block komplett entfernen

```python
# Imports, die Studierende selbst schreiben sollen
# SOLUTION_BEGIN
import numpy as np
from helper import calculate
# SOLUTION_END

# Diese Zeile bleibt in allen Branches
from dataclasses import dataclass
```

**Ergebnis:**
- **solution**: Alle Zeilen vorhanden, `SOLUTION_BEGIN/END` entfernt
- **startercode**: nur `from dataclasses import dataclass` bleibt

### Beispiel 2: Platzhalter einsetzen

```python
def quicksort(arr):
    """Sortiert ein Array."""
    # SOLUTION_BEGIN raise NotImplementedError
    if len(arr) <= 1:
        return arr
    pivot = arr[0]
    left = [x for x in arr[1:] if x < pivot]
    right = [x for x in arr[1:] if x >= pivot]
    return quicksort(left) + [pivot] + quicksort(right)
    # SOLUTION_END
```

**Ergebnis:**
- **solution**:
  ```python
  def quicksort(arr):
      """Sortiert ein Array."""
      if len(arr) <= 1:
          return arr
      pivot = arr[0]
      ...
  ```
- **startercode**:
  ```python
  def quicksort(arr):
      """Sortiert ein Array."""
      raise NotImplementedError
  ```

### Wichtig

- Marker dürfen **nicht verschachtelt** sein
- Replacement muss auf der **gleichen Zeile** wie `SOLUTION_BEGIN` stehen
- Führende Leerzeichen sind erlaubt (automatisch gemacht)

---

## Konfiguration: `.gitlab/ci/config.yml`

Auf **Pfad-Ebene** definieren, was entfernt/gepatcht werden soll:

```yaml
solution:
  remove_paths:
    - Aufgabenstellung          # Keine Aufgabe im Solution-Branch
    - .gitlab/ci                # Keine Lehrer-CI sichtbar
    - AUTHORING-WORKFLOW.md     # Nur intern relevant
  patch_files:
    .gitlab-ci.yml:
      remove_line_containing:
        - ".gitlab/ci/teacher.yml"
        - "include:"

startercode:
  # Identisch zu solution – nur unterschiedlich bei Bedarf
  remove_paths:
    - Aufgabenstellung
    - .gitlab/ci
    - AUTHORING-WORKFLOW.md
  patch_files:
    .gitlab-ci.yml:
      remove_line_containing:
        - ".gitlab/ci/teacher.yml"
        - "include:"
```

**Anpassung:** Nur ändern, wenn sich deine Repo-Struktur ändert. Code-Transformationen laufen über Marker im Quellcode.

---

## Einmaliges Setup

### 1. GitLab Access Token

1. GitLab → **Profile** → **Access Tokens**
2. Name: z.B. `CI_TOKEN`
3. Scope: `api` (schließt `write_repository` mit ein)
4. Ablauf: optional
5. Token kopieren

### 2. CI-Variable im Projekt

1. GitLab Projekt → **Settings → CI/CD → Variables**
2. **Add variable:**
   - Key: `GITLAB_TOKEN`
   - Value: Dein Token
   - ☑ **Protected** (Token läuft nur auf `main`)
   - ☑ **Masked** (Token erscheint nicht in Logs)

---

## Fehlerbehebung

| Problem | Ursache | Lösung |
|---|---|---|
| Block bleibt im startercode | Marker-Syntax falsch | `# SOLUTION_BEGIN` prüfen – kein Typo, Leerzeichen vor `#` OK |
| `publish-branches` schlägt fehl | `GITLAB_TOKEN` fehlt oder falscher Scope | Token mit Scope `api` als Protected+Masked Variable setzen |
| Zu viele Leerzeilen in Branches | `transform.py` kollabiert >3 Leerzeilen automatisch | Normales Verhalten – Dateien bleiben lesbar |
| Replacement wird ignoriert | Syntax falsch | `# SOLUTION_BEGIN raise NotImplementedError` – keine `:` nach `BEGIN` |
| Leeres `include:` in CI | `config.yml` entfernt nur eine Zeile | Beide `remove_line_containing`-Einträge hinzufügen |

---

## Verwendung in anderen Projekten

Diese Scripts sind **sprachenunabhängig** – sie funktionieren mit:

- Python (`.py`)
- Go (`.go`)
- Rust (`.rs`)
- JavaScript/TypeScript (`.js`, `.ts`)
- Java (`.java`)
- C/C++ (`.c`, `.cpp`, `.h`)
- und mehr (TextSuffixes in `transform.py`)

**Einfach anpassen:**
- Marker-Kommentare in der Sprache deines Projekts verwenden
- `.gitlab/ci/config.yml` auf deine Repo-Struktur abstimmen
- `transform.py` und `sync_issue.py` via curl laden

---

## Lizenz

Frei verfügbar. Nutze und modifiziere wie nötig.

---

## Kontakt / Feedback

Issues und PRs willkommen!
