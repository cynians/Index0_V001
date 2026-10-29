"""Bring the ontology store to its compact layout, and prove that what it holds is unchanged.

The store grew to twice its content: the worldgen's models are megabytes of
numbers written out as JSON text, and the database's index over values held
each of them a second time.  This packs every large JSON literal, takes large
values out of that index and compacts the file
(``PersistentOntologyStore.optimize_storage``).  What is read from the store
stays the same, value for value.

    python tools/compact_ontology_store.py --report               look only
    python tools/compact_ontology_store.py --database <copy>      rehearse on a copy
    python tools/compact_ontology_store.py                        the live store

Before and after, every value of the database is unpacked and hashed; the run
fails if the two fingerprints differ.  The live store is only touched when no
other Python process is running: a second writer can lose writes without an
error.  Take a copy first (``--database`` works on any copy that has its
manifest beside it); the tool makes none.
"""

from __future__ import annotations

import argparse
import hashlib
import sqlite3
import sys
import time
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.ontology_backup import other_python_processes  # noqa: E402
from world.ontology_repository import unpack_json_text  # noqa: E402
from world.persistent_ontology_store import PersistentOntologyStore  # noqa: E402

ONTOLOGY_PATH = PROJECT_ROOT / "ontology" / "index0.owl"


def content_fingerprint(database_path):
    """``(rows, digest)`` of everything the database holds, large literals unpacked: the same for both layouts."""
    connection = sqlite3.connect(f"file:{database_path}?mode=ro", uri=True)
    try:
        rows, total = 0, 0
        for table, columns in (("resources", "storid, iri"), ("objs", "c, s, p, o"), ("datas", "c, s, p, o, d")):
            for record in connection.execute(f"SELECT {columns} FROM {table}"):
                if table == "datas":
                    record = record[:3] + (unpack_json_text(record[3]),) + record[4:]
                digest = hashlib.blake2b(repr((table,) + tuple(record)).encode("utf-8"), digest_size=16).digest()
                total = (total + int.from_bytes(digest, "big")) % (1 << 128)  # the order of rows does not count
                rows += 1
        return rows, f"{total:032x}"
    finally:
        connection.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--database", help="a copy of the store's database to work on instead of the live one")
    parser.add_argument("--report", action="store_true", help="say what the store holds and stop")
    args = parser.parse_args(argv)

    store = PersistentOntologyStore(ONTOLOGY_PATH, database_path=args.database)
    report = store.storage_report()
    print(f"{store.database_path}")
    print(f"  {report['database_bytes'] / 1e9:.2f} GB; JSON literals to pack: {report['json_literals_plain']} holding "
          f"{report['json_literals_plain_chars'] / 1e9:.2f} GB of text; packed already: {report['json_literals_packed']}; "
          f"large values that are no JSON literal: {report['large_literals_not_json']}; "
          f"value index holds {'small values only' if report['value_index_is_partial'] else 'every value'}")
    if args.report:
        return 0
    if not args.database:
        others = other_python_processes()
        if others:
            print(f"not touching the live store: other Python processes are running: {others}")
            return 1

    started = time.perf_counter()
    before = content_fingerprint(store.database_path)
    print(f"  content before: {before[0]} rows, {before[1]} ({time.perf_counter() - started:.0f} s)")
    started = time.perf_counter()
    done = store.optimize_storage(progress=lambda share, message: print(f"    {share:4.0%} {message}", flush=True)
                                  if int(share * 100) % 10 == 0 else None)
    print(f"  optimized in {time.perf_counter() - started:.0f} s: {done}")
    started = time.perf_counter()
    after = content_fingerprint(store.database_path)
    print(f"  content after:  {after[0]} rows, {after[1]} ({time.perf_counter() - started:.0f} s)")
    if before != after:
        print("THE CONTENT CHANGED. Put the copy you took back in place.")
        return 2
    print(f"  the same content in {done['bytes_after'] / 1e9:.2f} GB instead of {done['bytes_before'] / 1e9:.2f} GB")
    if not args.database and other_python_processes():
        print("  note: another Python process started meanwhile; check its writes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
