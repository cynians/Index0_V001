import unittest

from simulations.world_gen.mechanical_lithology import (
    derive_planetary_mechanical_lithology_model,
    mechanical_profile_for_material,
    terrain_response_factors,
)


class MechanicalLithologyTests(unittest.TestCase):
    def test_strong_crystalline_material_retains_more_relief_than_sand(self):
        granite = mechanical_profile_for_material({
            "mechanical_class": "massive_crystalline_rock",
            "mechanical_rock_profile": {
                "bulk_density_kg_m3": 2720,
                "erodibility_index": 0.23,
                "slope_resistance_index": 0.86,
                "elastic_strength_index": 0.82,
            },
        })
        sand = mechanical_profile_for_material({
            "mechanical_class": "unconsolidated_sediment",
            "mechanical_rock_profile": {
                "bulk_density_kg_m3": 2050,
                "erodibility_index": 0.93,
                "slope_resistance_index": 0.12,
                "elastic_strength_index": 0.10,
            },
        })
        strong = terrain_response_factors({"aggregate_profile": granite})
        weak = terrain_response_factors({"aggregate_profile": sand})
        self.assertGreater(strong["relief_retention"], weak["relief_retention"])
        self.assertGreater(strong["elastic_thickness_factor"], weak["elastic_thickness_factor"])
        self.assertLess(strong["erosion_susceptibility"], weak["erosion_susceptibility"])

    def test_planetary_prior_is_weighted_from_ontology_shaped_candidates(self):
        model = derive_planetary_mechanical_lithology_model({
            "likely_materials": [
                {
                    "material_id": "mat_granite",
                    "prevalence_score": 0.8,
                    "mechanical_class": "massive_crystalline_rock",
                    "mechanical_rock_profile": {
                        "bulk_density_kg_m3": 2720,
                        "erodibility_index": 0.23,
                        "slope_resistance_index": 0.86,
                        "elastic_strength_index": 0.82,
                    },
                },
                {
                    "material_id": "mat_silica_sand",
                    "prevalence_score": 0.2,
                    "mechanical_class": "unconsolidated_sediment",
                    "mechanical_rock_profile": {
                        "bulk_density_kg_m3": 2050,
                        "erodibility_index": 0.93,
                        "slope_resistance_index": 0.12,
                        "elastic_strength_index": 0.10,
                    },
                },
            ],
        })
        self.assertEqual("mechanical_lithology_prior_derived", model["status"])
        self.assertEqual("massive_crystalline_rock", model["dominant_mechanical_class"])
        self.assertAlmostEqual(0.8, model["class_weights"]["massive_crystalline_rock"])
        self.assertGreater(model["aggregate_profile"]["slope_resistance_index"], 0.6)


if __name__ == "__main__":
    unittest.main()
