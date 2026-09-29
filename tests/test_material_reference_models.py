import unittest
from pathlib import Path

from simulations.world_gen.material_formation import (
    FORMATION_CATEGORIES,
    formation_suitability,
)
from simulations.world_gen.natural_materials import (
    configure_material_catalog,
    derive_natural_material_model,
)

from world.material_reference_models import (
    _TAXONOMY,
    _reference_entry,
    _refresh_offspring,
    material_matches_tags,
)


ONTOLOGY_PATH = Path(__file__).resolve().parents[1] / "ontology" / "index0.owl"


class MaterialMatchesTagsTests(unittest.TestCase):
    def test_matches_combine_classification_and_property_tags(self):
        stainless = {
            "id": "mat_stainless_steel",
            "tags": ["metallic", "alloy"],
            "engineering_property_tags": ["corrosion_resistant"],
            "production_role_tags": [],
            "production_process_tags": ["steelmaking"],
        }
        self.assertTrue(material_matches_tags(stainless, ["metallic", "corrosion_resistant"]))
        self.assertFalse(material_matches_tags(stainless, ["heat_resistant"]))
        self.assertFalse(
            material_matches_tags(stainless, ["metallic"], excluded_tags=["alloy"])
        )


class ReferenceEntryTests(unittest.TestCase):
    def test_concrete_entry_carries_world_gen_selection_fields(self):
        entry = _reference_entry({
            "id": "mat_example", "name": "Example", "material_class": "natural_material",
            "material_subclass": "rock", "canonical_parent": "mat_natural_rock",
            "required_element_thresholds": {"O": 1.0},
            "favorable_planet_tags": ["weathered_surface"],
        })
        self.assertEqual(["mat_natural_rock"], entry["parents"])
        self.assertEqual({"O": 1.0}, entry["required_element_thresholds"])
        self.assertEqual(["weathered_surface"], entry["favorable_planet_tags"])

    def test_family_and_engineered_entries_get_family_defaults(self):
        entry = _reference_entry({
            "id": "mat_metal_alloy", "name": "Metal Alloy", "material_class": "material_family",
            "material_subclass": "material_family", "canonical_parent": "mat_engineered_metal",
            "tags": ["material", "engineered_material"],
        })
        self.assertEqual("material_family", entry["material_system_role"])
        self.assertEqual("not_applicable", entry["natural_distribution_role"])


class RefreshOffspringTests(unittest.TestCase):
    def test_builds_child_tree_from_single_parent_links(self):
        materials_by_id = {
            "mat_bone": {"id": "mat_bone", "parents": []},
            "mat_elephant_bone": {"id": "mat_elephant_bone", "parents": ["mat_bone"]},
            "mat_whale_bone": {"id": "mat_whale_bone", "parents": ["mat_bone"]},
        }
        _refresh_offspring(materials_by_id)
        child_ids = {child["id"] for child in materials_by_id["mat_bone"]["offspring"]}
        self.assertEqual({"mat_elephant_bone", "mat_whale_bone"}, child_ids)


