"""Audit and apply the 2026 planet/star/material ontology cleanup.

The audit mode is read-only and writes an exact manifest.  Apply mode requires
that manifest, verifies that the authoritative quadstore is unchanged, creates
a recoverable database/RDF checkpoint, then commits all graph edits as one
transaction.
"""

from __future__ import annotations

import argparse
import copy
import json
import re
import shutil
import sqlite3
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from simulations.space.stellar import stellar_profile_for_class
from simulations.world_gen.natural_materials import natural_material_entries
from world.material_reference_models import apply_material_reference_models
from world.persistent_ontology_store import PersistentOntologyStore


ONTOLOGY_PATH = PROJECT_ROOT / "ontology" / "index0.owl"
REPORT_ROOT = PROJECT_ROOT / "artifacts" / "ontology_cleanup"
ARTICLE_FIELDS = ("wiki_entry", "article", "description", "notes")
PLANET_CLASSES = {"planet", "dwarf_planet", "moon"}
RELATION_FIELDS = {
    "parents",
    "related",
    "constituents",
    "parent_location",
    "parent_body",
    "location_entity",
    "refinement_root_planet_id",
    "refinement_parent_map_id",
    "refinement_source_location_id",
    "source_planet_id",
    "root_planet_id",
    "map_root_entity",
    "parent_entity",
    "derived_from_planet",
}
STANDARD_MATERIAL_FIELDS = {
    "material_record_schema_version",
    "material_system_role",
    "natural_distribution_role",
    "worldgen_participation",
    "resource_origin",
    "recyclability_class",
}
NATURAL_FORMATION_FIELDS = {
    "minimum_map_detail_level",
    "distribution_scale",
    "formation_category",
    "formation_process",
    "spatial_representation",
    "formation_requirements",
    "formation_contract_status",
    "surface_affinity_profile",
}


def _now_slug():
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _class_key(entity):
    return str(
        entity.get("location_class")
        or entity.get("body_class")
        or ""
    ).strip().lower()


def _text(value):
    return str(value or "").strip()


def _generated_article_text(value):
    text = _text(value)
    if not text:
        return False
    compact = " ".join(text.split()).casefold()
    if (
        compact.startswith("draft ")
        and (
            " created under " in compact
            or " selected under " in compact
        )
    ):
        return True
    lines = [
        line.strip()
        for line in text.splitlines()
        if line.strip()
    ]
    return bool(
        lines
        and lines[0].casefold() == "! planets"
        and all(
            line.casefold() == "! planets"
            or re.match(r"^!!\s*\[\[[^\]]+\]\]$", line)
            for line in lines
        )
    )


def _has_authored_article(entity):
    if any(
        _text(entity.get(field))
        and not _generated_article_text(entity.get(field))
        for field in ARTICLE_FIELDS
    ):
        return True
    return any(
        isinstance(snapshot, dict)
        and _text(snapshot.get("wiki_entry"))
        and not _generated_article_text(snapshot.get("wiki_entry"))
        for snapshot in (entity.get("timeline_snapshots") or [])
    )


def _entity_index(datasets):
    return {
        entity["id"]: entity
        for entries in datasets.values()
        for entity in entries
        if isinstance(entity, dict) and entity.get("id")
    }


def _dataset_index(datasets):
    return {
        entity["id"]: dataset_name
        for dataset_name, entries in datasets.items()
        for entity in entries
        if isinstance(entity, dict) and entity.get("id")
    }


def _relation_ids(value):
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str) and item]
    return []


def _planet_sets(locations):
    planets = [
        entity
        for entity in locations
        if _class_key(entity) in PLANET_CLASSES
    ]
    kept = [entity for entity in planets if _has_authored_article(entity)]
    removed = [entity for entity in planets if not _has_authored_article(entity)]
    return planets, kept, removed


def _parent_refs(entity):
    refs = set()
    for field in RELATION_FIELDS - {"constituents", "related"}:
        refs.update(_relation_ids(entity.get(field)))
    return refs


