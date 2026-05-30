#!/usr/bin/env python3
"""Create or update assignment work items in the current project.

- One work item of type "Issue" titled "Assignment"
    from Aufgabenstellung/Aufgabe.md
- For each file Aufgabenstellung/TaskN.md a work item of type
    "Task" titled "Task N", linked as child item under "Assignment".
"""

import os
import re
import tomllib
from importlib.metadata import PackageNotFoundError, version as pkg_version
from pathlib import Path
from typing import Any

import gitlab  # type: ignore


VERSION_ENV_VAR = "GENERATE_STARTERCODE_VERSION"


def _resolve_version() -> str:
    """Resolve version from CI env var, package metadata, or pyproject.toml."""
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

ISSUE_TITLE = "Assignment"
BASE_DIR = "Aufgabenstellung"
MAIN_FILE = os.path.join(BASE_DIR, "Aufgabe.md")

GITLAB_URL = os.environ["CI_SERVER_URL"]
PROJECT_PATH = os.environ["CI_PROJECT_PATH"]


def dbg(msg: str) -> None:
    """Print a debug line to stdout (flushed immediately for CI logs)."""
    print(f"[DEBUG] {msg}", flush=True)


print("=" * 70, flush=True)
print(f"sync_issue.py v{__version__} started", flush=True)
print(f"  GITLAB_URL   : {GITLAB_URL}", flush=True)
print(f"  PROJECT_PATH : {PROJECT_PATH}", flush=True)
print(f"  BASE_DIR     : {os.path.abspath(BASE_DIR)}", flush=True)
print(f"  MAIN_FILE    : {os.path.abspath(MAIN_FILE)}", flush=True)
print("=" * 70, flush=True)

gq = gitlab.GraphQL(GITLAB_URL, token=os.environ["GITLAB_TOKEN"])
dbg("GraphQL client initialized")
dbg(f"python-gitlab version: {gitlab.__version__}")

GET_WORK_ITEM_TYPES = """
query GetWorkItemTypes($projectPath: ID!) {
  project(fullPath: $projectPath) {
    workItemTypes {
      nodes {
        id
        name
      }
    }
  }
}
"""

FIND_WORK_ITEM_BY_TITLE = """
query FindWorkItemByTitle($projectPath: ID!, $search: String!, $types: [IssueType!]) {
  project(fullPath: $projectPath) {
    workItems(search: $search, types: $types, in: [TITLE]) {
      nodes {
        id
        iid
        title
      }
    }
  }
}
"""

CREATE_WORK_ITEM = """
mutation CreateWorkItem(
  $projectPath: ID!,
  $typeId: WorkItemsTypeID!,
  $title: String!,
  $description: String!
) {
  workItemCreate(input: {
    projectPath: $projectPath,
    title: $title,
    workItemTypeId: $typeId,
    descriptionWidget: { description: $description }
  }) {
    workItem {
      id
      iid
      title
    }
    errors
  }
}
"""

CREATE_CHILD_TASK = """
mutation CreateChildTask(
  $projectPath: ID!,
  $typeId: WorkItemsTypeID!,
  $title: String!,
  $description: String!,
  $parentId: WorkItemID!
) {
  workItemCreate(input: {
    projectPath: $projectPath,
    title: $title,
    workItemTypeId: $typeId,
    descriptionWidget: { description: $description },
    hierarchyWidget: { parentId: $parentId }
  }) {
    workItem {
      id
      iid
      title
    }
    errors
  }
}
"""

UPDATE_WORK_ITEM_DESCRIPTION = """
mutation UpdateWorkItemDescription($id: WorkItemID!, $description: String!) {
  workItemUpdate(input: {
    id: $id,
    descriptionWidget: { description: $description }
  }) {
    workItem {
      id
      iid
      title
    }
    errors
  }
}
"""


def get_work_item_type_gids() -> dict[str, str]:
    """Fetch work item type GIDs from the project (name -> GID)."""
    dbg("Querying GET_WORK_ITEM_TYPES ...")
    data = gq.execute(
        GET_WORK_ITEM_TYPES,
        variable_values={"projectPath": PROJECT_PATH},
    )
    project = data.get("project")
    if not project or not project.get("workItemTypes"):
        raise RuntimeError("Failed to fetch work item types")
    nodes = project["workItemTypes"]["nodes"]
    mapping = {n["name"].upper(): n["id"] for n in nodes}
    dbg(f"Available work item types ({len(mapping)}):")
    for name, gid in sorted(mapping.items()):
        dbg(f"  {name:20s} -> {gid}")
    return mapping


