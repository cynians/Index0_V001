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


if __name__ == "__main__":
    unittest.main()
