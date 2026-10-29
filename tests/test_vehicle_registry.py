import unittest
from pathlib import Path
from types import SimpleNamespace

import pygame

import tools.author_vehicle_unit_model as model
import tools.author_vehicle_unit_registry_v2_model as model_v2
from app.launch_affordance_resolver import LaunchAffordanceResolver
from simulations.vehicle.vehicle_registry_simulation import VehicleRegistrySimulation
from world.persistent_ontology_store import PersistentOntologyStore

ONTOLOGY_PATH = Path(__file__).resolve().parents[1] / "ontology" / "index0.owl"


class VehicleUnitModelBuilderTests(unittest.TestCase):
    """Structural checks on the migration transaction, independent of whether
    the live ontology already has the schema (a second run is a near no-op)."""

    def test_schema_fields_cover_identity_production_and_history(self):
        fields = model.SCHEMA_VEHICLE_UNIT_FIELDS
        for expected in (
            "represents_design", "produced_by", "production_line_id", "batch_label",
            "serial_number", "is_prototype", "year_constructed", "year_destroyed",
            "fate_notes", "assigned_faction", "current_link_entity_id",
        ):
            self.assertIn(expected, fields)
            self.assertTrue(fields[expected].get("optional"))

    def test_build_transaction_targets_the_vehicle_unit_schema(self):
        datasets = PersistentOntologyStore(ONTOLOGY_PATH).load_datasets()
        upserts = model.build_transaction(datasets)
        self.assertEqual(1, len(upserts))
        schema_entity = upserts[0]
        self.assertEqual("schema_vehicle_unit", schema_entity["id"])
        self.assertEqual("entity_core", schema_entity["extends"])
        self.assertEqual("vehicle_unit", schema_entity["schema"])


class VehicleUnitRegistryV2ModelBuilderTests(unittest.TestCase):
    """Structural checks on the v2 (versioning/placeholder) migration."""

    def test_updated_vehicle_unit_schema_drops_is_prototype_adds_version_label(self):
        schema_entity = {
            "id": "schema_vehicle_unit", "_dataset": "schemas", "schema": "vehicle_unit",
            "fields": {
                "is_prototype": {"type": "boolean", "optional": True},
                "assigned_faction": {"type": "entity", "target": "faction", "optional": True},
            },
        }
        updated = model_v2._updated_vehicle_unit_schema(schema_entity)
        self.assertNotIn("is_prototype", updated["fields"])
        self.assertIn("version_label", updated["fields"])
        self.assertEqual("factions", updated["fields"]["assigned_faction"]["target"])

    def test_updated_vehicle_schema_adds_unit_placeholders(self):
        schema_entity = {"id": "schema_vehicle", "_dataset": "schemas", "schema": "vehicle", "fields": {}}
        updated = model_v2._updated_vehicle_schema(schema_entity)
        self.assertIn("unit_placeholders", updated["fields"])

    def test_backfilled_unit_converts_prototype_flag(self):
        entity = {"id": "unit_x", "is_prototype": True}
        updated = model_v2._backfilled_vehicle_unit(entity)
        self.assertNotIn("is_prototype", updated)
        self.assertEqual("Prototype", updated["version_label"])

    def test_backfilled_unit_without_prototype_flag_has_no_version_label(self):
        entity = {"id": "unit_x", "is_prototype": False}
        updated = model_v2._backfilled_vehicle_unit(entity)
        self.assertNotIn("is_prototype", updated)
        self.assertNotIn("version_label", updated)


class LiveOntologyVehicleUnitSchemaTests(unittest.TestCase):
    """The live ontology is expected to already have both migrations applied
    (schema_vehicle_unit plus the v2 versioning/placeholder refinements)."""

    def test_schema_vehicle_unit_exists_with_expected_fields(self):
        datasets = PersistentOntologyStore(ONTOLOGY_PATH).load_datasets()
        schemas = model._schema_by_name(datasets)
        self.assertIn("vehicle_unit", schemas)
        fields = schemas["vehicle_unit"].get("fields", {})
        self.assertIn("represents_design", fields)
        self.assertIn("production_line_id", fields)

    def test_v2_fields_are_present_live(self):
        datasets = PersistentOntologyStore(ONTOLOGY_PATH).load_datasets()
        schemas = model._schema_by_name(datasets)
        unit_fields = schemas["vehicle_unit"].get("fields", {})
        self.assertIn("version_label", unit_fields)
        self.assertNotIn("is_prototype", unit_fields)
        self.assertEqual("factions", unit_fields["assigned_faction"]["target"])
        vehicle_fields = schemas["vehicle"].get("fields", {})
        self.assertIn("unit_placeholders", vehicle_fields)

    def test_no_live_vehicle_unit_still_carries_is_prototype(self):
        datasets = PersistentOntologyStore(ONTOLOGY_PATH).load_datasets()
        offenders = [
            entity.get("id") for entity in datasets.get("vehicle_units", [])
            if isinstance(entity, dict) and "is_prototype" in entity
        ]
        self.assertEqual([], offenders)