def _authored_descendant_planet_roots(locations, removal_ids):
    entities = {
        entity["id"]: entity
        for entity in locations
        if isinstance(entity, dict) and entity.get("id")
    }
    child_parents = {
        entity_id: _parent_refs(entity)
        for entity_id, entity in entities.items()
    }
    for parent in entities.values():
        for child_id in _relation_ids(parent.get("constituents")):
            child_parents.setdefault(child_id, set()).add(parent["id"])

    protected = set()
    authored_descendants = {}
    for entity_id, entity in entities.items():
        if (
            entity_id in removal_ids
            or _class_key(entity) in {"star", "star_system"}
            or not _has_authored_article(entity)
        ):
            continue
        frontier = list(child_parents.get(entity_id) or [])
        visited = set()
        while frontier:
            parent_id = frontier.pop()
            if parent_id in visited:
                continue
            visited.add(parent_id)
            if parent_id in removal_ids:
                protected.add(parent_id)
                authored_descendants.setdefault(parent_id, []).append(entity_id)
                continue
            frontier.extend(child_parents.get(parent_id) or [])
    return protected, {
        key: sorted(set(value))
        for key, value in sorted(authored_descendants.items())
    }


def _dependent_cleanup_ids(datasets, root_ids):
    entities = _entity_index(datasets)
    location_ids = {
        entity.get("id")
        for entity in datasets.get("locations", [])
        if isinstance(entity, dict)
    }
    delete_ids = set(root_ids)
    changed = True
    while changed:
        changed = False
        for entity_id in location_ids - delete_ids:
            entity = entities.get(entity_id) or {}
            if _has_authored_article(entity):
                continue
            refs = _parent_refs(entity)
            parent_owned = bool(refs.intersection(delete_ids))
            child_owned = any(
                entity_id in _relation_ids((entities.get(parent_id) or {}).get("constituents"))
                for parent_id in delete_ids
            )
            if parent_owned or child_owned:
                delete_ids.add(entity_id)
                changed = True
    return delete_ids


def _clean_relation_value(value, delete_ids):
    if isinstance(value, str):
        return "" if value in delete_ids else value
    if isinstance(value, list):
        return [item for item in value if item not in delete_ids]
    return value


def _remove_planet_links(wiki_text, removed_names, removed_ids):
    lines = str(wiki_text or "").splitlines()
    blocked = {str(value).strip().casefold() for value in (*removed_names, *removed_ids)}
    cleaned = []
    for line in lines:
        match = re.match(r"^\s*!!\s*\[\[([^\]|]+)", line)
        if match and match.group(1).strip().casefold() in blocked:
            continue
        cleaned.append(line)
    result = "\n".join(cleaned).rstrip()
    return f"{result}\n" if result else ""


def _system_candidates(locations, entities):
    referenced_system_ids = {
        str(entity.get("star_system"))
        for entity in locations
        if entity.get("star_system")
    }
    systems = {}
    for entity in locations:
        entity_id = entity.get("id")
        if (
            _class_key(entity) == "star_system"
            or entity.get("system_role") == "star_system"
            or entity_id in referenced_system_ids
            and "system" in _text(entity.get("name") or entity_id).casefold()
        ):
            systems[entity_id] = entity
    for system_id in referenced_system_ids:
        candidate = entities.get(system_id)
        if isinstance(candidate, dict):
            systems.setdefault(system_id, candidate)
    return list(systems.values())


def _star_profile(source):
    spectral = (
        source.get("spectral_class")
        or source.get("star_class")
        or "G2V"
    )
    return stellar_profile_for_class(spectral)


def _normalize_star(star, system, profile):
    star = copy.deepcopy(star)
    star.update({
        "_dataset": "locations",
        "type": "location",
        "location_class": "star",
        "body_class": "star",
        "location_role": "orbital_body",
        "system_role": "orbital_body",
        "star_system": system["id"],
        "parent_location": system["id"],
    })
    for field in (
        "spectral_class",
        "star_class",
        "mass_kg",
        "radius_m",
        "luminosity_solar",
        "display_color",
        "card_color",
        "habitable_zone_inner_au",
        "habitable_zone_outer_au",
    ):
        if star.get(field) in (None, "", [], {}):
            star[field] = copy.deepcopy(profile.get(field))
    return star


def _new_primary_star(system, entities):
    base_id = re.sub(r"^(system_|sys_|loc_)", "", system["id"])
    star_id = f"star_{base_id}_primary"
    suffix = 2
    while star_id in entities:
        star_id = f"star_{base_id}_primary_{suffix}"
        suffix += 1
    profile = _star_profile(system)
    return _normalize_star(
        {
            "id": star_id,
            "name": f"{system.get('name') or system['id']} Primary",
            "pretty_name": f"{system.get('name') or system['id']} Primary",
            "tags": ["stellar_primary", "ontology_standardized"],
        },
        system,
        profile,
    )


