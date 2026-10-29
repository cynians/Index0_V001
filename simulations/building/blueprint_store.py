"""Blueprint asset files and the ontology fields that point at them.

The geometry of a blueprint lives in ``assets/buildings/<id>.json.gz``; the
``building_blueprints`` ontology entity carries the semantic summary plus
``blueprint_asset_path`` and ``blueprint_fingerprint``.  This mirrors the
plant blueprint store (``assets/plants``).
"""

from __future__ import annotations

import copy
import gzip
import json
import os
from pathlib import Path
from typing import Any

from engine import asset_files
from .blueprint_model import (
    blueprint_fingerprint,
    derive_geometry,
    new_blueprint,
    normalize_blueprint,
    summary_fields,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
ASSET_DIRECTORY = "assets/buildings"
BLUEPRINT_DATASET = "building_blueprints"
BLUEPRINT_TYPE = "building_blueprint"


def safe_identifier(value: str) -> str:
    text = "".join(ch if ch.isalnum() or ch in "_-" else "_" for ch in str(value or ""))
    return text.strip("_") or "blueprint"


def default_asset_path(blueprint_id: str) -> str:
    return f"{ASSET_DIRECTORY}/{safe_identifier(blueprint_id)}.json.gz"


def is_blueprint_entity(entity: Any) -> bool:
    if not isinstance(entity, dict):
        return False
    return (
        str(entity.get("_dataset") or "") == BLUEPRINT_DATASET
        or str(entity.get("type") or "") == BLUEPRINT_TYPE
    )


class BlueprintAssetStore:
    """Load and save blueprint payloads, with an mtime-keyed read cache."""

    def __init__(self, project_root: Path | str | None = None):
        self.project_root = Path(project_root) if project_root else PROJECT_ROOT
        self._cache: dict[str, tuple[int, dict[str, Any]]] = {}

    def absolute_path(self, relative_path: str) -> Path:
        path = Path(str(relative_path))
        return path if path.is_absolute() else self.project_root / path

    def load(self, relative_path: str) -> dict[str, Any] | None:
        if not relative_path:
            return None
        path = self.absolute_path(relative_path)
        revision = asset_files.revision(path)
        if revision is None:
            return None
        key = str(path.resolve())
        cached = self._cache.get(key)
        if cached is not None and cached[0] == revision:
            return copy.deepcopy(cached[1])
        try:
            with asset_files.open_gzip_text(path) as handle:
                payload = json.load(handle)
        except (OSError, ValueError, json.JSONDecodeError):
            return None
        blueprint = normalize_blueprint(payload)
        self._cache[key] = (revision, blueprint)
        return copy.deepcopy(blueprint)

    def save(self, blueprint: dict[str, Any], relative_path: str | None = None) -> str:
        blueprint = normalize_blueprint(blueprint)
        relative_path = relative_path or default_asset_path(blueprint["blueprint_id"])
        path = self.absolute_path(relative_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + ".tmp")
        with gzip.open(temporary, "wt", encoding="utf-8", compresslevel=6) as handle:
            json.dump(blueprint, handle, separators=(",", ":"), sort_keys=True)
        os.replace(temporary, path)
        self._cache.pop(str(path.resolve()), None)
        return relative_path.replace("\\", "/")

    def load_for_entity(self, entity: dict[str, Any] | None) -> dict[str, Any] | None:
        if not isinstance(entity, dict):
            return None
        blueprint = self.load(str(entity.get("blueprint_asset_path") or ""))
        if blueprint is None:
            return None
        blueprint["blueprint_id"] = str(entity.get("id") or blueprint["blueprint_id"])
        return blueprint


_SHARED_STORE = None


def shared_store() -> BlueprintAssetStore:
    global _SHARED_STORE
    if _SHARED_STORE is None:
        _SHARED_STORE = BlueprintAssetStore()
    return _SHARED_STORE


def set_shared_store(store: BlueprintAssetStore | None) -> BlueprintAssetStore | None:
    """Swap the process-wide store (tests point it at a temporary root)."""

    global _SHARED_STORE
    previous = _SHARED_STORE
    _SHARED_STORE = store
    return previous


def entity_display_name(entity: dict[str, Any] | None, fallback: str = "Building Blueprint") -> str:
    if not isinstance(entity, dict):
        return fallback
    return str(entity.get("pretty_name") or entity.get("name") or entity.get("id") or fallback)


def blueprint_for_entity(entity: dict[str, Any] | None, store: BlueprintAssetStore | None = None):
    """Return the entity's blueprint, or a fresh empty one if none is saved."""

    store = store or shared_store()
    blueprint = store.load_for_entity(entity)
    if blueprint is not None:
        return blueprint
    entity_id = str((entity or {}).get("id") or "blueprint")
    return new_blueprint(entity_id, entity_display_name(entity))


def updated_blueprint_entity(entity: dict[str, Any], blueprint: dict[str, Any], asset_path: str) -> dict[str, Any]:
    """Full entity dict with refreshed summary fields.

    Returns a copy of the complete entity -- ontology writes replace the whole
    entity, so partial dicts would erase authored fields.
    """

    updated = copy.deepcopy(entity)
    blueprint = normalize_blueprint(blueprint)
    derived = derive_geometry(blueprint)
    updated.update(summary_fields(blueprint, derived))
    updated["blueprint_asset_path"] = asset_path
    updated["blueprint_fingerprint"] = blueprint_fingerprint(blueprint)
    updated.setdefault("blueprint_status", "draft")
    updated["_dataset"] = BLUEPRINT_DATASET
    updated["type"] = BLUEPRINT_TYPE
    return updated
