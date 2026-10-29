"""Behaviour of the material LOD pipeline and its vectorised terrain helpers.

See docs/worldgen_material_lod_plan_v001.md.
"""

import math
import os
import random
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import numpy as np
import pygame

from simulations.world_gen import heightmap as heightmap_module
from simulations.world_gen import water_cycle
from simulations.world_gen.lithotectonic_settings import (
    SETTING_IDS,
    classify_lithotectonic_settings,
    resolve_setting_recipes,
)
from simulations.world_gen.material_heatmaps import (
    generate_material_heatmap_model,
    load_parent_composition,
    load_raster_bundle_surface,
    planet_circumference_m,
)
from simulations.world_gen.material_lod import (
    COVER_CLASS_IDS,
    _parent_composition_sampler,
    _race_select,
    assemble_visible_composition,
    derive_child_material_product,
    label_components,
    rasterize_occurrences,
)
from simulations.world_gen.material_lineage import (
    TRUE_COLOR_LINEAGE_BUDGET,
    lineage_delta_e,
    linear_rgb_to_lab,
)
from simulations.world_gen.natural_materials import configure_material_catalog
from simulations.world_gen.true_color import AREAL_FRACTION_SEMANTICS, _mix_material_endmembers
from world.persistent_ontology_store import PersistentOntologyStore


def setUpModule():
    rows = PersistentOntologyStore(
        Path(__file__).resolve().parents[1] / "ontology" / "index0.owl"
    ).load_datasets().get("materials") or []
    configure_material_catalog(rows)


def _subduction_model():
    """One ocean-continent subduction boundary along v = 0.5 (overriding +v)."""
    segments = []
    for index in range(8):
        x1 = 0.30 + index * 0.05
        segments.append({
            "x1": x1, "y1": 0.5, "x2": x1 + 0.05, "y2": 0.5,
            "normal_x": 0.0, "normal_y": 1.0,
            "influence_width": 0.03, "activity_scale": 1.0,
            "orogen_system_id": "arc_system", "kind": "subduction",
        })
    return {
        "map_seed": "subduction-test",
        "plates": [
            {"id": "continent", "center_x": 0.5, "center_y": 0.75, "plate_type": "continental"},
            {"id": "ocean", "center_x": 0.5, "center_y": 0.25, "plate_type": "oceanic"},
        ],
        "boundary_segments": segments,
        "orogen_system_model": {"systems": [{
            "id": "arc_system",
            "mechanism": "ocean_continent_subduction",
            "sides": {"overriding_normal_side": 1},
            "forcing_profile": {
                "rock_uplift_peak_m": 2400.0,
                "tectonic_subsidence_peak_m": 3000.0,
                "volcanic_construction_peak_m": 1800.0,
                "reference_width": 0.03,
            },
        }]},
        "lithosphere_grid": {
            # Rows are v = 0 .. 1; continental crust north of the boundary.
            "continental_fraction_rows": [[0.0] * 9] * 4 + [[1.0] * 9] * 5,
            "ocean_floor_age_rows_myr": [[80.0] * 9] * 4 + [[0.0] * 9] * 5,
        },
    }


