import unittest

from ui.knowledge_browser_model import KnowledgeBrowserModel


class _SchemaLoader:
    schemas = {}

    @staticmethod
    def get_schema(_name):
        return None


class _WorldModel:
    def __init__(self, materials):
        self._materials = materials

    def get_dataset_names(self):
        return ["materials"]

    def get_entities_by_dataset(self, dataset_name):
        return list(self._materials) if dataset_name == "materials" else []


class _Host:
    IDEA_GENERIC_FIELDS = set()

    def __init__(self, materials, *, query=""):
        self.world_model = _WorldModel(materials)
        self.schema_loader = _SchemaLoader()
        self.browser_tree_state = {"locations": {}}
        self.browser_period_filter = None
        self.browser_filter_dataset = "materials"
        self.browser_filter_incomplete_only = False
        self.browser_search_query = query

    @staticmethod
    def _coerce_card_year(value):
        return value

    @staticmethod
    def _entity_display_label(entity, fallback="unknown"):
        return entity.get("name") or entity.get("pretty_name") or fallback


def _material(entity_id, name, parent=None, **fields):
    entity = {
        "id": entity_id,
        "name": name,
        "type": "material",
        "_dataset": "materials",
        "material_subclass": fields.pop("material_subclass", "material"),
    }
    if parent:
        entity["canonical_parent"] = parent
        entity["parents"] = [parent]
    entity.update(fields)
    return entity


class MaterialRepositoryHierarchyTests(unittest.TestCase):
    def setUp(self):
        self.materials = [
            _material("mat_material", "Material", material_subclass="material_family"),
            _material("mat_engineered", "Engineered Material", "mat_material", material_subclass="material_family"),
            _material("mat_metal", "Metal and Alloy", "mat_engineered", material_subclass="material_family"),
            _material("mat_steel", "Steel", "mat_metal", material_subclass="steel"),
            _material("mat_e325", "E325 Steel", "mat_steel", material_subclass="structural_steel"),
            _material("mat_bone", "Bone", "mat_material", material_subclass="biological_tissue"),
            _material("mat_elephant_bone", "Elephant Bone", "mat_bone", material_subclass="biological_tissue"),
        ]

    def test_materials_are_presented_as_an_indented_parent_child_tree(self):
        model = KnowledgeBrowserModel(_Host(self.materials))

        items = model._build_material_browser_items(model.world_model)
        rows = {item["entity_id"]: item for item in items}

        self.assertEqual(rows["mat_material"]["depth"], 0)
        self.assertEqual(rows["mat_engineered"]["depth"], 1)
        self.assertEqual(rows["mat_metal"]["depth"], 2)
        self.assertEqual(rows["mat_steel"]["depth"], 3)
        self.assertEqual(rows["mat_e325"]["depth"], 4)
        self.assertEqual(rows["mat_elephant_bone"]["depth"], 2)
        self.assertTrue(rows["mat_material"]["expanded"])
        self.assertEqual(rows["mat_e325"]["meta_text"], "[structural_steel]")

    def test_collapsing_a_material_branch_only_hides_its_descendants(self):
        host = _Host(self.materials)
        model = KnowledgeBrowserModel(host)
        model._set_expanded("mat_engineered", False, "materials")

        item_ids = [item["entity_id"] for item in model._build_material_browser_items(host.world_model)]

        self.assertIn("mat_engineered", item_ids)
        self.assertNotIn("mat_metal", item_ids)
        self.assertIn("mat_bone", item_ids)

    def test_search_reveals_the_matching_material_and_its_parent_chain(self):
        host = _Host(self.materials, query="e325")
        model = KnowledgeBrowserModel(host)
        model._set_expanded("mat_engineered", False, "materials")

        item_ids = [item["entity_id"] for item in model._build_material_browser_items(host.world_model)]

        self.assertEqual(item_ids, [
            "mat_material",
            "mat_engineered",
            "mat_metal",
            "mat_steel",
            "mat_e325",
        ])


class _ItemWorldModel:
    repository_revision = 0

    def __init__(self, datasets):
        self._datasets = datasets

    def get_dataset_names(self):
        return list(self._datasets)

    def get_entities_by_dataset(self, dataset_name):
        return list(self._datasets.get(dataset_name, []))


class _ItemHost:
    IDEA_GENERIC_FIELDS = set()

    def __init__(self, datasets, *, query="", filter_dataset="items", incomplete_only=False):
        self.world_model = _ItemWorldModel(datasets)
        self.schema_loader = _SchemaLoader()
        self.browser_tree_state = {}
        self.browser_period_filter = None
        self.browser_filter_dataset = filter_dataset
        self.browser_filter_incomplete_only = incomplete_only
        self.browser_search_query = query

    @staticmethod
    def _coerce_card_year(value):
        return value

    @staticmethod
    def _entity_display_label(entity, fallback="unknown"):
        return entity.get("name") or entity.get("pretty_name") or fallback