def _normalize_systems(datasets, delete_ids, removed_planets):
    entities = _entity_index(datasets)
    locations = datasets.get("locations", [])
    systems = _system_candidates(locations, entities)
    stars = [
        entity
        for entity in locations
        if _class_key(entity) == "star"
    ]
    stars_by_system = {}
    for star in stars:
        stars_by_system.setdefault(star.get("star_system"), []).append(star)

    upserts = []
    created_stars = []
    repaired_stars = []
    repaired_systems = []
    for source_system in sorted(systems, key=lambda item: item["id"]):
        system = copy.deepcopy(source_system)
        system.update({
            "_dataset": "locations",
            "type": "location",
            "location_class": "star_system",
            "location_role": "star_system",
            "system_role": "star_system",
        })
        # Some legacy cards used one self-referencing location as both the
        # system and its primary star.  Split that malformed record into the
        # extant system id plus a distinct star instead of upserting the same
        # id twice with conflicting classes.
        system_stars = [
            star
            for star in (stars_by_system.get(system["id"]) or [])
            if star.get("id") != system["id"]
        ]
        if not system_stars:
            for constituent_id in _relation_ids(system.get("constituents")):
                constituent = entities.get(constituent_id)
                if isinstance(constituent, dict) and _class_key(constituent) == "star":
                    system_stars.append(constituent)
        if not system_stars:
            new_star = _new_primary_star(system, entities)
            entities[new_star["id"]] = new_star
            system_stars.append(new_star)
            created_stars.append(new_star["id"])

        normalized_stars = []
        for star in system_stars:
            normalized = _normalize_star(star, system, _star_profile(star or system))
            normalized_stars.append(normalized)
            if normalized != star:
                repaired_stars.append(normalized["id"])
        system["multiplicity"] = len(normalized_stars)
        constituents = [
            entity_id
            for entity_id in _relation_ids(system.get("constituents"))
            if entity_id not in delete_ids
        ]
        for star in normalized_stars:
            if star["id"] not in constituents:
                constituents.append(star["id"])
        system["constituents"] = constituents
        system["wiki_entry"] = _remove_planet_links(
            system.get("wiki_entry"),
            [
                entity.get("name") or entity.get("pretty_name") or entity["id"]
                for entity in removed_planets
            ],
            [entity["id"] for entity in removed_planets],
        )
        if not system["wiki_entry"]:
            system.pop("wiki_entry", None)
        profile = _star_profile(normalized_stars[0])
        for field in (
            "spectral_class",
            "star_class",
            "luminosity_solar",
            "habitable_zone_inner_au",
            "habitable_zone_outer_au",
        ):
            if system.get(field) in (None, "", [], {}):
                system[field] = copy.deepcopy(profile.get(field))
        if system != source_system:
            repaired_systems.append(system["id"])
        upserts.extend(normalized_stars)
        upserts.append(system)
    return upserts, {
        "systems_audited": len(systems),
        "systems_repaired": sorted(set(repaired_systems)),
        "stars_created": sorted(set(created_stars)),
        "stars_repaired": sorted(set(repaired_stars)),
    }


