"""Author two more test craft for the debug collection: an orbital tug and a long-range craft.

Verification designs beside ``tools/create_test_craft_pathfinder.py``, so the
transfer panel's check (``docs/collection_simulation_concept_v001.md``
section 5) has craft that fail for different reasons:

- **Shuttler** (orbital spacecraft): plenty of delta-v for its size, orbital
  shielding and a month of life support -- fails every interplanetary window
  on shielding, and the long ones on life support too.
- **Longreach** (system spacecraft): nuclear-thermal engines at 900 s and four
  years of life support -- reaches the asteroid belt and Mercury, which
  Pathfinder cannot.

Both are tagged ``test craft``, so ``coll_debug_test_spacecraft`` picks them up
by its rule. Writes the parts and the vehicles in one ``apply_changes``;
re-running replaces them. ``--dry-run`` builds and checks without writing.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from simulations.logistics.vehicle_profiles import space_profile_from_design
from simulations.vehicle.vehicle_design import VehicleDesignController
from tools.create_test_craft_pathfinder import YEAR_S, _component, world_for
from world.persistent_ontology_store import PersistentOntologyStore

ONTOLOGY_PATH = PROJECT_ROOT / "ontology" / "index0.owl"
BACKUP_ROOT = PROJECT_ROOT / "artifacts" / "test_craft_fleet"
DAY_S = 86_400.0


def shuttler_parts():
    return [
        _component(
            "comp_test_shuttler_engine", "Shuttler Hypergolic Engine", 400.0, (1.8, 1.0, 1.0),
            ["propulsion_space"], ["main_engine"],
            thrust_n=200_000.0, specific_impulse_s=340.0,
            inputs=[{"resource_type": "fuel", "label": "Propellant"}],
            outputs=[{"resource_type": "thrust", "label": "Thrust"}],
        ),
        _component(
            "comp_test_shuttler_tank", "Shuttler Propellant Tank", 600.0, (4.0, 3.0, 3.0),
            ["fuel_storage"], ["propellant_storage"],
            propellant_capacity_kg=12_000.0,
            outputs=[{"resource_type": "fuel", "label": "Propellant"}],
        ),
        _component(
            "comp_test_shuttler_cabin", "Shuttler Crew Cabin", 800.0, (3.0, 3.0, 2.5),
            ["control", "life_support"], ["flight_control", "life_support"],
            life_support_s=30.0 * DAY_S,
            outputs=[{"resource_type": "control_signal", "label": "Flight Control"}],
        ),
        _component(
            "comp_test_shuttler_docking_collar", "Shuttler Docking Collar", 300.0, (1.0, 1.8, 1.8),
            ["docking"], ["docking"],
            docking=True,
        ),
    ]


def longreach_parts():
    return [
        _component(
            "comp_test_longreach_ntr_engine", "Longreach Nuclear-Thermal Engine", 3500.0, (6.0, 2.0, 2.0),
            ["propulsion_space"], ["main_engine"],
            thrust_n=250_000.0, specific_impulse_s=900.0,
            inputs=[{"resource_type": "fuel", "label": "Hydrogen"}],
            outputs=[{"resource_type": "thrust", "label": "Thrust"}],
        ),
        _component(
            "comp_test_longreach_hydrogen_tank", "Longreach Hydrogen Tank", 6000.0, (16.0, 9.0, 9.0),
            ["fuel_storage"], ["propellant_storage"],
            propellant_capacity_kg=60_000.0,
            outputs=[{"resource_type": "fuel", "label": "Hydrogen"}],
        ),
        _component(
            "comp_test_longreach_habitat", "Longreach Long-Duration Habitat", 15000.0, (9.0, 9.0, 9.0),
            ["life_support", "crew_accommodation"], ["crew_habitat", "life_support"],
            life_support_s=4.0 * YEAR_S,
        ),
        _component(
            "comp_test_longreach_storm_shelter", "Longreach Radiation Storm Shelter", 10000.0, (5.0, 7.0, 7.0),
            ["radiation_shielding"], ["radiation_shielding"],
            shielding_class="deep_space",
        ),
        _component(
            "comp_test_longreach_docking_port", "Longreach Docking Port", 600.0, (1.5, 2.0, 2.0),
            ["docking"], ["docking"],
            docking=True,
        ),
        _component(
            "comp_test_longreach_flight_deck", "Longreach Flight Deck", 1500.0, (2.5, 4.0, 3.0),
            ["control"], ["flight_control"],
            outputs=[{"resource_type": "control_signal", "label": "Flight Control"}],
        ),
    ]


def _vehicle(vehicle_id, name, vehicle_class, size_m, parts, placements, description, structure):
    length, width, height = size_m
    vehicle = {
        "id": vehicle_id, "name": name, "pretty_name": name, "description": description,
        "type": "vehicle", "_dataset": "vehicles", "vehicle_class": vehicle_class,
        "dimension_length_m": length, "dimension_width_m": width, "dimension_height_m": height,
        "component_catalog": [part["id"] for part in parts], "installed_components": [],
        "tags": ["spacecraft", "test craft", "logistics verification"],
        "entry_status": "verification sample",
        "structural_features": [structure],
    }
    controller = VehicleDesignController(world_model=world_for(parts), vehicle_entity=vehicle)
    controller.placed_components = []
    for catalog_id, along, across, up in placements:
        instance_id = controller.place_component_in_orthographic_view(catalog_id, "right", along, up)
        controller.move_component_axis(instance_id, "y", across)
        controller._get_component_by_instance_id(instance_id)["undefined_axis"] = None
    unmet = [item["category"] for item in controller.get_requirement_status_list() if not item.get("is_satisfied")]
    assert not unmet, f"{vehicle_id}: class requirements not met: {unmet}"
    vehicle["installed_components"] = controller.get_placed_components()
    return vehicle


def build_transaction():
    shuttler = shuttler_parts()
    longreach = longreach_parts()
    return shuttler + longreach + [
        _vehicle(
            "veh_test_craft_shuttler", "Shuttler Test Craft", "orbital_spacecraft", (11.0, 4.0, 4.0), shuttler,
            [("comp_test_shuttler_engine", 1.0, 2.0, 2.0), ("comp_test_shuttler_tank", 4.0, 2.0, 2.0),
             ("comp_test_shuttler_cabin", 7.5, 2.0, 2.0), ("comp_test_shuttler_docking_collar", 10.0, 2.0, 2.0)],
            "Logistics verification orbital tug: lots of delta-v for its size, orbital shielding, a month of life support.",
            {"id": "shuttler_frame", "label": "Tug spaceframe", "feature_type": "primary_structure",
             "satisfies_categories": ["structure", "spaceframe"], "shielding_class": "orbital"},
        ),
        _vehicle(
            "veh_test_craft_longreach", "Longreach Test Craft", "system_spacecraft", (78.0, 10.0, 10.0), longreach,
            [("comp_test_longreach_ntr_engine", 3.0, 3.0, 5.0), ("comp_test_longreach_ntr_engine", 3.0, 7.0, 5.0),
             ("comp_test_longreach_hydrogen_tank", 14.0, 5.0, 5.0), ("comp_test_longreach_hydrogen_tank", 31.0, 5.0, 5.0),
             ("comp_test_longreach_hydrogen_tank", 48.0, 5.0, 5.0), ("comp_test_longreach_storm_shelter", 59.0, 5.0, 5.0),
             ("comp_test_longreach_habitat", 66.5, 5.0, 5.0), ("comp_test_longreach_flight_deck", 73.0, 5.0, 5.0),
             ("comp_test_longreach_docking_port", 76.5, 5.0, 5.0)],
            "Logistics verification long-range craft: nuclear-thermal engines, four years of life support.",
            {"id": "longreach_truss", "label": "Long truss spaceframe", "feature_type": "primary_structure",
             "satisfies_categories": ["structure", "spaceframe"]},
        ),
    ]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="build and check without writing")
    args = parser.parse_args(argv)

    upserts = build_transaction()
    world = world_for(upserts)
    for vehicle in (entity for entity in upserts if entity["_dataset"] == "vehicles"):
        profile = space_profile_from_design(vehicle, world)
        print(f"{vehicle['id']}: {len(vehicle['installed_components'])} parts, "
              f"delta-v {profile.get('delta_v_m_s', 0.0) / 1000.0:.2f} km/s, shielding {profile.get('shielding_class')}, "
              f"life support {profile.get('life_support_s', 0.0) / DAY_S:.0f} days, docking {profile['docking']}")
    if args.dry_run:
        return

    from tools.ontology_backup import backup_entities

    store = PersistentOntologyStore(ONTOLOGY_PATH)
    print(f"backup: {backup_entities(store, BACKUP_ROOT, upserts, ())}")
    started = time.perf_counter()
    result = store.apply_changes(entities=upserts)
    print(f"applied in {time.perf_counter() - started:.2f}s: {result}")
    store.export_rdfxml(ONTOLOGY_PATH)
    store.compact_database()
    print("checkpoint written")


if __name__ == "__main__":
    main()
