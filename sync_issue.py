#!/usr/bin/env python3
"""Erstellt oder aktualisiert die Aufgaben-Work-Items im aktuellen Projekt.

- Ein Work Item vom Typ "Issue" mit Titel "Aufgabenstellung"
  aus Aufgabenstellung/Aufgabe.md
- Für jede Datei Aufgabenstellung/TaskN.md ein Work Item vom Typ
  "Task" mit Titel "Aufgabe N", als Child-Item unter "Aufgabenstellung".
"""

import os
import re
import sys
from typing import Any

import gitlab  # type: ignore

ISSUE_TITLE = "Aufgabenstellung"
BASE_DIR = "Aufgabenstellung"
MAIN_FILE = os.path.join(BASE_DIR, "Aufgabe.md")

GITLAB_URL = os.environ["CI_SERVER_URL"]
PROJECT_PATH = os.environ["CI_PROJECT_PATH"]


def dbg(msg: str) -> None:
    """Gibt eine Debug-Zeile auf stdout aus (sofort flushed, damit CI sie sieht)."""
    print(f"[DEBUG] {msg}", flush=True)


print("=" * 70, flush=True)
print(f"sync_issue.py gestartet", flush=True)
print(f"  GITLAB_URL   : {GITLAB_URL}", flush=True)
print(f"  PROJECT_PATH : {PROJECT_PATH}", flush=True)
print(f"  BASE_DIR     : {os.path.abspath(BASE_DIR)}", flush=True)
print(f"  MAIN_FILE    : {os.path.abspath(MAIN_FILE)}", flush=True)
print("=" * 70, flush=True)

gq = gitlab.GraphQL(GITLAB_URL, token=os.environ["GITLAB_TOKEN"])
dbg("GraphQL-Client initialisiert")
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
    """Holt die Work-Item-Typ-GIDs aus dem Projekt (Name -> GID)."""
    dbg("GET_WORK_ITEM_TYPES wird abgefragt ...")
    data = gq.execute(
        GET_WORK_ITEM_TYPES,
        variable_values={"projectPath": PROJECT_PATH},
    )
    project = data.get("project")
    if not project or not project.get("workItemTypes"):
        raise RuntimeError("Konnte Work-Item-Typen nicht abrufen")
    nodes = project["workItemTypes"]["nodes"]
    mapping = {n["name"].upper(): n["id"] for n in nodes}
    dbg(f"Verfügbare Work-Item-Typen ({len(mapping)}):")
    for name, gid in sorted(mapping.items()):
        dbg(f"  {name:20s} -> {gid}")
    return mapping


def find_work_item_by_title(title: str, issue_type: str) -> dict[str, Any] | None:
    """Sucht ein Work Item in diesem Projekt anhand des Titels und Typs.

    issue_type: "ISSUE" oder "TASK"
    Gibt ein Dict mit id/iid/title zurück oder None.
    """
    dbg(f"Suche Work Item: title={title!r} type={issue_type}")
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
        dbg(f"  -> Kein Ergebnis (project oder workItems fehlen in Antwort)")
        return None

    nodes = project["workItems"]["nodes"]
    dbg(f"  -> {len(nodes)} Treffer(s) von GraphQL (Suche nach {title!r})")
    for n in nodes:
        dbg(f"     iid=#{n.get('iid')} id={n.get('id')} title={n.get('title')!r}")
    matches = [n for n in nodes if n.get("title") == title]
    dbg(f"  -> {len(matches)} exakter Treffer(s) nach Titelabgleich")

    if len(matches) > 1:
        raise RuntimeError(f"Mehr als ein Work Item mit Titel {title!r} gefunden")

    if matches:
        dbg(f"  -> Gefunden: iid=#{matches[0]['iid']} id={matches[0]['id']}")
    else:
        dbg(f"  -> Nicht gefunden")
    return matches[0] if matches else None


def create_work_item(type_gid: str, title: str, description: str) -> dict[str, Any]:
    """Erzeugt ein neues Work Item (Issue, Task, ...) in diesem Projekt."""
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
        dbg(f"  -> FEHLER: {errors}")
        raise RuntimeError(f"Fehler beim Erstellen von Work Item {title!r}: {errors}")
    wi = result["workItem"]
    dbg(f"  -> Erstellt: iid=#{wi['iid']} id={wi['id']}")
    return wi


def create_child_task(
    type_gid: str, title: str, description: str, parent_id: str
) -> dict[str, Any]:
    """Erzeugt einen neuen Task als Child-Work-Item unter parent_id."""
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
        dbg(f"  -> FEHLER: {errors}")
        raise RuntimeError(f"Fehler beim Erstellen von Task {title!r}: {errors}")
    wi = result["workItem"]
    dbg(f"  -> Erstellt: iid=#{wi['iid']} id={wi['id']}")
    return wi