def _normalized_materials(datasets):
    initial = {
        entity["id"]: copy.deepcopy(entity)
        for dataset_name in ("material", "materials")
        for entity in datasets.get(dataset_name, [])
        if isinstance(entity, dict) and entity.get("id")
    }
    runtime_datasets = {
        key: [copy.deepcopy(entity) for entity in value]
        for key, value in datasets.items()
    }
    runtime_entities = _entity_index(runtime_datasets)
    target = type("RuntimeTarget", (), {})()
    target.datasets = runtime_datasets
    target.entities = runtime_entities
    apply_material_reference_models(target)
    natural_reference = {
        entity["id"]: entity
        for entity in natural_material_entries()
    }

    upserts = []
    before_missing = {}
    after_missing = {}
    unresolved_natural = []
    for entity_id, original in sorted(initial.items()):
        missing = sorted(
            field
            for field in STANDARD_MATERIAL_FIELDS
            if original.get(field) in (None, "", [], {})
        )
        if (
            original.get("material_class") == "natural_material"
            or original.get("material_subclass") in {"rock", "mineral", "sediment", "regolith", "ice"}
        ):
            missing.extend(
                field
                for field in sorted(NATURAL_FORMATION_FIELDS)
                if original.get(field) in (None, "", [], {})
            )
        before_missing[entity_id] = sorted(set(missing))

        normalized = copy.deepcopy(target.entities.get(entity_id) or original)
        reference = natural_reference.get(entity_id)
        if reference:
            authored_wiki = original.get("wiki_entry")
            normalized.update(copy.deepcopy(reference))
            if authored_wiki:
                normalized["wiki_entry"] = authored_wiki
        normalized["_dataset"] = "materials"
        normalized.setdefault("type", "material")
        upserts.append(normalized)

        required = set(STANDARD_MATERIAL_FIELDS)
        if normalized.get("material_system_role") == "natural_geologic_material":
            required.update(NATURAL_FORMATION_FIELDS)
        after_missing[entity_id] = sorted(
            field
            for field in required
            if normalized.get(field) in (None, "", [], {})
        )
        if (
            normalized.get("material_system_role") == "natural_geologic_material"
            and normalized.get("formation_contract_status") != "resolved"
        ):
            unresolved_natural.append(entity_id)

    catalog = natural_material_entries()
    catalog_unresolved = [
        entry["id"]
        for entry in catalog
        if (
            entry.get("material_system_role") == "natural_geologic_material"
            and entry.get("formation_contract_status") != "resolved"
        )
    ]
    return upserts, {
        "persistent_records_audited": len(initial),
        "runtime_catalog_records_audited": len(catalog),
        "persistent_missing_fields_before": before_missing,
        "persistent_missing_fields_after": after_missing,
        "persistent_unresolved_natural_materials": unresolved_natural,
        "runtime_catalog_unresolved_natural_materials": catalog_unresolved,
    }


def _cleanup_upserts(datasets, delete_ids, removed_planets):
    upserts = []
    removed_names = [
        entity.get("name") or entity.get("pretty_name") or entity["id"]
        for entity in removed_planets
    ]
    removed_ids = [entity["id"] for entity in removed_planets]
    for entries in datasets.values():
        for source in entries:
            if not isinstance(source, dict) or source.get("id") in delete_ids:
                continue
            entity = copy.deepcopy(source)
            if (
                _class_key(entity) == "star_system"
                or entity.get("system_role") == "star_system"
            ):
                continue
            changed = False
            for field in RELATION_FIELDS:
                if field not in entity:
                    continue
                cleaned = _clean_relation_value(entity.get(field), delete_ids)
                if cleaned != entity.get(field):
                    if cleaned in ("", []):
                        entity.pop(field, None)
                    else:
                        entity[field] = cleaned
                    changed = True
            if changed:
                upserts.append(entity)
    return upserts


def _merge_upserts(*groups):
    merged = {}
    order = []
    for group in groups:
        for entity in group:
            entity_id = entity["id"]
            if entity_id not in merged:
                order.append(entity_id)
                merged[entity_id] = copy.deepcopy(entity)
            else:
                merged[entity_id].update(copy.deepcopy(entity))
    # Stars must exist before systems store their constituent relations.
    order.sort(key=lambda entity_id: (
        0 if _class_key(merged[entity_id]) == "star" else
        2 if _class_key(merged[entity_id]) == "star_system" else
        1,
        entity_id,
    ))
    return [merged[entity_id] for entity_id in order]


