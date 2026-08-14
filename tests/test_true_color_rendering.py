import unittest

import pygame

from simulations.world_gen.true_color import (
    ORBITAL_APPEARANCE_INFLUENCES,
    TRUE_COLOR_MODEL_VERSION,
    _optical_mixture_fraction,
    derive_true_color_model,
    render_true_color_surface,
    river_true_color_rgb,
)
from simulations.world_gen.material_optics import material_optical_surface_profile

try:
    import numpy as np
except ImportError:  # pragma: no cover
    np = None


def _heightmap(*, ocean=True):
    return {
        "model_version": "heightmap-test",
        "projection": "equirectangular",
        "map_seed": "true-color-test-seed",
        "min_elevation_m": -3000.0,
        "max_elevation_m": 4500.0,
        "sea_level_m": 0.0 if ocean else None,
        "sample_spacing_x_m": 1000.0,
        "sample_spacing_y_m": 1000.0,
        "sample_grid": {
            "width": 5,
            "height": 3,
            "rows": [
                [-2500.0, -1200.0, 300.0, 1200.0, -2500.0],
                [-1800.0, -200.0, 2200.0, 4400.0, -1800.0],
                [-2500.0, -1000.0, 200.0, 900.0, -2500.0],
            ],
        },
        "surface_masks": {
            "ice_rows": [
                [True, False, False, False, True],
                [False, False, False, False, False],
                [True, False, False, False, True],
            ],
        },
        "hypsometry_summary": {
            "ocean_fraction": 0.45 if ocean else 0.0,
            "ice_fraction": 0.08,
        },
    }


