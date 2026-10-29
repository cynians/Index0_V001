"""Safely author reviewed fields on an existing plant or supported fungus.

This command replaces one-off ``tools/author_<species>.py`` scripts for
routine species-card updates.  It is deliberately limited to existing plant
taxa and verified fungi with an explicit surface or bracket recipe: identity
changes, taxonomy migrations, and custom asset generation need
their own explicitly reviewed workflows.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any, Iterable, Mapping, TextIO

from world.persistent_ontology_store import PersistentOntologyStore
from world.plant_catalogue import PlantCatalogue
from world.plant_growth_catalog import controlled_plant_field_rows
from world.plant_traits import (
    PLANT_ARCHITECTURE_RANGE_FIELDS,
    PLANT_TRAIT_SCHEMA_FIELDS,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ONTOLOGY_PATH = PROJECT_ROOT / "ontology" / "index0.owl"

# The process also maintains the species' prose entry.  Identity, presentation,
# taxonomy, and dataset metadata are intentionally absent from this allow-list.
ALLOWED_NON_TRAIT_FIELDS = frozenset({"wiki_entry"})
ALLOWED_UPDATE_FIELDS = frozenset(PLANT_TRAIT_SCHEMA_FIELDS) | ALLOWED_NON_TRAIT_FIELDS
PROTECTED_FIELDS = frozenset(
    {
        "id",
        "parents",
        "type",
        "_dataset",
        "name",
        "pretty_name",
        "common_name",
        "binomial_name",
        "species_class",
    }
)
PROVENANCE_FIELDS = ("inferred_field_sources", "inference_conflicts")


class AuthoringError(ValueError):
    """Raised when an authoring request would violate the tool contract."""


def _all_entities(datasets: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    entities: dict[str, dict[str, Any]] = {}
    for rows in datasets.values():
        if not isinstance(rows, list):
            continue
        for row in rows:
            if isinstance(row, dict) and row.get("id"):
                entities[str(row["id"])] = row
    return entities


def _species_row(datasets: Mapping[str, Any], species_id: str) -> dict[str, Any] | None:
    return next(
        (
            row
            for row in datasets.get("species", [])
            if isinstance(row, dict) and row.get("id") == species_id
        ),
        None,
    )


def _read_payload(input_path: str | None, updates_json: str | None, stdin: TextIO) -> dict[str, Any]:
    if updates_json is not None:
        source = "--updates-json"
        text = updates_json
    elif input_path and input_path != "-":
        source = input_path
        try:
            text = Path(input_path).read_text(encoding="utf-8")
        except OSError as exc:
            raise AuthoringError(f"Could not read update payload {input_path}: {exc}") from exc
    else:
        source = "stdin"
        text = stdin.read()

    if not text.strip():
        raise AuthoringError(f"No JSON update payload received from {source}")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise AuthoringError(f"Invalid JSON update payload from {source}: {exc}") from exc
    if not isinstance(payload, dict):
        raise AuthoringError("The update payload must be a JSON object")
    return payload


def parse_updates(payload: Mapping[str, Any], species_id: str) -> dict[str, Any]:
    """Accept either a raw field mapping or a labelled update envelope."""

    if "updates" not in payload:
        return dict(payload)

    unexpected = set(payload) - {"species_id", "updates"}
    if unexpected:
        raise AuthoringError(
            "Update envelope has unsupported keys: " + ", ".join(sorted(unexpected))
        )
    payload_species_id = str(payload.get("species_id") or "").strip()
    if payload_species_id and payload_species_id != species_id:
        raise AuthoringError(
            f"Payload species_id {payload_species_id!r} does not match {species_id!r}"
        )
    updates = payload.get("updates")
    if not isinstance(updates, dict):
        raise AuthoringError("The update envelope's 'updates' value must be an object")
    return dict(updates)


def _validate_json_numbers(value: Any, field_name: str) -> None:
    if isinstance(value, bool) or value is None or isinstance(value, (str, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise AuthoringError(f"{field_name} contains a non-finite number")
        return
    if isinstance(value, list):
        for item in value:
            _validate_json_numbers(item, field_name)
        return
    if isinstance(value, dict):
        for item in value.values():
            _validate_json_numbers(item, field_name)
        return
    raise AuthoringError(f"{field_name} contains a non-JSON value of type {type(value).__name__}")


def _validate_schema_type(field_name: str, value: Any) -> None:
    expected = PLANT_TRAIT_SCHEMA_FIELDS[field_name]["type"]
    valid = {
        "string": isinstance(value, str),
        "number": isinstance(value, (int, float)) and not isinstance(value, bool),
        "dict": isinstance(value, dict),
        "string_list": isinstance(value, list) and all(isinstance(item, str) for item in value),
    }.get(expected, True)
    if not valid:
        raise AuthoringError(
            f"{field_name} must have schema type {expected}; got {type(value).__name__}"
        )


def _validate_controlled_value(field_name: str, value: Any) -> None:
    rows = controlled_plant_field_rows(field_name)
    choices = {str(row["value"]) for row in rows if row.get("kind") != "heading" and "value" in row}
    if choices and value not in choices:
        allowed = ", ".join(sorted(choices))
        raise AuthoringError(
            f"{field_name}={value!r} is not an exact live-schema value; allowed: {allowed}"
        )


def _validate_architecture_range(field_name: str, value: Mapping[str, Any]) -> None:
    missing = {"min", "typical", "max"} - set(value)
    if missing:
        raise AuthoringError(
            f"{field_name} must include min, typical, and max; missing: {', '.join(sorted(missing))}"
        )
    numbers = []
    for key in ("min", "typical", "max"):
        number = value[key]
        if isinstance(number, bool) or not isinstance(number, (int, float)) or not math.isfinite(number):
            raise AuthoringError(f"{field_name}.{key} must be a finite number")
        if not 0.0 <= float(number) <= 1.0:
            raise AuthoringError(f"{field_name}.{key} must be between 0.0 and 1.0")
        numbers.append(float(number))
    if numbers != sorted(numbers):
        raise AuthoringError(f"{field_name} must satisfy min <= typical <= max")


def validate_updates(updates: Mapping[str, Any]) -> None:
    profile=updates.get('plant_shoot_profile')
    if isinstance(profile,dict) and profile.get('form')=='mixed_tillers':
        from simulations.species.mixed_tillers import mixed_tiller_profile
        if mixed_tiller_profile(profile) is None:
            raise AuthoringError('Invalid mixed_tillers profile; finite bounded tiller, blade and culm controls required')
    profile=updates.get('plant_shoot_profile')
    if isinstance(profile,dict) and profile.get('form')=='offset_rosettes':
        from simulations.species.offset_rosettes import offset_rosette_profile
        if offset_rosette_profile(profile) is None:
            raise AuthoringError('Invalid offset_rosettes recipe; bounded crown, offset and connector controls required')
    profile=updates.get('plant_shoot_profile')
    if isinstance(profile,dict) and profile.get('form')=='flower_terminated_forks':
        from simulations.species.flower_terminated_forks import fork_profile
        if fork_profile(profile) is None:
            raise AuthoringError('Invalid flower_terminated_forks recipe: finite bounded units, sockets and organ dimensions required')
    if not updates:
        raise AuthoringError("The update payload is empty")
    if isinstance(updates.get('surface_growth_profile'), dict) and 'atmospheric_tolerance' in updates['surface_growth_profile']:
        from simulations.species.surface_atmosphere import validate_atmospheric_tolerance
        try:
            validate_atmospheric_tolerance(updates['surface_growth_profile']['atmospheric_tolerance'])
        except ValueError as exc:
            raise AuthoringError(str(exc)) from exc
    if "fungal_growth_profile" in updates:
        from world.fungal_traits import validate_fungal_profile
        try:
            validate_fungal_profile(updates["fungal_growth_profile"])
        except ValueError as exc:
            raise AuthoringError(str(exc)) from exc
    protected = set(updates) & PROTECTED_FIELDS
    if protected:
        raise AuthoringError(
            "Identity/taxonomy fields require an explicit migration and cannot be authored here: "
            + ", ".join(sorted(protected))
        )
    unsupported = set(updates) - ALLOWED_UPDATE_FIELDS
    if unsupported:
        raise AuthoringError(
            "Unsupported species-card fields: " + ", ".join(sorted(unsupported))
        )

    for field_name, value in updates.items():
        _validate_json_numbers(value, field_name)
        if field_name == "wiki_entry":
            if not isinstance(value, str):
                raise AuthoringError("wiki_entry must be a string")
            continue
        _validate_schema_type(field_name, value)
        _validate_controlled_value(field_name, value)
        if field_name == "plant_leaf_palette":
            from simulations.species.leaf_palette import leaf_palette
            if leaf_palette(value) is None:
                raise AuthoringError("Invalid leaf palette: mature, shade and pale colours must be RGB bytes")
        if field_name == "plant_reproductive_profile" and "pendant_display" in value:
            from simulations.species.pendant_reproduction import pendant_display_profile
            if pendant_display_profile(value["pendant_display"]) is None:
                raise AuthoringError("Invalid pendant display; bounded stalk lengths, radius and RGB color required")
        if field_name == 'plant_reproductive_profile' and 'fruit_cluster_display' in value:
            from simulations.species.pendant_reproduction import fruit_cluster_profile, pendant_display_profile
            pendant=pendant_display_profile(value.get('pendant_display'))
            if (fruit_cluster_profile(value['fruit_cluster_display']) is None
                    or not pendant or not pendant['fruit_drop_m']):
                raise AuthoringError('Invalid fruit cluster; 1-12 capsules, bounded metre spread and a hanging fruit display required')
        if field_name == "plant_inflorescence_profile" and value.get("form") == "umbellate_head":
            from simulations.species.umbellate_heads import umbellate_head_profile
            if umbellate_head_profile(value) is None:
                raise AuthoringError("Invalid umbellate head; bounded tube/limb dimensions, count and RGB colors required")
        if field_name == "plant_inflorescence_profile" and value.get("form") == "raceme":
            from simulations.species.racemes import raceme_profile
            if raceme_profile(value) is None:
                raise AuthoringError("Invalid raceme display recipe; finite bounded dimensions, count and colors are required")
        if field_name == "plant_inflorescence_profile" and value.get("form") == "capitulum_cluster":
            from simulations.species.capitulum_clusters import capitulum_cluster_profile
            if capitulum_cluster_profile(value) is None:
                raise AuthoringError("Invalid capitulum cluster; bounded dimensions, count, layout and RGB color required")
        if field_name == 'plant_shoot_profile' and value.get('form') == 'leafy_moss':
            from simulations.species.moss_turfs import moss_turf_profile
            if moss_turf_profile(value) is None:
                raise AuthoringError('Invalid leafy_moss recipe; bounded finite shoot, leaf, patch and hair-point controls required')
        if field_name == "plant_shoot_profile" and value.get("form") == "woody_spurs":
            from simulations.species.woody_spurs import woody_spur_profile
            if woody_spur_profile(value) is None:
                raise AuthoringError("Invalid woody spurs profile")
        if field_name == "plant_reproductive_profile" and "persistent_calyx_display" in value:
            from simulations.species.persistent_calyces import persistent_calyx_profile
            if persistent_calyx_profile(value["persistent_calyx_display"]) is None:
                raise AuthoringError("Invalid persistent calyx display profile")
        if field_name == "plant_shoot_profile" and value.get("form") == "columnar_succulent":
            from simulations.species.columnar_succulents import columnar_profile
            if columnar_profile(value) is None:
                raise AuthoringError("Invalid columnar succulent: bounded finite metric dimensions, onset fractions and counts required")
        if field_name == "plant_shoot_profile" and value.get("form") == "terminal_rosette":
            from simulations.species.terminal_rosettes import terminal_rosette_profile
            if terminal_rosette_profile(value) is None:
                raise AuthoringError("Invalid terminal rosette: bounded metric axes, leaves, panicle and counts required")
        if field_name == "plant_shoot_profile" and value.get("form") == "creeping_uprights":
            from simulations.species.creeping_uprights import creeping_upright_profile
            if creeping_upright_profile(value) is None:
                raise AuthoringError("Invalid creeping upright recipe: bounded axes, leaves, spore cones and geometry budget required")
        if field_name == 'plant_shoot_profile' and value.get('form') == 'planar_foliage_sprays':
            from simulations.species.planar_sprays import planar_spray_profile
            if planar_spray_profile(value) is None:
                raise AuthoringError('Invalid planar_foliage_sprays recipe; bounded shoot dimensions, plane angles and group counts required')
        if field_name == 'plant_shoot_profile' and value.get('form') == 'renewing_canes':
            from simulations.species.renewing_canes import renewing_cane_profile
            if renewing_cane_profile(value) is None:
                raise AuthoringError('Invalid renewing_canes recipe; bounded dimensions, counts and ordered model ages required')
        if field_name == "plant_shoot_profile" and value.get("form") == "seasonal_rhizome":
            from simulations.species.seasonal_rhizomes import seasonal_rhizome_profile
            if seasonal_rhizome_profile(value) is None:
                raise AuthoringError("Invalid seasonal rhizome: bounded rhizome, shoot, leaf and count controls required")
        if field_name == "plant_shoot_profile" and value.get("form") == "basal_rosette_raceme":
            from simulations.species.rosette_racemes import rosette_raceme_profile
            if rosette_raceme_profile(value) is None:
                raise AuthoringError("Invalid basal rosette raceme: finite stem radius required")
        if field_name == "plant_shoot_profile" and value.get("form") == "scape_rosette":
            from simulations.species.scape_rosettes import scape_rosette_profile
            if scape_rosette_profile(value) is None:
                raise AuthoringError("Invalid scape rosette: bounded count, radius and spread required")
        if field_name == "plant_root_profile":
            from simulations.species.root_growth import shallow_radial_profile
            if shallow_radial_profile(value) is None:
                raise AuthoringError("Invalid root profile: shallow_radial dimensions and bounded axes required")
        if field_name == "plant_shoot_profile" and value.get("form") == "branched_rosette":
            from simulations.species.rosette_shoots import rosette_shoot_profile
            if rosette_shoot_profile(value) is None:
                raise AuthoringError("Invalid branched_rosette display recipe; all bounded controls are required")
        if field_name == "plant_shoot_profile" and value.get("form") == "woody_axes":
            from simulations.species.woody_axes import woody_axes_profile
            if woody_axes_profile(value) is None:
                raise AuthoringError("Invalid woody_axes recipe; bounded radius ratios, taper exponent and crown base required")
        if field_name == 'plant_shoot_profile' and value.get('form') == 'cushion_subshrub':
            from simulations.species.cushion_subshrubs import cushion_profile
            if cushion_profile(value) is None:
                raise AuthoringError('Invalid cushion_subshrub recipe; bounded dimensions and counts required')
        if field_name == "plant_shoot_profile" and value.get("form") == "basal_subshrub":
            from simulations.species.basal_subshrubs import basal_subshrub_profile
            if basal_subshrub_profile(value) is None:
                raise AuthoringError("Invalid basal_subshrub recipe; bounded crown, radius, leaf width and shoot/node counts required")
        if field_name == "plant_shoot_profile" and value.get("form") == "basal_herb":
            from simulations.species.basal_herbs import basal_herb_profile
            if basal_herb_profile(value) is None:
                raise AuthoringError("Invalid basal_herb recipe; bounded crown, radius, leaf width and shoot/node counts required")
        if field_name == "plant_shoot_profile" and value.get("form") == "emergent_rosette":
            from simulations.species.emergent_rosettes import emergent_rosette_profile
            if emergent_rosette_profile(value) is None:
                raise AuthoringError("Invalid emergent_rosette recipe; finite bounded stalk, blade and scene controls required")
        if field_name == 'plant_shoot_profile' and value.get('form') == 'rhizome_raceme':
            from simulations.species.rhizome_racemes import rhizome_raceme_profile
            if rhizome_raceme_profile(value) is None:
                raise AuthoringError('Invalid rhizome_raceme dimensions or counts')
        if field_name == "plant_shoot_profile" and value.get("form") == "clonal_forb":
            from simulations.species.clonal_forb_profiles import clonal_forb_profile
            if clonal_forb_profile(value) is None:
                raise AuthoringError("Invalid clonal_forb recipe; bounded reach, radius, branching onset and node count required")
        if field_name == "plant_shoot_profile" and value.get("form") == "creeping_herb":
            from simulations.species.creeping_herbs import creeping_herb_profile
            if creeping_herb_profile(value) is None:
                raise AuthoringError("Invalid creeping_herb recipe; finite bounded lengths, widths, counts and recurve required")
        if field_name == "plant_shoot_profile" and value.get("form") == "creeping_woody":
            from simulations.species.creeping_woody import creeping_woody_profile
            if creeping_woody_profile(value) is None:
                raise AuthoringError("Invalid creeping_woody recipe; finite bounded runner, shoot and leaf controls required")
        if field_name == "plant_shoot_profile" and value.get("form") == "dimorphic_herb":
            from simulations.species.dimorphic_herbs import dimorphic_herb_profile
            if dimorphic_herb_profile(value) is None:
                raise AuthoringError("Invalid dimorphic_herb recipe; bounded shoot, leaf and raceme controls required")
        if field_name == 'plant_shoot_profile' and value.get('form') == 'sympodial_herb':
            from simulations.species.sympodial_herbs import sympodial_herb_profile
            if sympodial_herb_profile(value) is None:
                raise AuthoringError('Invalid sympodial_herb recipe; bounded node, lateral and organ controls required')
        if field_name == 'plant_shoot_profile' and value.get('form') == 'paniculate_rosette':
            from simulations.species.paniculate_rosettes import paniculate_rosette_profile
            if paniculate_rosette_profile(value) is None:
                raise AuthoringError('Invalid paniculate_rosette recipe; bounded petiole, shoot and panicle controls required')
        if field_name == 'plant_shoot_profile' and value.get('form') == 'tufted_sedge':
            from simulations.species.tufted_sedges import tufted_sedge_profile
            if tufted_sedge_profile(value) is None:
                raise AuthoringError('Invalid tufted_sedge recipe; finite bounded culm, blade, bract, ray and spikelet controls required')
        if field_name=='plant_shoot_profile' and value.get('form')=='branched_vine':
            from simulations.species.vine_organs import branched_vine_profile
            if branched_vine_profile(value) is None:
                raise AuthoringError('Invalid branched_vine recipe; finite bounded spacing, lateral and ground-posture controls required')
        if field_name=='plant_shoot_profile' and value.get('form')=='pleiochasial_herb':
            from simulations.species.cyme_herbs import cyme_herb_profile
            if cyme_herb_profile(value) is None:
                raise AuthoringError('Invalid pleiochasial_herb recipe; finite bounded shoots, leaves, bracts, rays and fork controls required')
        if field_name in PLANT_ARCHITECTURE_RANGE_FIELDS:
            _validate_architecture_range(field_name, value)


def prepare_update(
    datasets: Mapping[str, Any], species_id: str, updates: Mapping[str, Any]
) -> tuple[dict[str, Any], dict[str, dict[str, Any]], set[str]]:
    validate_updates(updates)
    entities = _all_entities(datasets)
    catalogue = PlantCatalogue.build(entities)
    # A lichen body recipe can be authored on a verified fungal species.
    # This does not broaden Plantae membership or permit arbitrary animals.
    fungal = PlantCatalogue.build(entities, root_id="cladis_fungi")
    proposed = {**entities.get(species_id, {}), **updates}
    surface_lichen = (fungal.is_species(species_id)
                      and proposed.get("plant_growth_form") == "lichen"
                      and proposed.get("plant_growth_behaviour") == "surface_covering"
                      and isinstance(proposed.get("surface_growth_profile"), dict)
                      and bool(proposed["surface_growth_profile"]))
    bracket_fungus = fungal.is_species(species_id) and bool(proposed.get("fungal_growth_profile"))
    if bracket_fungus:
        from world.fungal_traits import validate_fungal_profile
        validate_fungal_profile(proposed["fungal_growth_profile"])
    if proposed.get("fungal_growth_profile") and not fungal.is_species(species_id):
        raise AuthoringError("Fungal body recipes require verified Fungi ancestry")
    if not catalogue.is_species(species_id) and not surface_lichen and not bracket_fungus:
        if species_id in entities:
            raise AuthoringError(f"{species_id} is not a species below cladis_plants_plantae")
        raise AuthoringError(f"The live ontology has no plant species {species_id}")

    original = _species_row(datasets, species_id)
    if original is None:
        raise AuthoringError(f"Plant catalogue contains {species_id}, but its species row is missing")
    entity = deepcopy(original)
    changed_fields: set[str] = set(updates)
    diff: dict[str, dict[str, Any]] = {}
    for field_name, value in updates.items():
        diff[field_name] = {"before": original.get(field_name), "after": value}
        entity[field_name] = deepcopy(value)

    for provenance_field in PROVENANCE_FIELDS:
        before = entity.get(provenance_field)
        if not isinstance(before, dict):
            continue
        after = deepcopy(before)
        for field_name in updates:
            after.pop(field_name, None)
        if after != before:
            entity[provenance_field] = after
            changed_fields.add(provenance_field)

    if entity.get("id") != original.get("id") or entity.get("parents") != original.get("parents"):
        raise AuthoringError("Refusing to change species identity or taxonomy")
    return entity, diff, changed_fields


def _verify_reloaded(
    store: PersistentOntologyStore,
    species_id: str,
    entity: Mapping[str, Any],
    changed_fields: Iterable[str],
) -> None:
    saved = _species_row(store.load_datasets(), species_id)
    if saved is None:
        raise RuntimeError(f"Persisted species {species_id} was not present after reload")
    for field_name in changed_fields:
        if saved.get(field_name) != entity.get(field_name):
            raise RuntimeError(
                f"Reload verification failed for {field_name}: "
                f"saved={saved.get(field_name)!r}, expected={entity.get(field_name)!r}"
            )


def author_species(
    store: PersistentOntologyStore,
    species_id: str,
    updates: Mapping[str, Any],
    *,
    apply: bool = False,
    export_checkpoint: bool = False,
) -> dict[str, Any]:
    if export_checkpoint and not apply:
        raise AuthoringError("--export-checkpoint requires --apply")
    entity, diff, changed_fields = prepare_update(store.load_datasets(), species_id, updates)
    result: dict[str, Any] = {
        "species_id": species_id,
        "status": "dry_run",
        "changed_field_count": len(diff),
        "diff": diff,
    }
    if not apply:
        return result

    if not store.persist_entity_fields(entity, changed_fields):
        raise RuntimeError(f"Could not persist reviewed fields for {species_id}")
    _verify_reloaded(store, species_id, entity, changed_fields)
    result["status"] = "persisted_and_reloaded"
    result["persisted_fields"] = sorted(changed_fields)
    if export_checkpoint:
        store.export_rdfxml(store.ontology_path)
        result["checkpoint"] = str(store.ontology_path)
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Dry-run, validate, persist, and verify reviewed fields on an existing plant species."
    )
    parser.add_argument("species_id", help="Stable ID of an existing eligible plant or fungal species")
    source = parser.add_mutually_exclusive_group()
    source.add_argument(
        "--input",
        metavar="PATH",
        help="JSON field mapping or update envelope; use '-' for stdin (the default)",
    )
    source.add_argument("--updates-json", help="Inline JSON field mapping or update envelope")
    parser.add_argument("--apply", action="store_true", help="Persist after validation; default is dry-run")
    parser.add_argument(
        "--export-checkpoint",
        action="store_true",
        help="Export ontology/index0.owl after a verified apply",
    )
    parser.add_argument(
        "--ontology",
        type=Path,
        default=DEFAULT_ONTOLOGY_PATH,
        help=argparse.SUPPRESS,
    )
    return parser


def main(argv: list[str] | None = None, *, stdin: TextIO = sys.stdin) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        payload = _read_payload(args.input, args.updates_json, stdin)
        updates = parse_updates(payload, args.species_id)
        store = PersistentOntologyStore(args.ontology)
        result = author_species(
            store,
            args.species_id,
            updates,
            apply=args.apply,
            export_checkpoint=args.export_checkpoint,
        )
    except (AuthoringError, RuntimeError) as exc:
        parser.exit(2, f"error: {exc}\n")
    print(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
