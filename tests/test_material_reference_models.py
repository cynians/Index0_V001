import unittest
from types import SimpleNamespace

from world.material_reference_models import (
    apply_material_reference_models,
    material_matches_tags,
)


class MaterialReferenceModelTests(unittest.TestCase):
    def test_catalog_materials_are_named_and_have_one_canonical_parent(self):
        loader = SimpleNamespace(entities={}, datasets={})

        self.assertTrue(apply_material_reference_models(loader))

        iron = loader.entities["mat_element_fe"]
        quartz = loader.entities["mat_quartz"]
        self.assertEqual(["mat_elemental_material"], iron["parents"])
        self.assertIn("metallic", iron["tags"])
        self.assertEqual(["mat_natural_mineral"], quartz["parents"])
        self.assertGreaterEqual(len(loader.datasets["materials"]), 175)

    def test_bone_entries_are_children_of_the_generic_bone_material(self):
        loader = SimpleNamespace(entities={}, datasets={})
        apply_material_reference_models(loader)

        bone = loader.entities["mat_bone"]
        child_ids = {child["id"] for child in bone["offspring"]}
        self.assertEqual(["mat_bone"], loader.entities["mat_elephant_bone"]["parents"])
        self.assertEqual(["mat_bone"], loader.entities["mat_whale_bone"]["parents"])
        self.assertTrue({"mat_elephant_bone", "mat_whale_bone"}.issubset(child_ids))

    def test_existing_materials_gain_hierarchy_and_property_tags(self):
        stainless = {"id": "mat_stainless_steel", "name": "Stainless Steel", "tags": ["authored"]}
        loader = SimpleNamespace(
            entities={"mat_stainless_steel": stainless},
            datasets={"materials": [stainless]},
        )

        apply_material_reference_models(loader)

        self.assertEqual(["mat_steel"], stainless["parents"])
        self.assertIn("authored", stainless["tags"])
        self.assertIn("corrosion_resistant", stainless["engineering_property_tags"])
        self.assertTrue(material_matches_tags(stainless, ["metallic", "corrosion_resistant"]))
        self.assertFalse(material_matches_tags(stainless, ["heat_resistant"]))

    def test_e325_is_queryable_by_properties_without_a_second_parent(self):
        loader = SimpleNamespace(entities={}, datasets={})
        apply_material_reference_models(loader)

        e325 = loader.entities["mat_e325_steel"]
        self.assertEqual(["mat_steel"], e325["parents"])
        self.assertTrue(material_matches_tags(e325, ["structural", "weldable"]))
        self.assertFalse(material_matches_tags(e325, ["heat_resistant"]))


if __name__ == "__main__":
    unittest.main()