def find_work_item_by_title(title: str, issue_type: str) -> dict[str, Any] | None:
    """Find a work item in this project by title and type.

    issue_type: "ISSUE" or "TASK"
    Returns a dict with id/iid/title or None.
    """
    dbg(f"Searching work item: title={title!r} type={issue_type}")
    variables = {
        "projectPath": PROJECT_PATH,
        "search": title,
        "types": [issue_type],
    }
    data = gq.execute(
        FIND_WORK_ITEM_BY_TITLE,
        variable_values=variables,
    )
    project = data.get("project")
    if not project or not project.get("workItems"):
        dbg("  -> No result (project or workItems missing in response)")
        return None

    nodes = project["workItems"]["nodes"]
    dbg(f"  -> {len(nodes)} GraphQL hit(s) (search for {title!r})")
    for n in nodes:
        dbg(f"     iid=#{n.get('iid')} id={n.get('id')} title={n.get('title')!r}")
    matches = [n for n in nodes if n.get("title") == title]
    dbg(f"  -> {len(matches)} exact match(es) after title check")

    if len(matches) > 1:
        raise RuntimeError(f"Found more than one work item with title {title!r}")

    if matches:
        dbg(f"  -> Found: iid=#{matches[0]['iid']} id={matches[0]['id']}")
    else:
        dbg("  -> Not found")
    return matches[0] if matches else None


def create_work_item(type_gid: str, title: str, description: str) -> dict[str, Any]:
    """Create a new work item (Issue, Task, ...) in this project."""
    dbg(f"CREATE_WORK_ITEM: title={title!r} typeId={type_gid}")
    variables = {
        "projectPath": PROJECT_PATH,
        "typeId": type_gid,
        "title": title,
        "description": description,
    }
    data = gq.execute(
        CREATE_WORK_ITEM,
        variable_values=variables,
    )
    result = data["workItemCreate"]
    errors = result.get("errors") or []
    if errors:
        dbg(f"  -> ERROR: {errors}")
        raise RuntimeError(f"Error creating work item {title!r}: {errors}")
    wi = result["workItem"]
    dbg(f"  -> Created: iid=#{wi['iid']} id={wi['id']}")
    return wi


def create_child_task(
    type_gid: str, title: str, description: str, parent_id: str
) -> dict[str, Any]:
    """Create a new task as child work item under parent_id."""
    dbg(f"CREATE_CHILD_TASK: title={title!r} typeId={type_gid} parentId={parent_id}")
    variables = {
        "projectPath": PROJECT_PATH,
        "typeId": type_gid,
        "title": title,
        "description": description,
        "parentId": parent_id,
    }
    data = gq.execute(
        CREATE_CHILD_TASK,
        variable_values=variables,
    )
    result = data["workItemCreate"]
    errors = result.get("errors") or []
    if errors:
        dbg(f"  -> ERROR: {errors}")
        raise RuntimeError(f"Error creating task {title!r}: {errors}")
    wi = result["workItem"]
    dbg(f"  -> Created: iid=#{wi['iid']} id={wi['id']}")
    return wi


def update_work_item_description(
    work_item_id: str, title: str, description: str
) -> dict[str, Any]:
    """Update the description of an existing work item."""
    dbg(f"UPDATE_WORK_ITEM_DESCRIPTION: title={title!r} id={work_item_id}")
    variables = {
        "id": work_item_id,
        "description": description,
    }
    data = gq.execute(
        UPDATE_WORK_ITEM_DESCRIPTION,
        variable_values=variables,
    )
    result = data["workItemUpdate"]
    errors = result.get("errors") or []
    if errors:
        dbg(f"  -> ERROR: {errors}")
        raise RuntimeError(f"Error updating work item {title!r}: {errors}")
    wi = result["workItem"]
    dbg(f"  -> Updated: iid=#{wi['iid']} id={wi['id']}")
    return wi