class _World:
    def __init__(self, entities):
        self.entities = {entity["id"]: entity for entity in entities}
        self.loader = SimpleNamespace(
            datasets={"vehicles": [], "vehicle_units": [], "producers": [], "factions": []},
            persist_entity=self._persist_entity,
        )
        for entity in entities:
            dataset = entity.get("_dataset", "entries")
            self.loader.datasets.setdefault(dataset, []).append(entity)

    def _persist_entity(self, entity):
        entity_id = entity.get("id")
        if not entity_id:
            return False
        self.entities[entity_id] = entity
        dataset = self.loader.datasets.setdefault(entity.get("_dataset", "entries"), [])
        for index, existing in enumerate(dataset):
            if existing.get("id") == entity_id:
                dataset[index] = entity
                break
        else:
            dataset.append(entity)
        return True

    def get_entity(self, entity_id):
        return self.entities.get(entity_id)

    def set_literal(self, entity_id, field_name, value):
        entity = self.entities.get(entity_id)
        if entity is None:
            return False
        entity[field_name] = value
        return True


def _vehicle_entity(**fields):
    entity = {"id": "veh_test", "type": "vehicle", "_dataset": "vehicles", "name": "Test Vehicle"}
    entity.update(fields)
    return entity


def _unit(unit_id, **fields):
    entity = {"id": unit_id, "type": "vehicle_unit", "_dataset": "vehicle_units", "represents_design": "veh_test"}
    entity.update(fields)
    return entity


def _producer(producer_id, name, production_lines=None):
    return {
        "id": producer_id, "type": "producer", "_dataset": "producers", "name": name,
        "production_lines": production_lines or [],
    }


def _faction(faction_id, name):
    return {"id": faction_id, "type": "faction", "_dataset": "factions", "name": name}


def _key(event_type, key, unicode="", mod=0):
    return SimpleNamespace(type=event_type, key=key, unicode=unicode, mod=mod)


def _type_text(sim, text):
    for char in text:
        sim.handle_specification_key(_key(pygame.KEYDOWN, pygame.K_a, unicode=char))


class VehicleRegistrySimulationTests(unittest.TestCase):
    def test_groups_units_by_version_then_production_line(self):
        world = _World([
            _vehicle_entity(),
            _unit("unit_1", serial_number="Sn-1", version_label="Prototype"),
            _unit("unit_2", serial_number="Sn-2", version_label="Mk I", production_line_id="line_a", batch_label="First Batch"),
            _unit("unit_3", serial_number="Sn-3", version_label="Mk I", production_line_id="line_a"),
            _unit("unit_4", serial_number="Sn-4", version_label="Mk II"),
        ])
        sim = VehicleRegistrySimulation(world, "veh_test")
        groups = sim.get_grouped_units()
        self.assertEqual(["Prototype", "Mk I", "Mk II"], [g["version_label"] for g in groups])
        self.assertEqual(["Sn-1"], [u["serial_number"] for u in groups[0]["batches"][0]["units"]])
        mk1_batches = groups[1]["batches"]
        self.assertEqual(["First Batch"], [b["label"] for b in mk1_batches])
        self.assertEqual(["Sn-2", "Sn-3"], [u["serial_number"] for u in mk1_batches[0]["units"]])

    def test_units_without_version_label_are_grouped_last_as_unspecified(self):
        world = _World([
            _vehicle_entity(),
            _unit("unit_1", serial_number="Sn-1", version_label="Mk I"),
            _unit("unit_2", serial_number="Sn-2"),
        ])
        sim = VehicleRegistrySimulation(world, "veh_test")
        groups = sim.get_grouped_units()
        self.assertEqual(["Mk I", "Unspecified"], [g["version_label"] for g in groups])

    def test_group_without_batch_label_falls_back_to_line_id(self):
        world = _World([_vehicle_entity(), _unit("unit_1", serial_number="Sn-1", production_line_id="line_z")])
        sim = VehicleRegistrySimulation(world, "veh_test")
        groups = sim.get_grouped_units()
        self.assertEqual(1, len(groups))
        self.assertIn("line_z", groups[0]["batches"][0]["label"])

    def test_units_from_other_designs_are_excluded(self):
        world = _World([
            _vehicle_entity(),
            _unit("unit_1", serial_number="Sn-1"),
            {"id": "unit_other", "type": "vehicle_unit", "_dataset": "vehicle_units",
             "represents_design": "veh_other", "serial_number": "Sn-99"},
        ])
        sim = VehicleRegistrySimulation(world, "veh_test")
        self.assertEqual(["Sn-1"], [u["serial_number"] for u in sim.get_units()])

    def test_inline_cell_edit_round_trips_through_set_literal(self):
        world = _World([_vehicle_entity(), _unit("unit_1", serial_number="Sn-1")])
        sim = VehicleRegistrySimulation(world, "veh_test")
        self.assertTrue(sim.set_active_cell("unit_1", "fate_notes"))
        _type_text(sim, "Lost at sea")
        sim.handle_specification_key(_key(pygame.KEYDOWN, pygame.K_RETURN))
        self.assertEqual("Lost at sea", world.get_entity("unit_1")["fate_notes"])
        self.assertIsNone(sim.active_cell)

    def test_year_fields_coerce_to_numbers_or_none(self):
        world = _World([_vehicle_entity(), _unit("unit_1", serial_number="Sn-1")])
        sim = VehicleRegistrySimulation(world, "veh_test")
        sim.set_active_cell("unit_1", "year_constructed")
        _type_text(sim, "1956")
        sim.handle_specification_key(_key(pygame.KEYDOWN, pygame.K_RETURN))
        self.assertEqual(1956.0, world.get_entity("unit_1")["year_constructed"])

    def test_escape_cancels_without_persisting(self):
        world = _World([_vehicle_entity(), _unit("unit_1", serial_number="Sn-1")])
        sim = VehicleRegistrySimulation(world, "veh_test")
        sim.set_active_cell("unit_1", "fate_notes")
        sim.handle_specification_key(_key(pygame.KEYDOWN, pygame.K_x, unicode="x"))
        sim.handle_specification_key(_key(pygame.KEYDOWN, pygame.K_ESCAPE))
        self.assertIsNone(sim.active_cell)
        self.assertIsNone(world.get_entity("unit_1").get("fate_notes"))