def update_work_item_description(
    work_item_id: str, title: str, description: str
) -> dict[str, Any]:
    """Aktualisiert die Beschreibung eines bestehenden Work Items."""
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
        dbg(f"  -> FEHLER: {errors}")
        raise RuntimeError(
            f"Fehler beim Aktualisieren von Work Item {title!r}: {errors}"
        )
    wi = result["workItem"]
    dbg(f"  -> Aktualisiert: iid=#{wi['iid']} id={wi['id']}")
    return wi


# ---------------------------------------------------------------------------
# Work-Item-Typen dynamisch ermitteln
# ---------------------------------------------------------------------------

print("\n--- Work-Item-Typen ermitteln ---", flush=True)
_type_gids = get_work_item_type_gids()
ISSUE_TYPE_GID = _type_gids.get("ISSUE")
TASK_TYPE_GID = _type_gids.get("TASK")

dbg(f"ISSUE_TYPE_GID = {ISSUE_TYPE_GID}")
dbg(f"TASK_TYPE_GID  = {TASK_TYPE_GID}")

if not ISSUE_TYPE_GID:
    raise RuntimeError("Work-Item-Typ 'Issue' nicht im Projekt gefunden")
if not TASK_TYPE_GID:
    raise RuntimeError("Work-Item-Typ 'Task' nicht im Projekt gefunden")

# ---------------------------------------------------------------------------
# Haupt-Work-Item "Aufgabenstellung" upserten
# ---------------------------------------------------------------------------

print("\n--- Haupt-Work-Item 'Aufgabenstellung' ---", flush=True)
if os.path.exists(MAIN_FILE):
    with open(MAIN_FILE, encoding="utf-8") as f:
        main_description = f.read()
    dbg(f"Hauptdatei gelesen: {MAIN_FILE} ({len(main_description)} Zeichen)")
else:
    main_description = ""
    dbg(f"WARNUNG: Hauptdatei nicht gefunden: {MAIN_FILE} (leere Beschreibung)")

existing_main = find_work_item_by_title(ISSUE_TITLE, "ISSUE")

if existing_main:
    dbg(f"Vorhandenes Issue gefunden (iid=#{existing_main['iid']}), wird aktualisiert")
    updated = update_work_item_description(
        existing_main["id"], ISSUE_TITLE, main_description
    )
    print(f"✓ Work Item '{ISSUE_TITLE}' (ISSUE) #{updated['iid']} aktualisiert", flush=True)
    main_work_item_id = updated["id"]
else:
    dbg(f"Kein vorhandenes Issue gefunden, wird neu erstellt")
    created = create_work_item(ISSUE_TYPE_GID, ISSUE_TITLE, main_description)
    print(f"✓ Work Item '{ISSUE_TITLE}' (ISSUE) #{created['iid']} erstellt", flush=True)
    main_work_item_id = created["id"]

dbg(f"main_work_item_id = {main_work_item_id}")

# ---------------------------------------------------------------------------
# Task-Dateien durchgehen und je ein Task-Work-Item "Aufgabe N" upserten
# ---------------------------------------------------------------------------

print("\n--- Task-Dateien verarbeiten ---", flush=True)
if not os.path.isdir(BASE_DIR):
    print(f"WARNUNG: Verzeichnis '{BASE_DIR}' nicht gefunden, keine Tasks.", flush=True)
else:
    all_files = sorted(os.listdir(BASE_DIR))
    task_files = [f for f in all_files if f.lower().startswith("task") and f.lower().endswith(".md")]
    other_files = [f for f in all_files if f not in task_files]
    dbg(f"Dateien in '{BASE_DIR}': {all_files}")
    dbg(f"  -> Task-Dateien ({len(task_files)}): {task_files}")
    dbg(f"  -> Übersprungen  ({len(other_files)}): {other_files}")

    for fname in sorted(os.listdir(BASE_DIR)):
        if not fname.lower().startswith("task") or not fname.lower().endswith(".md"):
            continue

        path = os.path.join(BASE_DIR, fname)
        with open(path, encoding="utf-8") as f:
            task_description = f.read()

        m = re.search(r"(\d+)", fname)
        task_title = f"Aufgabe {m.group(1)}" if m else os.path.splitext(fname)[0]

        print(f"\n  Verarbeite: {fname} -> '{task_title}'", flush=True)
        dbg(f"  Beschreibung: {len(task_description)} Zeichen")

        existing_task = find_work_item_by_title(task_title, "TASK")

        if existing_task:
            dbg(f"  Vorhandener Task gefunden (iid=#{existing_task['iid']}), wird aktualisiert")
            updated_task = update_work_item_description(
                existing_task["id"], task_title, task_description
            )
            print(f"  ✓ Task '{task_title}' #{updated_task['iid']} aktualisiert", flush=True)
        else:
            dbg(f"  Kein vorhandener Task gefunden, wird neu erstellt")
            new_task = create_child_task(
                TASK_TYPE_GID, task_title, task_description, main_work_item_id
            )
            print(
                f"  ✓ Task '{task_title}' #{new_task['iid']} erstellt"
                f" (Child von '{ISSUE_TITLE}')",
                flush=True,
            )

print("\n" + "=" * 70, flush=True)
print("sync_issue.py abgeschlossen", flush=True)
print("=" * 70, flush=True)
