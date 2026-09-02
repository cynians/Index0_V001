"""Author the vehicle/crew placeholders used by the Formation Sim prototype."""

from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from world.persistent_ontology_store import PersistentOntologyStore


FORMATION_ID = "form_heeresgruppe_1"
TEST_FORMATION_ID = "form_test_formation_armed_forces"


def placeholder_vehicles():
    common = {
        "_dataset": "vehicles",
        "type": "vehicle",
        "entry_status": "draft",
        "card_image_side": "placeholder:formation_side_profile",
    }
    return [
        {
            **common,
            "id": "veh_test_army_jeep",
            "name": "Test Army Jeep",
            "pretty_name": "Test Army Jeep",
            "vehicle_class": "ground_vehicle",
            "formation_display_profile": "jeep",
            "crew_complement": 2,
            "crew_roles": [
                {"role": "Driver", "count": 1},
                {"role": "Gunner", "count": 1},
            ],
            "dimension_length_m": 3.8,
            "dimension_width_m": 1.7,
            "dimension_height_m": 1.9,
            "wiki_entry": "Generic Formation Sim utility vehicle placeholder.",
        },
        {
            **common,
            "id": "veh_test_tank",
            "name": "Test Tank",
            "pretty_name": "Test Tank",
            "vehicle_class": "ground_vehicle",
            "formation_display_profile": "tank",
            "crew_complement": 4,
            "crew_roles": [
                {"role": "Driver", "count": 1},
                {"role": "Loader", "count": 1},
                {"role": "Commander", "count": 1},
                {"role": "Gunner", "count": 1},
            ],
            "dimension_length_m": 7.2,
            "dimension_width_m": 3.6,
            "dimension_height_m": 2.7,
            "wiki_entry": "Generic Formation Sim armored vehicle placeholder.",
        },
        {
            **common,
            "id": "veh_test_spacecraft",
            "name": "Test Spacecraft",
            "pretty_name": "Test Spacecraft",
            "vehicle_class": "interstellar_spacecraft",
            "formation_display_profile": "spacecraft",
            "crew_complement": 1000,
            "crew_roles": [
                {"role": "Command", "count": 20},
                {"role": "Navigation", "count": 120},
                {"role": "Engineering", "count": 300},
                {"role": "Operations", "count": 400},
                {"role": "Support", "count": 160},
            ],
            "dimension_length_m": 600.0,
            "dimension_width_m": 120.0,
            "dimension_height_m": 80.0,
            "wiki_entry": "Generic Formation Sim large-crew spacecraft placeholder.",
        },
        {
            **common,
            "id": "veh_test_exosuit",
            "name": "Test Exosuit",
            "pretty_name": "Test Exosuit",
            "vehicle_class": "exosuit",
            "formation_display_profile": "exosuit",
            "crew_complement": 1,
            "crew_roles": [{"role": "Operator", "count": 1}],
            "dimension_length_m": 0.8,
            "dimension_width_m": 0.7,
            "dimension_height_m": 2.2,
            "wiki_entry": "Generic Formation Sim worn exosuit placeholder.",
        },
    ]


def author_placeholders(ontology_path=None):
    store = PersistentOntologyStore(ontology_path or PROJECT_ROOT / "ontology" / "index0.owl")
    datasets = store.load_datasets()
    formations = datasets.get("formations", [])
    formation = next(entity for entity in formations if entity.get("id") == FORMATION_ID)
    test_formation = next(
        (entity for entity in formations if entity.get("id") == TEST_FORMATION_ID),
        {
            "id": TEST_FORMATION_ID,
            "_dataset": "formations",
            "type": "formation",
            "name": "Test Formation Armed Forces",
            "pretty_name": "Test Formation Armed Forces",
            "entry_status": "draft",
        },
    )
    vehicles = placeholder_vehicles()
    vehicle_ids = [vehicle["id"] for vehicle in vehicles]

    # These are catalog cards only. They must become visible in a Formation
    # Sim only after a formation explicitly assigns them through ``vehicles``
    # (or a vehicle explicitly points back through ``operated_by``/``operators``).
    test_formation["vehicles"] = []
    formation["vehicles"] = []

    # Keep the two formations the user already authored as siblings under the
    # new test root. Future formations created from that root will follow the
    # same parent relation and can be reordered in the Formation Sim.
    for entity in formations:
        if entity.get("id") in {"form_test_airforce", "form_test_army"}:
            entity["parents"] = [TEST_FORMATION_ID]
            entity["formation_order"] = 0 if entity.get("id") == "form_test_airforce" else 1

    schema = next(
        entity for entity in datasets.get("schemas", [])
        if entity.get("id") == "schema_vehicle"
    )
    fields = dict(schema.get("fields") or {})
    fields.update(
        {
            "crew_complement": {"type": "number", "optional": True},
            "crew_roles": {"type": "object_list", "section": "Crew", "optional": True},
            "card_image_side": {"type": "string", "section": "Media", "optional": True},
            "formation_display_profile": {"type": "string", "section": "Formation Sim", "optional": True},
        }
    )
    schema["fields"] = fields
    store.persist_entities(vehicles + [formation, test_formation, schema] + [
        entity for entity in formations
        if entity.get("id") in {"form_test_airforce", "form_test_army"}
    ])
    return vehicle_ids


if __name__ == "__main__":
    print("Authored:", ", ".join(author_placeholders()))