class VehicleRegistryPlaceholderTests(unittest.TestCase):
    def test_add_placeholder_stores_name_on_design_metadata_not_a_new_entity(self):
        world = _World([_vehicle_entity()])
        sim = VehicleRegistrySimulation(world, "veh_test")
        name = sim.add_placeholder("Sn-2")
        self.assertEqual("Sn-2", name)
        self.assertEqual([{"name": "Sn-2"}], world.get_entity("veh_test")["unit_placeholders"])
        self.assertEqual(0, len(sim.get_units()))

    def test_add_placeholder_with_no_name_suggests_next_serial(self):
        world = _World([_vehicle_entity(), _unit("unit_1", serial_number="Sn-1")])
        sim = VehicleRegistrySimulation(world, "veh_test")
        name = sim.add_placeholder()
        self.assertEqual("Sn-2", name)

    def test_promote_placeholder_creates_a_real_unit_and_removes_the_placeholder(self):
        world = _World([_vehicle_entity(unit_placeholders=[{"name": "Sn-2"}, {"name": "Sn-3"}])])
        sim = VehicleRegistrySimulation(world, "veh_test")
        new_id = sim.promote_placeholder(0)
        self.assertIsNotNone(new_id)
        created = world.get_entity(new_id)
        self.assertEqual("Sn-2", created["serial_number"])
        self.assertEqual("veh_test", created["represents_design"])
        remaining = world.get_entity("veh_test")["unit_placeholders"]
        self.assertEqual([{"name": "Sn-3"}], remaining)

    def test_promote_placeholder_out_of_range_is_a_noop(self):
        world = _World([_vehicle_entity(unit_placeholders=[{"name": "Sn-2"}])])
        sim = VehicleRegistrySimulation(world, "veh_test")
        self.assertIsNone(sim.promote_placeholder(5))
        self.assertEqual(0, len(sim.get_units()))


