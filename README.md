# generate_startercode

Automatic generation of startercode and solution branches from a shared main branch.

This repository is now structured as a uv project, includes tests, and uses GitHub Actions for pre-commit, tests, and automatic releases with Semantic Release.

## Installation (uv)

1. Install uv: https://docs.astral.sh/uv/
2. Install dependencies:

```bash
uv sync --extra dev
```

3. Optionally install pre-commit hooks:

```bash
uv run pre-commit install --install-hooks
```

## Local Usage

### transform.py

```bash
uv run python transform.py --target solution --repo-root /path/to/repo
uv run python transform.py --target startercode --repo-root /path/to/repo
```

### sync_issue.py

```bash
uv run python sync_issue.py
```

Note: sync_issue.py expects GitLab environment variables, especially GITLAB_TOKEN, CI_SERVER_URL, and CI_PROJECT_PATH.

## Download Latest Release Version

You can download the scripts from the latest GitHub release tag (instead of main):

```bash
LATEST_TAG=$(curl -fsSL https://api.github.com/repos/obcode/generate_startercode/releases/latest | python3 -c "import json,sys; print(json.load(sys.stdin)['tag_name'])")
export GENERATE_STARTERCODE_VERSION="${LATEST_TAG#v}"

curl -fsSL "https://raw.githubusercontent.com/obcode/generate_startercode/${LATEST_TAG}/transform.py" -o /tmp/transform.py
curl -fsSL "https://raw.githubusercontent.com/obcode/generate_startercode/${LATEST_TAG}/sync_issue.py" -o /tmp/sync_issue.py
```

## Replacement for Existing GitLab CI Usage

If your GitLab project currently downloads directly from main, replace that with a download from the latest GitHub release tag.

The following .gitlab-ci configuration is a direct replacement for your previous flow:

```yaml
# -- Sync issue ------------------------------------------------
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

# -- Generate branches -----------------------------------------
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

Note: At least one GitHub release must exist. The additional environment variable GENERATE_STARTERCODE_VERSION ensures that the downloaded standalone script reports the correct release version even without a local pyproject. If no release exists yet, initially load once from a fixed tag (for example v1.0.0) or temporarily from main.

## Configuration: .gitlab/ci/config.yml

The file `.gitlab/ci/config.yml` controls what is included per target (solution/startercode) in generated branches. Code transformations (SOLUTION_BEGIN/END markers) are defined directly in source code. This config only controls path removals, file patches, and postprocess commands.

### Complete Example

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

List of paths (files or directories) that are fully removed in the generated branch. Paths are relative to the repository root.

```yaml
solution:
  remove_paths:
    - Aufgabenstellung        # full directory
    - .gitlab/ci              # subdirectory
    - src/secret_tests.py     # single file
```

### patch_files

Allows line-based modifications for selected files in the generated branch. Currently supported operation: `remove_line_containing` - removes all lines containing the given substring.

```yaml
solution:
  patch_files:
    .gitlab-ci.yml:
      remove_line_containing:
        - ".gitlab/ci/teacher.yml"   # removes every line containing this string
        - "include:"
    README.md:
      remove_line_containing:
        - "SOLUTION_ONLY"
```

### postprocess_commands

Shell commands executed in the generated tree after all other transformations and before committing the branch. Useful for running formatters or linters after marker removal.

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

Note: `goimports` requires `go install golang.org/x/tools/cmd/goimports@latest` in the CI environment. If you only need formatting, `gofmt` is enough.

## GitHub Actions

### CI Workflow

File: .github/workflows/ci.yml

Runs on push to main and on pull requests:

- pre-commit on all files
- pytest test suite
- Semantic Release dry-run on pull requests (`--print`)
- Semantic Release on main, but only if pre-commit and tests succeed

### Release Workflow

File: .github/workflows/release.yml

Optional manual workflow (`workflow_dispatch`) for release experiments.

## Versioning Without Hardcoded Single Values

Scripts no longer read their version from a manually maintained fixed value.
Instead, the version is resolved from package metadata or pyproject.toml.
The version in pyproject.toml is managed by Semantic Release.

## Tests

Tests are located under tests/ and can be run locally with uv:

```bash
uv run pytest
```

## Pre-commit

The existing .pre-commit-config.yaml remains active and is executed in CI.

Run manually:

```bash
uv run pre-commit run --all-files
```