class VectorisedTerrainParityTests(unittest.TestCase):
    def test_orogen_forcing_grid_matches_scalar_evaluator(self):
        model = heightmap_module._ensure_heightmap_tectonic_model(_subduction_model())
        u_values = np.linspace(0.25, 0.75, 41)
        v_values = np.linspace(0.40, 0.62, 23)
        grid = heightmap_module.orogen_forcing_grid(u_values, v_values, model)
        rng = random.Random(4)
        for _ in range(120):
            y = rng.randrange(v_values.size)
            x = rng.randrange(u_values.size)
            scalar = heightmap_module._orogen_forcing_at(float(u_values[x]), float(v_values[y]), model)
            for key, value in scalar.items():
                self.assertAlmostEqual(float(value), float(grid[key][y, x]), places=6, msg=key)

    def test_mountain_mask_array_matches_python_reference(self):
        model = heightmap_module._ensure_heightmap_tectonic_model(_subduction_model())
        rng = random.Random(9)
        rows = [[rng.uniform(-400.0, 2600.0) for _x in range(33)] for _y in range(21)]
        land = [[value > 0.0 for value in row] for row in rows]
        kwargs = {
            "wrap_x": False,
            "tectonic_model": model,
            "source_uv_bounds": {"min_u": 0.35, "max_u": 0.65, "min_v": 0.42, "max_v": 0.60},
            "sea_level": 0.0,
        }
        new_mask, new_threshold = heightmap_module._mountain_morphology_mask_array(rows, land, 12_000.0, **kwargs)
        old_mask, old_threshold = heightmap_module._mountain_morphology_mask_python(rows, land, 12_000.0, **kwargs)
        self.assertEqual(old_threshold, new_threshold)
        worst = max(abs(a - b) for row_a, row_b in zip(old_mask, new_mask) for a, b in zip(row_a, row_b))
        self.assertLessEqual(worst, 1.01e-4)

    def test_koppen_display_grid_array_matches_python_reference(self):
        height, width = 9, 17
        yy, xx = np.mgrid[0:height, 0:width]
        latitude = (0.5 - yy / (height - 1)) * 180.0
        fields = [
            300.0 - np.abs(latitude) * 0.9 + np.sin(xx * 0.7) * 6.0,
            12.0 + np.abs(latitude) * 0.3,
            np.clip(2200.0 * np.cos(np.radians(latitude)) ** 2 + np.sin(xx) * 300.0, 0.0, None),
            np.clip(0.5 + np.sin(xx * 0.4) * 0.4, 0.0, 1.0),
            np.clip(0.5 + np.cos(yy * 0.5) * 0.4, 0.0, 1.0),
            np.sin(xx * 0.9 + yy) * 1500.0,
        ]
        for values in fields:
            values[:, -1] = values[:, 0]
        rows = [values.tolist() for values in fields]
        kwargs = dict(sea_level=0.0, map_seed="parity", source_uv_bounds={}, wrap_x=True)
        new_classes, new_elevation = water_cycle._derive_koppen_display_grid(*rows, **kwargs)
        saved = water_cycle.np
        water_cycle.np = None
        try:
            old_classes, old_elevation = water_cycle._derive_koppen_display_grid(*rows, **kwargs)
        finally:
            water_cycle.np = saved
        self.assertEqual(old_classes, new_classes)
        self.assertEqual(old_elevation, new_elevation)


class LithotectonicClassificationTests(unittest.TestCase):
    def test_subduction_places_arc_inland_and_forearc_toward_the_trench(self):
        u_values = np.linspace(0.0, 1.0, 101)
        v_values = np.linspace(0.0, 1.0, 101)
        memberships, _evidence = classify_lithotectonic_settings(
            u_values, v_values, tectonic_model=_subduction_model(),
        )
        column = 50  # u = 0.5, mid-boundary
        arc_row = int(round((0.5 + 1.24 * 0.03) * 100))
        forearc_row = int(round((0.5 - 0.10 * 0.03) * 100))
        dominant = memberships.argmax(axis=0)
        self.assertEqual("continental_arc", SETTING_IDS[dominant[arc_row, column]])
        self.assertEqual("forearc_accretionary", SETTING_IDS[dominant[forearc_row, column]])
        self.assertIn(SETTING_IDS[dominant[10, column]], {"abyssal_ocean_floor", "oceanic_ridge"})
        self.assertAlmostEqual(1.0, float(memberships.sum(axis=0).mean()), places=5)

    def test_recipes_follow_ontology_setting_weights_and_chemistry(self):
        candidates = [
            {"material_id": "mat_granite", "confidence": 0.9},
            {"material_id": "mat_gneiss", "confidence": 0.9},
            {"material_id": "mat_basalt", "confidence": 0.9},
        ]
        recipes, provenance = resolve_setting_recipes({"likely_materials": candidates})
        shield = dict(recipes["exposed_shield"])
        self.assertIn("mat_gneiss", shield)
        self.assertIn("mat_granite", shield)
        self.assertNotIn("mat_basalt", shield)
        self.assertEqual("mat_basalt", recipes["oceanic_ridge"][0][0])
        self.assertEqual("direct", provenance["exposed_shield"])
        for recipe in recipes.values():
            self.assertAlmostEqual(1.0, sum(share for _material_id, share in recipe), places=6)

    def test_ultramafic_chemistry_moves_mafic_volcanic_share_to_ultramafic_rocks(self):
        candidates = [
            {"material_id": "mat_basalt", "confidence": 0.9, "relative_abundance": 0.68},
            {"material_id": "mat_komatiite", "confidence": 0.9, "relative_abundance": 1.0},
        ]
        plain, _ = resolve_setting_recipes({"likely_materials": candidates, "planet_tags": []})
        ultramafic, _ = resolve_setting_recipes({"likely_materials": candidates, "planet_tags": ["ultramafic_tendency"]})
        self.assertGreater(
            dict(ultramafic["volcanic_plains"]).get("mat_komatiite", 0.0),
            dict(plain["volcanic_plains"]).get("mat_komatiite", 0.0) + 0.3,
        )


