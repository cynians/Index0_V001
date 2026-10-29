"""Author need tags and their examples (Person Sim slice N1, then rest).

Need tags are ordinary tag entities with ``tag_class: need`` (see
world/need_tags.py). This tool adds the fields the resolver reads to their
schemas, the Food tag family, a Food tag on the Foodstuff category, and one
example of each way a thing can be food for a hungry person:

    Chips Bag          an item tagged Snack
    Vending Machine    an installed item that dispenses Chips Bags
    Fishmonger         a job that hands out Smoked Fish, held by Ivo Brann
    Black Crowberry    a species whose harvest yields Crowberries

and for rest: the Rest tag family, a Bed and a Bench with their
``rest_quality``, and four beds in the lumber site's barracks.

Existing entities (schemas, Foodstuff, the crowberry species) are merged
over their full stored dict, because ``apply_changes`` replaces an entity's
properties wholesale. See docs/person_simulation_concept_v001.md section 5.

Dry run by default; ``--apply`` writes.
"""

import argparse
import copy
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.author_item_component_model import SCHEMA_ITEM_FIELDS
from tools.author_job_production_model import JOB_FIELDS
from world.need_tags import NEEDS
from world.persistent_ontology_store import PersistentOntologyStore


ONTOLOGY_PATH = PROJECT_ROOT / "ontology" / "index0.owl"

TAG_FIELDS = {
    "serves_need": {
        "type": "string", "section": "Need", "optional": True,
        "description": (
            f"For tag_class 'need': the need this tag serves ({', '.join(NEEDS)}). "
            "A need tag without it inherits the need of its parent tag."
        ),
    },
}

SPECIES_FIELDS = {
    "harvest_yields": {
        "type": "entity_list", "target": "items", "section": "Use", "optional": True,
        "description": "Items a person can gather from a living plant of this species, e.g. its berries.",
    },
}

SCHEMA_FIELDS = {
    "schema_tags": TAG_FIELDS,
    "schema_item": {
        "dispenses_items": SCHEMA_ITEM_FIELDS["dispenses_items"],
        "rest_quality": SCHEMA_ITEM_FIELDS["rest_quality"],
    },
    "schema_job": {"hands_out_items": JOB_FIELDS["hands_out_items"]},
    "schema_species": SPECIES_FIELDS,
}

FOOD_TAG_COLORS = {"primary_color": "#c49a4f", "secondary_color": "#3a2e1c"}
REST_TAG_COLORS = {"primary_color": "#6f8fc4", "secondary_color": "#1e2a3c"}

