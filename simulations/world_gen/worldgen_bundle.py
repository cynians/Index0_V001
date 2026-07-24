"""Read and write single-file Index0 headless world-generation bundles."""

from __future__ import annotations

import hashlib
import json
import os
import zipfile
from dataclasses import asdict, is_dataclass
from pathlib import Path

from simulations.world_gen.storage_policy import (
    RETENTION_CLASSES,
    RETENTION_RETAINED,
    WORLDGEN_BUNDLE_EXTENSION,
    utc_timestamp,
)


WORLDGEN_BUNDLE_FORMAT = "index0_worldgen_bundle"
WORLDGEN_BUNDLE_VERSION = 1


def _json_bytes(value):
    return (json.dumps(value, indent=2, sort_keys=True, default=str) + "\n").encode("utf-8")


def _sha256(data):
    return hashlib.sha256(data).hexdigest()


def write_worldgen_bundle(bundle_path, *, result, retention=RETENTION_RETAINED, include_images=False):
    """Archive a completed isolated run and atomically publish one ``.i0wg``."""
    if retention not in RETENTION_CLASSES - {"temporary"}:
        raise ValueError("A persisted bundle must be retained or pinned")
    bundle_path = Path(bundle_path).resolve()
    if bundle_path.suffix.lower() != WORLDGEN_BUNDLE_EXTENSION:
        bundle_path = bundle_path.with_suffix(WORLDGEN_BUNDLE_EXTENSION)
    result_payload = asdict(result) if is_dataclass(result) else dict(result)
    run_root = Path(result_payload["output_root"]).resolve()
    entries = {
        "result.json": _json_bytes(result_payload),
    }
    source_paths = {
        "input_contract.json": result_payload.get("input_contract_path"),
        "summary.json": result_payload.get("summary_path"),
        "planet.json": result_payload.get("planet_path"),
        "regional/region.json": result_payload.get("regional_region_path"),
        "regional/materials.json": result_payload.get("regional_materials_path"),
    }
    for entry_name, source in source_paths.items():
        if source and Path(source).is_file():
            entries[entry_name] = Path(source).read_bytes()
    if "planet.json" in entries:
        planet_payload = json.loads(entries["planet.json"].decode("utf-8"))
        coastal_model = planet_payload.get("coastal_geomorphology_model") or {}
        if coastal_model:
            entries["reports/coastal_geomorphology.json"] = _json_bytes({
                "planet_id": planet_payload.get("id"),
                "summary": coastal_model.get("summary") or {},
                "model_version": coastal_model.get("model_version"),
                "segments": coastal_model.get("segments") or [],
                "fidelity": coastal_model.get("fidelity") or {},
            })
    for source_path in run_root.rglob("*.i0r"):
        try:
            relative = source_path.resolve().relative_to(run_root)
        except ValueError:
            continue
        entries[f"derived/{relative.as_posix()}"] = source_path.read_bytes()
    if include_images:
        image_paths = list(result_payload.get("stage_screenshots") or [])
        image_paths.extend(item.get("path") for item in result_payload.get("layer_images") or [])
        image_paths.extend(item.get("path") for item in result_payload.get("regional_layer_images") or [])
        image_paths.extend(filter(None, (result_payload.get("contact_sheet"), result_payload.get("regional_contact_sheet"))))
        for source in image_paths:
            source_path = Path(source)
            if not source_path.is_file():
                continue
            try:
                relative = source_path.resolve().relative_to(run_root)
            except ValueError:
                relative = Path("images") / source_path.name
            entries[relative.as_posix()] = source_path.read_bytes()
    manifest = {
        "format": WORLDGEN_BUNDLE_FORMAT,
        "format_version": WORLDGEN_BUNDLE_VERSION,
        "retention": retention,
        "created_at_utc": utc_timestamp(),
        "planet_id": result_payload.get("planet_id"),
        "includes_rendered_images": bool(include_images),
        "entries": {
            name: {"byte_count": len(data), "sha256": _sha256(data)}
            for name, data in sorted(entries.items())
        },
    }
    entries["manifest.json"] = _json_bytes(manifest)
    bundle_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = bundle_path.with_name(f".{bundle_path.name}.tmp-{os.getpid()}")
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name, data in sorted(entries.items()):
                archive.writestr(name, data)
        validate_worldgen_bundle(temporary)
        os.replace(temporary, bundle_path)
    finally:
        if temporary.exists():
            temporary.unlink()
    return bundle_path


def write_worldgen_directory_bundle(bundle_path, source_directory, *, retention="pinned", metadata=None):
    """Migrate a legacy retained run tree into one validated archive."""
    if retention not in RETENTION_CLASSES - {"temporary"}:
        raise ValueError("A persisted bundle must be retained or pinned")
    source_root = Path(source_directory).resolve()
    if not source_root.is_dir():
        raise ValueError(f"Legacy world-generation directory does not exist: {source_root}")
    bundle_path = Path(bundle_path).resolve()
    if bundle_path.suffix.lower() != WORLDGEN_BUNDLE_EXTENSION:
        bundle_path = bundle_path.with_suffix(WORLDGEN_BUNDLE_EXTENSION)
    entries = {
        f"legacy/{path.relative_to(source_root).as_posix()}": path.read_bytes()
        for path in source_root.rglob("*")
        if path.is_file()
    }
    manifest = {
        "format": WORLDGEN_BUNDLE_FORMAT,
        "format_version": WORLDGEN_BUNDLE_VERSION,
        "retention": retention,
        "created_at_utc": utc_timestamp(),
        "migration": {"kind": "legacy_worldgen_directory", "source_name": source_root.name, **(metadata or {})},
        "entries": {
            name: {"byte_count": len(data), "sha256": _sha256(data)}
            for name, data in sorted(entries.items())
        },
    }
    entries["manifest.json"] = _json_bytes(manifest)
    bundle_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = bundle_path.with_name(f".{bundle_path.name}.tmp-{os.getpid()}")
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name, data in sorted(entries.items()):
                archive.writestr(name, data)
        validate_worldgen_bundle(temporary)
        os.replace(temporary, bundle_path)
    finally:
        if temporary.exists():
            temporary.unlink()
    return bundle_path


def validate_worldgen_bundle(bundle_path):
    path = Path(bundle_path)
    try:
        with zipfile.ZipFile(path, "r") as archive:
            manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
            if manifest.get("format") != WORLDGEN_BUNDLE_FORMAT:
                raise ValueError("Not an Index0 world-generation bundle")
            if int(manifest.get("format_version", 0) or 0) != WORLDGEN_BUNDLE_VERSION:
                raise ValueError("Unsupported world-generation bundle version")
            for name, metadata in (manifest.get("entries") or {}).items():
                data = archive.read(name)
                if len(data) != int(metadata.get("byte_count", -1)) or _sha256(data) != metadata.get("sha256"):
                    raise ValueError(f"World-generation bundle entry failed validation: {name}")
            return manifest
    except (OSError, KeyError, json.JSONDecodeError, zipfile.BadZipFile) as exc:
        raise ValueError(f"Invalid world-generation bundle: {path}") from exc


def read_worldgen_bundle_json(bundle_path, entry_name):
    validate_worldgen_bundle(bundle_path)
    with zipfile.ZipFile(bundle_path, "r") as archive:
        return json.loads(archive.read(entry_name).decode("utf-8"))