def _category(entity_id, name, parents=None):
    entity = {
        "id": entity_id,
        "name": name,
        "type": "category",
        "_dataset": "categories",
        "category_kind": "functional",
    }
    if parents:
        entity["parents"] = list(parents)
    return entity


def _item(entity_id, name, categories=None, *, dataset="items"):
    entity = {
        "id": entity_id,
        "name": name,
        "type": "component" if dataset == "components" else "item",
        "_dataset": dataset,
    }
    if categories:
        entity["categories"] = list(categories)
    return entity


class ItemCategoryHierarchyTests(unittest.TestCase):
    def setUp(self):
        self.datasets = {
            "categories": [
                _category("cat_manufactured", "Manufactured Good"),
                _category("cat_industrial", "Industrial Good", ["cat_manufactured"]),
                _category("cat_machinery", "Machinery Module", ["cat_manufactured"]),
                _category("cat_small_arm", "Small Arm", ["cat_manufactured"]),
            ],
            "items": [
                _item("item_pump", "Pump Module", ["cat_industrial", "cat_machinery"]),
                _item("item_rifle", "Test Rifle", ["cat_small_arm"]),
                _item("item_mystery", "Mystery Object"),
            ],
            "components": [
                _item("comp_engine", "Engine Block", ["cat_machinery"], dataset="components"),
                _item("comp_loose_bolt", "Loose Bolt", dataset="components"),
            ],
        }

    def _rows(self, host):
        model = KnowledgeBrowserModel(host)
        return model._build_item_browser_items(model.world_model)

    def test_categories_form_an_indented_tree_with_items_as_leaves(self):
        rows = self._rows(_ItemHost(self.datasets))
        by_depth = [(row.get("text"), row.get("depth"), row.get("dataset_name") or row.get("kind")) for row in rows]

        self.assertIn(("Manufactured Good", 0, "categories"), by_depth)
        self.assertIn(("Industrial Good", 1, "categories"), by_depth)
        self.assertIn(("Pump Module", 2, "items"), by_depth)

    def test_item_with_multiple_categories_appears_under_each_parent(self):
        rows = self._rows(_ItemHost(self.datasets))
        pump_rows = [row for row in rows if row.get("entity_id") == "item_pump"]

        self.assertEqual(len(pump_rows), 2)
        self.assertEqual({row["dataset_name"] for row in pump_rows}, {"items"})

    def test_uncategorized_items_are_grouped_at_the_end(self):
        rows = self._rows(_ItemHost(self.datasets))
        labels = [row["text"] for row in rows if row.get("kind") == "label"]
        self.assertIn("(Uncategorized)", labels)
        mystery_rows = [row for row in rows if row.get("entity_id") == "item_mystery"]
        self.assertEqual(len(mystery_rows), 1)

    def test_categories_filter_hides_item_leaves_but_keeps_the_taxonomy(self):
        rows = self._rows(_ItemHost(self.datasets, filter_dataset="categories"))
        datasets = {row.get("dataset_name") for row in rows if row.get("kind") == "tree_entity"}
        self.assertEqual(datasets, {"categories"})

    def test_collapsing_a_category_hides_its_descendants(self):
        host = _ItemHost(self.datasets)
        model = KnowledgeBrowserModel(host)
        model._set_expanded("cat_industrial", False, "categories")
        rows = model._build_item_browser_items(model.world_model)

        texts = [row.get("text") for row in rows]
        self.assertIn("Industrial Good", texts)
        industrial_pump = [
            row for row in rows
            if row.get("entity_id") == "item_pump" and row.get("depth") == 2
        ]
        # Pump still shows under Machinery Module (depth 2), but not under the
        # collapsed Industrial Good branch.
        self.assertEqual(len(industrial_pump), 1)

    def test_search_reveals_the_matching_item_and_its_category_chain(self):
        rows = self._rows(_ItemHost(self.datasets, query="rifle"))
        texts = [row.get("text") for row in rows]
        self.assertEqual(texts, ["Manufactured Good", "Small Arm", "Test Rifle"])

    def test_components_sit_in_the_same_category_tree_as_items(self):
        rows = self._rows(_ItemHost(self.datasets))
        machinery_children = [
            row for row in rows
            if row.get("depth") == 2 and row.get("dataset_name") in {"items", "components"}
        ]
        labels = {(row["text"], row["dataset_name"], row["meta_text"]) for row in machinery_children}
        self.assertIn(("Engine Block", "components", "[Component]"), labels)
        self.assertIn(("Pump Module", "items", "[Item]"), labels)

        uncategorized = [row["text"] for row in rows if row.get("dataset_name") in {"items", "components"}
                         and row.get("depth") == 1]
        self.assertIn("Loose Bolt", uncategorized)
        self.assertIn("Mystery Object", uncategorized)

    def test_components_filter_shows_only_component_leaves(self):
        rows = self._rows(_ItemHost(self.datasets, filter_dataset="components"))
        leaf_datasets = {row["dataset_name"] for row in rows if row.get("kind") == "tree_entity"
                         and row["dataset_name"] in {"items", "components"}}
        self.assertEqual(leaf_datasets, {"components"})
        # taxonomy is still there as structure
        self.assertIn("Manufactured Good", [row.get("text") for row in rows])