class CompositionTests(unittest.TestCase):
    def _heightmap(self, *, size=65, level=2, bounds=None):
        rng = np.random.default_rng(3)
        yy, xx = np.mgrid[0:size, 0:size]
        rows = 400.0 + 300.0 * np.sin(xx / 7.0) * np.cos(yy / 9.0) + rng.normal(0.0, 20.0, (size, size))
        return {
            "map_detail_level": level,
            "sea_level_m": 0.0,
            "wrap_x": False,
            "map_seed": "composition-test",
            "source_uv_bounds": bounds or {"min_u": 0.40, "max_u": 0.4025, "min_v": 0.40, "max_v": 0.405},
            "region_width_m": 100_000.0,
            "region_height_m": 100_000.0,
            "sample_grid": {"rows": rows.round(1).tolist()},
        }

    def test_child_units_preserve_the_parent_mixture(self):
        heightmap = self._heightmap()
        parent = {
            "material_ids": ["mat_granite", "mat_basalt"],
            "composition": np.stack([np.full((5, 5), 0.6), np.full((5, 5), 0.4)]).astype(np.float32),
            "bounds": {"min_u": 0.39, "max_u": 0.41, "min_v": 0.39, "max_v": 0.41},
            "wrap_x": False,
        }
        product = derive_child_material_product(
            {"id": "child", "radius_m": 6_371_000.0},
            {"planet_tags": [], "likely_materials": [
                {"material_id": "mat_granite", "confidence": 0.9},
                {"material_id": "mat_basalt", "confidence": 0.9},
            ]},
            heightmap,
            parent=parent,
            level=1,
            map_seed="composition-test",
            circumference_m=40_030_000.0,
        )
        substrate = dict(zip(product["substrate_ids"], product["substrate"].mean(axis=(1, 2))))
        self.assertAlmostEqual(0.6, substrate["mat_granite"], delta=0.15)
        self.assertAlmostEqual(0.4, substrate["mat_basalt"], delta=0.15)
        # Mapped units are mostly one lithology (purity), not the parent blend.
        self.assertGreater(float(product["substrate"].max(axis=0).mean()), 0.7)

    def test_units_are_bodies_of_many_cells_even_on_a_tile_too_coarse_for_its_level(self):
        # A "Macroregion" refined over most of a planet: 48 km cells, against
        # units of 60 km at that level.  Every cell used to draw its own unit.
        size = 97
        heightmap = self._heightmap(size=size, level=1, bounds={"min_u": 0.2, "max_u": 0.2 + 96 * 48_000.0 / 40_030_000.0,
                                                               "min_v": 0.3, "max_v": 0.3 + 96 * 48_000.0 / 20_015_000.0})
        parent = {
            "material_ids": ["mat_granite", "mat_basalt", "mat_gabbro"],
            "composition": np.stack([np.full((9, 9), 0.4), np.full((9, 9), 0.35), np.full((9, 9), 0.25)]).astype(np.float32),
            "bounds": {"min_u": 0.15, "max_u": 0.45, "min_v": 0.25, "max_v": 0.6},
            "wrap_x": False,
        }
        product = derive_child_material_product(
            {"id": "child", "radius_m": 6_371_000.0},
            {"planet_tags": [], "likely_materials": [
                {"material_id": material_id, "confidence": 0.9} for material_id in parent["material_ids"]
            ]},
            heightmap, parent=parent, level=1, map_seed="coarse-tile", circumference_m=40_030_000.0,
        )
        dominant = product["substrate"].argmax(axis=0)
        same_right = float((dominant[:, 1:] == dominant[:, :-1]).mean())
        same_below = float((dominant[1:, :] == dominant[:-1, :]).mean())
        self.assertGreater(min(same_right, same_below), 0.75)
        self.assertGreaterEqual(product["unit_scale_m"], 8.0 * 47_000.0)
        # The mixture is still the parent's.
        shares = dict(zip(product["substrate_ids"], product["substrate"].mean(axis=(1, 2))))
        self.assertAlmostEqual(0.4, shares["mat_granite"], delta=0.15)
        # A tile with the cells its level expects keeps the level's unit size.
        usual = derive_child_material_product(
            {"id": "child", "radius_m": 6_371_000.0},
            {"planet_tags": [], "likely_materials": [
                {"material_id": material_id, "confidence": 0.9} for material_id in parent["material_ids"]
            ]},
            self._heightmap(), parent={**parent, "bounds": {"min_u": 0.39, "max_u": 0.41, "min_v": 0.39, "max_v": 0.41}},
            level=1, map_seed="coarse-tile", circumference_m=40_030_000.0,
        )
        self.assertEqual(60_000.0, usual["unit_scale_m"])

    def test_parent_staircase_does_not_print_into_child_contacts(self):
        # A shallow straight contact rasterised on the parent grid is a
        # staircase of whole parent cells; the child must follow the line.
        size = 24
        ys, xs = np.mgrid[0:size, 0:size]
        upper = (ys < 0.18 * xs + 6.0).astype(np.float32)
        parent = {
            "material_ids": ["mat_granite", "mat_basalt"],
            "composition": np.stack([upper, 1.0 - upper]),
            "bounds": {"min_u": 0.0, "max_u": 1.0, "min_v": 0.0, "max_v": 1.0},
            "wrap_x": False,
        }
        child_u = np.linspace(0.2, 0.8, 181)[None, :] * np.ones((181, 1))
        child_v = np.linspace(0.1, 0.6, 181)[:, None] * np.ones((1, 181))

        def contact_residual(smoothing):
            _ids, composition = _parent_composition_sampler(parent, smoothing)(child_u, child_v)
            rows = (composition[0] >= 0.5).sum(axis=0).astype(float)
            fit = np.polyval(np.polyfit(np.arange(rows.size), rows, 1), np.arange(rows.size))
            return float(np.std(rows - fit)), composition

        raw_residual, raw = contact_residual(0.0)
        smooth_residual, smooth = contact_residual(1.5)
        self.assertLess(smooth_residual, raw_residual * 0.5)
        self.assertAlmostEqual(float(raw[0].mean()), float(smooth[0].mean()), delta=0.02)

    def test_race_draw_keeps_proportions_without_contact_ghosts(self):
        # A grades into B across each row with a small constant share of C
        # listed between them.  Each row is one unit with fixed draws.
        units, columns = 2000, 101
        a_share = np.linspace(0.95, 0.0, columns)[None, :] * np.ones((units, 1))
        composition = np.stack([a_share, np.full(a_share.shape, 0.05), 0.95 - a_share])
        rng = np.random.default_rng(7)
        draws = rng.random((3, units, 1)) * np.ones((1, 1, columns))
        winner = _race_select(composition, lambda index: draws[index].copy())
        self.assertAlmostEqual(0.05, float((winner == 1).mean()), delta=0.01)
        # Rows where C wins only inside the contact, not at either end.
        ghost = ((winner == 1).any(axis=1) & (winner[:, 0] != 1) & (winner[:, -1] != 1)).mean()
        # The old inverse-CDF draw along the list order gives almost every row one.
        cumulative = np.cumsum(composition, axis=0)
        inverse_cdf = np.minimum((cumulative < draws[0][None]).sum(axis=0), 2)
        inverse_ghost = ((inverse_cdf == 1).any(axis=1) & (inverse_cdf[:, 0] != 1) & (inverse_cdf[:, -1] != 1)).mean()
        self.assertLess(float(ghost), 0.08)
        self.assertGreater(float(inverse_ghost), 0.8)

    def test_regional_heightmaps_use_the_planet_circumference(self):
        regional = {"map_detail_level": 2, "circumference_m": 166_792.0, "planet_circumference_m": 40_030_000.0}
        self.assertEqual(40_030_000.0, planet_circumference_m(regional))
        # Without the planet value, a child falls back to the terrain seed or radius, never its own width.
        legacy = {"map_detail_level": 2, "circumference_m": 166_792.0}
        self.assertEqual(40_000_000.0, planet_circumference_m(legacy, {"circumference_m": 40_000_000.0}))
        self.assertAlmostEqual(2.0 * math.pi * 3_389_500.0, planet_circumference_m(legacy, {}, {"radius_m": 3_389_500.0}))
        self.assertEqual(40_075_000.0, planet_circumference_m({"map_detail_level": 0, "circumference_m": 40_075_000.0}))

    def test_climate_defined_cover_returns_to_substrate_outside_its_niche(self):
        shape = (1, 2)
        substrate = np.ones((1, *shape), dtype=np.float32)
        cover = {class_id: np.zeros(shape, dtype=np.float32) for class_id in COVER_CLASS_IDS}
        cover["duricrust"] = np.full(shape, 0.4, dtype=np.float32)
        candidates = {"duricrust": [{
            "material_id": "mat_ferricrete",
            "prevalence": 0.5,
            "temperature_k": None,
            "precipitation_mm": (450.0, 800.0, 1700.0, 2600.0),
        }]}
        ids, visible, cover_total = assemble_visible_composition(
            ["mat_granite"], substrate, cover, candidates,
            temperature_k=np.full(shape, 300.0),
            precipitation_mm=np.asarray([[100.0, 1200.0]]),
        )
        ferricrete = visible[ids.index("mat_ferricrete")]
        self.assertAlmostEqual(0.0, float(ferricrete[0, 0]), places=6)
        self.assertAlmostEqual(0.4, float(ferricrete[0, 1]), places=6)
        np.testing.assert_allclose(visible.sum(axis=0), 1.0, atol=1e-6)
        self.assertAlmostEqual(0.0, float(cover_total[0, 0]), places=6)

    def test_label_components_joins_across_the_wrapped_seam(self):
        classes = np.asarray([
            [1, 0, 0, 1],
            [1, 0, 0, 1],
            [2, 2, 2, 2],
        ])
        labels = label_components(classes, wrap_x=True)
        self.assertEqual(labels[0, 0], labels[0, 3])
        self.assertEqual(labels[0, 1], labels[1, 2])
        self.assertNotEqual(labels[0, 0], labels[0, 1])
        self.assertEqual(3, len(np.unique(labels)))
        unwrapped = label_components(classes, wrap_x=False)
        self.assertNotEqual(unwrapped[0, 0], unwrapped[0, 3])

    def test_occurrence_bodies_rasterize_inside_their_footprint(self):
        context = {
            "shape": (41, 41),
            "bounds": {"min_u": 0.5, "max_u": 0.5025, "min_v": 0.5, "max_v": 0.505},
            "u": np.linspace(0.5, 0.5025, 41),
            "v": np.linspace(0.5, 0.505, 41),
            "land": np.ones((41, 41), dtype=bool),
        }
        occurrence = {
            "material_id": "mat_bauxite",
            "center_global_uv": {"u": 0.50125, "v": 0.5025},
            "deposit_body": {"geometry": {
                "bounding_radius_m": 20_000.0,
                "geometry_fill_fraction": 0.5,
                "footprint_vertices": [
                    [math.cos(index * math.tau / 16.0), math.sin(index * math.tau / 16.0)]
                    for index in range(16)
                ],
            }},
        }
        layers, roles, _ore = rasterize_occurrences(context, [occurrence], 40_030_000.0)
        field = layers["mat_bauxite"]
        self.assertEqual("sparse_deposit", roles["mat_bauxite"])
        self.assertAlmostEqual(0.4, float(field[20, 20]), places=6)
        self.assertEqual(0.0, float(field[0, 0]))
        # An ore system is copper and pyrite in the ground, not a layer.
        ore_body = {**occurrence, "material_id": "mat_chalcopyrite",
                    "ore_system": {"element": "Cu", "grade_wt_percent": 0.8, "pyrite_wt_percent": 4.6}}
        layers, _roles, ore = rasterize_occurrences(context, [ore_body], 40_030_000.0)
        self.assertEqual({}, layers)
        # Its weathered top spans the whole outline, as a mapped unit's does.
        self.assertAlmostEqual(0.9, float(ore["Cu"]["share"][20, 20]), places=6)
        self.assertAlmostEqual(0.72, float(ore["Cu"]["content_percent"][20, 20]), places=6)
        self.assertAlmostEqual(4.14, float(ore["Cu"]["pyrite_wt"][20, 20]), places=6)
        # A body smaller than a cell takes its area's share of the cell holding its centre.
        cell_m = 0.0025 / 40 * 40_030_000.0 * math.cos(0.0025 * math.pi)
        small = {**occurrence, "deposit_body": {"geometry": {**occurrence["deposit_body"]["geometry"], "bounding_radius_m": 0.3 * cell_m}}}
        layers, _roles, _ore = rasterize_occurrences(context, [small], 40_030_000.0)
        field = layers["mat_bauxite"]
        self.assertEqual(1, int(np.count_nonzero(field)))
        # 16-gon of area 3.06 r^2, r = 0.3 cells, exposed 0.4.
        self.assertAlmostEqual(0.4 * 8.0 * math.sin(math.tau / 16.0) * 0.09, float(field.max()), delta=0.005)