NEW_ENTITIES = [
    {
        "id": "tag_need_food", "_dataset": "tags", "type": "tag",
        "name": "Food", "pretty_name": "Food", "tag_class": "need", "serves_need": "food",
        "wiki_entry": "Anything a hungry person can eat, or get something to eat from.",
        **FOOD_TAG_COLORS,
    },
    {
        "id": "tag_need_snack", "_dataset": "tags", "type": "tag",
        "name": "Snack", "pretty_name": "Snack", "tag_class": "need", "parents": ["tag_need_food"],
        "wiki_entry": "Small packaged food eaten between meals; seldom filling.",
        **FOOD_TAG_COLORS,
    },
    {
        "id": "tag_need_fish", "_dataset": "tags", "type": "tag",
        "name": "Fish", "pretty_name": "Fish", "tag_class": "need", "parents": ["tag_need_food"],
        "wiki_entry": "Fish prepared to eat.",
        **FOOD_TAG_COLORS,
    },
    {
        "id": "tag_need_berries", "_dataset": "tags", "type": "tag",
        "name": "Berries", "pretty_name": "Berries", "tag_class": "need", "parents": ["tag_need_food"],
        "wiki_entry": "Small fruit picked and eaten raw.",
        **FOOD_TAG_COLORS,
    },
    {
        "id": "tag_need_rest", "_dataset": "tags", "type": "tag",
        "name": "Rest", "pretty_name": "Rest", "tag_class": "need", "serves_need": "rest",
        "wiki_entry": "Anything a tired person can rest on or in.",
        **REST_TAG_COLORS,
    },
    {
        "id": "tag_need_bed", "_dataset": "tags", "type": "tag",
        "name": "Bed", "pretty_name": "Bed", "tag_class": "need", "parents": ["tag_need_rest"],
        "wiki_entry": "Something to lie down and sleep on.",
        **REST_TAG_COLORS,
    },
    {
        "id": "tag_need_seat", "_dataset": "tags", "type": "tag",
        "name": "Seat", "pretty_name": "Seat", "tag_class": "need", "parents": ["tag_need_rest"],
        "wiki_entry": "Something to sit on for a while; rest, not sleep.",
        **REST_TAG_COLORS,
    },
    {
        "id": "item_bed", "_dataset": "items", "type": "item",
        "name": "Bed", "pretty_name": "Bed",
        "categories": ["cat_manufactured_good"], "tags": ["Bed"], "rest_quality": 1.0,
        "portable": "team", "placeable": True, "install_contexts": ["building interior"],
        "mass_kg": 40, "dimension_length_m": 2.0, "dimension_width_m": 0.9, "dimension_height_m": 0.5,
        "wiki_entry": "A plain single bed with a mattress.",
    },
    {
        "id": "item_bench", "_dataset": "items", "type": "item",
        "name": "Bench", "pretty_name": "Bench",
        "categories": ["cat_manufactured_good"], "tags": ["Seat"], "rest_quality": 0.35,
        "portable": "team", "placeable": True, "install_contexts": ["building interior", "site"],
        "mass_kg": 25, "dimension_length_m": 1.6, "dimension_width_m": 0.4, "dimension_height_m": 0.45,
        "wiki_entry": "A wooden bench. Somewhere to sit down for a while, not to sleep.",
    },
    {
        "id": "item_chips_bag", "_dataset": "items", "type": "item",
        "name": "Chips Bag", "pretty_name": "Chips Bag",
        "categories": ["cat_prepared_food"], "tags": ["Snack"],
        "consumable": True, "food_energy_kcal": 530, "food_satiation": 15,
        "mass_kg": 0.1, "portable": "hand", "default_unit": "bag",
        "wiki_entry": "A sealed bag of fried potato chips. Quick to eat, not very filling.",
    },
    {
        "id": "item_smoked_fish", "_dataset": "items", "type": "item",
        "name": "Smoked Fish", "pretty_name": "Smoked Fish",
        "categories": ["cat_prepared_food"], "tags": ["Fish"],
        "consumable": True, "food_energy_kcal": 400, "food_satiation": 45,
        "mass_kg": 0.2, "portable": "hand", "default_unit": "fish",
        "wiki_entry": "A whole smoked fish, ready to eat.",
    },
    {
        "id": "item_crowberries", "_dataset": "items", "type": "item",
        "name": "Crowberries", "pretty_name": "Crowberries",
        "categories": ["cat_foodstuff"], "tags": ["Berries"],
        "consumable": True, "food_energy_kcal": 50, "food_satiation": 6,
        "mass_kg": 0.1, "portable": "hand", "default_unit": "handful",
        "wiki_entry": "A handful of black crowberries picked from the shrub. Watery and mild.",
    },
    {
        "id": "item_vending_machine", "_dataset": "items", "type": "item",
        "name": "Vending Machine", "pretty_name": "Vending Machine",
        "categories": ["cat_manufactured_good"],
        "dispenses_items": ["item_chips_bag"],
        "portable": "fixed", "placeable": True, "install_contexts": ["building interior", "site"],
        "mass_kg": 300, "dimension_length_m": 0.9, "dimension_width_m": 0.8, "dimension_height_m": 1.8,
        "wiki_entry": "A coin-free test machine that hands out a bag of chips when operated, while stocked.",
    },
    {
        "id": "job_fishmonger", "_dataset": "jobs", "type": "job",
        "name": "Fishmonger", "pretty_name": "Fishmonger", "job_class": "food retail",
        "hands_out_items": ["item_smoked_fish"],
        "exchange_doctrine": "Hands a fish to anyone who asks while stock lasts; no payment in this test.",
        "job_criticality": 0.5,
    },
    {
        "id": "person_test_fishmonger", "_dataset": "people", "type": "person",
        "name": "Ivo Brann", "pretty_name": "Ivo Brann", "sex": "male", "person_class": "worker",
        "is_employed_as": "job_fishmonger",
        "wiki_entry": "Test fishmonger for the Person Sim need-satisfaction examples.",
    },
]

# Fields merged onto entities that already exist.
MERGES = {
    "cat_foodstuff": {"tags": ["Food"]},
    "spec_empetrum_nigrum": {"harvest_yields": ["item_crowberries"]},
    "location_lumber_test_barracks": {"inventory_items": [{"item": "item_bed", "quantity": 4, "unit": "bed"}]},
}


def _merged_list(existing, additions):
    values = list(existing or [])
    values.extend(value for value in additions if value not in values)
    return values


def build_changes(datasets):
    by_id = {
        entity.get("id"): entity
        for entities in datasets.values() if isinstance(entities, list)
        for entity in entities if isinstance(entity, dict)
    }
    changes = []
    for schema_id, fields in SCHEMA_FIELDS.items():
        schema = copy.deepcopy(by_id[schema_id])
        schema["fields"] = {**(schema.get("fields") or {}), **copy.deepcopy(fields)}
        changes.append(schema)

    for entity_id, fields in MERGES.items():
        entity = copy.deepcopy(by_id[entity_id])
        for field_name, value in fields.items():
            entity[field_name] = _merged_list(entity.get(field_name), value) if isinstance(value, list) else value
        changes.append(entity)

    for entity in NEW_ENTITIES:
        existing = by_id.get(entity["id"])
        changes.append({**copy.deepcopy(existing), **entity} if existing else copy.deepcopy(entity))
    return changes


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true", help="Write to the ontology store; default is a dry run")
    args = parser.parse_args(argv)

    store = PersistentOntologyStore(ONTOLOGY_PATH)
    changes = build_changes(store.load_datasets())
    for change in changes:
        print(f"{change['id']}: {len(change)} fields")
    if not args.apply:
        print(f"Dry run: {len(changes)} entities would be written")
        return
    result = store.apply_changes(entities=changes)
    print(f"Authored {result['upserted']} need-tag ontology entities")


if __name__ == "__main__":
    main()