class _AliasLoader:
    entity_aliases = {}


class _LocationWorldModel:
    repository_revision = 0

    def __init__(self, datasets):
        self._datasets = datasets
        self.loader = _AliasLoader()

    def get_dataset_names(self):
        return list(self._datasets)

    def get_entities_by_dataset(self, dataset_name):
        return list(self._datasets.get(dataset_name, []))


class _LocationHost:
    IDEA_GENERIC_FIELDS = set()
    ORBIT_LOCATION_CLASS_KEYS = frozenset()

    def __init__(self, datasets, *, query="", filter_dataset="all", incomplete_only=False):
        self.world_model = _LocationWorldModel(datasets)
        self.schema_loader = _SchemaLoader()
        self.browser_tree_state = {}
        self.browser_period_filter = None
        self.browser_filter_dataset = filter_dataset
        self.browser_filter_incomplete_only = incomplete_only
        self.browser_search_query = query

    @staticmethod
    def _coerce_card_year(value):
        return value

    @staticmethod
    def _entity_display_label(entity, fallback="unknown"):
        return entity.get("name") or entity.get("pretty_name") or fallback


def _location(entity_id, name, parent=None, *, location_class="planet"):
    entity = {
        "id": entity_id,
        "name": name,
        "type": "location",
        "_dataset": "locations",
        "location_class": location_class,
    }
    if parent:
        entity["parent_location"] = parent
    return entity


def _city(entity_id, name, parent_location, *, location_class="city"):
    return {
        "id": entity_id,
        "name": name,
        "type": "city",
        "_dataset": "cities",
        "location_class": location_class,
        "parent_location": parent_location,
    }


class CityLocationSubclassTests(unittest.TestCase):
    """`cities` is a subclass of `locations` (schema `extends: locations`,
    OWL `city_entry subClassOf location_entry`): its rows nest into the same
    browser tree as ordinary locations instead of getting a section of
    their own. See tools/author_cities_location_subclass.py."""

    def setUp(self):
        self.datasets = {
            "locations": [_location("loc_earth", "Earth", location_class="planet")],
            "cities": [_city("city_capital", "Capital City", "loc_earth")],
        }

    def test_city_nests_under_its_parent_location(self):
        host = _LocationHost(self.datasets)
        model = KnowledgeBrowserModel(host)
        model._set_expanded("loc_earth", True)

        rows = model._build_location_browser_items(host.world_model)
        by_id = {row["entity_id"]: row for row in rows if row.get("kind") == "tree_entity"}

        self.assertIn("city_capital", by_id)
        self.assertEqual(by_id["city_capital"]["depth"], by_id["loc_earth"]["depth"] + 1)
        self.assertEqual(by_id["city_capital"]["dataset_name"], "cities")
        self.assertEqual(by_id["city_capital"]["meta_text"], "[City]")

    def test_cities_never_get_their_own_top_level_section(self):
        host = _LocationHost(self.datasets)
        model = KnowledgeBrowserModel(host)

        rows = model._build_browser_items(host.world_model)

        section_titles = [row["text"] for row in rows if row.get("kind") == "section"]
        self.assertIn("Locations / Systems", section_titles)
        self.assertNotIn("Cities", section_titles)

    def test_cities_filter_narrows_the_location_tree_to_cities(self):
        host = _LocationHost(self.datasets, filter_dataset="cities")
        model = KnowledgeBrowserModel(host)
        model._set_expanded("loc_earth", True)

        rows = model._build_location_browser_items(host.world_model)
        entity_ids = [row["entity_id"] for row in rows if row.get("kind") == "tree_entity"]

        self.assertEqual(entity_ids, ["loc_earth", "city_capital"])

    def test_search_reveals_the_matching_city_and_its_parent_chain(self):
        host = _LocationHost(self.datasets, query="capital")
        model = KnowledgeBrowserModel(host)

        rows = model._build_location_browser_items(host.world_model)
        entity_ids = [row["entity_id"] for row in rows if row.get("kind") == "tree_entity"]

        self.assertEqual(entity_ids, ["loc_earth", "city_capital"])


if __name__ == "__main__":
    unittest.main()
