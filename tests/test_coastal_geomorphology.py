import math
import unittest

from simulations.world_gen.coastal_geomorphology import (
    _ordered_chains,
    _resolve_delta_systems,
    _shoreline_euclidean_distance_field,
    _squared_distance_transform_1d,
    derive_coastal_geomorphology_model,
    enrich_coastal_hydrology,
    ensure_coastal_model_current,
    inherit_parent_coastal_context,
    materialize_regional_coastal_landforms,
    stabilize_regional_coastal_topology,
)
from simulations.world_gen.heightmap import refresh_heightmap_derivatives
from simulations.world_gen.regional_refinement import (
    _scale_appropriate_relief,
    refinement_sample_dimensions,
    surface_detail_contract,
)


def _heightmap(*, steep=False, wrap=True):
    width, height = 33, 17
    rows = []
    for y in range(height):
        row = []
        for x in range(width):
            u = 0.0 if x == width - 1 and wrap else x / max(1, width - 1)
            coast = math.sin(u * math.tau * 2.0) * (900.0 if steep else 120.0)
            latitude = (y / (height - 1) - 0.5) * (2600.0 if steep else 260.0)
            row.append(round(coast + latitude, 2))
        if wrap:
            row[-1] = row[0]
        rows.append(row)
    return refresh_heightmap_derivatives({
        "status": "fixture",
        "projection": "equirectangular",
        "coverage": "full_planet" if wrap else "regional_patch",
        "wrap_x": wrap,
        "radius_m": 6_371_000.0,
        "circumference_m": 40_030_000.0,
        "equator_resolution_m_per_px": 1_250_000.0,
        "sea_level_m": 0.0,
        "sea_level_locked": True,
        "sample_grid": {"width": width, "height": height, "wrap_x": wrap, "rows": rows},
        "surface_masks": {"ice_rows": [[False] * width for _ in range(height)]},
    })


