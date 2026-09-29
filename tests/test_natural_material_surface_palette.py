import unittest

from simulations.world_gen.natural_materials import (
    derive_planet_surface_palette,
    material_surface_phase_stability,
)


class NaturalMaterialSurfacePaletteTests(unittest.TestCase):
    def test_surface_phase_stability_uses_temperature_and_partial_pressure(self):
        atmosphere = {
            "surface_pressure_bar": 0.059,
            "composition": [{"molecule": "CO2", "fraction": 0.5867}],
        }

        sulfur = material_surface_phase_stability("mat_sulfur_ice", 257.1, atmosphere)
        carbon_dioxide = material_surface_phase_stability("mat_carbon_dioxide_ice", 257.1, atmosphere)
        hot_sulfur = material_surface_phase_stability("mat_sulfur_ice", 400.0, atmosphere)

        self.assertTrue(sulfur["stable"])
        self.assertEqual("solid_elemental_sulfur", sulfur["phase"])
        self.assertFalse(carbon_dioxide["stable"])
        self.assertLess(carbon_dioxide["transition_temperature_k"], 170.0)
        self.assertFalse(hot_sulfur["stable"])

    def test_sulfur_ice_controls_surface_palette_over_associated_ores(self):
        palette = derive_planet_surface_palette({
            "likely_materials": [
                {
                    "material_id": "mat_galena",
                    "name": "Galena",
                    "material_subclass": "mineral",
                    "display_color": [82, 82, 84],
                    "confidence": 0.98,
                },
                {
                    "material_id": "mat_pyrite",
                    "name": "Pyrite",
                    "material_subclass": "mineral",
                    "display_color": [182, 144, 54],
                    "confidence": 0.93,
                },
                {
                    "material_id": "mat_sulfur_ice",
                    "name": "Sulfur Ice",
                    "material_subclass": "ice",
                    "display_color": [216, 188, 62],
                    "confidence": 0.87,
                    "evidence_tags": ["sulfur_bearing_crust", "volcanic_surface"],
                },
                {
                    "material_id": "mat_carbon_dioxide_ice",
                    "name": "Carbon Dioxide Ice",
                    "material_subclass": "ice",
                    "display_color": [190, 196, 196],
                    "confidence": 0.82,
                    "evidence_tags": ["co2_bearing_atmosphere", "cratered_regolith"],
                },
            ],
            "element_profile": {"Si": 48.9, "Fe": 14.3, "S": 1.55},
        }, atmosphere={"estimated_surface_temperature_k": 262.7})

        self.assertEqual(3, palette["palette_version"])
        self.assertEqual("surface_phase", palette["render_mode"])
        self.assertEqual("mat_sulfur_ice", palette["primary_surface_material"])
        self.assertEqual("mat_sulfur_ice", palette["surface_materials"][0]["material_id"])

        lowland, plain, highland, _shadow = palette["palette"]
        self.assertGreater(plain[0], plain[1])
        self.assertGreater(plain[1], plain[2] + 90)
        self.assertLess(sum(lowland), sum(plain))
        self.assertGreater(sum(highland), sum(plain))

    def test_bulk_palette_remains_the_fallback_without_surface_phase(self):
        palette = derive_planet_surface_palette({
            "likely_materials": [
                {
                    "material_id": "mat_quartz",
                    "name": "Quartz",
                    "material_subclass": "mineral",
                    "display_color": [190, 189, 185],
                    "confidence": 0.90,
                },
            ],
            "element_profile": {"Si": 49.0, "O": 46.0},
        })

        self.assertEqual("bulk_composition", palette["render_mode"])
        self.assertEqual("mat_quartz", palette["primary_surface_material"])

    def test_regional_deposits_do_not_recolour_planetary_basalt(self):
        basalt = {
            "material_id": "mat_basalt",
            "name": "Basalt",
            "material_subclass": "rock",
            "display_color": [72, 76, 70],
            "confidence": 0.72,
            "minimum_map_detail_level": 0,
            "distribution_scale": "planetary_province",
        }
        alluvium = {
            "material_id": "mat_alluvium",
            "name": "Alluvium",
            "material_subclass": "regolith",
            "display_color": [196, 164, 62],
            "confidence": 0.98,
            "minimum_map_detail_level": 2,
            "distribution_scale": "regional_deposit",
        }
        palette = derive_planet_surface_palette({
            "likely_materials": [alluvium, basalt],
            "planetary_surface_materials": [basalt],
        }, terrain={"hydrology": {"target_ocean_fraction": 0.65}})

        self.assertEqual("mat_basalt", palette["primary_surface_material"])
        self.assertEqual("planetary_surface_only", palette["selection_scope"])
        self.assertLess(abs(palette["surface_color"][0] - palette["surface_color"][1]), 20)


if __name__ == "__main__":
    unittest.main()