def build_audit(store):
    datasets = store.load_datasets()
    entities = _entity_index(datasets)
    dataset_by_id = _dataset_index(datasets)
    planets, kept_planets, removal_candidates = _planet_sets(datasets.get("locations", []))
    protected_planet_ids, descendant_sources = _authored_descendant_planet_roots(
        datasets.get("locations", []),
        {entity["id"] for entity in removal_candidates},
    )
    protected_planets = [
        entity
        for entity in removal_candidates
        if entity["id"] in protected_planet_ids
    ]
    kept_planets = [*kept_planets, *protected_planets]
    removed_planets = [
        entity
        for entity in removal_candidates
        if entity["id"] not in protected_planet_ids
    ]
    delete_ids = _dependent_cleanup_ids(
        datasets,
        {entity["id"] for entity in removed_planets},
    )
    authored_descendants = []
    for entity in datasets.get("locations", []):
        if (
            not _has_authored_article(entity)
            or entity.get("id") in delete_ids
            or _class_key(entity) in {"star", "star_system"}
        ):
            continue
        refs = _parent_refs(entity)
        if refs.intersection(delete_ids):
            authored_descendants.append(entity["id"])

    relation_upserts = _cleanup_upserts(datasets, delete_ids, removed_planets)
    system_upserts, system_report = _normalize_systems(
        datasets,
        delete_ids,
        removed_planets,
    )
    material_upserts, material_report = _normalized_materials(datasets)
    upserts = _merge_upserts(relation_upserts, material_upserts, system_upserts)
    # A few malformed legacy identities are deliberately migrated in place
    # (for example, a card that used to masquerade as both a planet and a
    # system).  An upsert wins over removal and therefore is not a final
    # deletion target.
    delete_ids.difference_update(entity["id"] for entity in upserts)
    stat = store.database_path.stat()
    manifest = {
        "version": 1,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "ontology_path": str(store.ontology_path),
        "database_path": str(store.database_path),
        "database_signature": {
            "size": stat.st_size,
            "mtime_ns": stat.st_mtime_ns,
        },
        "before_dataset_counts": {
            key: len(value)
            for key, value in sorted(datasets.items())
        },
        "planets": {
            "audited": len(planets),
            "kept_authored": [
                {"id": entity["id"], "name": entity.get("name"), "class": _class_key(entity)}
                for entity in sorted(kept_planets, key=lambda item: item["id"])
            ],
            "kept_for_authored_descendants": [
                {
                    "id": entity["id"],
                    "name": entity.get("name"),
                    "authored_descendants": descendant_sources.get(entity["id"], []),
                }
                for entity in sorted(protected_planets, key=lambda item: item["id"])
            ],
            "removed_generated_only": [
                {"id": entity["id"], "name": entity.get("name"), "class": _class_key(entity)}
                for entity in sorted(removed_planets, key=lambda item: item["id"])
            ],
            "generated_dependents_removed": [
                {
                    "id": entity_id,
                    "name": (entities.get(entity_id) or {}).get("name"),
                    "dataset": dataset_by_id.get(entity_id),
                    "class": _class_key(entities.get(entity_id) or {}),
                }
                for entity_id in sorted(
                    delete_ids - {entity["id"] for entity in removed_planets}
                )
            ],
            "authored_descendant_conflicts": sorted(authored_descendants),
        },
        "systems": system_report,
        "materials": material_report,
        "transaction": {
            "delete_ids": sorted(delete_ids),
            "upsert_entities": upserts,
        },
    }
    return manifest


def _write_manifest(manifest, output_path=None):
    output_path = Path(output_path) if output_path else REPORT_ROOT / f"audit_{_now_slug()}.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return output_path.resolve()


def _backup_store(store, backup_dir):
    backup_dir.mkdir(parents=True, exist_ok=False)
    database_backup = backup_dir / store.database_path.name
    source = sqlite3.connect(
        f"file:{store.database_path}?mode=ro",
        uri=True,
        check_same_thread=False,
    )
    destination = sqlite3.connect(database_backup)
    try:
        source.backup(destination, pages=8192, sleep=0.02)
    finally:
        destination.close()
        source.close()
    shutil.copy2(store.manifest_path, backup_dir / store.manifest_path.name)
    shutil.copy2(store.ontology_path, backup_dir / store.ontology_path.name)
    return database_backup


