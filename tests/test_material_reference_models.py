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
        concrete = [
            material
            for material in loader.datasets["materials"]
            if material.get("material_class") != "material_family"
        ]
        families = [
            material
            for material in loader.datasets["materials"]
            if material.get("material_class") == "material_family"
        ]
        self.assertEqual(322, len(concrete))
        self.assertEqual(
            200,
            sum(
                material.get("material_system_role")
                == "natural_geologic_material"
                for material in concrete
            ),
        )
        self.assertEqual(18, len(families))

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

    def test_all_concrete_materials_follow_the_v2_system_contract(self):
        loader = SimpleNamespace(entities={}, datasets={})
        apply_material_reference_models(loader)
        concrete = [
            material
            for material in loader.datasets["materials"]
            if material.get("material_class") != "material_family"
        ]
        required_fields = {
            "material_record_schema_version",
            "material_system_role",
            "natural_distribution_role",
            "worldgen_participation",
            "production_role_tags",
            "production_process_tags",
            "resource_origin",
            "recyclability_class",
            "distribution_scale",
        }

        self.assertEqual(322, len(concrete))
        for material in concrete:
            self.assertTrue(
                required_fields.issubset(material),
                material["id"],
            )
            self.assertEqual(
                2,
                material["material_record_schema_version"],
                material["id"],
            )
            for feedstock_id in material.get("feedstock_material_ids") or []:
                self.assertIn(feedstock_id, loader.entities, material["id"])

    def test_natural_and_engineered_materials_share_worldgen_production_bridge(self):
        loader = SimpleNamespace(entities={}, datasets={})
        apply_material_reference_models(loader)

        basalt = loader.entities["mat_basalt"]
        bauxite = loader.entities["mat_bauxite"]
        carbon_steel = loader.entities["mat_carbon_steel"]

        self.assertEqual("bedrock", basalt["natural_distribution_role"])
        self.assertIn("construction_stone", basalt["production_role_tags"])
        self.assertEqual("sparse_deposit", bauxite["natural_distribution_role"])
        self.assertIn("ore_feedstock", bauxite["production_role_tags"])
        self.assertEqual(
            "not_naturally_distributed",
            carbon_steel["distribution_scale"],
        )
        self.assertEqual(
            ["mat_element_fe", "mat_element_c"],
            carbon_steel["feedstock_material_ids"],
        )
        self.assertTrue(
            material_matches_tags(
                carbon_steel,
                ["manufactured_stock", "steelmaking"],
            )
        )

    def test_expanded_geology_keeps_resource_uses_separate_from_map_role(self):
        loader = SimpleNamespace(entities={}, datasets={})
        apply_material_reference_models(loader)

        rock_salt = loader.entities["mat_rock_salt"]
        molybdenite = loader.entities["mat_molybdenite"]
        dune_sand = loader.entities["mat_dune_sand"]

        self.assertEqual("local_lithology", rock_salt["natural_distribution_role"])
        self.assertIn("chemical_feedstock", rock_salt["production_role_tags"])
        self.assertEqual("sparse_deposit", molybdenite["natural_distribution_role"])
        self.assertIn("ore_feedstock", molybdenite["production_role_tags"])
        self.assertEqual("surface_cover", dune_sand["natural_distribution_role"])
        self.assertIn("glass_feedstock", dune_sand["production_role_tags"])


if __name__ == "__main__":
    unittest.main()
