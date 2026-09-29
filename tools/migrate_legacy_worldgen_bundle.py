"""Migrate a retained legacy worldgen directory into one .i0wg bundle."""

import argparse
import json
import shutil
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from simulations.world_gen.storage_policy import WorldGenStoragePolicy, require_within
from simulations.world_gen.worldgen_bundle import (
    validate_worldgen_bundle,
    write_worldgen_directory_bundle,
)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--pinned", action="store_true")
    parser.add_argument("--delete-source", action="store_true")
    args = parser.parse_args(argv)
    legacy_root = (PROJECT_ROOT / "artifacts" / "headless_worldgen").resolve()
    policy = WorldGenStoragePolicy.for_project(PROJECT_ROOT)
    source = require_within(args.source, legacy_root)
    output = policy.validate_generated_target(args.output)
    destination = write_worldgen_directory_bundle(
        output,
        source,
        retention="pinned" if args.pinned else "retained",
        metadata={"migrated_by": "tools/migrate_legacy_worldgen_bundle.py"},
    )
    manifest = validate_worldgen_bundle(destination)
    if args.delete_source:
        source = require_within(source, legacy_root)
        shutil.rmtree(source)
    print(json.dumps({
        "bundle_path": str(destination),
        "entry_count": len(manifest.get("entries") or {}),
        "retention": manifest.get("retention"),
        "source_deleted": bool(args.delete_source),
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

