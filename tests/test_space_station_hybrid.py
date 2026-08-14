import unittest
from types import SimpleNamespace

from app.launch_affordance_resolver import LaunchAffordanceResolver
from simulations.vehicle.vehicle_design import VehicleDesignController
from simulations.vehicle.vehicle_simulation import VehicleSimulation
from ui.card import EntityCard
from ui.knowledge_browser_ui import KnowledgeBrowserUI
from world.component_host import COMPONENT_HOST_SCHEMA_ENTITY, apply_component_host_schema
from world.schema_loader import SchemaLoader


class _World:
    def __init__(self, entities=None, datasets=None):
        entities = list(entities or [])
        self.loader = SimpleNamespace(
            entities={entity["id"]: entity for entity in entities},
            datasets=datasets or {"locations": entities, "schemas": []},
        )
        self.persisted = []

    def get_entity(self, entity_id):
        return self.loader.entities.get(entity_id)

    def get_entities_by_dataset(self, dataset_name):
        return self.loader.datasets.get(dataset_name, [])

    def get_dataset_names(self):
        return list(self.loader.datasets)

    def set_literal(self, entity_id, field_name, value, persist=True):
        entity = self.get_entity(entity_id)
        if entity is None:
            return []
        entity[field_name] = value
        self.persisted.append((entity_id, field_name, value, persist))
        return [entity_id]


class SpaceStationHybridTests(unittest.TestCase):
    def _station_template(self, ui):
        ui.schema_entry_templates = [
            {
                "dataset_name": "locations",
                "entity_type": "location",
                "label": "Location",
                "id_prefix": "loc",
            }
        ]
        return next(
            template
            for template in ui._conversion_templates()
            if template.get("subclass_field") == "location_class"
            and template.get("subclass_value") == "space_station"
        )

    def test_space_station_template_creates_one_location_with_design_capability(self):
        ui = KnowledgeBrowserUI()
        world = _World(datasets={"locations": [], "schemas": []})
        ui.world_model = world
        template = self._station_template(ui)

        station = ui._create_template_entity(
            template,
            requested_id="loc_station_accord",
            initial_fields={"name": "Accord Station", "pretty_name": "Accord Station"},
        )

        self.assertEqual("locations", station["_dataset"])
        self.assertEqual("location", station["type"])
        self.assertEqual("space_station", station["location_class"])
        self.assertEqual("orbital_body", station["system_role"])
        self.assertEqual(["component_host"], station["schema_mixins"])
        self.assertEqual([], station["installed_components"])
        self.assertNotIn("vehicles", world.loader.datasets)

    def test_component_host_schema_is_reusable_as_an_entity_mixin(self):
        schema_entities = [
            {
                "id": "schema_entity_core",
                "type": "schema",
                "schema": "entity_core",
                "fields": {"name": {"type": "string"}},
            },
            {
                "id": "schema_locations",
                "type": "schema",
                "schema": "locations",
                "extends": "entity_core",
                "fields": {"location_class": {"type": "string"}},
            },
            COMPONENT_HOST_SCHEMA_ENTITY,
        ]
        schema_loader = SchemaLoader(schema_entities=schema_entities)
        world = SimpleNamespace(schemas=schema_loader, loader=SimpleNamespace(entities={}))
        card = EntityCard(
            {
                "id": "loc_station",
                "type": "location",
                "_dataset": "locations",
                "location_class": "space_station",
                "schema_mixins": ["component_host"],
            },
            dataset_name="locations",
            world_model=world,
        )

        fields = card._get_schema_field_specs()

        self.assertIn("location_class", fields)
        self.assertIn("installed_components", fields)
        self.assertIn("dimension_length_m", fields)

    def test_runtime_schema_registration_is_idempotent(self):
        loader = SimpleNamespace(entities={}, datasets={})

        self.assertTrue(apply_component_host_schema(loader))
        self.assertFalse(apply_component_host_schema(loader))
        self.assertEqual(1, len(loader.datasets["schemas"]))

    def test_station_exposes_space_interior_and_design_launches(self):
        station = {
            "id": "loc_station",
            "type": "location",
            "_dataset": "locations",
            "location_class": "space_station",
            "star_system": "system_sol",
        }

        options = LaunchAffordanceResolver().options_for_entity(station)

        self.assertEqual(["space", "building", "vehicle"], [option["mode"] for option in options])
        self.assertEqual(["Space", "Interior", "Design"], [option["label"] for option in options])

    def test_vehicle_designer_loads_authored_station_components(self):
        component = {
            "instance_id": "placed_component_007",
            "catalog_id": "comp_reactor",
            "label": "Station Reactor",
            "component_type": "reactor_component",
            "local_rect_m": {"x": 2.0, "y": 3.0, "width": 8.0, "height": 6.0},
        }
        station = {
            "id": "loc_station",
            "location_class": "space_station",
            "vehicle_class": "orbital_spacecraft",
            "installed_components": [component],
        }

        design = VehicleDesignController(vehicle_entity=station)

        self.assertEqual(["placed_component_007"], [item["instance_id"] for item in design.get_placed_components()])
        self.assertEqual(8, design.next_component_index)

    def test_station_design_persists_installed_components_to_same_entity(self):
        station = {
            "id": "loc_station",
            "name": "Station",
            "type": "location",
            "_dataset": "locations",
            "location_class": "space_station",
            "vehicle_class": "orbital_spacecraft",
            "installed_components": [],
        }
        world = _World([station])
        simulation = VehicleSimulation(world_model=world, vehicle_entity_id="loc_station")
        simulation.design.placed_components = [
            {
                "instance_id": "placed_component_001",
                "catalog_id": "comp_thruster",
                "label": "Thruster",
                "component_type": "thruster_component",
                "local_rect_m": {"x": 1.0, "y": 1.0, "width": 2.0, "height": 2.0},
            }
        ]

        self.assertTrue(simulation._persist_design_state())

        self.assertEqual("installed_components", world.persisted[-1][1])
        self.assertEqual("placed_component_001", station["installed_components"][0]["instance_id"])


if __name__ == "__main__":
    unittest.main()
