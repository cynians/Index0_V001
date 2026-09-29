"""Report or prune orphaned generated world assets within guarded roots."""

import argparse
import json
import sys
import time
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from simulations.world_gen.storage_policy import WorldGenStoragePolicy, require_within
from simulations.world_gen.worldgen_bundle import validate_worldgen_bundle


def _referenced_raster_names(project_root):
    referenced = set()
    for path in (project_root / "world").rglob("*.json"):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for token in text.replace("\\", "/").split('"'):
            if token.lower().endswith(".i0r"):
                referenced.add(Path(token).name.lower())
    return referenced


def _tree_size(path):
    if path.is_file():
        return path.stat().st_size
    return sum(candidate.stat().st_size for candidate in path.rglob("*") if candidate.is_file())


def inventory(policy, max_age_days=14.0, max_temp_count=20, max_temp_bytes=2_000_000_000):
    cutoff = time.time() - max(0.0, float(max_age_days)) * 86400.0
    referenced = _referenced_raster_names(policy.project_root)
    temporary = sorted(
        list(policy.diagnostic_cache_root.iterdir()) if policy.diagnostic_cache_root.exists() else [],
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    stale_temporary = {path for path in temporary if path.stat().st_mtime < cutoff}
    retained_bytes = 0
    for index, path in enumerate(temporary):
        size = _tree_size(path)
        if index >= max(0, int(max_temp_count)) or retained_bytes + size > max(0, int(max_temp_bytes)):
            stale_temporary.add(path)
        else:
            retained_bytes += size
    orphaned_rasters = []
    for path in policy.raster_root.glob("*.i0r") if policy.raster_root.exists() else []:
        if path.name.lower().startswith("planet_faux_") or path.name.lower() in referenced:
            continue
        orphaned_rasters.append(path)
    invalid_bundles = []
    for path in policy.retained_root.rglob("*.i0wg") if policy.retained_root.exists() else []:
        try:
            validate_worldgen_bundle(path)
        except ValueError:
            invalid_bundles.append(path)
    return {
        "stale_temporary": sorted(stale_temporary),
        "orphaned_rasters": orphaned_rasters,
        "invalid_bundles": invalid_bundles,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-age-days", type=float, default=14.0)
    parser.add_argument("--max-temp-count", type=int, default=20)
    parser.add_argument("--max-temp-bytes", type=int, default=2_000_000_000)
    parser.add_argument("--apply", action="store_true", help="Delete reported temporary/orphan/invalid files.")
    args = parser.parse_args(argv)
    policy = WorldGenStoragePolicy.for_project(PROJECT_ROOT)
    report = inventory(policy, args.max_age_days, args.max_temp_count, args.max_temp_bytes)
    deleted = []
    if args.apply:
        for path in report["stale_temporary"]:
            target = require_within(path, policy.diagnostic_cache_root)
            if target.is_dir():
                policy.remove_temporary_tree(target)
            elif target.exists():
                target.unlink()
            deleted.append(str(target))
        for category, root in (("orphaned_rasters", policy.raster_root), ("invalid_bundles", policy.retained_root)):
            for path in report[category]:
                target = require_within(path, root)
                target.unlink()
                deleted.append(str(target))
    payload = {
        key: [str(path) for path in paths]
        for key, paths in report.items()
    }
    payload["deleted"] = deleted
    payload["dry_run"] = not args.apply
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
