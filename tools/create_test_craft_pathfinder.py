"""Author the Pathfinder test craft: a system spacecraft for the logistics checks.

A verification design, like ``tools/create_mig21_vehicle_design.py``, for the
space capability profile (``simulations/logistics/vehicle_profiles.py``,
``docs/logistics_simulation_concept_v001.md`` section 7). Its parts are real
component entities carrying the spaceflight fields added by
``tools/author_component_spaceflight_fields.py``, so the profile reads them the
way it will read any authored design.

Two engines, two tanks, a habitat, a storm shelter, a docking port and a
flight deck, on a truss spaceframe: about 41 t dry and 341 t fuelled, 7.8 km/s.
From Earth that reaches Mars and Venus (low orbit to low orbit) but not
Mercury, Ceres or Jupiter -- which is what the test design is for.

Writes the six components and the vehicle in one ``apply_changes``; re-running
replaces them. ``--dry-run`` builds and checks without writing.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from types import SimpleNamespace


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from simulations.logistics.vehicle_profiles import space_profile_from_design
from simulations.vehicle.vehicle_design import VehicleDesignController
from world.persistent_ontology_store import PersistentOntologyStore

ONTOLOGY_PATH = PROJECT_ROOT / "ontology" / "index0.owl"
BACKUP_ROOT = PROJECT_ROOT / "artifacts" / "test_craft_pathfinder"
VEHICLE_ID = "veh_test_craft_pathfinder"
YEAR_S = 365.25 * 86_400.0


def _component(component_id, name, mass_kg, size_m, categories, roles, **fields):
    length, width, height = size_m
    return {
        "id": component_id, "_dataset": "components", "type": "component",
        "name": name, "pretty_name": name,
        "mass_kg": mass_kg, "power_kw": 0.0,
        "dimension_length_m": length, "dimension_width_m": width, "dimension_height_m": height,
        "satisfies_categories": categories, "functional_roles": roles,
        "operational_groups": ["Spaceflight"], "subsystem_labels": roles,
        "categories": ["cat_vehicle_part"], "install_contexts": ["vehicle"],
        "tags": ["component", "spacecraft", "test craft", "logistics verification"],
        "entry_status": "verification sample",
        **fields,
    }


def components():
    return [
        _component(
            "comp_test_pathfinder_vacuum_engine", "Pathfinder Vacuum Methalox Engine", 2000.0, (4.5, 2.4, 2.4),
            ["propulsion_space"], ["main_engine"],
            thrust_n=1_200_000.0, specific_impulse_s=375.0,
            inputs=[{"resource_type": "fuel", "label": "Propellant"}],
            outputs=[{"resource_type": "thrust", "label": "Thrust"}],
        ),
        _component(
            "comp_test_pathfinder_main_tank", "Pathfinder Main Propellant Tank", 7500.0, (14.0, 8.0, 8.0),
            ["fuel_storage"], ["propellant_storage"],
            propellant_capacity_kg=150_000.0,
            outputs=[{"resource_type": "fuel", "label": "Propellant"}],
        ),
        _component(
            "comp_test_pathfinder_habitat", "Pathfinder Crew Habitat", 12000.0, (8.0, 8.0, 8.0),
            ["life_support", "crew_accommodation"], ["crew_habitat", "life_support"],
            life_support_s=2.0 * YEAR_S,
        ),
        _component(
            "comp_test_pathfinder_storm_shelter", "Pathfinder Radiation Storm Shelter", 8000.0, (4.0, 6.0, 6.0),
            ["radiation_shielding"], ["radiation_shielding"],
            shielding_class="deep_space",
        ),
        _component(
            "comp_test_pathfinder_docking_port", "Pathfinder Docking Port", 600.0, (1.5, 2.0, 2.0),
            ["docking"], ["docking"],
            docking=True,
        ),
        _component(
            "comp_test_pathfinder_flight_deck", "Pathfinder Flight Deck", 1500.0, (2.5, 4.0, 3.0),
            ["control"], ["flight_control"],
            outputs=[{"resource_type": "control_signal", "label": "Flight Control"}],
        ),
    ]


# (catalog id, along the length, across, height), metres from the stern
PLACEMENTS = [
    ("comp_test_pathfinder_vacuum_engine", 2.5, 2.5, 4.5),
    ("comp_test_pathfinder_vacuum_engine", 2.5, 6.5, 4.5),
    ("comp_test_pathfinder_main_tank", 12.0, 4.5, 4.5),
    ("comp_test_pathfinder_main_tank", 27.0, 4.5, 4.5),
    ("comp_test_pathfinder_storm_shelter", 37.0, 4.5, 4.5),
    ("comp_test_pathfinder_habitat", 43.0, 4.5, 4.5),
    ("comp_test_pathfinder_flight_deck", 48.5, 4.5, 4.5),
    ("comp_test_pathfinder_docking_port", 51.0, 4.5, 4.5),
]


def world_for(entities):
    by_id = {entity["id"]: entity for entity in entities}
    return SimpleNamespace(get_entity=by_id.get)


def build_vehicle(parts):
    vehicle = {
        "id": VEHICLE_ID,
        "name": "Pathfinder Test Craft",
        "pretty_name": "Pathfinder Test Craft",
        "description": "Logistics verification spacecraft: a crewed interplanetary transfer craft whose parts "
                       "carry spaceflight capability fields. Approximate figures, not a real design.",
        "type": "vehicle",
        "_dataset": "vehicles",
        "vehicle_class": "system_spacecraft",
        "dimension_length_m": 52.0,
        "dimension_width_m": 9.0,
        "dimension_height_m": 9.0,
        "component_catalog": [part["id"] for part in parts],
        "installed_components": [],
        "tags": ["spacecraft", "interplanetary", "test craft", "logistics verification"],
        "entry_status": "verification sample",
        "vehicle_specifications": [
            {"id": "spec_crew", "label": "Crew", "value": "4", "unit": "person", "category": "operations"},
            {"id": "spec_propellant", "label": "Propellant", "value": "methane / oxygen", "unit": "", "category": "propulsion"},
        ],
        "design_requirements": [
            {"id": "req_mars_transfer", "label": "Earth to Mars transfer", "target": "low orbit to low orbit",
             "unit": "", "priority": "critical", "notes": "logistics verification brief"},
        ],
        "structural_features": [
            {"id": "pathfinder_truss", "label": "Integrated truss spaceframe", "feature_type": "primary_structure",
             "satisfies_categories": ["structure", "spaceframe"]},
        ],
    }
    controller = VehicleDesignController(world_model=world_for(parts), vehicle_entity=vehicle)
    controller.placed_components = []
    for catalog_id, along, across, height in PLACEMENTS:
        instance_id = controller.place_component_in_orthographic_view(catalog_id, "right", along, height)
        controller.move_component_axis(instance_id, "y", across)
        controller._get_component_by_instance_id(instance_id)["undefined_axis"] = None
    unmet = [item["category"] for item in controller.get_requirement_status_list() if not item.get("is_satisfied")]
    assert not unmet, f"class requirements not met: {unmet}"
    vehicle["installed_components"] = controller.get_placed_components()
    return vehicle


def build_transaction():
    parts = components()
    return parts + [build_vehicle(parts)]


def _report(upserts):
    vehicle = upserts[-1]
    profile = space_profile_from_design(vehicle, world_for(upserts))
    print(f"{vehicle['id']}: {len(vehicle['installed_components'])} parts installed")
    print(f"  delta-v {profile.get('delta_v_m_s', 0.0) / 1000.0:.2f} km/s, shielding {profile.get('shielding_class')}, "
          f"life support {profile.get('life_support_s', 0.0) / YEAR_S:.1f} years, "
          f"docking {profile['docking']}, atmosphere entry {profile['atmosphere_entry']}")
    return profile


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="build and check without writing")
    args = parser.parse_args(argv)

    upserts = build_transaction()
    _report(upserts)
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
