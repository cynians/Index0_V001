import unittest

from simulations.world_gen.material_formation import FORMATION_CATEGORIES
from simulations.world_gen.material_optics import (
    FORMATION_OPTICAL_FAMILIES,
    MATERIAL_OPTICAL_PROFILE_VERSION,
    material_optical_surface_profile,
    reflectance_triplet,
)
from simulations.world_gen.natural_materials import natural_material_entries
from simulations.world_gen.surface_exposure import (
    SURFACE_EXPOSURE_MODEL_VERSION,
    derive_surface_exposure_fields,
    derive_surface_exposure_model,
)


class MaterialOpticsTests(unittest.TestCase):
    def test_every_formation_category_has_an_optical_family(self):
        self.assertEqual(
            set(FORMATION_CATEGORIES),
            set(FORMATION_OPTICAL_FAMILIES),
        )

    def test_every_geologic_card_has_a_bounded_optical_profile(self):
        entries = [
            entry
            for entry in natural_material_entries()
            if entry.get("material_system_role") == "natural_geologic_material"
        ]
        self.assertEqual(200, len(entries))
        for entry in entries:
            profile = entry.get("optical_surface_profile")
            self.assertIsInstance(profile, dict, entry["id"])
            self.assertEqual(
                MATERIAL_OPTICAL_PROFILE_VERSION,
                profile.get("profile_version"),
                entry["id"],
            )
            for channel in reflectance_triplet(profile):
                self.assertGreaterEqual(channel, 0.002, entry["id"])
                self.assertLessEqual(channel, 0.98, entry["id"])
            self.assertIn(
                profile.get("mixing_mode"),
                {"intimate", "areal", "coating", "translucent"},
                entry["id"],
            )

    def test_representative_endmembers_have_expected_optical_order(self):
        basalt = material_optical_surface_profile(
            "mat_basalt",
            formation_category="igneous_mafic",
            material_subclass="rock",
        )
        anorthosite = material_optical_surface_profile(
            "mat_anorthosite",
            formation_category="igneous_intrusive_felsic",
            material_subclass="rock",
        )
        hematite = material_optical_surface_profile(
            "mat_hematite",
            formation_category="iron_weathering",
            material_subclass="mineral",
        )
        ice = material_optical_surface_profile(
            "mat_water_ice",
            formation_category="volatile_ice",
            material_subclass="ice",
        )
        self.assertLess(
            basalt["broadband_albedo"],
            anorthosite["broadband_albedo"],
        )
        self.assertLess(
            anorthosite["broadband_albedo"],
            ice["broadband_albedo"],
        )
        red, green, blue = reflectance_triplet(hematite)
        self.assertGreater(red, green * 3.0)
        self.assertGreater(green, blue)

    def test_natural_colour_families_are_distinct_without_display_swatches(self):
        cases = {
            "green_alteration": material_optical_surface_profile(
                "mat_serpentine",
                formation_category="hydrated_alteration",
                material_subclass="mineral",
            ),
            "red_oxide": material_optical_surface_profile(
                "mat_hematite",
                formation_category="iron_weathering",
                material_subclass="mineral",
            ),
            "yellow_sulfur": material_optical_surface_profile(
                "mat_native_sulfur",
                formation_category="sulfur_surface",
                material_subclass="mineral",
            ),
            "pale_salt": material_optical_surface_profile(
                "mat_halite",
                formation_category="evaporite_basin",
                material_subclass="mineral",
            ),
            "dark_mafic": material_optical_surface_profile(
                "mat_basalt",
                formation_category="igneous_mafic",
                material_subclass="rock",
            ),
        }
        green = reflectance_triplet(cases["green_alteration"])
        red = reflectance_triplet(cases["red_oxide"])
        yellow = reflectance_triplet(cases["yellow_sulfur"])
        pale = reflectance_triplet(cases["pale_salt"])
        dark = reflectance_triplet(cases["dark_mafic"])

        self.assertGreater(green[1], max(green[0], green[2]) * 1.35)
        self.assertGreater(red[0], red[1] * 3.0)
        self.assertGreater(yellow[0], yellow[2] * 8.0)
        self.assertGreater(yellow[1], yellow[2] * 5.0)
        self.assertGreater(sum(pale), sum(dark) * 6.0)
        self.assertEqual(5, len({tuple(values) for values in (green, red, yellow, pale, dark)}))

    def test_future_card_can_define_optical_coloring_power(self):
        profile = material_optical_surface_profile(
            "mat_future_blue_coating",
            formation_category="weathering_clay",
            material_subclass="mineral",
            explicit={
                "mixing_mode": "coating",
                "optical_coloring_power": 4.25,
            },
        )
        self.assertEqual("coating", profile["mixing_mode"])
        self.assertEqual(4.25, profile["optical_coloring_power"])

    def test_future_material_inherits_formation_optics_without_a_swatch(self):
        profile = material_optical_surface_profile(
            "mat_future_delta_mud",
            formation_category="fluvial_sediment",
            material_subclass="sediment",
        )
        self.assertEqual("siliciclastic", profile["family_id"])
        self.assertEqual(
            "formation_category_default",
            profile["source_kind"],
        )

    def test_four_mountain_lithology_regimes_resolve_distinct_surface_physics(self):
        granite = material_optical_surface_profile(
            "mat_granite",
            formation_category="igneous_intrusive_felsic",
            material_subclass="rock",
        )
        limestone = material_optical_surface_profile(
            "mat_limestone",
            formation_category="carbonate_sedimentary_basin",
            material_subclass="rock",
        )
        shale = material_optical_surface_profile(
            "mat_shale",
            formation_category="clastic_sedimentary_basin",
            material_subclass="rock",
        )
        gneiss = material_optical_surface_profile(
            "mat_gneiss",
            formation_category="regional_metamorphism",
            material_subclass="rock",
        )
        andesite = material_optical_surface_profile(
            "mat_andesite",
            formation_category="igneous_extrusive_intermediate",
            material_subclass="rock",
        )

        self.assertEqual("massive", granite["surface_fabric"])
        self.assertEqual("bedded", limestone["surface_fabric"])
        self.assertEqual("bedded", shale["surface_fabric"])
        self.assertEqual("foliated", gneiss["surface_fabric"])
        self.assertEqual("volcanic_flow", andesite["surface_fabric"])
        self.assertGreater(
            limestone["surface_fabric_strength"],
            granite["surface_fabric_strength"] * 10.0,
        )
        self.assertGreater(
            sum(reflectance_triplet(limestone)),
            sum(reflectance_triplet(shale)) * 3.0,
        )
        fresh = reflectance_triplet(andesite)
        weathered = andesite["weathered_visible_reflectance"]
        self.assertGreater(weathered["red_650nm"], fresh[0])
        self.assertLess(weathered["blue_450nm"], fresh[2])

    def test_alkaline_volcanic_provinces_do_not_share_one_optical_endmember(self):
        profiles = {
            material_id: material_optical_surface_profile(
                material_id,
                formation_category="igneous_extrusive_intermediate",
                material_subclass="rock",
            )
            for material_id in ("mat_andesite", "mat_trachyte", "mat_phonolite", "mat_latite")
        }
        triplets = {
            tuple(round(value, 4) for value in reflectance_triplet(profile))
            for profile in profiles.values()
        }
        self.assertEqual(4, len(triplets))
        trachyte = reflectance_triplet(profiles["mat_trachyte"])
        phonolite = reflectance_triplet(profiles["mat_phonolite"])
        self.assertGreater(sum(trachyte), sum(phonolite))
        self.assertGreater(phonolite[1], phonolite[0])

    def test_future_card_can_define_weathering_and_fabric_without_renderer_code(self):
        profile = material_optical_surface_profile(
            "mat_future_folded_rock",
            formation_category="regional_metamorphism",
            material_subclass="rock",
            explicit={
                "surface_fabric": "foliated",
                "surface_fabric_strength": 0.73,
                "weathered_visible_reflectance": {
                    "red_650nm": 0.31,
                    "green_550nm": 0.24,
                    "blue_450nm": 0.17,
                },
                "weathering_color_response": 0.64,
            },
        )
        self.assertEqual("foliated", profile["surface_fabric"])
        self.assertEqual(0.73, profile["surface_fabric_strength"])
        self.assertEqual(0.64, profile["weathering_color_response"])
        self.assertEqual(
            0.31,
            profile["weathered_visible_reflectance"]["red_650nm"],
        )

    def test_surface_exposure_stratifies_substrate_cover_and_constituents(self):
        heatmaps = {
            "model_version": "material-heatmaps-test",
            "layers": [
                {
                    "material_id": "mat_basalt",
                    "distribution_role": "bedrock",
                    "formation_category": "igneous_mafic",
                },
                {
                    "material_id": "mat_dune_sand",
                    "distribution_role": "surface_cover",
                    "formation_category": "aeolian_sediment",
                },
                {
                    "material_id": "mat_pyroxene",
                    "distribution_role": "mineral_constituent",
                    "formation_category": "mafic_rock_forming_phase",
                },
            ],
        }
        model = derive_surface_exposure_model(
            {},
            heightmap={"source_heightfield_fingerprint": "test"},
            material_heatmap_model=heatmaps,
        )
        self.assertEqual(
            SURFACE_EXPOSURE_MODEL_VERSION,
            model["model_version"],
        )
        roles = {
            item["material_id"]: item["visual_role"]
            for item in model["endmembers"]
        }
        self.assertEqual("substrate", roles["mat_basalt"])
        self.assertEqual(
            "mobile_or_regolith_cover",
            roles["mat_dune_sand"],
        )
        self.assertEqual(
            "intimate_substrate_component",
            roles["mat_pyroxene"],
        )

    def test_depositional_flatland_exposes_cover_above_bedrock(self):
        heightmap = {
            "sample_spacing_x_m": 1000.0,
            "sample_spacing_y_m": 1000.0,
            "sample_grid": {
                "rows": [[100.0] * 4 for _row in range(3)],
            },
        }
        evolution = {
            "process_grid": {
                "erosion_potential_rows": [[0.0] * 4 for _row in range(3)],
                "sediment_deposition_rows": [[1.0] * 4 for _row in range(3)],
                "aeolian_transport_rows": [[0.7] * 4 for _row in range(3)],
                "chemical_weathering_rows": [[0.2] * 4 for _row in range(3)],
                "glacial_erosion_rows": [[0.0] * 4 for _row in range(3)],
                "relative_surface_age_rows": [[0.7] * 4 for _row in range(3)],
            },
        }
        fields = derive_surface_exposure_fields(
            heightmap,
            {},
            surface_evolution=evolution,
            target_size=(16, 8),
        )
        self.assertGreater(
            float(fields["cover_fraction"].mean()),
            float(fields["bedrock_exposure"].mean()),
        )
        self.assertGreater(float(fields["cover_fraction"].mean()), 0.65)


if __name__ == "__main__":
    unittest.main()