class OntologyMaterialContractTests(unittest.TestCase):
    """Regression checks against the sole durable material registry."""

    @classmethod
    def setUpClass(cls):
        from world.persistent_ontology_store import PersistentOntologyStore
        cls.concrete = [
            material
            for material in PersistentOntologyStore(ONTOLOGY_PATH).load_datasets().get("materials") or []
            if isinstance(material, dict)
            and material.get("material_class") != "material_family"
        ]
        # Production startup builds this cache from EntityLoader's ontology
        # dataset. This isolated unit suite supplies its fixture explicitly.
        configure_material_catalog(cls.concrete)

    def test_family_count_matches_taxonomy_scaffold(self):
        self.assertEqual(18, len(_TAXONOMY))

    def test_all_concrete_materials_follow_the_v2_system_contract(self):
        required_fields = {
            "material_record_schema_version",
            "material_system_role",
            "natural_distribution_role",
            "worldgen_participation",
            "production_role_tags",
            "resource_origin",
            "recyclability_class",
            "distribution_scale",
        }
        self.assertEqual(332, len(self.concrete))
        concrete_ids = {material["id"] for material in self.concrete}
        for material in self.concrete:
            self.assertTrue(required_fields.issubset(material), material["id"])
            self.assertEqual(2, material["material_record_schema_version"], material["id"])
            self.assertIsInstance(material.get("production_process_tags") or [], list)
            for feedstock_id in material.get("feedstock_material_ids") or []:
                self.assertIn(feedstock_id, concrete_ids, material["id"])

    def test_geological_material_count(self):
        geological_count = sum(
            material.get("material_system_role") == "natural_geologic_material"
            for material in self.concrete
        )
        self.assertEqual(210, geological_count)

    def test_geological_materials_have_ontology_mechanical_contracts(self):
        geological = [
            material for material in self.concrete
            if material.get("material_system_role") == "natural_geologic_material"
        ]
        self.assertEqual(210, len(geological))
        for material in geological:
            self.assertTrue(material.get("mechanical_class"), material.get("id"))
            profile = material.get("mechanical_rock_profile")
            self.assertIsInstance(profile, dict, material.get("id"))
            for field in (
                "bulk_density_kg_m3", "cohesion_mpa", "friction_angle_deg",
                "tensile_strength_mpa", "erodibility_index",
                "permeability_index", "slope_resistance_index",
                "fracture_density_index", "elastic_strength_index", "fabric",
            ):
                self.assertIn(field, profile, f"{material.get('id')}:{field}")

    def test_test6_geological_units_have_complete_physical_and_spawn_contracts(self):
        expected_formations = {
            "mat_andesite": "igneous_extrusive_intermediate",
            "mat_silica_sand": "quartz_sand_accumulation",
            "mat_syenite": "igneous_intrusive_alkaline",
            "mat_granodiorite": "igneous_intrusive_felsic",
            "mat_diorite": "igneous_intrusive_intermediate",
            "mat_granite": "igneous_intrusive_felsic",
            "mat_tonalite": "igneous_intrusive_felsic",
            "mat_monzonite": "igneous_intrusive_intermediate",
            "mat_nepheline_syenite": "igneous_intrusive_alkaline",
            "mat_diabase": "igneous_hypabyssal_mafic",
            "mat_basalt": "igneous_extrusive_mafic",
        }
        records = {material["id"]: material for material in self.concrete}
        planet_tags = {
            "silicate_crust", "silica_rich_crust", "felsic_crust",
            "intermediate_silicate_crust", "mafic_crust", "basaltic_surface",
            "volcanic_surface", "plate_tectonic_surface", "weathered_surface",
            "active_hydrology", "aeolian_surface",
        }
        for material_id, category in expected_formations.items():
            material = records[material_id]
            self.assertEqual(category, material["formation_category"])
            self.assertEqual(3, len(material["display_color"]), material_id)
            self.assertEqual(3, len(material["geological_map_color"]), material_id)
            self.assertEqual("resolved", material["formation_contract_status"])
            self.assertIn(0, material["formation_requirements"]["valid_scale_levels"])
            optical = material["optical_surface_profile"]
            self.assertEqual(
                {"red_650nm", "green_550nm", "blue_450nm"},
                set(optical["visible_reflectance"]),
            )
            self.assertEqual(
                {"red_650nm", "green_550nm", "blue_450nm"},
                set(optical["weathered_visible_reflectance"]),
            )
            self.assertGreater(
                formation_suitability(
                    {
                        **material["formation_requirements"],
                        "category_id": category,
                    },
                    {
                        "planet_tags": planet_tags,
                        "volcanic": 1.0,
                        "low_slope": 1.0,
                    },
                    available_host_categories=FORMATION_CATEGORIES,
                ),
                0.0,
                material_id,
            )

        model = derive_natural_material_model(
            {
                "major_elements": [
                    {"symbol": "O", "abundance_percent": 40.0},
                    {"symbol": "Si", "abundance_percent": 22.0},
                    {"symbol": "Al", "abundance_percent": 10.0},
                    {"symbol": "Fe", "abundance_percent": 8.0},
                    {"symbol": "Mg", "abundance_percent": 6.0},
                    {"symbol": "Ca", "abundance_percent": 5.0},
                    {"symbol": "Na", "abundance_percent": 4.0},
                    {"symbol": "K", "abundance_percent": 3.0},
                ],
                "trace_elements": [],
            },
            planet_tags,
        )
        candidate_ids = {
            candidate["material_id"]
            for candidate in model["likely_materials"]
        }
        self.assertTrue(set(expected_formations).issubset(candidate_ids))


if __name__ == "__main__":
    unittest.main()
