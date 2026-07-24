"""Storage policy for generated world assets and diagnostics.

Durable entity truth is owned by the ontology repository.  Reproducible
rasters use stable per-entity bundle names, while diagnostic runs default to
temporary storage and only survive when explicitly retained.
"""

from __future__ import annotations

import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


RETENTION_TEMPORARY = "temporary"
RETENTION_RETAINED = "retained"
RETENTION_PINNED = "pinned"
RETENTION_CLASSES = {RETENTION_TEMPORARY, RETENTION_RETAINED, RETENTION_PINNED}
WORLDGEN_BUNDLE_EXTENSION = ".i0wg"


def safe_slug(value):
    slug = re.sub(r"[^0-9A-Za-z_]+", "_", str(value or "world")).strip("_").lower()
    return slug or "world"


def _resolved(path):
    return Path(path).expanduser().resolve()


def require_within(path, root, *, allow_root=False):
    """Resolve *path* and reject destructive targets outside *root*."""
    target = _resolved(path)
    boundary = _resolved(root)
    try:
        relative = target.relative_to(boundary)
    except ValueError as exc:
        raise ValueError(f"Generated-data path escapes its storage root: {target}") from exc
    if not allow_root and relative == Path("."):
        raise ValueError(f"Refusing to operate on the storage root itself: {boundary}")
    return target


def atomic_replace(source, destination):
    source = _resolved(source)
    destination = _resolved(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    os.replace(source, destination)
    return destination


@dataclass(frozen=True)
class WorldGenStoragePolicy:
    project_root: Path

    @classmethod
    def for_project(cls, project_root=None):
        root = _resolved(project_root or Path(__file__).resolve().parents[2])
        return cls(project_root=root)

    @property
    def diagnostic_cache_root(self):
        return self.project_root / ".cache" / "worldgen"

    @property
    def retained_root(self):
        return self.project_root / "artifacts" / "worldgen"

    @property
    def raster_root(self):
        return self.project_root / "assets" / "maps" / "material_heatmaps"

    def canonical_raster_bundle(self, entity_id):
        return self.raster_root / f"{safe_slug(entity_id)}.i0r"

    def retained_bundle(self, label, *, pinned=False):
        directory = self.retained_root / ("pinned" if pinned else "retained")
        return directory / f"{safe_slug(label)}{WORLDGEN_BUNDLE_EXTENSION}"

    def temporary_run_directory(self, prefix="run"):
        self.diagnostic_cache_root.mkdir(parents=True, exist_ok=True)
        return Path(tempfile.mkdtemp(prefix=f"{safe_slug(prefix)}-", dir=self.diagnostic_cache_root))

    def validate_generated_target(self, path):
        target = _resolved(path)
        valid_roots = (self.diagnostic_cache_root, self.retained_root, self.raster_root)
        if not any(target == _resolved(root) or root.resolve() in target.parents for root in valid_roots):
            raise ValueError(f"Path is not in an approved generated-data root: {target}")
        return target

    def remove_temporary_tree(self, path):
        target = require_within(path, self.diagnostic_cache_root)
        if target.exists():
            shutil.rmtree(target)


def utc_timestamp():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

