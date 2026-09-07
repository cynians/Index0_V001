"""Author the first Formation Blueprint and its placeholder equipment cards."""

from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from world.persistent_ontology_store import PersistentOntologyStore


TEST_FORMATION_ID = "form_test_formation_armed_forces"
BLUEPRINT_ID = "form_blueprint_infantry_group"


def placeholder_factions():
    return [
        {
            "id": "fac_test_military_a",
            "_dataset": "factions",
            "type": "faction",
            "entry_status": "draft",
            "name": "Test Military Faction A",
            "pretty_name": "Test Military Faction A",
            "wiki_entry": "Generic Formation Sim faction placeholder A.",
        },
        {
            "id": "fac_test_military_b",
            "_dataset": "factions",
            "type": "faction",
            "entry_status": "draft",
            "name": "Test Military Faction B",
            "pretty_name": "Test Military Faction B",
            "wiki_entry": "Generic Formation Sim faction placeholder B.",
        },
    ]


def placeholder_items():
    return [
        {
            "id": "item_test_assault_rifle",
            "_dataset": "items",
            "type": "item",
            "entry_status": "draft",
            "name": "Test Assault Rifle",
            "pretty_name": "Test Assault Rifle",
            "categories": ["cat_small_arm"],
            "start_year": 2300,
            "wiki_entry": "Generic Formation Blueprint small-arms placeholder.",
        },
        {
            "id": "item_test_light_machine_gun",
            "_dataset": "items",
            "type": "item",
            "entry_status": "draft",
            "name": "Test Light Machine Gun",
            "pretty_name": "Test Light Machine Gun",
            "categories": ["cat_small_arm"],
            "start_year": 2350,
            "wiki_entry": "Generic Formation Blueprint automatic-weapon placeholder.",
        },
        {
            "id": "item_test_new_assault_rifle",
            "_dataset": "items",
            "type": "item",
            "entry_status": "draft",
            "name": "Test New Assault Rifle",
            "pretty_name": "Test New Assault Rifle",
            "categories": ["cat_small_arm"],
            "start_year": 2401,
            "wiki_entry": "Generic future small-arms placeholder for temporal-view testing.",
        },
    ]


def author_blueprint(ontology_path=None):
    store = PersistentOntologyStore(ontology_path or PROJECT_ROOT / "ontology" / "index0.owl")
    datasets = store.load_datasets()
    formations = datasets.get("formations", [])
    root = next(entity for entity in formations if entity.get("id") == TEST_FORMATION_ID)
    factions = datasets.get("factions", [])
    faction_cards = placeholder_factions()
    faction_by_id = {entity.get("id"): entity for entity in factions}
    for faction in faction_cards:
        existing = faction_by_id.get(faction["id"])
        if existing is not None:
            existing.update(faction)
        else:
            factions.append(faction)
            faction_by_id[faction["id"]] = faction
    items = placeholder_items()
    item_ids = [item["id"] for item in items]

    blueprint = next(
        (entity for entity in formations if entity.get("id") == BLUEPRINT_ID),
        {
            "id": BLUEPRINT_ID,
            "_dataset": "formations",
            "type": "formation",
            "name": "Infantry Group",
            "pretty_name": "Infantry Group",
            "entry_status": "draft",
        },
    )
    blueprint.update(
        {
            "name": "Faction A Infantry Group",
            "pretty_name": "Faction A Infantry Group",
            "formation_kind": "blueprint",
            "faction": "fac_test_military_a",
            "blueprint_items": item_ids,
            "wiki_entry": (
                "A draft Formation Blueprint for a general infantry force.\n"
                "Equipment is intentionally represented by placeholder item cards."
            ),
        }
    )
    blueprint.setdefault(
        "formation_snapshots",
        [
            {
                "start_year": 2400,
                "end_year": 2400,
                "state": {
                    "personnel": blueprint.get("personnel"),
                    "blueprint_items": item_ids,
                    "organization": [],
                },
            }
        ],
    )

    linked_blueprints = list(root.get("blueprints") or [])
    if BLUEPRINT_ID not in linked_blueprints:
        linked_blueprints.append(BLUEPRINT_ID)
    root["blueprints"] = linked_blueprints

    schema = next(
        entity for entity in datasets.get("schemas", [])
        if entity.get("id") == "schema_formation"
    )
    fields = dict(schema.get("fields") or {})
    fields.update(
        {
            "formation_kind": {
                "type": "string",
                "section": "Formation Sim",
                "optional": True,
            },
            "blueprint": {
                "type": "entity",
                "target": "formation",
                "section": "Formation Sim",
                "optional": True,
            },
            "blueprints": {
                "type": "entity_list",
                "target": "formation",
                "section": "Formation Sim",
                "optional": True,
            },
            "blueprint_items": {
                "type": "entity_list",
                "target": "items",
                "section": "Formation Sim",
                "optional": True,
            },
            "equipment_items": {
                "type": "entity_list",
                "target": "items",
                "section": "Formation Sim",
                "optional": True,
            },
            "sub_blueprints": {
                "type": "entity_list",
                "target": "formation",
                "section": "Formation Sim",
                "optional": True,
            },
            "designed_for": {
                "type": "entity",
                "target": "formation",
                "section": "Formation Sim",
                "optional": True,
            },
            "personnel": {
                "type": "number",
                "section": "Formation Sim",
                "optional": True,
            },
            "formation_snapshots": {
                "type": "object_list",
                "section": "Formation Sim",
                "optional": True,
            },
        }
    )
    schema["fields"] = fields
    if not store.persist_entities(items + faction_cards + [blueprint, root, schema]):
        raise RuntimeError("Unable to persist Infantry Group blueprint placeholders")
    return BLUEPRINT_ID, item_ids, [faction["id"] for faction in faction_cards]


if __name__ == "__main__":
    blueprint_id, item_ids, faction_ids = author_blueprint()
    print("Authored blueprint:", blueprint_id)
    print("Authored items:", ", ".join(item_ids))
    print("Authored factions:", ", ".join(faction_ids))
