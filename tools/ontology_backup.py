"""A small backup for an ontology authoring run: what the run is about to replace or remove.

An authoring tool used to copy the whole store before it wrote, gigabytes for
a change of a few entities.  This keeps the stored form of exactly those
entities, and which of them did not exist yet, so the run can be undone:

    python tools/ontology_backup.py restore artifacts/<tool>/backup_<stamp>            look first
    python tools/ontology_backup.py restore artifacts/<tool>/backup_<stamp> --apply

Undoing puts the kept entities back and removes the ones the run created.
It does not touch anything else that was written since.
"""

from __future__ import annotations

import argparse
import copy
import gzip
import json
import os
import subprocess
import sys
import time
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

BACKUP_FILE = "entities_before.json.gz"


def other_python_processes():
    """Python processes other than this one and the launcher that started it (Windows; elsewhere none are found).

    The store takes one writer.  A write made while another process has it
    open can be reported as done and not be in the database.
    """
    if os.name != "nt":
        return []
    listing = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True, text=True, check=False).stdout
    mine = {os.getpid(), os.getppid()}
    found = []
    for line in listing.splitlines():
        parts = [part.strip('"') for part in line.split('","')]
        if len(parts) >= 2 and parts[0].lower().startswith(("python", "py.exe")) and parts[1].isdigit():
            if int(parts[1]) not in mine:
                found.append((parts[0], int(parts[1])))
    return found


def _plain(entity):
    materialize = getattr(entity, "materialize", None)
    return copy.deepcopy(dict(materialize() if callable(materialize) else entity))


def backup_entities(store, backup_root, entities=(), remove_entity_ids=()):
    """Keep the stored form of what a run will replace or remove; returns the folder it is in."""
    touched = [str(entity["id"]) for entity in entities if isinstance(entity, dict) and entity.get("id")]
    touched += [str(entity_id) for entity_id in remove_entity_ids if entity_id]
    stored = {}
    for dataset in store.load_datasets().values():
        for entity in dataset:
            if isinstance(entity, dict) and str(entity.get("id")) in touched:
                stored[str(entity["id"])] = _plain(entity)
    backup_dir = Path(backup_root) / f"backup_{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}"
    backup_dir.mkdir(parents=True, exist_ok=False)
    record = {
        "written": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "database": str(store.database_path),
        "replaced_or_removed": [stored[entity_id] for entity_id in dict.fromkeys(touched) if entity_id in stored],
        "created_by_the_run": [entity_id for entity_id in dict.fromkeys(touched) if entity_id not in stored],
    }
    with gzip.open(backup_dir / BACKUP_FILE, "wt", encoding="utf-8") as handle:
        json.dump(record, handle, ensure_ascii=False, default=str)
    return backup_dir


def read_backup(backup_dir):
    with gzip.open(Path(backup_dir) / BACKUP_FILE, "rt", encoding="utf-8") as handle:
        return json.load(handle)


def restore(store, backup_dir):
    """Put back what a run replaced or removed and take out what it created."""
    record = read_backup(backup_dir)
    return store.apply_changes(entities=record["replaced_or_removed"], remove_entity_ids=record["created_by_the_run"])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    undo = commands.add_parser("restore", help="undo the run a backup was taken for")
    undo.add_argument("backup_dir")
    undo.add_argument("--apply", action="store_true", help="write; without it the backup is only described")
    args = parser.parse_args(argv)

    from world.persistent_ontology_store import PersistentOntologyStore

    record = read_backup(args.backup_dir)
    print(f"taken {record['written']} for {record['database']}")
    print(f"  would put back {len(record['replaced_or_removed'])}: "
          f"{[entity.get('id') for entity in record['replaced_or_removed']][:12]}")
    print(f"  would remove {len(record['created_by_the_run'])}: {record['created_by_the_run'][:12]}")
    if not args.apply:
        return 0
    others = other_python_processes()
    if others:
        print(f"not writing: other Python processes are running: {others}")
        return 1
    store = PersistentOntologyStore(PROJECT_ROOT / "ontology" / "index0.owl")
    print(f"restored: {restore(store, args.backup_dir)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