# ---------------------------------------------------------------------------
# Resolve work item types dynamically
# ---------------------------------------------------------------------------

print("\n--- Resolving work item types ---", flush=True)
_type_gids = get_work_item_type_gids()
ISSUE_TYPE_GID = _type_gids.get("ISSUE")
TASK_TYPE_GID = _type_gids.get("TASK")

dbg(f"ISSUE_TYPE_GID = {ISSUE_TYPE_GID}")
dbg(f"TASK_TYPE_GID  = {TASK_TYPE_GID}")

if not ISSUE_TYPE_GID:
    raise RuntimeError("Work item type 'Issue' not found in project")
if not TASK_TYPE_GID:
    raise RuntimeError("Work item type 'Task' not found in project")

# ---------------------------------------------------------------------------
# Upsert main work item "Assignment"
# ---------------------------------------------------------------------------

print("\n--- Main work item 'Assignment' ---", flush=True)
if os.path.exists(MAIN_FILE):
    with open(MAIN_FILE, encoding="utf-8") as f:
        main_description = f.read()
    dbg(f"Main file read: {MAIN_FILE} ({len(main_description)} chars)")
else:
    main_description = ""
    dbg(f"WARNING: main file not found: {MAIN_FILE} (empty description)")

existing_main = find_work_item_by_title(ISSUE_TITLE, "ISSUE")

if existing_main:
    dbg(f"Existing issue found (iid=#{existing_main['iid']}), updating")
    updated = update_work_item_description(
        existing_main["id"], ISSUE_TITLE, main_description
    )
    print(
        f"✓ Work item '{ISSUE_TITLE}' (ISSUE) #{updated['iid']} updated",
        flush=True,
    )
    main_work_item_id = updated["id"]
else:
    dbg("No existing issue found, creating new one")
    created = create_work_item(ISSUE_TYPE_GID, ISSUE_TITLE, main_description)
    print(f"✓ Work item '{ISSUE_TITLE}' (ISSUE) #{created['iid']} created", flush=True)
    main_work_item_id = created["id"]

dbg(f"main_work_item_id = {main_work_item_id}")

# ---------------------------------------------------------------------------
# Iterate over task files and upsert one task work item per file
# ---------------------------------------------------------------------------

print("\n--- Processing task files ---", flush=True)
if not os.path.isdir(BASE_DIR):
    print(f"WARNING: directory '{BASE_DIR}' not found, no tasks.", flush=True)
else:
    all_files = sorted(os.listdir(BASE_DIR))
    task_files = [
        f
        for f in all_files
        if f.lower().startswith("task") and f.lower().endswith(".md")
    ]
    other_files = [f for f in all_files if f not in task_files]
    dbg(f"Files in '{BASE_DIR}': {all_files}")
    dbg(f"  -> Task files ({len(task_files)}): {task_files}")
    dbg(f"  -> Skipped    ({len(other_files)}): {other_files}")

    for fname in sorted(os.listdir(BASE_DIR)):
        if not fname.lower().startswith("task") or not fname.lower().endswith(".md"):
            continue

        path = os.path.join(BASE_DIR, fname)
        with open(path, encoding="utf-8") as f:
            task_description = f.read()

        m = re.search(r"(\d+)", fname)
        task_title = f"Task {m.group(1)}" if m else os.path.splitext(fname)[0]

        print(f"\n  Processing: {fname} -> '{task_title}'", flush=True)
        dbg(f"  Description: {len(task_description)} chars")

        existing_task = find_work_item_by_title(task_title, "TASK")

        if existing_task:
            dbg(f"  Existing task found (iid=#{existing_task['iid']}), updating")
            updated_task = update_work_item_description(
                existing_task["id"], task_title, task_description
            )
            print(
                f"  ✓ Task '{task_title}' #{updated_task['iid']} updated",
                flush=True,
            )
        else:
            dbg("  No existing task found, creating new one")
            new_task = create_child_task(
                TASK_TYPE_GID, task_title, task_description, main_work_item_id
            )
            print(
                f"  ✓ Task '{task_title}' #{new_task['iid']} created"
                f" (child of '{ISSUE_TITLE}')",
                flush=True,
            )

print("\n" + "=" * 70, flush=True)
print("sync_issue.py finished", flush=True)
print("=" * 70, flush=True)