def _validate_and_export(store, manifest, manifest_path, result):
    transaction = manifest["transaction"]
    validation_datasets = store.load_datasets()
    validation_entities = _entity_index(validation_datasets)
    upsert_ids = {
        entity["id"]
        for entity in transaction["upsert_entities"]
    }
    remaining_deleted = [
        entity_id
        for entity_id in transaction["delete_ids"]
        if entity_id not in upsert_ids
        if entity_id in validation_entities
    ]
    if remaining_deleted:
        raise RuntimeError(
            "Cleanup validation failed; entities remain: " + ", ".join(remaining_deleted[:20])
        )
    kept_ids = {
        item["id"]
        for item in manifest["planets"]["kept_authored"]
    }
    missing_kept = sorted(kept_ids - set(validation_entities))
    if missing_kept:
        raise RuntimeError(
            "Cleanup validation failed; authored planets missing: " + ", ".join(missing_kept)
        )

    invalid_systems = []
    for system_id in manifest["systems"]["systems_repaired"]:
        system = validation_entities.get(system_id) or {}
        star_ids = [
            entity_id
            for entity_id in _relation_ids(system.get("constituents"))
            if _class_key(validation_entities.get(entity_id) or {}) == "star"
        ]
        if not star_ids:
            invalid_systems.append(system_id)
    if invalid_systems:
        raise RuntimeError(
            "Cleanup validation failed; systems lack stars: " + ", ".join(invalid_systems)
        )

    store.export_rdfxml()
    result["validated"] = True
    result["rdfxml_exported"] = str(store.ontology_path)
    result["after_dataset_counts"] = {
        key: len(value)
        for key, value in sorted(validation_datasets.items())
    }
    result_path = manifest_path.with_name(manifest_path.stem + "_result.json")
    result_path.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return result_path.resolve(), result


def apply_manifest(store, manifest_path):
    manifest_path = Path(manifest_path).resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected = manifest["database_signature"]
    actual = store.database_path.stat()
    if (
        actual.st_size != expected["size"]
        or actual.st_mtime_ns != expected["mtime_ns"]
    ):
        raise RuntimeError(
            "The ontology changed after the audit; generate a fresh audit before applying."
        )
    conflicts = manifest["planets"].get("authored_descendant_conflicts") or []
    if conflicts:
        raise RuntimeError(
            "Authored descendants would be orphaned: " + ", ".join(conflicts)
        )

    backup_dir = REPORT_ROOT / f"backup_{_now_slug()}"
    database_backup = _backup_store(store, backup_dir)
    transaction = manifest["transaction"]
    started = time.perf_counter()
    result = store.apply_changes(
        entities=transaction["upsert_entities"],
        remove_entity_ids=transaction["delete_ids"],
    )
    result["elapsed_seconds"] = round(time.perf_counter() - started, 3)
    result["backup_database"] = str(database_backup.resolve())
    return _validate_and_export(store, manifest, manifest_path, result)


def finalize_applied_manifest(store, manifest_path):
    """Validate/export after a commit whose post-check was interrupted."""
    manifest_path = Path(manifest_path).resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    backups = sorted(
        REPORT_ROOT.glob("backup_*"),
        key=lambda path: path.stat().st_mtime_ns,
        reverse=True,
    )
    result = {
        "recovered_after_validation_interruption": True,
        "removed_requested": len(manifest["transaction"]["delete_ids"]),
        "upserted_requested": len(manifest["transaction"]["upsert_entities"]),
        "backup_database": (
            str((backups[0] / store.database_path.name).resolve())
            if backups
            else ""
        ),
    }
    return _validate_and_export(store, manifest, manifest_path, result)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--audit", action="store_true")
    parser.add_argument("--apply", metavar="MANIFEST")
    parser.add_argument("--finalize", metavar="MANIFEST")
    parser.add_argument("--output")
    args = parser.parse_args()
    if not args.audit and not args.apply and not args.finalize:
        parser.error("choose --audit, --apply MANIFEST, or --finalize MANIFEST")

    store = PersistentOntologyStore(ONTOLOGY_PATH)
    if args.audit:
        manifest = build_audit(store)
        path = _write_manifest(manifest, args.output)
        print(path)
        print(json.dumps({
            "planets_audited": manifest["planets"]["audited"],
            "planets_kept": len(manifest["planets"]["kept_authored"]),
            "planets_removed": len(manifest["planets"]["removed_generated_only"]),
            "dependents_removed": len(manifest["planets"]["generated_dependents_removed"]),
            "authored_descendant_conflicts": manifest["planets"]["authored_descendant_conflicts"],
            "systems_audited": manifest["systems"]["systems_audited"],
            "stars_created": len(manifest["systems"]["stars_created"]),
            "materials_audited": manifest["materials"]["persistent_records_audited"],
            "material_unresolved_after": manifest["materials"]["persistent_unresolved_natural_materials"],
        }, indent=2))
        return
    if args.apply:
        result_path, result = apply_manifest(store, args.apply)
    else:
        result_path, result = finalize_applied_manifest(store, args.finalize)
    print(result_path)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