def _water(heightmap):
    rows = heightmap["sample_grid"]["rows"]
    height, width = len(rows), len(rows[0])
    return {
        "model_version": "fixture-water-v1",
        "climate_grid": {
            "temperature_seasonality_rows_k": [[18.0] * width for _ in range(height)],
        },
        "rivers": [{
            "id": "river_fixture",
            "points": [[width // 2, 2], [width // 2, height // 2]],
            "estimated_discharge_m3_s": 6000.0,
        }],
    }


class CoastalGeomorphologyTests(unittest.TestCase):
    @staticmethod
    def _delta_segment(*, wave=0.15, tide_m=0.6, gradient=0.002):
        return {
            "id": "coast_delta_test",
            "measurements": {
                "centroid_uv": [0.5, 0.5],
                "seaward_normal_uv": [1.0, 0.0],
                "nearshore_gradient": gradient,
                "embayment_index": 0.45,
                "shelf_width_km": 80.0,
            },
            "wave_climate": {
                "transport_capacity_index": wave,
            },
            "tidal_regime": {
                "estimated_range_m": tide_m,
            },
            "sediment_budget": {
                "river_supply": 0.75,
                "accommodation_index": 0.7,
            },
            "relative_sea_level_state": "stable",
            "substrate": "mud",
            "influences": {"material_erodibility_proxy": 0.8},
            "primary_assemblage": "clastic_beach",
            "morphology_assemblage": "clastic_beach",
            "coastal_system": "clastic_beach",
            "rule_trace": {},
        }

    @staticmethod
    def _delta_river(**overrides):
        river = {
            "id": "river_delta_test",
            "mouth": "ocean",
            "flow_regime": "perennial",
            "estimated_discharge_m3_s": 4200.0,
            "catchment_area_km2": 420_000.0,
            "catchment_mean_runoff_mm": 480.0,
            "source_elevation_m": 1800.0,
            "channel_morphology": {"gradient_m_per_m": 0.004},
            "points": [
                {"x": 0.45, "y": 0.5},
                {"x": 0.5, "y": 0.5},
            ],
        }
        river.update(overrides)
        return river

    def test_sediment_rich_river_builds_planform_and_distributaries(self):
        segment = self._delta_segment()
        assessments, deltas = _resolve_delta_systems(
            {"rivers": [self._delta_river()]},
            [segment],
            width=129,
            height=65,
            wrap_x=False,
        )

        self.assertEqual(1, len(deltas))
        self.assertEqual("formed_delta", assessments[0]["formation_state"])
        self.assertEqual("deltaic", segment["coastal_system"])
        self.assertGreaterEqual(len(deltas[0]["footprint_points"]), 5)
        self.assertEqual(
            deltas[0]["distributary_count"],
            len(deltas[0]["distributaries"]),
        )
        self.assertEqual("prograding", deltas[0]["trajectory"])

    def test_sediment_starved_steep_mouth_does_not_become_delta(self):
        segment = self._delta_segment(
            wave=0.9,
            tide_m=4.5,
            gradient=0.025,
        )
        segment["sediment_budget"]["river_supply"] = 0.02
        segment["influences"]["material_erodibility_proxy"] = 0.08
        river = self._delta_river(
            estimated_discharge_m3_s=0.4,
            catchment_area_km2=45.0,
            catchment_mean_runoff_mm=8.0,
            source_elevation_m=90.0,
            flow_regime="intermittent",
            channel_morphology={"gradient_m_per_m": 0.0002},
        )

        assessments, deltas = _resolve_delta_systems(
            {"rivers": [river]},
            [segment],
            width=129,
            height=65,
            wrap_x=False,
        )

        self.assertEqual([], deltas)
        self.assertEqual("no_delta", assessments[0]["formation_state"])
        self.assertNotEqual("deltaic", segment["coastal_system"])

    def test_strong_tidal_work_shapes_but_does_not_forbid_supplied_delta(self):
        segment = self._delta_segment(wave=0.18, tide_m=5.0)
        assessments, deltas = _resolve_delta_systems(
            {"rivers": [self._delta_river()]},
            [segment],
            width=129,
            height=65,
            wrap_x=False,
        )

        self.assertTrue(deltas)
        self.assertEqual("tide_dominated", deltas[0]["morphodynamic_dominance"])
        self.assertGreater(
            assessments[0]["sediment_supply_index"],
            assessments[0]["reworking_index"] * 0.5,
        )

    def test_lake_receives_a_lacustrine_delta_without_marine_forcing(self):
        river = self._delta_river(
            mouth="lake",
            points=[[48, 28], [64, 32]],
        )
        assessments, deltas = _resolve_delta_systems(
            {
                "rivers": [river],
                "lakes": [{
                    "id": "lake_delta_test",
                    "center": {"x": 0.5, "y": 0.5},
                    "area_fraction": 0.04,
                    "water_balance_limited": False,
                }],
            },
            [],
            width=129,
            height=65,
            wrap_x=False,
        )

        self.assertEqual("formed_delta", assessments[0]["formation_state"])
        self.assertEqual("lacustrine", deltas[0]["morphodynamic_dominance"])
        self.assertEqual({"x": 0.5, "y": 0.5}, deltas[0]["center"])
        self.assertGreaterEqual(len(deltas[0]["distributaries"]), 3)

    def test_physical_distance_transform_is_euclidean_and_anisotropic(self):
        distances, nearest = _squared_distance_transform_1d(
            [math.inf, 0.0, math.inf, math.inf], 2.0,
        )
        self.assertEqual([4.0, 0.0, 4.0, 16.0], distances)
        self.assertEqual([1, 1, 1, 1], nearest)

        shoreline = [
            [False, False, False],
            [False, True, False],
            [False, False, False],
        ]
        morphologies = [
            [None, None, None],
            [None, "rocky_cliff", None],
            [None, None, None],
        ]
        field, morphology = _shoreline_euclidean_distance_field(
            shoreline, morphologies, 2.0, 3.0,
        )
        self.assertAlmostEqual(math.sqrt(13.0), field[0][0])
        self.assertEqual("rocky_cliff", morphology[0][0])

    def test_local_shoreline_chains_do_not_wrap_opposite_patch_edges(self):
        edges = [([0.0, 0.2], [0.1, 0.2]), ([1.0, 0.2], [0.9, 0.2])]
        self.assertEqual(2, len(_ordered_chains(edges, wrap_x=False)))
        self.assertEqual(1, len(_ordered_chains(edges, wrap_x=True)))

    def test_derivative_refresh_conserves_water_and_excludes_duplicate_seam(self):
        model = _heightmap()
        model["sea_level_locked"] = False
        model["equivalent_global_water_depth_m"] = 80.0
        refreshed = refresh_heightmap_derivatives(model)
        self.assertEqual("heightmap-derivatives-v1", refreshed["derivative_model_version"])
        self.assertEqual("volume_balance_against_evolved_hypsometry", refreshed["sea_level_resolution"])
        self.assertTrue(refreshed["hypsometry_summary"]["duplicate_longitude_seam_excluded"])
        self.assertEqual(
            refreshed["surface_masks"]["land_rows"][0][0],
            refreshed["surface_masks"]["land_rows"][0][-1],
        )

    def test_shoreline_ids_and_classifications_are_deterministic(self):
        heightmap = _heightmap(steep=True)
        planet = {"id": "fixture", "radius_m": 6_371_000.0, "tags": ["solid_surface"]}
        first = derive_coastal_geomorphology_model(
            planet=planet, heightmap=heightmap, water_cycle=_water(heightmap),
            tectonic_model={}, surface_evolution={}, star={},
        )
        second = derive_coastal_geomorphology_model(
            planet=planet, heightmap=heightmap, water_cycle=_water(heightmap),
            tectonic_model={}, surface_evolution={}, star={},
        )
        self.assertGreater(len(first["segments"]), 0)
        self.assertEqual(
            [segment["id"] for segment in first["segments"]],
            [segment["id"] for segment in second["segments"]],
        )
        self.assertEqual(first["summary"], second["summary"])
        self.assertTrue(all(segment["rule_trace"]["reduced_physics"] for segment in first["segments"]))

    def test_biogenic_coasts_remain_unoccupied_without_biosphere(self):
        heightmap = _heightmap()
        model = derive_coastal_geomorphology_model(
            planet={"id": "carbonate", "tags": ["carbonate_surface"]},
            heightmap=heightmap,
            water_cycle=_water(heightmap),
            tectonic_model={},
            surface_evolution={},
            star={},
        )
        self.assertTrue(model["segments"])
        self.assertTrue(all(not segment["biogenic_accommodation"]["occupied"] for segment in model["segments"]))
        self.assertTrue(all(segment["biogenic_accommodation"]["requires_biosphere_result"] for segment in model["segments"]))

    def test_older_saved_world_rebuilds_stale_derivatives_and_coast(self):
        heightmap = _heightmap()
        heightmap.pop("derivatives", None)
        heightmap.pop("source_heightfield_fingerprint", None)
        planet = {"id": "legacy", "heightmap_model": heightmap, "water_cycle_model": _water(heightmap)}

        self.assertTrue(ensure_coastal_model_current(planet))
        self.assertEqual("current", planet["heightmap_model"]["derivatives"]["status"])
        self.assertEqual("coastal_geomorphology_resolved", planet["coastal_geomorphology_model"]["status"])

    def test_fjord_label_requires_glacial_erosion(self):
        heightmap = _heightmap(steep=True)
        model = derive_coastal_geomorphology_model(
            planet={"id": "nonglacial"}, heightmap=heightmap,
            water_cycle=_water(heightmap), tectonic_model={},
            surface_evolution={}, star={},
        )
        self.assertNotIn("glacial_fjord_fjard_skerry", {segment["primary_assemblage"] for segment in model["segments"]})

    def test_required_causal_gates_control_specialized_coasts(self):
        low = _heightmap()
        ordinary = derive_coastal_geomorphology_model(
            planet={"id": "ordinary"}, heightmap=low, water_cycle=_water(low),
            tectonic_model={}, surface_evolution={}, star={},
        )
        ordinary_types = {segment["primary_assemblage"] for segment in ordinary["segments"]}
        self.assertTrue(ordinary_types & {"clastic_beach", "barrier_lagoon"})
        self.assertNotIn("volcanic", ordinary_types)
        self.assertNotIn("carbonate_karst", ordinary_types)
        self.assertNotIn("permafrost", ordinary_types)

        carbonate = derive_coastal_geomorphology_model(
            planet={"id": "carbonate", "tags": ["carbonate_surface"]}, heightmap=low,
            water_cycle=_water(low), tectonic_model={}, surface_evolution={}, star={},
        )
        volcanic = derive_coastal_geomorphology_model(
            planet={"id": "volcanic", "tags": ["volcanic_surface"]}, heightmap=low,
            water_cycle=_water(low), tectonic_model={}, surface_evolution={}, star={},
        )
        self.assertEqual({"carbonate_karst"}, {segment["primary_assemblage"] for segment in carbonate["segments"]})
        self.assertEqual({"volcanic"}, {segment["primary_assemblage"] for segment in volcanic["segments"]})
        self.assertTrue(all(segment["morphology_assemblage"] != "carbonate_karst" for segment in carbonate["segments"]))
        self.assertTrue(all(segment["morphology_assemblage"] != "volcanic" for segment in volcanic["segments"]))
        self.assertTrue(all("carbonate_karst" in segment["geologic_characters"] for segment in carbonate["segments"]))
        self.assertTrue(all("volcanic" in segment["geologic_characters"] for segment in volcanic["segments"]))

    def test_planet_wide_volcanic_context_is_localized_by_spatial_tectonics(self):
        heightmap = _heightmap()
        model = derive_coastal_geomorphology_model(
            planet={"id": "localized-volcanism", "tags": ["volcanic_surface"]},
            heightmap=heightmap,
            water_cycle=_water(heightmap),
            tectonic_model={
                "status": "tectonics_advanced",
                "hotspot_model": {
                    "hotspots": [{
                        "track": [{
                            "x": 0.08,
                            "y": 0.5,
                            "age_myr": 0.0,
                            "relative_volume": 1.0,
                        }],
                    }],
                },
            },
            surface_evolution={},
            star={},
        )
        assemblages = {segment["primary_assemblage"] for segment in model["segments"]}
        self.assertTrue(assemblages - {"volcanic"})
        self.assertTrue(any(not segment["influences"]["volcanic"] for segment in model["segments"]))

    def test_regional_centroids_retain_planetary_coordinate_context(self):
        heightmap = _heightmap(wrap=False)
        heightmap["coverage"] = "regional_patch"
        heightmap["source_uv_bounds"] = {
            "min_u": 0.62,
            "max_u": 0.66,
            "min_v": 0.18,
            "max_v": 0.22,
        }
        model = derive_coastal_geomorphology_model(
            planet={"id": "regional-coordinates"},
            heightmap=heightmap,
            water_cycle=_water(heightmap),
            tectonic_model={},
            surface_evolution={},
            star={},
        )
        self.assertTrue(model["segments"])
        for segment in model["segments"]:
            planetary = segment["measurements"]["planetary_centroid_uv"]
            self.assertGreaterEqual(planetary[0], 0.62)
            self.assertLessEqual(planetary[0], 0.66)
            self.assertGreaterEqual(planetary[1], 0.18)
            self.assertLessEqual(planetary[1], 0.22)

    def test_sediment_starved_steep_coast_does_not_form_barriers(self):
        heightmap = _heightmap(steep=True)
        model = derive_coastal_geomorphology_model(
            planet={"id": "cliff"}, heightmap=heightmap,
            water_cycle={"climate_grid": {}}, tectonic_model={}, surface_evolution={}, star={},
        )
        self.assertNotIn("barrier_lagoon", {segment["primary_assemblage"] for segment in model["segments"]})

    def test_delta_records_receive_wave_tide_and_river_end_member(self):
        heightmap = _heightmap()
        water = _water(heightmap)
        water["deltas"] = [{"id": "delta_fixture", "center": {"x": 0.5, "y": 0.5}}]
        water["drainage_network_model"] = {"deltas": water["deltas"]}
        model = derive_coastal_geomorphology_model(
            planet={"id": "delta"}, heightmap=heightmap, water_cycle=water,
            tectonic_model={}, surface_evolution={}, star={},
        )
        enrich_coastal_hydrology(water, model)
        delta = water["deltas"][0]
        self.assertIn(delta["marine_reworking_end_member"], {"river_dominated", "wave_dominated", "tide_dominated"})
        self.assertIn("coastal_segment_id", delta)
        self.assertEqual({"river_dominated", "wave_dominated", "tide_dominated"}, set(delta["forcing_strengths"]))

    def test_available_satellite_orbit_contributes_to_tidal_potential(self):
        heightmap = _heightmap()
        star = {"mass_kg": 1.98847e30}
        base = {"id": "tides", "radius_m": 6_371_000.0, "semi_major_axis_m": 149_597_870_700.0}
        solar_only = derive_coastal_geomorphology_model(
            planet=base, heightmap=heightmap, water_cycle=_water(heightmap),
            tectonic_model={}, surface_evolution={}, star=star,
        )
        with_moon = derive_coastal_geomorphology_model(
            planet={**base, "satellites": [{"id": "moon", "mass_kg": 7.342e22, "semi_major_axis_m": 384_400_000.0}]},
            heightmap=heightmap, water_cycle=_water(heightmap),
            tectonic_model={}, surface_evolution={}, star=star,
        )
        self.assertGreater(
            with_moon["segments"][0]["tidal_regime"]["estimated_range_m"],
            solar_only["segments"][0]["tidal_regime"]["estimated_range_m"],
        )
        self.assertIn("moon", with_moon["segments"][0]["tidal_regime"]["contributors"])

    def test_regional_landforms_request_exactly_one_drainage_reconciliation(self):
        heightmap = _heightmap(wrap=False)
        model = derive_coastal_geomorphology_model(
            planet={"id": "region"}, heightmap=heightmap,
            water_cycle=_water(heightmap), tectonic_model={},
            surface_evolution={}, star={},
        )
        changed, refinement = materialize_regional_coastal_landforms(heightmap, model, detail_level=2)
        self.assertIsInstance(changed, dict)
        if refinement["status"] == "regional_coastal_landforms_materialized":
            self.assertTrue(refinement["drainage_reconciliation_required"])
            self.assertTrue(refinement["sediment_budget_conserved"])
            self.assertEqual(
                heightmap["sample_grid"]["rows"][0],
                changed["sample_grid"]["rows"][0],
            )

    def test_parent_coastal_system_rejects_incompatible_local_class(self):
        parent = {
            "segments": [{
                "id": "parent_delta",
                "primary_assemblage": "deltaic",
                "morphology_assemblage": "deltaic",
                "coastal_system": "deltaic",
                "measurements": {"planetary_centroid_uv": [0.4, 0.6]},
            }],
        }
        child = {
            "segments": [{
                "id": "child",
                "primary_assemblage": "volcanic",
                "morphology_assemblage": "rocky_cliff",
                "geologic_characters": ["volcanic"],
                "measurements": {"planetary_centroid_uv": [0.401, 0.599]},
            }],
        }
        inherit_parent_coastal_context(child, parent)
        segment = child["segments"][0]
        self.assertEqual("deltaic", segment["coastal_system"])
        self.assertEqual("deltaic", segment["morphology_assemblage"])
        self.assertEqual("rocky_cliff", segment["local_morphology_assemblage"])
        self.assertEqual(["volcanic"], segment["geologic_characters"])

    def test_locally_resolved_delta_survives_coarser_parent_coast_label(self):
        parent = {
            "segments": [{
                "id": "parent_rocky",
                "primary_assemblage": "rocky_cliff",
                "morphology_assemblage": "rocky_cliff",
                "coastal_system": "rocky_cliff",
                "measurements": {"planetary_centroid_uv": [0.4, 0.6]},
            }],
        }
        child = {
            "segments": [{
                "id": "child_delta",
                "delta_id": "delta_001",
                "primary_assemblage": "deltaic",
                "morphology_assemblage": "deltaic",
                "coastal_system": "deltaic",
                "measurements": {"planetary_centroid_uv": [0.401, 0.599]},
            }],
        }

        inherit_parent_coastal_context(child, parent)

        segment = child["segments"][0]
        self.assertEqual("deltaic", segment["coastal_system"])
        self.assertEqual("deltaic", segment["morphology_assemblage"])
        self.assertEqual(
            "locally_resolved_delta_retained_from_sediment_budget",
            segment["scale_consistency"],
        )

    def test_delta_relief_is_bounded_by_physical_footprint(self):
        rows = [[-110.0, 0.0, 110.0], [-90.0, 0.0, 90.0], [-70.0, 0.0, 70.0]]
        limited, audit = _scale_appropriate_relief(
            rows, 0.0, 10.0, 10.0, {"coastal_system": "deltaic"},
        )
        resolved_range = max(max(row) for row in limited) - min(min(row) for row in limited)
        self.assertTrue(audit["applied"])
        self.assertLessEqual(resolved_range, 1.200001)

    def test_survey_scale_keeps_object_detail_out_of_heightfield_features(self):
        heightmap = _heightmap(wrap=False)
        heightmap["region_width_m"] = 10.0
        heightmap["region_height_m"] = 10.0
        heightmap["sample_spacing_x_m"] = 10.0 / 32.0
        heightmap["sample_spacing_y_m"] = 10.0 / 16.0
        model = derive_coastal_geomorphology_model(
            planet={"id": "survey"}, heightmap=heightmap,
            water_cycle=_water(heightmap), tectonic_model={},
            surface_evolution={}, star={},
        )
        _changed, refinement = materialize_regional_coastal_landforms(
            heightmap, model, detail_level=7,
        )
        self.assertNotIn("clast_scale_roughness", refinement["resolved_feature_families"])
        self.assertIn("clasts", refinement["deferred_object_detail_families"])
        self.assertEqual("sparse_objects_not_heightfield", refinement["object_detail_policy"])
        self.assertTrue(refinement["profile_amplitudes_scaled_to_physical_footprint"])

    def test_survey_topology_removes_single_cell_coastal_speckle(self):
        rows = [[1.0] * 9 for _ in range(9)]
        rows[4][4] = -1.0
        rows[2][2] = -1.0
        heightmap = {
            "sea_level_m": 0.0,
            "sample_spacing_x_m": 0.05,
            "sample_grid": {"width": 9, "height": 9, "wrap_x": False, "rows": rows},
        }
        changed, audit = stabilize_regional_coastal_topology(heightmap, detail_level=7)
        self.assertGreaterEqual(audit["flipped_cell_count"], 2)
        self.assertGreater(changed["sample_grid"]["rows"][4][4], 0.0)
        self.assertGreater(changed["sample_grid"]["rows"][2][2], 0.0)

    def test_ground_detail_sampling_stops_at_ten_centimetres(self):
        self.assertEqual((301, 301), refinement_sample_dimensions(6, 30.0, 30.0))
        self.assertEqual((101, 101), refinement_sample_dimensions(7, 10.0, 10.0))
        width, height = refinement_sample_dimensions(7, 10.05, 10.05)
        self.assertGreaterEqual(10.05 / (width - 1), 0.10)
        self.assertGreaterEqual(10.05 / (height - 1), 0.10)

    def test_surface_detail_contract_defers_insect_and_clast_scale_objects(self):
        contract = surface_detail_contract({
            "map_detail_level": 7,
            "sample_spacing_x_m": 0.1,
            "sample_spacing_y_m": 0.1,
        })
        self.assertEqual(0.1, contract["minimum_terrain_sample_spacing_m"])
        self.assertTrue(contract["object_detail_layer"]["active_for_this_region"])
        self.assertIn("loose_rocks", contract["object_detail_layer"]["future_object_families"])
        self.assertIn("individual_organisms", contract["heightfield_exclusions"])

    def test_topology_removes_sub_half_metre_enclosed_pool_at_ten_cm_grid(self):
        rows = [[1.0] * 15 for _ in range(15)]
        for y in range(6, 9):
            for x in range(6, 9):
                rows[y][x] = -1.0
        heightmap = {
            "sea_level_m": 0.0,
            "sample_spacing_x_m": 0.1,
            "sample_spacing_y_m": 0.1,
            "sample_grid": {"width": 15, "height": 15, "wrap_x": False, "rows": rows},
        }
        changed, audit = stabilize_regional_coastal_topology(heightmap, detail_level=7)
        self.assertGreaterEqual(audit["flipped_cell_count"], 9)
        self.assertGreater(changed["sample_grid"]["rows"][7][7], 0.0)


if __name__ == "__main__":
    unittest.main()
