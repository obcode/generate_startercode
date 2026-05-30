#!/usr/bin/env python3
"""Erstellt oder aktualisiert die Aufgaben-Work-Items im aktuellen Projekt.

- Ein Work Item vom Typ "Issue" mit Titel "Aufgabenstellung"
  aus Aufgabenstellung/Aufgabe.md
- Für jede Datei Aufgabenstellung/TaskN.md ein Work Item vom Typ
  "Task" mit Titel "Aufgabe N", als Child-Item unter "Aufgabenstellung".
"""

import os
import re
from typing import Any

import gitlab  # type: ignore

ISSUE_TITLE = "Aufgabenstellung"
BASE_DIR = "Aufgabenstellung"
MAIN_FILE = os.path.join(BASE_DIR, "Aufgabe.md")

GITLAB_URL = os.environ["CI_SERVER_URL"]
PROJECT_PATH = os.environ["CI_PROJECT_PATH"]

gq = gitlab.GraphQL(GITLAB_URL, token=os.environ["GITLAB_TOKEN"])

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
    """Holt die Work-Item-Typ-GIDs aus dem Projekt (Name -> GID)."""
    data = gq.execute(
        GET_WORK_ITEM_TYPES,
        variable_values={"projectPath": PROJECT_PATH},
    )
    project = data.get("project")
    if not project or not project.get("workItemTypes"):
        raise RuntimeError("Konnte Work-Item-Typen nicht abrufen")
    nodes = project["workItemTypes"]["nodes"]
    return {n["name"].upper(): n["id"] for n in nodes}


def find_work_item_by_title(title: str, issue_type: str) -> dict[str, Any] | None:
    """Sucht ein Work Item in diesem Projekt anhand des Titels und Typs.

    issue_type: "ISSUE" oder "TASK"
    Gibt ein Dict mit id/iid/title zurück oder None.
    """
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
        return None

    nodes = project["workItems"]["nodes"]
    matches = [n for n in nodes if n.get("title") == title]

    if len(matches) > 1:
        raise RuntimeError(f"Mehr als ein Work Item mit Titel {title!r} gefunden")

    return matches[0] if matches else None


def create_work_item(type_gid: str, title: str, description: str) -> dict[str, Any]:
    """Erzeugt ein neues Work Item (Issue, Task, ...) in diesem Projekt."""
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
        raise RuntimeError(f"Fehler beim Erstellen von Work Item {title!r}: {errors}")
    return result["workItem"]


def create_child_task(
    type_gid: str, title: str, description: str, parent_id: str
) -> dict[str, Any]:
    """Erzeugt einen neuen Task als Child-Work-Item unter parent_id."""
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
        raise RuntimeError(f"Fehler beim Erstellen von Task {title!r}: {errors}")
    return result["workItem"]


def update_work_item_description(
    work_item_id: str, title: str, description: str
) -> dict[str, Any]:
    """Aktualisiert die Beschreibung eines bestehenden Work Items."""
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
        raise RuntimeError(
            f"Fehler beim Aktualisieren von Work Item {title!r}: {errors}"
        )
    return result["workItem"]


# ---------------------------------------------------------------------------
# Work-Item-Typen dynamisch ermitteln
# ---------------------------------------------------------------------------

_type_gids = get_work_item_type_gids()
ISSUE_TYPE_GID = _type_gids.get("ISSUE")
TASK_TYPE_GID = _type_gids.get("TASK")

if not ISSUE_TYPE_GID:
    raise RuntimeError("Work-Item-Typ 'Issue' nicht im Projekt gefunden")
if not TASK_TYPE_GID:
    raise RuntimeError("Work-Item-Typ 'Task' nicht im Projekt gefunden")

# ---------------------------------------------------------------------------
# Haupt-Work-Item "Aufgabenstellung" upserten
# ---------------------------------------------------------------------------

if os.path.exists(MAIN_FILE):
    with open(MAIN_FILE, encoding="utf-8") as f:
        main_description = f.read()
else:
    main_description = ""

existing_main = find_work_item_by_title(ISSUE_TITLE, "ISSUE")

if existing_main:
    updated = update_work_item_description(
        existing_main["id"], ISSUE_TITLE, main_description
    )
    print(f"✓ Work Item '{ISSUE_TITLE}' (ISSUE) {updated['iid']} aktualisiert")
    main_work_item_id = updated["id"]
else:
    created = create_work_item(ISSUE_TYPE_GID, ISSUE_TITLE, main_description)
    print(f"✓ Work Item '{ISSUE_TITLE}' (ISSUE) {created['iid']} erstellt")
    main_work_item_id = created["id"]

# ---------------------------------------------------------------------------
# Task-Dateien durchgehen und je ein Task-Work-Item "Aufgabe N" upserten
# ---------------------------------------------------------------------------

if os.path.isdir(BASE_DIR):
    for fname in sorted(os.listdir(BASE_DIR)):
        if not fname.lower().startswith("task") or not fname.lower().endswith(".md"):
            continue

        path = os.path.join(BASE_DIR, fname)
        with open(path, encoding="utf-8") as f:
            task_description = f.read()

        m = re.search(r"(\d+)", fname)
        task_title = f"Aufgabe {m.group(1)}" if m else os.path.splitext(fname)[0]

        existing_task = find_work_item_by_title(task_title, "TASK")

        if existing_task:
            updated_task = update_work_item_description(
                existing_task["id"], task_title, task_description
            )
            print(f"✓ Task '{task_title}' {updated_task['iid']} aktualisiert")
        else:
            new_task = create_child_task(
                TASK_TYPE_GID, task_title, task_description, main_work_item_id
            )
            print(
                f"✓ Task '{task_title}' {new_task['iid']} erstellt"
                f" (Child von '{ISSUE_TITLE}')"
            )