class ArealTrueColorTests(unittest.TestCase):
    def test_areal_components_mix_linearly(self):
        pygame.init()
        size = (4, 2)
        components = []
        for material_id, reflectance in (("mat_granite", 0.5), ("mat_basalt", 0.1)):
            surface = pygame.Surface(size, pygame.SRCALPHA)
            surface.fill((255, 255, 255, 128))
            components.append({
                "material_id": material_id,
                "surface": surface,
                "fraction_semantics": AREAL_FRACTION_SEMANTICS,
                "optical_surface_profile": {
                    "visible_reflectance": {"red_650nm": reflectance, "green_550nm": reflectance, "blue_450nm": reflectance},
                    "weathered_visible_reflectance": {"red_650nm": reflectance, "green_550nm": reflectance, "blue_450nm": reflectance},
                    "weathering_color_response": 0.0,
                },
            })
        mixed, _properties = _mix_material_endmembers(
            components, (0.2, 0.2, 0.2), {"one": np.ones((2, 4), dtype=np.float32)}, size,
        )
        np.testing.assert_allclose(mixed, 0.3, atol=0.01)


class TrueColorLineageTests(unittest.TestCase):
    def test_lab_conversion_anchors(self):
        lab = linear_rgb_to_lab(np.asarray([[1.0, 1.0, 1.0], [0.0, 0.0, 0.0], [0.18, 0.18, 0.18]]))
        np.testing.assert_allclose(lab[0], [100.0, 0.0, 0.0], atol=0.05)
        np.testing.assert_allclose(lab[1], [0.0, 0.0, 0.0], atol=0.05)
        self.assertAlmostEqual(49.5, float(lab[2, 0]), delta=0.2)

    def test_child_true_color_box_filters_to_the_parent_within_budget(self):
        rng = np.random.default_rng(12)
        size = 97
        parent_bounds = {"min_u": 0.40, "max_u": 0.41, "min_v": 0.40, "max_v": 0.41}
        yy, xx = np.mgrid[0:size, 0:size]
        parent_rows = 600.0 + 250.0 * np.sin(xx / 11.0) * np.cos(yy / 13.0) + rng.normal(0.0, 15.0, (size, size))
        natural = {"planet_tags": [], "likely_materials": [
            {"material_id": material_id, "confidence": 0.9}
            for material_id in ("mat_granite", "mat_basalt", "mat_limestone")
        ]}
        grain = np.clip(0.5 + 0.4 * np.sin(np.linspace(0.0, 3.0, 9))[None, :] * np.ones((9, 1)), 0.1, 0.9)
        root = {
            "material_ids": ["mat_granite", "mat_basalt", "mat_limestone"],
            "composition": np.stack([grain * 0.7, (1.0 - grain) * 0.7, np.full((9, 9), 0.3)]).astype(np.float32),
            "bounds": {"min_u": 0.39, "max_u": 0.42, "min_v": 0.39, "max_v": 0.42},
            "wrap_x": False,
        }

        def heightmap(rows, bounds, level, width_m):
            return {
                "map_detail_level": level, "sea_level_m": 0.0, "wrap_x": False, "map_seed": "lineage-test",
                "source_uv_bounds": bounds, "region_width_m": width_m, "region_height_m": width_m,
                "sample_grid": {"rows": np.round(rows, 1).tolist()},
            }

        def product(parent, rows, bounds, level, width_m):
            return derive_child_material_product(
                {"id": f"lineage_{level}", "radius_m": 6_371_000.0}, natural,
                heightmap(rows, bounds, level, width_m),
                parent=parent, level=level, map_seed="lineage-test", circumference_m=40_030_000.0,
            )

        parent = product(root, parent_rows, parent_bounds, 1, 250_000.0)
        child_bounds = {"min_u": 0.403, "max_u": 0.406, "min_v": 0.403, "max_v": 0.406}
        # The child terrain is the parent terrain over the child footprint.
        u = np.linspace(child_bounds["min_u"], child_bounds["max_u"], size)
        v = np.linspace(child_bounds["min_v"], child_bounds["max_v"], size)
        fx = (u - 0.40) / 0.01 * (size - 1)
        fy = (v - 0.40) / 0.01 * (size - 1)
        child_rows = np.asarray([[parent_rows[int(round(y)), int(round(x))] for x in fx] for y in fy])
        child_rows = child_rows + rng.normal(0.0, 4.0, child_rows.shape)
        child = product(
            {"material_ids": parent["substrate_ids"], "composition": parent["substrate"], "bounds": parent_bounds, "wrap_x": False},
            child_rows, child_bounds, 2, 75_000.0,
        )
        result = lineage_delta_e(
            {"material_ids": parent["visible_ids"], "composition": parent["visible"], "bounds": parent_bounds},
            {"material_ids": child["visible_ids"], "composition": child["visible"], "bounds": child_bounds},
        )
        self.assertGreater(result["parent_cells"], 400)
        self.assertLess(result["mean_delta_e"], TRUE_COLOR_LINEAGE_BUDGET["mean_delta_e"])
        self.assertLess(result["p95_delta_e"], TRUE_COLOR_LINEAGE_BUDGET["p95_delta_e"])