class VehicleRegistryRelationPickerTests(unittest.TestCase):
    def test_opening_picker_lists_matching_producers_filtered_by_query(self):
        world = _World([
            _vehicle_entity(),
            _unit("unit_1", serial_number="Sn-1"),
            _producer("prod_a", "Mikoyan-Gurevich OKB"),
            _producer("prod_b", "Sukhoi Design Bureau"),
        ])
        sim = VehicleRegistrySimulation(world, "veh_test")
        self.assertTrue(sim.open_picker("unit_1", "produced_by"))
        all_matches = sim._picker_matches()
        self.assertEqual(2, len(all_matches))
        sim._picker["query"] = "mikoyan"
        filtered = sim._picker_matches()
        self.assertEqual(["prod_a"], [m["id"] for m in filtered])

    def test_committing_a_matched_producer_sets_the_real_entity_id(self):
        world = _World([
            _vehicle_entity(),
            _unit("unit_1", serial_number="Sn-1"),
            _producer("prod_a", "Mikoyan-Gurevich OKB"),
        ])
        sim = VehicleRegistrySimulation(world, "veh_test")
        sim.open_picker("unit_1", "produced_by")
        sim._commit_picker_selection(0)
        self.assertEqual("prod_a", world.get_entity("unit_1")["produced_by"])
        self.assertIsNone(sim._picker)

    def test_typing_an_unmatched_name_and_committing_stores_raw_unresolved_text(self):
        world = _World([
            _vehicle_entity(),
            _unit("unit_1", serial_number="Sn-1"),
            _faction("fac_a", "Northern Alliance"),
        ])
        sim = VehicleRegistrySimulation(world, "veh_test")
        sim.open_picker("unit_1", "assigned_faction")
        sim._picker["query"] = "Rogue Squadron"
        sim._commit_picker_selection()
        self.assertEqual("Rogue Squadron", world.get_entity("unit_1")["assigned_faction"])

    def test_reopening_picker_on_unresolved_value_prefills_query_for_editing(self):
        world = _World([
            _vehicle_entity(),
            _unit("unit_1", serial_number="Sn-1", assigned_faction="Rogue Squadron"),
            _faction("fac_a", "Northern Alliance"),
        ])
        sim = VehicleRegistrySimulation(world, "veh_test")
        sim.open_picker("unit_1", "assigned_faction")
        self.assertEqual("Rogue Squadron", sim._picker["query"])
        sim._picker["query"] = "Northern"
        matches = sim._picker_matches()
        self.assertEqual(["fac_a"], [m["id"] for m in matches])
        sim._commit_picker_selection(0)
        self.assertEqual("fac_a", world.get_entity("unit_1")["assigned_faction"])

    def test_production_line_picker_lists_the_resolved_producers_lines(self):
        world = _World([
            _vehicle_entity(),
            _unit("unit_1", serial_number="Sn-1", produced_by="prod_a"),
            _producer("prod_a", "Mikoyan-Gurevich OKB", production_lines=[
                {"line_id": "line_1", "batch_label": "First Batch"},
                {"line_id": "line_2"},
            ]),
        ])
        sim = VehicleRegistrySimulation(world, "veh_test")
        self.assertTrue(sim.open_picker("unit_1", "production_line_id"))
        matches = sim._picker_matches()
        self.assertEqual({"line_1", "line_2"}, {m["id"] for m in matches})

    def test_production_line_picker_unavailable_without_a_resolved_producer(self):
        world = _World([_vehicle_entity(), _unit("unit_1", serial_number="Sn-1")])
        sim = VehicleRegistrySimulation(world, "veh_test")
        self.assertFalse(sim.open_picker("unit_1", "production_line_id"))

    def test_escape_closes_picker_without_committing(self):
        world = _World([
            _vehicle_entity(),
            _unit("unit_1", serial_number="Sn-1"),
            _producer("prod_a", "Mikoyan-Gurevich OKB"),
        ])
        sim = VehicleRegistrySimulation(world, "veh_test")
        sim.open_picker("unit_1", "produced_by")
        sim.handle_specification_key(_key(pygame.KEYDOWN, pygame.K_ESCAPE))
        self.assertIsNone(sim._picker)
        self.assertNotIn("produced_by", world.get_entity("unit_1"))

    def test_picker_typing_and_enter_flow_through_handle_specification_key(self):
        world = _World([
            _vehicle_entity(),
            _unit("unit_1", serial_number="Sn-1"),
            _producer("prod_a", "Mikoyan-Gurevich OKB"),
        ])
        sim = VehicleRegistrySimulation(world, "veh_test")
        sim.open_picker("unit_1", "produced_by")
        _type_text(sim, "mikoyan")
        sim.handle_specification_key(_key(pygame.KEYDOWN, pygame.K_RETURN))
        self.assertEqual("prod_a", world.get_entity("unit_1")["produced_by"])


class VehicleRegistryLaunchAffordanceTests(unittest.TestCase):
    def test_vehicle_offers_registry_launch_option(self):
        options = LaunchAffordanceResolver().options_for_entity(
            {"id": "veh_x", "type": "vehicle", "_dataset": "vehicles"}
        )
        self.assertIn("vehicle_registry", [option["mode"] for option in options])


if __name__ == "__main__":
    unittest.main()