class TrueColorRenderingTests(unittest.TestCase):
    def test_river_true_color_uses_hydrology_not_vegetation(self):
        clear = river_true_color_rgb({
            "flow": 0.9, "flow_regime": "perennial", "mouth": "ocean",
            "estimated_discharge_m3_s": 9000.0,
            "catchment_mean_runoff_mm": 360.0,
        })
        sediment = river_true_color_rgb({
            "flow": 0.25, "flow_regime": "intermittent", "mouth": "basin",
            "source_elevation_m": 5200.0, "catchment_dryness_ratio": 2.6,
            "catchment_mean_runoff_mm": 720.0,
        })
        self.assertGreater(clear[2], clear[0])
        self.assertGreater(sediment[0], sediment[2])

    @unittest.skipIf(np is None, "numpy unavailable")
    def test_opaque_pigment_coating_outcolors_clear_crystal_at_equal_abundance(self):
        abundance = np.full((2, 2), 0.08, dtype=np.float32)
        hematite = material_optical_surface_profile(
            "mat_hematite",
            formation_category="iron_weathering",
            material_subclass="mineral",
        )
        quartz = material_optical_surface_profile(
            "mat_quartz",
            formation_category="plutonic_crystalline_phase",
            material_subclass="mineral",
        )
        ferric_influence = _optical_mixture_fraction(abundance, hematite)
        quartz_influence = _optical_mixture_fraction(abundance, quartz)
        self.assertGreater(
            float(ferric_influence.mean()),
            float(quartz_influence.mean()) * 5.0,
        )

    def test_true_color_declares_ten_physical_influences_without_cosmetic_noise(self):
        model = derive_true_color_model({
            "id": "appearance-contract",
            "heightmap_model": _heightmap(ocean=False),
            "atmosphere_model": {"surface_pressure_bar": 0.0},
        })

        self.assertEqual(10, len(ORBITAL_APPEARANCE_INFLUENCES))
        self.assertEqual(
            list(ORBITAL_APPEARANCE_INFLUENCES),
            model["rendering"]["orbital_appearance_influences"],
        )
        self.assertFalse(
            model["rendering"]["unrelated_cosmetic_albedo_noise"]
        )

    def test_airless_world_gets_regolith_recipe_without_fabricated_biology(self):
        heightmap = _heightmap(ocean=False)
        planet = {
            "id": "luna",
            "heightmap_model": heightmap,
            "surface_palette": {
                "surface_color": [142, 138, 132],
                "palette": [[70, 68, 66], [142, 138, 132], [198, 196, 190]],
            },
            "atmosphere_model": {"surface_pressure_bar": 0.0},
            "natural_material_model": {
                "catalog_version": 4,
                "planet_tags": ["airless_regolith", "cratered_regolith"],
            },
        }

        model = derive_true_color_model(planet)

        self.assertEqual(TRUE_COLOR_MODEL_VERSION, model["model_version"])
        self.assertEqual("airless_regolith", model["surface_regime"])
        self.assertFalse(model["rendering"]["clouds"])
        self.assertFalse(model["rendering"]["vegetation"])

    def test_true_color_raster_is_deterministic_and_separates_land_water_ice(self):
        heightmap = _heightmap(ocean=True)
        planet = {
            "id": "ares",
            "heightmap_model": heightmap,
            "surface_palette": {
                "surface_color": [164, 104, 76],
                "palette": [[72, 54, 48], [164, 104, 76], [214, 168, 126]],
            },
            "atmosphere_model": {
                "surface_pressure_bar": 0.008,
                "visual_model": {
                    "visible": True,
                    "tint_color": [188, 142, 110],
                },
            },
            "natural_material_model": {
                "catalog_version": 4,
                "planet_tags": [
                    "oxidizing_surface",
                    "aeolian_surface",
                    "weathered_surface",
                ],
            },
        }
        model = derive_true_color_model(planet)

        first = render_true_color_surface(
            heightmap,
            model,
            atmosphere=planet["atmosphere_model"],
            target_size=(96, 48),
        )
        second = render_true_color_surface(
            heightmap,
            model,
            atmosphere=planet["atmosphere_model"],
            target_size=(96, 48),
        )

        self.assertEqual((96, 48), first.get_size())
        self.assertEqual(
            pygame.image.tostring(first, "RGB"),
            pygame.image.tostring(second, "RGB"),
        )
        ocean = first.get_at((4, 24))
        land = first.get_at((66, 24))
        ice = first.get_at((0, 0))
        self.assertGreater(ocean.b, ocean.r)
        self.assertGreater(land.r, land.b)
        self.assertGreater(sum(ice[:3]), sum(ocean[:3]))

    def test_material_reflectance_changes_surface_without_replacing_relief(self):
        heightmap = _heightmap(ocean=False)
        planet = {
            "id": "material-world",
            "heightmap_model": heightmap,
            "surface_palette": {
                "surface_color": [120, 112, 98],
                "palette": [[65, 61, 54], [120, 112, 98], [188, 180, 160]],
            },
            "atmosphere_model": {"surface_pressure_bar": 0.0},
            "natural_material_model": {
                "planet_tags": ["airless_regolith"],
            },
        }
        model = derive_true_color_model(planet)
        material = pygame.Surface((8, 4))
        material.fill((184, 72, 52))

        plain = render_true_color_surface(
            heightmap, model, target_size=(96, 48)
        )
        tinted = render_true_color_surface(
            heightmap,
            model,
            material_surface=material,
            target_size=(96, 48),
        )

        self.assertNotEqual(
            pygame.image.tostring(plain, "RGB"),
            pygame.image.tostring(tinted, "RGB"),
        )
        self.assertNotEqual(tinted.get_at((48, 24)), tinted.get_at((72, 24)))

    def test_individual_endmembers_drive_true_color_not_display_swatches(self):
        heightmap = _heightmap(ocean=False)
        heightmap["sample_grid"]["rows"] = [
            [500.0] * 5,
            [500.0] * 5,
            [500.0] * 5,
        ]
        planet = {
            "id": "endmember-world",
            "heightmap_model": heightmap,
            "atmosphere_model": {"surface_pressure_bar": 0.0},
            "natural_material_model": {
                "planet_tags": ["airless_regolith"],
            },
        }
        model = derive_true_color_model(planet)
        basalt = pygame.Surface((16, 8), pygame.SRCALPHA)
        anorthosite = pygame.Surface((16, 8), pygame.SRCALPHA)
        basalt.fill((200, 20, 200, 0))
        anorthosite.fill((200, 20, 200, 0))
        basalt.fill((200, 20, 200, 255), pygame.Rect(0, 0, 8, 8))
        anorthosite.fill(
            (200, 20, 200, 255),
            pygame.Rect(8, 0, 8, 8),
        )
        shared = {
            "distribution_role": "bedrock",
            "visual_role": "substrate",
            "process_driver": "geological_exposure",
            "display_color": [200, 20, 200],
        }
        rendered = render_true_color_surface(
            heightmap,
            model,
            material_components=[
                {
                    **shared,
                    "material_id": "mat_basalt",
                    "formation_category": "igneous_mafic",
                    "material_subclass": "rock",
                    "surface": basalt,
                },
                {
                    **shared,
                    "material_id": "mat_anorthosite",
                    "formation_category": "igneous_intrusive_felsic",
                    "material_subclass": "rock",
                    "surface": anorthosite,
                },
            ],
            target_size=(96, 48),
        )
        dark = sum(rendered.get_at((24, 24))[:3])
        bright = sum(rendered.get_at((72, 24))[:3])
        self.assertGreater(bright, dark * 1.35)
        self.assertLess(rendered.get_at((24, 24)).r, 150)

    def test_strong_ferric_colour_stays_inside_its_bounded_exposure(self):
        heightmap = _heightmap(ocean=False)
        heightmap["sample_grid"]["rows"] = [[500.0] * 5 for _ in range(3)]
        model = derive_true_color_model({
            "id": "localized-pigment-world",
            "heightmap_model": heightmap,
            "atmosphere_model": {"surface_pressure_bar": 0.0},
            "natural_material_model": {"planet_tags": []},
        })
        basalt = pygame.Surface((16, 8), pygame.SRCALPHA)
        basalt.fill((255, 255, 255, 255))
        hematite = pygame.Surface((16, 8), pygame.SRCALPHA)
        hematite.fill((255, 255, 255, 0))
        hematite.fill((255, 255, 255, 80), pygame.Rect(0, 0, 5, 8))
        rendered = render_true_color_surface(
            heightmap,
            model,
            material_components=[
                {
                    "material_id": "mat_basalt",
                    "formation_category": "igneous_mafic",
                    "material_subclass": "rock",
                    "visual_role": "substrate",
                    "surface": basalt,
                },
                {
                    "material_id": "mat_hematite",
                    "formation_category": "iron_weathering",
                    "material_subclass": "mineral",
                    "visual_role": "bounded_exposure",
                    "maximum_visible_fraction": 0.38,
                    "surface_expression_precomputed": True,
                    "surface": hematite,
                },
            ],
            target_size=(96, 48),
        )
        inside = rendered.get_at((12, 24))
        outside = rendered.get_at((78, 24))
        self.assertGreater(inside.r - inside.b, outside.r - outside.b + 20)
        self.assertLess(max(outside[:3]) - min(outside[:3]), 30)

    def test_four_mountain_lithologies_remain_distinct_in_production_renderer(self):
        heightmap = _heightmap(ocean=False)
        heightmap["sample_grid"]["rows"] = [[1200.0] * 5 for _ in range(3)]
        planet = {
            "id": "mountain-optics-calibration",
            "heightmap_model": heightmap,
            "atmosphere_model": {"surface_pressure_bar": 0.0},
            "natural_material_model": {"planet_tags": []},
        }
        model = derive_true_color_model(planet)
        cases = (
            ("mat_granite", "igneous_intrusive_felsic"),
            ("mat_limestone", "carbonate_sedimentary_basin"),
            ("mat_gneiss", "regional_metamorphism"),
            ("mat_andesite", "igneous_extrusive_intermediate"),
        )
        colors = {}
        for material_id, formation_category in cases:
            coverage = pygame.Surface((16, 8), pygame.SRCALPHA)
            coverage.fill((255, 0, 255, 255))
            rendered = render_true_color_surface(
                heightmap,
                model,
                material_components=[{
                    "material_id": material_id,
                    "formation_category": formation_category,
                    "material_subclass": "rock",
                    "distribution_role": "bedrock",
                    "visual_role": "substrate",
                    "surface": coverage,
                }],
                target_size=(96, 48),
            )
            colors[material_id] = tuple(rendered.get_at((48, 24))[:3])

        self.assertEqual(4, len(set(colors.values())))
        self.assertGreater(
            sum(colors["mat_limestone"]),
            sum(colors["mat_andesite"]) * 1.35,
        )
        self.assertGreater(colors["mat_granite"][0], colors["mat_granite"][2])
        self.assertLess(max(colors["mat_gneiss"]) - min(colors["mat_gneiss"]), 35)

    def test_surface_texture_changes_with_heightfield_not_only_seed(self):
        relief_heightmap = _heightmap(ocean=False)
        flat_heightmap = _heightmap(ocean=False)
        flat_heightmap["sample_grid"]["rows"] = [[500.0] * 5 for _ in range(3)]
        planet = {
            "id": "terrain-coupling",
            "surface_palette": {"surface_color": [132, 116, 94]},
            "atmosphere_model": {"surface_pressure_bar": 0.0},
            "natural_material_model": {"planet_tags": ["airless_regolith"]},
        }
        relief_model = derive_true_color_model(
            {**planet, "heightmap_model": relief_heightmap}
        )
        flat_model = derive_true_color_model(
            {**planet, "heightmap_model": flat_heightmap}
        )

        relief = render_true_color_surface(
            relief_heightmap, relief_model, target_size=(96, 48)
        )
        flat = render_true_color_surface(
            flat_heightmap, flat_model, target_size=(96, 48)
        )

        self.assertNotEqual(
            pygame.image.tostring(relief, "RGB"),
            pygame.image.tostring(flat, "RGB"),
        )

    def test_structural_bedrock_banding_renders_at_full_map_shape(self):
        heightmap = _heightmap(ocean=False)
        planet = {
            "id": "folded-range",
            "heightmap_model": heightmap,
            "surface_palette": {"surface_color": [132, 116, 94]},
            "atmosphere_model": {"surface_pressure_bar": 0.0},
            "natural_material_model": {"planet_tags": ["airless_regolith"]},
        }
        model = derive_true_color_model(planet)
        surface = render_true_color_surface(
            heightmap,
            model,
            surface_geomorphology={
                "model_version": "surface-geomorphology-test",
                "structural_fabric": {
                    "bedrock_banding_enabled": True,
                    "dominant_strike_degrees": 37.0,
                },
            },
            target_size=(96, 48),
        )

        self.assertEqual((96, 48), surface.get_size())

    def test_active_ocean_cycle_takes_precedence_over_oxidized_dust_tag(self):
        planet = {
            "id": "wet-oxidized-world",
            "heightmap_model": _heightmap(ocean=True),
            "atmosphere_model": {"surface_pressure_bar": 1.0},
            "water_cycle_model": {"model_version": "water-test"},
            "natural_material_model": {
                "planet_tags": ["oxidizing_surface", "aeolian_surface", "iron_rich_crust"],
            },
            "surface_evolution_model": {"process_means": {"aeolian_transport": 0.7}},
        }
        self.assertEqual("hydrologic", derive_true_color_model(planet)["surface_regime"])


if __name__ == "__main__":
    unittest.main()