class MaterialBundleTests(unittest.TestCase):
    def test_planetary_bundle_packs_substrate_for_children_and_provinces(self):
        rows = np.full((17, 33), -3000.0)
        rows[5:13, 8:26] = 800.0
        heightmap = {
            "map_detail_level": 0,
            "sea_level_m": 0.0,
            "wrap_x": True,
            "map_seed": "bundle-test",
            "sample_grid": {"rows": rows.tolist()},
        }
        natural_model = {
            "planet_tags": ["plate_tectonic_surface", "silicate_crust"],
            "likely_materials": [
                {"material_id": "mat_granite", "confidence": 0.9},
                {"material_id": "mat_gneiss", "confidence": 0.9},
                {"material_id": "mat_sandstone", "confidence": 0.9},
                {"material_id": "mat_basalt", "confidence": 0.9},
            ],
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            model = generate_material_heatmap_model(
                {"id": "bundle_planet", "radius_m": 6_371_000.0},
                natural_model,
                {"map_seed": "bundle-test"},
                heightmap,
                output_root=Path(temp_dir) / "assets" / "maps" / "material_heatmaps",
                storage_root=Path(temp_dir),
            )
            self.assertEqual("generated", model["status"])
            self.assertEqual(AREAL_FRACTION_SEMANTICS, model["fraction_semantics"])
            bundle = Path(temp_dir) / model["bundle_path"]
            alphas = sum(
                np.asarray(pygame.surfarray.array_alpha(load_raster_bundle_surface(bundle, layer["bundle_layer_id"])), dtype=np.float64)
                for layer in model["layers"]
            ) / 255.0
            self.assertLess(float(np.abs(alphas - 1.0).max()), 0.05)
            parent = load_parent_composition(model, Path(temp_dir))
            self.assertEqual(model["substrate_layers"]["material_ids"], parent["material_ids"])
            np.testing.assert_allclose(parent["composition"].sum(axis=0), 1.0, atol=1e-5)
            provinces = model["province_model"]["provinces"]
            self.assertGreaterEqual(len(provinces), 2)
            self.assertTrue(model["_pending_material_cards"])
            self.assertEqual(
                (17 + 1) // 2,
                len(model["province_model"]["province_index_rows"]),
            )


if __name__ == "__main__":
    unittest.main()
