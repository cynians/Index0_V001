"""Author a skeleton inbound/outbound logistics pair for the lumber test site.

This is a one-way ontology authoring utility, following the same pattern as
tools/author_person_food_ownership_model.py: runtime code (SiteSimulation,
VehicleSimulation) resolves these entities from the ontology projection and
does not maintain a parallel logistics registry.

Adds:
* a vehicle DESIGN entity (the type/catalog side of the vehicle split
  described in docs/conceptual_layer_overview_v006.txt section 21) for the
  cart used by the actuated delivery route;
* a raw-lumber item, institution-owned at the site the same way the food
  ingredients are;
* two logistics route entities, both active and actuated by SiteSimulation
  (inbound delivery and outbound shipment, stock-bounded by what workers
  have actually unloaded into site storage);
* the site fields (inbound_logistics_routes, outbound_logistics_routes,
  logistics_arrival_point) that let SiteSimulation find and actuate them.
"""

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from world.persistent_ontology_store import PersistentOntologyStore


ONTOLOGY_PATH = PROJECT_ROOT / "ontology" / "index0.owl"


LOGISTICS_SCHEMA_FIELDS = {
    "route_class": {"type": "string", "section": "Classification", "optional": True},
    "origin_location": {"type": "entity", "target": "locations", "section": "Route", "optional": True},
    "destination_location": {"type": "entity", "target": "locations", "section": "Route", "optional": True},
    "cargo_item": {"type": "entity", "target": "items", "section": "Cargo", "optional": True},
    "cargo_quantity_per_trip": {"type": "number", "section": "Cargo", "optional": True},
    "schedule_interval_s": {"type": "number", "section": "Schedule", "optional": True},
    "assigned_vehicle_design": {"type": "entity", "target": "vehicles", "section": "Route", "optional": True},
    "status": {"type": "string", "section": "Classification", "optional": True},
}


LOCATION_SCHEMA_EXTENSIONS = {
    "inbound_logistics_routes": {"type": "entity_list", "target": "logistics", "section": "Logistics", "optional": True},
    "outbound_logistics_routes": {"type": "entity_list", "target": "logistics", "section": "Logistics", "optional": True},
    "logistics_arrival_point": {"type": "object", "section": "Logistics", "optional": True},
}


def _schema_name(entity):
    return str(entity.get("schema") or entity.get("name") or entity.get("id") or "").removeprefix("schema_")


def build_changes(datasets):
    schemas = {_schema_name(entity): dict(entity) for entity in datasets.get("schemas", []) if isinstance(entity, dict)}
    locations_by_id = {
        entity["id"]: entity
        for entity in datasets.get("locations", [])
        if isinstance(entity, dict) and entity.get("id")
    }
    changes = []

    logistics_schema = schemas.get("logistics")
    if logistics_schema:
        logistics_schema["fields"] = {**(logistics_schema.get("fields") or {}), **LOGISTICS_SCHEMA_FIELDS}
        changes.append(logistics_schema)

    location_schema = schemas.get("locations")
    if location_schema:
        location_schema["fields"] = {**(location_schema.get("fields") or {}), **LOCATION_SCHEMA_EXTENSIONS}
        changes.append(location_schema)

    changes.extend([
        {
            "id": "veh_design_lumber_hauler_cart", "_dataset": "vehicles", "type": "vehicle",
            "name": "Lumber Hauler Cart", "pretty_name": "Lumber Hauler Cart",
            "vehicle_class": "horse-drawn logistics cart", "manufacturer_name": "North Road Village Wainwrights",
            "dimension_length_m": 4.2, "dimension_width_m": 1.8, "dimension_height_m": 1.6,
            "operators": ["institution_test_city_council"],
        },
        {
            "id": "item_raw_lumber", "_dataset": "items", "type": "item",
            "name": "Raw Lumber", "pretty_name": "Raw Lumber", "item_class": "raw building material",
            "consumable": False, "inventory_unit": "log", "stackable": True,
            "produced_by": ["location_lumber_test_woodlot"],
            "ownership_records": ["ownership_lumber_storage_stock"],
        },
        {
            "id": "log_lumber_inbound_delivery", "_dataset": "logistics", "type": "logistics",
            "name": "Lumber Inbound Delivery", "pretty_name": "Lumber Inbound Delivery",
            "route_class": "inbound delivery",
            "origin_location": "location_lumber_neighbor_village",
            "destination_location": "location_lumber_test_site",
            "cargo_item": "item_raw_lumber", "cargo_quantity_per_trip": 20,
            "schedule_interval_s": 90, "assigned_vehicle_design": "veh_design_lumber_hauler_cart",
            "status": "active",
            "associated_locations": ["location_lumber_neighbor_village", "location_lumber_test_site"],
            "wiki_entry": (
                "Placeholder aggregate-logistics endpoint: periodically actuates a runtime "
                "delivery cart carrying raw lumber into the lumber test site yard, where "
                "authored workers unload it into site storage."
            ),
        },
        {
            "id": "log_lumber_outbound_planks", "_dataset": "logistics", "type": "logistics",
            "name": "Lumber Outbound Planks", "pretty_name": "Lumber Outbound Planks",
            "route_class": "outbound delivery",
            "origin_location": "location_lumber_test_site",
            "destination_location": "location_lumber_neighbor_village",
            "cargo_item": "item_raw_lumber", "cargo_quantity_per_trip": 10,
            "schedule_interval_s": 180, "assigned_vehicle_design": "veh_design_lumber_hauler_cart",
            "status": "active",
            "associated_locations": ["location_lumber_test_site", "location_lumber_neighbor_village"],
            "wiki_entry": (
                "Periodically actuates a runtime cart that loads raw lumber from site "
                "storage (bounded by what workers have actually unloaded from inbound "
                "deliveries) and departs toward the neighbor village. Ships the same "
                "raw-lumber item rather than a finished-goods item: the factory's plank "
                "production line is a deliberate later addition."
            ),
        },
        {
            # apply_changes fully replaces an entity's stored properties, so
            # this must carry the site's existing fields forward rather than
            # patching in isolation -- a bare partial dict here would wipe
            # bounds/resident_people/terrain_zones/etc. authored elsewhere.
            **locations_by_id.get("location_lumber_test_site", {
                "id": "location_lumber_test_site", "_dataset": "locations", "type": "location",
            }),
            "inbound_logistics_routes": ["log_lumber_inbound_delivery"],
            "outbound_logistics_routes": ["log_lumber_outbound_planks"],
            "logistics_arrival_point": [56.0, 15.0],
        },
        {
            "id": "ownership_lumber_storage_stock", "_dataset": "ownerships", "type": "ownership",
            "name": "Lumber Storage Stock Ownership", "pretty_name": "Lumber Storage Stock Ownership",
            "ownership_class": "institutional stock",
            "owner_entities": ["institution_person_sim_lab"],
            "owned_assets": ["item_raw_lumber"],
            "use_policy": "institutional",
            "permitted_users": ["institution_person_sim_lab"],
        },
    ])
    return changes


def main():
    store = PersistentOntologyStore(ONTOLOGY_PATH)
    changes = build_changes(store.load_datasets())
    result = store.apply_changes(entities=changes)
    print(f"Authored {result['upserted']} lumber logistics ontology entities")


if __name__ == "__main__":
    main()
