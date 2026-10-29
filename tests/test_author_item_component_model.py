import unittest
from pathlib import Path

from world.entity_loader import EntityLoader
from world.persistent_ontology_store import PersistentOntologyStore
from world.schema_loader import SchemaLoader
import tools.author_item_component_model as model

ONTOLOGY_PATH = Path(__file__).resolve().parents[1] / "ontology" / "index0.owl"


class ItemComponentModelBuilderTests(unittest.TestCase):
    """Structural checks on the transaction the tool builds -- independent of
    whether the live ontology has already been migrated (a second run is a
    near no-op)."""

    def test_category_taxonomy_has_a_shallow_hierarchy(self):
        cats = {c["id"]: c for c in model._category_entities()}
        self.assertIn("cat_manufactured_good", cats)
        self.assertEqual(["cat_manufactured_good"], cats["cat_machinery_module"]["parents"])
        self.assertNotIn("parents", cats["cat_manufactured_good"])
        # parents are emitted before their children
        emitted = [c["id"] for c in model._category_entities()]
        self.assertLess(
            emitted.index("cat_manufactured_good"), emitted.index("cat_machinery_module")
        )

    def test_only_the_three_owned_schemas_are_authored(self):
        datasets = PersistentOntologyStore(ONTOLOGY_PATH).load_datasets()
        changes = model._schema_changes(datasets)
        schema_ids = {c["id"] for c in changes}
        self.assertEqual(
            {"schema_category", "schema_item", "schema_components"}, schema_ids
        )
        by_id = {c["id"]: c for c in changes}
        self.assertEqual("item", by_id["schema_components"]["extends"])
        item_fields = by_id["schema_item"]["fields"]
        self.assertIn("categories", item_fields)
        for gone in ("item_class", "component_equivalent", "installable",
                     "inventory_unit", "stackable", "uses_technology"):
            self.assertNotIn(gone, item_fields)


class MigratedOntologyStateTests(unittest.TestCase):
    """The live ontology is expected to be in the consolidated shape after
    tools/author_item_component_model.py has run."""

    @classmethod
    def setUpClass(cls):
        cls.datasets = PersistentOntologyStore(ONTOLOGY_PATH).load_datasets()
        cls.by_id = {
            e["id"]: e
            for entries in cls.datasets.values()
            for e in entries
            if isinstance(e, dict)
        }

    def test_categories_dataset_exists(self):
        self.assertGreaterEqual(len(self.datasets.get("categories", [])), len(model.CATEGORY_TREE))

    def test_component_is_a_subclass_of_item(self):
        schema = SchemaLoader(ONTOLOGY_PATH).get_schema("components")
        self.assertIn("functional_roles", schema["fields"])   # own
        self.assertIn("storage_modes", schema["fields"])       # inherited
        self.assertIn("categories", schema["fields"])          # inherited

    def test_bridge_pointers_and_class_strings_are_gone(self):
        item_schema = SchemaLoader(ONTOLOGY_PATH).get_schema("item")
        self.assertNotIn("item_class", item_schema["fields"])
        self.assertNotIn("component_equivalent", item_schema["fields"])
        for entity in self.datasets.get("items", []) + self.datasets.get("components", []):
            self.assertNotIn("item_class", entity)
            self.assertNotIn("component_class", entity)
            self.assertNotIn("component_equivalent", entity)
            self.assertNotIn("represented_item", entity)

    def test_duplicate_twins_are_deleted_and_folded_into_the_item(self):
        self.assertNotIn("comp_pump_module", self.by_id)
        self.assertNotIn("comp_storage_rack", self.by_id)
        pump = self.by_id["item_pump_module"]
        self.assertEqual("item", pump["type"])
        self.assertIn("functional_roles", pump)
        self.assertIn("cat_machinery_module", pump["categories"])

    def test_item_class_migrated_to_categories(self):
        meal = self.by_id["item_cooked_meal"]
        self.assertEqual(["cat_prepared_food"], meal["categories"])
        self.assertEqual("meal", meal["default_unit"])

    def test_production_referrers_no_longer_point_at_deleted_twins(self):
        for prod_id in ("prod_pump_module_assembly", "prod_steel_plate_rolling"):
            blob = str(self.by_id[prod_id])
            self.assertNotIn("comp_pump_module", blob)
            self.assertNotIn("comp_storage_rack", blob)

    def test_category_members_are_derived_through_the_loader(self):
        loader = EntityLoader(
            entries_directory=Path(__file__).resolve().parents[1] / "entries",
            ontology_path=ONTOLOGY_PATH,
            use_ontology=True,
        )
        industrial = loader.get("cat_industrial_good")
        self.assertIn("item_steel_plate", industrial.get("members", []))


if __name__ == "__main__":
    unittest.main()
