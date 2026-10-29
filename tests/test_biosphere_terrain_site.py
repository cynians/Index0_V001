import math
import os
import unittest
from types import SimpleNamespace
from unittest import mock

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame

from app.navigation_controller import NavigationController
from simulations.biosphere import terrain_site
from simulations.biosphere.biosphere_renderer import BiosphereBuilderRenderer
from simulations.biosphere.biosphere_simulation import BiosphereSimulation
from simulations.biosphere.ecology import profile_from_entity, thermal_response
from simulations.biosphere.representatives import RepresentativePopulationManager as RepresentativePopulationManagerProbe
from simulations.map.map_simulation import MapSimulation
from simulations.map.worldgen_substrate import LayeredSubstrate, WorldgenSubstrate
from tests.test_blueprint_designer import BlueprintWorld
from ui.ui_manager import UIManager
from world.simulation_context import SimulationContext


REGION_ID = "refined_lod4_bio_fixture"
REGION_WIDTH_M = 512.0
REGION_HEIGHT_M = 256.0
COLUMNS, ROWS = 65, 33  # 8 m between samples: a Site-level region


def _grid(value):
    return [[value(column, row) for column in range(COLUMNS)] for row in range(ROWS)]


def _region(region_id=REGION_ID, **climate):
    """A Site map: ground rising 1 m per 8 m eastward, open water along its west edge."""
    water = lambda column, _row: column < 4
    coldest = climate.get("coldest_k", 278.15)
    warmest = climate.get("warmest_k", 295.15)
    return {
        "id": region_id, "_dataset": "locations", "type": "location",
        "name": "Fixture Site", "location_class": "generated_region",
        "location_role": "map_refinement_region", "map_detail_level": 4,
        "map_detail_profile": {"id": "site", "label": "Site"},
        "refinement_root_planet_id": "planet_fixture",
        # Parent-map coordinates: nothing like metres.
        "bounds": {"type": "bbox", "min_x": 40.0, "max_x": 40.2, "min_y": -8.1, "max_y": -8.0},
        "heightmap_model": {
            "region_width_m": REGION_WIDTH_M, "region_height_m": REGION_HEIGHT_M,
            "min_elevation_m": 300.0, "max_elevation_m": 364.0, "sea_level_m": 0.0,
            "source_heightfield_fingerprint": "bio-fixture-a",
            "sample_grid": {"width": COLUMNS, "height": ROWS, "rows": _grid(lambda column, _row: 300.0 + column)},
        },
        "water_cycle_model": {
            "koppen_classes": [{"id": "Cfb", "label": "Temperate Oceanic"}],
            "climate_grid": {
                "temperature_rows_k": _grid(lambda *_: (coldest + warmest) * 0.5),
                "seasonal_min_temperature_rows_k": _grid(lambda *_: coldest),
                "seasonal_max_temperature_rows_k": _grid(lambda *_: warmest),
                "annual_precipitation_rows_mm": _grid(lambda *_: 820.0),
                "koppen_rows": _grid(lambda *_: "Cfb"),
            },
            "runoff_grid": {"wetness_index_rows": _grid(lambda column, _row: 0.2 + 0.5 * column / (COLUMNS - 1))},
            "surface_water_grid": {
                "water_presence_rows": _grid(water),
                "water_depth_m_rows": _grid(lambda column, row: 1.0 if water(column, row) else 0.0),
            },
        },
        "regolith_soil_model": {
            "nutrient_status": "deferred_to_biomatter_system",
            "grid": {
                "soil_depth_m_rows": _grid(lambda *_: 0.6), "ph_rows": _grid(lambda *_: 6.8),
                "parent_nitrogen_index_rows": _grid(lambda column, _row: column / (COLUMNS - 1)),
                "parent_phosphorus_index_rows": _grid(lambda *_: 0.3),
            },
        },
    }


SPECIES = [
    {"id": "spec_biomasser_13b", "_dataset": "species", "type": "species", "pretty_name": "Biomasser 13B",
     "plant_growth_form": "lichen", "species_simulation_enabled": True, "biosphere_bootstrap_species": True,
     "biosphere_growth_profile": {"seasonal_growth_rate": 0.58, "seasonal_dispersal": 0.21,
                                  "carrying_biomass_kg_m2": 3.2, "moisture_optimum": 0.38,
                                  "moisture_tolerance": 0.58, "light_minimum": 0.08}},
    {"id": "spec_lolium_perenne", "_dataset": "species", "type": "species", "pretty_name": "Perennial Ryegrass",
     "plant_growth_form": "graminoid", "moisture_preference": "moist"},
]


def _world(*extra, **climate):
    return BlueprintWorld([_region(**climate), *[dict(entity) for entity in SPECIES], *extra])


def _region_point(x_m, y_m):
    """A metre position on the fixture region, in the region's own map coordinates."""
    return 40.0 + x_m / REGION_WIDTH_M * 0.2, -8.1 + y_m / REGION_HEIGHT_M * 0.1


def _fake_refinement(world_model, parent, bounds, *, sample_dimensions=None, **_kwargs):
    """Stands in for worldgen: a chunk on a 1 m grid, 0.25 m above its parent."""
    parent_bounds = parent["bounds"]
    width_m = (bounds["max_x"] - bounds["min_x"]) / (parent_bounds["max_x"] - parent_bounds["min_x"]) * REGION_WIDTH_M
    height_m = (bounds["max_y"] - bounds["min_y"]) / (parent_bounds["max_y"] - parent_bounds["min_y"]) * REGION_HEIGHT_M
    x0_m = (bounds["min_x"] - parent_bounds["min_x"]) / (parent_bounds["max_x"] - parent_bounds["min_x"]) * REGION_WIDTH_M
    columns, rows = sample_dimensions
    index = sum(1 for entity in world_model.entities if str(entity).startswith("refined_lod5_")) + 1
    chunk = {
        "id": f"refined_lod5_chunk_{index:02d}", "_dataset": "locations", "type": "location",
        "location_class": "generated_region", "map_detail_level": 5,
        "map_detail_profile": {"id": "parcel", "label": "Parcel"},
        "refinement_parent_map_id": parent["id"], "parent_location": parent["id"],
        "bounds": {"type": "bbox", **{key: float(bounds[key]) for key in ("min_x", "max_x", "min_y", "max_y")}},
        "heightmap_model": {
            "region_width_m": width_m, "region_height_m": height_m,
            "min_elevation_m": 300.0, "max_elevation_m": 364.0,
            "sample_grid": {"width": columns, "height": rows, "rows": [
                [300.25 + (x0_m + width_m * column / (columns - 1)) / 8.0 for column in range(columns)]
                for _row in range(rows)
            ]},
        },
    }
    world_model.loader.persist_entity(chunk)
    return chunk


class FoundingTests(unittest.TestCase):
    def setUp(self):
        self.world = _world()
        self.region = self.world.get_entity(REGION_ID)

    def test_only_finely_resolved_generated_terrain_can_carry_a_biosphere(self):
        self.assertEqual(terrain_site.founding_report(self.world, self.region), (True, ""))
        self.assertFalse(terrain_site.founding_report(self.world, None)[0])
        self.assertEqual(
            terrain_site.founding_report(self.world, {"id": "loc", "location_class": "region"}),
            (False, "needs generated terrain"),
        )
        coarse = _region("refined_lod3_coarse")
        coarse["heightmap_model"].update(region_width_m=20_000.0, region_height_m=10_000.0)
        self.assertEqual(terrain_site.founding_report(self.world, coarse), (False, "refine to Site first"))

    def test_a_site_is_the_regions_metre_frame_with_a_founding_point(self):
        site = terrain_site.found_biosphere_site(self.world, REGION_ID, _region_point(384.0, 64.0), year=2400)

        self.assertIs(self.world.get_entity(site["id"]), site)
        self.assertEqual(site["location_class"], "biosphere_patch")
        self.assertEqual(site["map_coordinate_space"], "site_meters")
        self.assertEqual(site["terrain_source_map_id"], REGION_ID)
        self.assertNotIn("parent_location", site)
        self.assertNotIn("heightmap_model", site)  # read through the link, never copied
        self.assertEqual(site["bounds"], {"type": "bbox", "min_x": 0.0, "max_x": 512.0, "min_y": 0.0, "max_y": 256.0})
        self.assertAlmostEqual(site["biosphere_founding_point_local_m"][0], 384.0, places=3)
        self.assertAlmostEqual(site["biosphere_founding_point_local_m"][1], 64.0, places=3)
        # Parent maps draw the founding square, in the region's coordinates.
        footprint = site["geographic_source_bounds"]
        self.assertAlmostEqual((footprint["min_x"] + footprint["max_x"]) * 0.5, _region_point(384.0, 64.0)[0])
        self.assertAlmostEqual(
            (footprint["max_x"] - footprint["min_x"]) / 0.2 * REGION_WIDTH_M, terrain_site.INITIAL_EXTENT_M)
        self.assertEqual(
            terrain_site.founding_domain(site), {"min_x": 379.0, "max_x": 389.0, "min_y": 59.0, "max_y": 69.0})
        self.assertEqual([entity["id"] for entity in terrain_site.sites_on_region(self.world, REGION_ID)], [site["id"]])

    def test_a_site_can_be_founded_from_a_city_map_of_the_same_region(self):
        from simulations.city import city_site

        city = city_site.found_city(self.world, REGION_ID)
        # A city map is already in metres.
        site = terrain_site.found_biosphere_site(self.world, city["id"], (100.0, 200.0))
        self.assertEqual(site["terrain_source_map_id"], REGION_ID)
        self.assertEqual(site["biosphere_founding_point_local_m"], [100.0, 200.0])


class SubstrateTests(unittest.TestCase):
    def setUp(self):
        self.world = _world()
        self.site = terrain_site.found_biosphere_site(self.world, REGION_ID, _region_point(384.0, 64.0))

    def test_the_site_reads_ground_water_and_climate_from_the_region(self):
        substrate = terrain_site.site_substrate(self.world, self.site)
        environment = substrate.environment_at(256.0, 128.0)

        self.assertAlmostEqual(environment["elevation_m"], 332.0)
        self.assertAlmostEqual(environment["annual_precipitation_mm"], 820.0)
        self.assertAlmostEqual(environment["coldest_month_temperature_k"], 278.15)
        self.assertAlmostEqual(environment["warmest_month_temperature_k"], 295.15)
        self.assertAlmostEqual(environment["soil_moisture"], 0.45)
        self.assertAlmostEqual(environment["parent_nitrogen_index"], 0.5)
        self.assertTrue(substrate.open_water_at(8.0, 100.0))
        self.assertFalse(substrate.open_water_at(256.0, 100.0))
        self.assertEqual(substrate.koppen_at(256.0, 128.0), ("Cfb", "Temperate Oceanic"))

    def test_array_sampling_agrees_with_point_sampling_across_layers(self):
        import numpy as np

        _fake_refinement(self.world, dict(self.world.get_entity(REGION_ID)), self.chunk_bounds(), sample_dimensions=(129, 129))
        substrate = terrain_site.site_substrate(self.world, self.site)
        self.assertIsInstance(substrate, LayeredSubstrate)
        self.assertIsInstance(substrate.base, WorldgenSubstrate)
        xs = np.array([10.0, 250.0, 300.0, 400.0, 505.0])
        ys = np.array([20.0, 60.0, 200.0, 64.0, 250.0])
        for visible in (False, True):
            array = substrate.elevation_array(xs, ys, visible)
            for index in range(len(xs)):
                self.assertAlmostEqual(array[index], substrate.elevation(xs[index], ys[index], visible), places=9)
        # The chunk (x 384-512, y 0-128) is 0.25 m above the region it refines.
        self.assertAlmostEqual(substrate.elevation(400.0, 64.0), 350.25)
        self.assertAlmostEqual(substrate.elevation(300.0, 200.0), 337.5)
        self.assertEqual(substrate.detail_level_at(400.0, 64.0), 5)
        self.assertEqual(substrate.detail_level_at(300.0, 200.0), 4)
        water = substrate.open_water_array(np.array([8.0, 256.0]), np.array([100.0, 100.0]))
        self.assertEqual(water.tolist(), [True, False])

    def test_a_rill_a_few_centimetres_deep_is_ground_not_open_water(self):
        import numpy as np

        surface = self.world.get_entity(REGION_ID)["water_cycle_model"]["surface_water_grid"]
        # Worldgen flags a characteristic channel at column 40; it runs 4 cm deep.
        for row in range(ROWS):
            surface["water_presence_rows"][row][40] = True
            surface["water_depth_m_rows"][row][40] = 0.044
        substrate = terrain_site.site_substrate(self.world, self.site)
        self.assertFalse(substrate.open_water_at(320.0, 100.0))
        self.assertTrue(substrate.terrestrial_habitat_at(320.0, 100.0))
        self.assertTrue(substrate.open_water_at(8.0, 100.0))  # the metre-deep water still is
        self.assertEqual(substrate.open_water_array(np.array([320.0, 8.0]), np.array([100.0, 100.0])).tolist(), [False, True])
        # Without resolved depth, presence is all there is to go on.
        del surface["water_depth_m_rows"]
        self.assertTrue(terrain_site.site_substrate(self.world, self.site).open_water_at(320.0, 100.0))

    def chunk_bounds(self):
        low, high = _region_point(384.0, 0.0), _region_point(512.0, 128.0)
        return {"min_x": low[0], "max_x": high[0], "min_y": low[1], "max_y": high[1]}

    def _drifted_chunk(self):
        """A chunk as worldgen makes them: its own climate, a little off, and rills the region never saw."""
        chunk = _fake_refinement(self.world, dict(self.world.get_entity(REGION_ID)), self.chunk_bounds(), sample_dimensions=(129, 129))
        rows = lambda value: [[value(column, row) for column in range(129)] for row in range(129)]
        chunk["water_cycle_model"] = {
            "koppen_classes": [{"id": "BSh", "label": "Hot Steppe"}],
            "climate_grid": {
                "temperature_rows_k": rows(lambda *_: 288.45),
                "seasonal_min_temperature_rows_k": rows(lambda *_: 279.95),
                "seasonal_max_temperature_rows_k": rows(lambda *_: 296.95),
                "annual_precipitation_rows_mm": rows(lambda *_: 700.0),
                "koppen_rows": rows(lambda *_: "BSh"),
            },
            # A rill every eighth metre, damp; dry ground between.
            "runoff_grid": {"wetness_index_rows": rows(lambda column, _row: 1.0 if column % 8 == 0 else 0.6)},
        }
        return chunk

    def test_a_chunk_refines_the_ground_and_leaves_the_climate_to_the_region(self):
        self._drifted_chunk()
        substrate = terrain_site.site_substrate(self.world, self.site)
        inside, outside = substrate.environment_at(448.0, 64.0), substrate.environment_at(300.0, 64.0)
        self.assertEqual(substrate.detail_level_at(448.0, 64.0), 5)
        for key in ("temperature_k", "coldest_month_temperature_k", "warmest_month_temperature_k", "annual_precipitation_mm"):
            self.assertAlmostEqual(inside[key], outside[key], msg=key)
            self.assertAlmostEqual(substrate.sample(key, 448.0, 64.0), outside[key], msg=key)
        self.assertEqual(substrate.koppen_at(448.0, 64.0), ("Cfb", "Temperate Oceanic"))
        # The plain layering other views use still answers with the chunk's own climate.
        plain = LayeredSubstrate(substrate.base, [(bounds, layer) for bounds, layer in substrate.layers()[1:]])
        self.assertAlmostEqual(plain.environment_at(448.0, 64.0)["annual_precipitation_mm"], 700.0)
        self.assertEqual(plain.koppen_at(448.0, 64.0), ("BSh", "Hot Steppe"))

    def test_a_chunk_shows_where_the_regions_water_sits_without_adding_any(self):
        import numpy as np

        self._drifted_chunk()
        substrate = terrain_site.site_substrate(self.world, self.site)
        xs, ys = np.meshgrid(np.linspace(384.5, 511.5, 128), np.linspace(0.5, 127.5, 128))
        refined = substrate.sample_array("soil_moisture", xs, ys)
        region = substrate.base.sample_array("soil_moisture", xs, ys)
        # The chunk's own wetness averages 0.65; the region holds 0.64 over that ground.
        self.assertGreater(float(substrate.layers()[1][1].sample_array("soil_moisture", xs, ys).mean()), 0.645)
        self.assertAlmostEqual(float(refined.mean()), float(region.mean()), delta=0.005)
        # The pattern survives, flattened: there is less water to put into the rills.
        rill, between = substrate.sample("soil_moisture", 384.0 + 64.0, 64.0), substrate.sample("soil_moisture", 384.0 + 68.0, 64.0)
        self.assertGreater(rill, between + 0.2)
        self.assertLess(rill, 0.95)
        # The driest ground stays exactly as dry as the chunk found it.
        self.assertAlmostEqual(between, 0.6, places=6)
        self.assertAlmostEqual(substrate.environment_at(452.0, 64.0)["soil_moisture"], between)
        self.assertAlmostEqual(float(substrate.sample_array("soil_moisture", np.array([452.0]), np.array([64.0]))[0]), between)
        plain = LayeredSubstrate(substrate.base, [(bounds, layer) for bounds, layer in substrate.layers()[1:]])
        self.assertAlmostEqual(plain.sample("soil_moisture", 448.0, 64.0), 1.0)

    def test_a_chunk_wetter_throughout_than_its_region_reads_as_the_region(self):
        chunk = self._drifted_chunk()
        # Even its driest ground is above what the region holds: there is no surplus to place.
        chunk["water_cycle_model"]["runoff_grid"]["wetness_index_rows"] = [
            [0.9 if column % 8 == 0 else 0.7 for column in range(129)] for _row in range(129)]
        substrate = terrain_site.site_substrate(self.world, self.site)
        rill, between = substrate.sample("soil_moisture", 448.0, 64.0), substrate.sample("soil_moisture", 452.0, 64.0)
        self.assertAlmostEqual(rill, between)
        self.assertAlmostEqual(between, 0.6375, delta=0.005)

    def test_a_chunk_drier_than_its_region_puts_the_missing_water_where_its_water_sits(self):
        import numpy as np

        chunk = self._drifted_chunk()
        # Mostly dry ground at 0.3 with damp rills at 0.5; the region holds 0.64 over it.
        chunk["water_cycle_model"]["runoff_grid"]["wetness_index_rows"] = [
            [0.5 if column % 8 == 0 else 0.3 for column in range(129)] for _row in range(129)]
        substrate = terrain_site.site_substrate(self.world, self.site)
        xs, ys = np.meshgrid(np.linspace(384.5, 511.5, 128), np.linspace(0.5, 127.5, 128))
        self.assertAlmostEqual(float(substrate.sample_array("soil_moisture", xs, ys).mean()),
                               float(substrate.base.sample_array("soil_moisture", xs, ys).mean()), delta=0.005)
        rill, between = substrate.sample("soil_moisture", 448.0, 64.0), substrate.sample("soil_moisture", 452.0, 64.0)
        # The wettest ground reaches the top of the range and no further; the rest is lifted with it.
        self.assertAlmostEqual(rill, 1.0)
        self.assertGreater(between, 0.3)
        self.assertLess(between, 0.64)

    def test_a_field_a_chunk_does_not_carry_is_read_from_the_region(self):
        import numpy as np

        # The plain fixture chunk is ground only: no climate, water or soil of its own.
        _fake_refinement(self.world, dict(self.world.get_entity(REGION_ID)), self.chunk_bounds(), sample_dimensions=(129, 129))
        substrate = terrain_site.site_substrate(self.world, self.site)
        region = substrate.base.environment_at(448.0, 64.0)
        inside = substrate.environment_at(448.0, 64.0)
        self.assertAlmostEqual(inside["elevation_m"], region["elevation_m"] + 0.25)
        for key in ("soil_moisture", "soil_depth_m", "soil_ph", "parent_nitrogen_index", "annual_precipitation_mm"):
            self.assertAlmostEqual(inside[key], region[key], msg=key)
            self.assertAlmostEqual(float(substrate.sample_array(key, np.array([448.0]), np.array([64.0]))[0]), region[key], msg=key)
        self.assertNotIn("soil_moisture", inside["runtime_default_fields"])

    def test_a_click_on_raised_ground_maps_back_to_the_ground_point(self):
        substrate = terrain_site.site_substrate(self.world, self.site)
        state = {"scale": 6.0, "center_x": 384.0, "center_y": 64.0, "origin_x": 800.0, "origin_y": 450.0,
                 "substrate": substrate, "datum_m": substrate.elevation(384.0, 64.0, True), "vertical_scale": 5.0}
        for x, y in ((384.0, 64.0), (420.0, 40.0), (350.0, 100.0)):
            screen = BiosphereBuilderRenderer._iso(state, x, y)
            back = substrate.ground_screen_to_world(state, screen)
            self.assertAlmostEqual(back[0], x, places=3)
            self.assertAlmostEqual(back[1], y, places=3)
        # The view centre's own ground sits exactly on the projection origin.
        self.assertEqual(BiosphereBuilderRenderer._iso(state, 384.0, 64.0), (800.0, 450.0))


class TerrainDetailTests(unittest.TestCase):
    def setUp(self):
        self.world = _world()
        self.site = terrain_site.found_biosphere_site(self.world, REGION_ID, _region_point(384.0, 64.0))
        self.detail = terrain_site.TerrainDetail(self.world, self.site)

    def test_chunks_tile_the_region_and_are_asked_for_only_under_the_domain(self):
        self.assertEqual((self.detail.columns, self.detail.rows), (4, 2))
        self.assertEqual(self.detail.chunk_bounds_m((3, 0)), {"min_x": 384.0, "max_x": 512.0, "min_y": 0.0, "max_y": 128.0})
        domain = terrain_site.founding_domain(self.site)
        # The founding square straddles the line between two chunks.
        self.assertEqual(sorted(self.detail.missing(domain)), [(2, 0), (3, 0)])
        self.assertEqual(self.detail.missing({"min_x": 390.0, "max_x": 400.0, "min_y": 59.0, "max_y": 69.0}), [(3, 0)])
        self.assertTrue(self.detail.can_generate())

    def test_a_refined_chunk_is_a_child_of_the_region_and_is_not_asked_for_again(self):
        domain = {"min_x": 390.0, "max_x": 400.0, "min_y": 59.0, "max_y": 69.0}
        with mock.patch.object(terrain_site, "generate_refined_region", side_effect=_fake_refinement) as generate:
            chunk = self.detail.generate((3, 0))
        parent, bounds = generate.call_args.args[1], generate.call_args.args[2]
        self.assertEqual(parent["id"], REGION_ID)
        self.assertEqual(generate.call_args.kwargs["sample_dimensions"], (129, 129))
        # The chunk is requested in the region's own coordinates, not metres.
        self.assertAlmostEqual(bounds["min_x"], _region_point(384.0, 0.0)[0])
        self.assertAlmostEqual(bounds["max_y"], _region_point(512.0, 128.0)[1])
        self.assertEqual(chunk["refinement_parent_map_id"], REGION_ID)
        self.assertEqual(self.detail.missing(domain), [])
        self.assertEqual(self.detail.missing({"min_x": 250.0, "max_x": 400.0, "min_y": 59.0, "max_y": 69.0}), [(2, 0), (1, 0)])

    def test_a_region_that_is_already_fine_needs_no_chunks(self):
        region = self.world.get_entity(REGION_ID)
        region["heightmap_model"].update(region_width_m=64.0, region_height_m=32.0)
        site = terrain_site.found_biosphere_site(self.world, REGION_ID, (40.1, -8.05))
        detail = terrain_site.TerrainDetail(self.world, site)
        self.assertFalse(detail.needed())
        self.assertEqual(detail.missing(site["bounds"]), [])


class BiosphereOnTerrainTests(unittest.TestCase):
    def setUp(self):
        pygame.init()
        self.world = _world()
        self.site = terrain_site.found_biosphere_site(self.world, REGION_ID, _region_point(400.0, 64.0), year=2400)
        self.sim = BiosphereSimulation(self.world, {"patch_location_id": self.site["id"], "year": 2400})

    def test_the_simulation_starts_as_a_small_domain_inside_the_regions_frame(self):
        sim = self.sim
        self.assertEqual(sim.bounds, {"min_x": 395.0, "max_x": 405.0, "min_y": 59.0, "max_y": 69.0})
        self.assertEqual(sim.ecology.bounds, sim.bounds)
        self.assertEqual(sim.terrain_frame, {"min_x": 0.0, "max_x": 512.0, "min_y": 0.0, "max_y": 256.0})
        # The root keeps the region's frame; only the domain is small.
        self.assertEqual(sim.get_root_entity()["bounds"]["max_x"], 512.0)
        self.assertIsInstance(sim.substrate, LayeredSubstrate)
        self.assertIs(sim.ecology.substrate, sim.substrate)
        self.assertTrue(sim.replaces_map_view)
        self.assertEqual(sim.pending_terrain_chunks(), [(3, 0)])
        # Re-resolving the root frame must not snap the domain to the region.
        sim.bounds = sim._resolve_root_bounds()
        self.assertEqual(sim.get_map_size(), 10.0)

    def test_ecology_reads_worldgen_climate_and_parent_material(self):
        environment = self.sim.ecology.environment_at(400.0, 64.0)
        self.assertAlmostEqual(environment["soil_moisture"], 0.2 + 0.5 * 400.0 / 512.0)
        self.assertAlmostEqual(environment["temperature_k"], (278.15 + 295.15) * 0.5)
        self.assertAlmostEqual(environment["parent_nitrogen_index"], 400.0 / 512.0)
        # Soil nutrients are seeded from the region's parent material, not defaults.
        self.assertAlmostEqual(self.sim.soil.parent_nitrogen_index_rows[16][16], 400.0 / 512.0, places=2)
        status = self.sim.get_terrain_status()
        self.assertTrue(status["linked"])
        self.assertEqual(status["label"], "Ground: Site · 8.0 m samples · 1 chunk queued")
        self.assertEqual(
            status["climate_label"],
            "Temperate Oceanic (Cfb) · 5 to 22 °C monthly · 820 mm/yr · wetness 0.59",
        )

    def test_chunks_resolve_on_request_and_only_then_when_the_app_drives_it(self):
        sim = self.sim
        with mock.patch.object(terrain_site, "generate_refined_region", side_effect=_fake_refinement) as generate:
            sim.update(1.0)
            sim.update(1.0)
            self.assertEqual(generate.call_count, 0)  # no app, no background worldgen

            sim.auto_resolve_terrain = True
            sim.update(1.0)
            self.assertEqual(generate.call_count, 0)  # one frame shows the notice first
            self.assertTrue(sim.get_terrain_status()["resolving"])
            sim.update(1.0)
            self.assertEqual(generate.call_count, 1)
        self.assertEqual(sim.pending_terrain_chunks(), [])
        self.assertEqual(sim.substrate.detail_level_at(400.0, 64.0), 5)
        self.assertAlmostEqual(sim.ecology.abiotic_environment_at(400.0, 64.0)["elevation_m"], 350.25)
        self.assertEqual(sim.get_terrain_status()["label"], "Ground: Parcel · 1.0 m samples")

    def test_a_failed_refinement_is_reported_and_not_retried_forever(self):
        sim = self.sim
        sim.auto_resolve_terrain = True
        with mock.patch.object(terrain_site, "generate_refined_region", side_effect=ValueError("no parent grid")) as generate:
            for _ in range(8):
                sim.update(1.0)
        self.assertEqual(generate.call_count, 1)
        self.assertEqual(sim.pending_terrain_chunks(), [])
        self.assertIn("no parent grid", sim.get_terrain_status()["error"])

    def test_planting_beyond_the_domain_grows_it_and_detail_follows_a_close_view(self):
        sim = self.sim
        with mock.patch.object(terrain_site, "generate_refined_region", side_effect=_fake_refinement):
            sim.resolve_terrain()
        self.assertEqual(sim.pending_terrain_chunks(), [])

        introduction = sim.place_selected_species(370.0, 70.0)
        self.assertIsNotNone(introduction)
        self.assertLess(sim.bounds["min_x"], 370.0)
        self.assertEqual(sim.bounds["max_x"], 405.0)
        self.assertEqual(sim.soil.bounds, sim.bounds)
        self.assertGreater(sim.ecology.abundance_at("spec_biomasser_13b", 370.0, 70.0), 0.0)
        self.assertIsNone(sim.place_selected_species(900.0, 70.0))  # outside the region

        # Sown ground is not refined for its own sake ...
        self.assertEqual(sim._refresh_terrain_pending(), [])
        # ... only once the view rests on it from close by.
        sim.REFINE_VIEW_REST_SECONDS = 0.0
        sim._isometric_projection_state = {"center_x": 370.0, "center_y": 70.0, "scale": 2.0}
        self.assertEqual(sim._refresh_terrain_pending(), [])  # too far out to need it
        sim._isometric_projection_state = {"center_x": 370.0, "center_y": 70.0, "scale": 12.0}
        self.assertEqual(sim._refresh_terrain_pending(), [(2, 0)])

    def test_a_brush_sows_a_thin_stand_over_an_area_and_the_living_area_grows_to_hold_it(self):
        sim = self.sim
        self.assertEqual(sim.get_seeding_brush_label(), "Sow by hand")
        hand = sim.seeding_radius(sim.ecology.profiles["spec_biomasser_13b"])
        sim.cycle_seeding_brush()
        sim.cycle_seeding_brush()
        self.assertEqual((sim.seeding_brush_m, sim.get_seeding_brush_label()), (20.0, "Sow 20 m radius"))

        sim.place_selected_species(400.0, 64.0)
        patch = sim.ecology.patches[-1]
        self.assertEqual(patch.radius_m, 20.0)
        self.assertGreater(patch.radius_m, hand * 10)
        self.assertAlmostEqual(patch.abundance, 0.30 * (2.0 / 20.0) ** 0.5)  # sown thin
        self.assertLessEqual(sim.bounds["min_x"], 378.0)
        self.assertGreaterEqual(sim.bounds["max_x"], 422.0)
        self.assertEqual(sim.soil.bounds, sim.bounds)
        for _ in range(2):
            sim.cycle_seeding_brush()
        self.assertIsNone(sim.seeding_brush_m)

    def test_populations_reaching_the_edge_expand_the_domain_within_the_frame(self):
        sim = self.sim
        sim.place_selected_species(400.0, 64.0)
        sim.ecology.patches[0].abundance = 0.6
        self.assertFalse(sim._expand_if_population_reaches_edge())  # still well inside
        sim.ecology.patches[0].radius_m = 5.5
        self.assertTrue(sim._expand_if_population_reaches_edge())
        self.assertEqual(sim.bounds, {"min_x": 393.0, "max_x": 407.0, "min_y": 57.0, "max_y": 71.0})
        self.assertEqual(sim.get_root_entity()["bounds"]["max_x"], 512.0)
        self.assertEqual(sim.soil.bounds, sim.bounds)

    def test_the_view_zooms_about_the_cursor_and_pans_by_dragging(self):
        sim = self.sim
        renderer = BiosphereBuilderRenderer(SimpleNamespace())
        screen = pygame.Surface((1200, 800))
        renderer.draw(screen, sim)
        cursor = (900, 300)
        before = sim._screen_to_world(None, cursor)

        self.assertTrue(sim.zoom_isometric_view(1 / 3.0, cursor))
        renderer.draw(screen, sim)
        after = sim._screen_to_world(None, cursor)
        self.assertAlmostEqual(after[0], before[0], delta=0.02)
        self.assertAlmostEqual(after[1], before[1], delta=0.02)

        centre = sim._view_center()
        camera = SimpleNamespace(x=0.0, y=0.0, zoom=1.0)
        sim._begin_camera_drag((600, 400), camera)
        self.assertTrue(sim._update_camera_drag((600 + 60, 400), camera))
        renderer.draw(screen, sim)
        scale = sim._isometric_projection_state["scale"]
        self.assertAlmostEqual(sim._view_center()[0], centre[0] - 30.0 / scale)
        self.assertAlmostEqual(sim._view_center()[1], centre[1] + 30.0 / scale)
        self.assertEqual((camera.x, camera.y), (0.0, 0.0))  # the Map camera is not what is drawn
        sim._reset_camera_drag()

        sim.reset_isometric_view()
        self.assertEqual((sim.isometric_view_zoom, sim.isometric_view_center), (1.0, None))
        sim.cycle_terrain_relief()
        self.assertEqual(sim.terrain_vertical_scale, 2.0)

    def test_the_isometric_ground_is_the_heightfield_and_is_reused_while_the_view_rests(self):
        sim = self.sim
        sim.isometric_view_zoom = 0.2
        renderer = BiosphereBuilderRenderer(SimpleNamespace())
        screen = pygame.Surface((800, 600))
        with mock.patch.object(renderer, "_render_generated_ground", wraps=renderer._render_generated_ground) as render:
            renderer.draw(screen, sim)
            renderer.draw(screen, sim)
            self.assertEqual(render.call_count, 1)
            self.assertEqual(render.call_args.args[3], renderer.GROUND_CELL_PX)
            sim.isometric_view_center = (402.0, 64.0)
            renderer.draw(screen, sim)  # moving: one coarse mesh under the slid picture
            self.assertEqual(render.call_args.args[3], renderer.GROUND_CELL_PX_MOVING)
            renderer.draw(screen, sim)  # a pause shorter than the settle time costs nothing
            self.assertEqual(render.call_count, 2)
            renderer.GROUND_SETTLE_SECONDS = 0.0
            sim.is_camera_dragging = sim.camera_drag_has_moved = True
            renderer.draw(screen, sim)  # still held: no fine mesh mid-drag
            self.assertEqual(render.call_count, 2)
            sim.is_camera_dragging = sim.camera_drag_has_moved = False
            renderer.draw(screen, sim)  # at rest: meshed finely once more
            self.assertEqual(render.call_count, 3)
            self.assertEqual(render.call_args.args[3], renderer.GROUND_CELL_PX)
        state = sim._isometric_projection_state
        self.assertTrue(state["generated"])
        self.assertAlmostEqual(state["datum_m"], sim.substrate.elevation(402.0, 64.0, True))
        # East is higher: with the datum at the centre, eastern ground is drawn above the flat plane.
        flat_y = state["origin_y"] + (20.0 + 0.0) * state["scale"] * 0.5
        self.assertLess(BiosphereBuilderRenderer._iso(state, 422.0, 64.0)[1], flat_y)
        # The ground is not the dark backdrop at the view centre.
        self.assertNotEqual(tuple(screen.get_at((round(state["origin_x"]), round(state["origin_y"]) + 40)))[:3], (15, 20, 18))


class ClimateResponseTests(unittest.TestCase):
    def test_moisture_preference_places_a_species_on_the_wetness_index(self):
        dry = profile_from_entity({"id": "a", "plant_growth_form": "tree", "moisture_preference": "dry"})
        wet = profile_from_entity({"id": "b", "plant_growth_form": "tree", "moisture_preference": "wet"})
        unknown = profile_from_entity({"id": "c", "plant_growth_form": "tree"})
        authored = profile_from_entity({"id": "d", "plant_growth_form": "tree", "moisture_preference": "wet",
                                        "biosphere_growth_profile": {"moisture_optimum": 0.3}})
        self.assertEqual((dry.moisture_optimum, wet.moisture_optimum), (0.20, 0.78))
        self.assertEqual(dry.moisture_source, "moisture_preference qualitative default")
        self.assertEqual((unknown.moisture_optimum, unknown.moisture_source), (0.48, "growth_form_default"))
        self.assertEqual((authored.moisture_optimum, authored.moisture_source), (0.3, "authored biosphere moisture_optimum"))

    def test_temperature_limits_growth_only_where_worldgen_resolved_the_seasons(self):
        hardy = profile_from_entity({"id": "a", "plant_growth_form": "tree", "frost_tolerance": {"min_c": -30.0}})
        tender = profile_from_entity({"id": "b", "plant_growth_form": "tree", "frost_tolerance": {"min_c": -2.0}})
        unknown = profile_from_entity({"id": "c", "plant_growth_form": "tree"})

        def climate(coldest_c, warmest_c):
            return {"coldest_month_temperature_k": coldest_c + 273.15, "warmest_month_temperature_k": warmest_c + 273.15}

        self.assertEqual(thermal_response(hardy, {}), (1.0, None))  # no seasonal normals: unresolved, not judged
        self.assertEqual(thermal_response(hardy, climate(-10.0, 18.0)), (1.0, None))
        self.assertEqual(thermal_response(tender, climate(-10.0, 18.0)), (0.0, "frost"))
        self.assertEqual(thermal_response(unknown, climate(-10.0, 18.0)), (1.0, None))  # no authored limit
        self.assertEqual(thermal_response(unknown, climate(-30.0, 3.0)), (0.0, "growing-season warmth"))
        score, limiting = thermal_response(unknown, climate(30.0, 43.0))
        self.assertEqual(limiting, "heat")
        self.assertAlmostEqual(score, 0.5)

    def test_a_cold_site_suppresses_growth_through_the_population_kernel(self):
        suitability = {}
        for name, climate in (("temperate", {}), ("polar", {"coldest_k": 243.15, "warmest_k": 276.15})):
            world = _world(**climate)
            site = terrain_site.found_biosphere_site(world, REGION_ID, _region_point(400.0, 64.0))
            sim = BiosphereSimulation(world, {"patch_location_id": site["id"]})
            profile = sim.ecology.profiles["spec_biomasser_13b"]
            suitability[name] = sim.ecology._suitability(profile, sim.ecology.environment_at(400.0, 64.0))
            fit = sim.get_species_climate_fit("spec_biomasser_13b")
            self.assertAlmostEqual(fit["suitability"], suitability[name])
        self.assertGreater(suitability["temperate"], 0.3)
        self.assertEqual(suitability["polar"], 0.0)


class TerraformingFeedbackTests(unittest.TestCase):
    """What a player is told while building a barren site into living ground."""

    def setUp(self):
        pygame.init()
        pygame.font.init()

    def _sim(self, **climate):
        world = _world(**climate)
        site = terrain_site.found_biosphere_site(world, REGION_ID, _region_point(400.0, 64.0), year=2400)
        return BiosphereSimulation(world, {"patch_location_id": site["id"], "year": 2400})

    def test_a_new_site_is_barren_and_only_the_bootstrap_organism_can_be_planted(self):
        sim = self._sim()
        summary = sim.ecology.summary()
        self.assertEqual((summary["living_biomass_kg"], summary["population_patch_count"]), (0.0, 0))
        self.assertEqual(summary["soil"]["soil_stage"], "barren mineral substrate")
        self.assertEqual(summary["soil"]["max_soil_organic_matter_kg_m2"], 0.0)
        self.assertEqual(
            [profile.species_id for profile in sim.species_profiles if sim.is_species_unlocked(profile.species_id)],
            ["spec_biomasser_13b"],
        )
        self.assertEqual(sim.get_field_notes(), [])

    def test_suitability_names_its_terms_and_the_weakest_one(self):
        sim = self._sim()
        ryegrass = sim.ecology.profiles["spec_lolium_perenne"]
        environment = sim.ecology.environment_at(400.0, 64.0)
        factors = sim.ecology.suitability_factors(ryegrass, environment)
        self.assertEqual(factors["suitability"], sim.ecology._suitability(ryegrass, environment))
        self.assertEqual(
            set(factors["scores"]),
            {"moisture", "light", "rooting depth", "organic soil", "nitrogen", "phosphorus", "temperature"})
        # Good water and warmth, but nothing has built soil yet.
        self.assertEqual(factors["limiting"], "organic soil")
        self.assertEqual(sim.diagnose("spec_lolium_perenne", 400.0, 64.0)["reason"],
                         "soil too raw (needs 0.150 kg/m² organic matter)")
        water = sim.diagnose("spec_lolium_perenne", 8.0, 100.0)
        self.assertEqual((water["suitability"], water["reason"]), (0.0, "open water"))

    def test_the_catalogue_is_a_ladder_and_says_how_the_site_suits_each_species(self):
        sim = self._sim()
        items = sim.get_species_catalog_items()
        self.assertEqual([item["succession_tier"] for item in items], [0, 1])
        # The lichen needs no soil; the grass suits the climate but not the raw ground.
        self.assertEqual([item["site_fit"]["verdict"] for item in items], ["pioneer", "suits"])
        self.assertTrue(items[0]["trait_lines"][0].startswith("Site: Can pioneer the raw ground here"))
        self.assertTrue(items[1]["trait_lines"][0].startswith("Site: Suits this site once soil is built"))
        self.assertEqual(items[1]["site_fit"]["raw"], 0.0)

        polar = self._sim(coldest_k=243.15, warmest_k=276.15)
        fit = polar.get_species_climate_fit("spec_lolium_perenne")
        self.assertEqual((fit["verdict"], fit["potential"], fit["sustainable"]), ("unfit", 0.0, False))
        self.assertEqual(fit["label"], "Cannot hold here: summers too cold")

        def with_wetness(value, **climate):
            sim = self._sim(**climate)
            for row in sim.world_model.get_entity(REGION_ID)["water_cycle_model"]["runoff_grid"]["wetness_index_rows"]:
                row[:] = [value] * len(row)
            sim._rebuild_substrate()
            return sim

        # Dry ground under good rain: built soil holds enough water for the grass.
        fit = with_wetness(0.02).get_species_climate_fit("spec_lolium_perenne")
        self.assertEqual((fit["verdict"], fit["moisture"]), ("marginal", 0.0))
        self.assertAlmostEqual(fit["potential"], 1.0 - abs(0.02 + 0.43 * 0.82 - 0.58) / 0.42)
        # The wetness quoted is the built soil's, the ground the verdict speaks of.
        self.assertIn("too dry (wetness 0.37, best near 0.58)", fit["label"])
        # Hot as well as dry: only under a canopy.
        fit = with_wetness(0.02, coldest_k=303.15, warmest_k=320.15).get_species_climate_fit("spec_lolium_perenne")
        self.assertEqual(fit["verdict"], "sheltered")
        self.assertEqual(fit["label"], "Needs built soil and a nurse canopy here: too hot without shade in the open")

    def test_field_notes_record_plantings_soil_stages_and_failures_with_their_cause(self):
        sim = self._sim()
        sim.place_selected_species(400.0, 64.0)
        self.assertEqual([(note["kind"], note["text"]) for note in sim.get_field_notes()],
                         [("plan", "Introduced Biomasser 13B")])
        sim.select_species("spec_lolium_perenne")  # still locked: nothing happens
        self.assertEqual(sim.selected_species_id, "spec_biomasser_13b")

        for _ in range(60):
            sim.advance_seasons(1)
            if sim.soil.summary()["supported_succession_tier"] >= 1:
                break
        texts = [note["text"] for note in sim.get_field_notes(10)]
        self.assertIn("Soil reached herbaceous pioneer soil: 1 more species can be planted", texts)
        self.assertEqual(sim.get_field_notes(1)[0]["when"][:1], "Y")

        self.assertTrue(sim.select_species("spec_lolium_perenne"))
        sim.place_selected_species(400.0, 64.0)
        self.assertEqual(sim.get_field_notes(1)[0]["text"], "Introduced Perennial Ryegrass")
        # A terrestrial species sown into open water is warned about at once.
        sim.maximum_extent_m = 512.0
        sim.place_selected_species(8.0, 64.0)
        warning = sim.get_field_notes(2)
        self.assertEqual(
            [(note["kind"], note["text"]) for note in warning if note["kind"] == "warning"],
            [("warning", "Introduced Perennial Ryegrass; unlikely to hold: open water")],
        )

    def test_a_population_the_climate_kills_is_reported_with_the_reason(self):
        sim = self._sim(coldest_k=243.15, warmest_k=276.15)
        sim.place_selected_species(400.0, 64.0)
        self.assertEqual(
            (sim.get_field_notes(1)[0]["kind"], sim.get_field_notes(1)[0]["text"]),
            ("warning", "Introduced Biomasser 13B; unlikely to hold: summers too cold"),
        )
        for _ in range(80):
            sim.advance_seasons(1)
            if not sim.ecology.patches:
                break
        self.assertEqual(sim.ecology.patches, [])
        failure = next(note for note in sim.get_field_notes(10) if note["kind"] == "failure")
        self.assertEqual(failure["text"], "Biomasser 13B died out: summers too cold")
        self.assertNotIn("Biomasser 13B established", [note["text"] for note in sim.field_notes])

    def test_the_cursor_reads_the_ground_and_the_selected_species_fate_there(self):
        sim = self._sim()
        renderer = BiosphereBuilderRenderer(SimpleNamespace())
        screen = pygame.Surface((1600, 900))
        renderer.draw(screen, sim)
        self.assertIsNone(sim.get_cursor_readout())  # no pointer yet
        state = sim._isometric_projection_state
        sim._pointer_screen_pos = tuple(round(v) for v in BiosphereBuilderRenderer._iso(state, 400.0, 64.0))
        readout = sim.get_cursor_readout()
        self.assertTrue(readout["inside_domain"])
        self.assertIn("wetness 0.59", readout["ground"])
        self.assertIn("soil organic 0.000 kg/m²", readout["ground"])
        cover = sim.ecology.expected_cover(sim.ecology.profiles["spec_biomasser_13b"], readout["suitability"])
        word = "would thrive" if cover >= 0.6 else "would hold"
        self.assertTrue(readout["species"].startswith(f"Biomasser 13B {word} here"))
        self.assertTrue(readout["holds"])
        self.assertAlmostEqual(readout["cover"], cover)
        sim.isometric_view_zoom = 0.2
        renderer.draw(screen, sim)
        sim._pointer_screen_pos = tuple(round(v) for v in BiosphereBuilderRenderer._iso(
            sim._isometric_projection_state, 440.0, 64.0))
        self.assertIn("outside the living area", sim.get_cursor_readout()["ground"])

    def test_the_hud_draws_the_ground_strip_notes_and_catalogue_verdicts(self):
        sim = self._sim()
        sim.place_selected_species(400.0, 64.0)
        ui = UIManager()
        ui.rebuild_for_state(sim, 1600, 900, camera=None, world_model=sim.world_model)
        ids = {button.id for button in ui.buttons}
        self.assertTrue({"biosphere_cycle_relief", "biosphere_reset_view", "biosphere_open_species_picker"} <= ids)
        self.assertIsNotNone(ui.biosphere_terrain_rect)
        self.assertEqual(ui.biosphere_dashboard["field_notes"][0]["text"], "Introduced Biomasser 13B")
        surface = pygame.Surface((1600, 900))
        font = pygame.font.SysFont("consolas", 16)
        ui.draw(surface, font)
        sim.open_species_picker()
        ui.rebuild_for_state(sim, 1600, 900, camera=None, world_model=sim.world_model)
        ui.draw(surface, font)
        self.assertEqual(
            [item["site_fit"]["verdict"] for item in ui.biosphere_picker_model["items"]], ["pioneer", "suits"])


class TerraformingKernelTests(unittest.TestCase):
    """Limits, amelioration and spread: what makes a barren site a ladder."""

    def setUp(self):
        pygame.init()

    def _sim(self, wetness=None, **climate):
        world = _world(**climate)
        if wetness is not None:
            for row in world.get_entity(REGION_ID)["water_cycle_model"]["runoff_grid"]["wetness_index_rows"]:
                row[:] = [wetness] * len(row)
        site = terrain_site.found_biosphere_site(world, REGION_ID, _region_point(400.0, 64.0), year=2400)
        return BiosphereSimulation(world, {"patch_location_id": site["id"], "year": 2400})

    def _enrich(self, sim, organic):
        for name, value in (("organic_matter_rows", organic), ("available_nitrogen_rows", 4.0),
                            ("available_phosphorus_rows", 1.0)):
            setattr(sim.soil, name, [[value] * sim.soil.columns for _ in range(sim.soil.rows)])
        sim.soil.revision += 1

    def test_water_soil_and_temperature_cap_growth_whatever_else_is_plentiful(self):
        sim = self._sim()
        ryegrass = sim.ecology.profiles["spec_lolium_perenne"]
        # Raw ground: ample water and light cannot stand in for soil.
        self.assertEqual(sim.diagnose("spec_lolium_perenne", 400.0, 64.0)["suitability"], 0.0)
        self._enrich(sim, 1.0)
        rich = sim.diagnose("spec_lolium_perenne", 400.0, 64.0)
        self.assertGreater(rich["suitability"], 0.8)

        dry = self._sim(wetness=0.0)
        self._enrich(dry, 0.16)  # enough soil to plant in, too little to hold much water
        factors = dry.ecology.suitability_factors(ryegrass, dry.ecology.environment_at(400.0, 64.0))
        self.assertEqual((factors["suitability"], factors["limiting"]), (0.0, "moisture"))

    def test_tall_neighbours_overtop_low_ones_and_low_ones_barely_trouble_tall_ones(self):
        sim = self._sim()
        ecology = sim.ecology
        from dataclasses import replace

        # The live roster authors these heights; the bare fixture species do not.
        ecology.profiles["spec_biomasser_13b"] = replace(ecology.profiles["spec_biomasser_13b"], mature_height_m=0.1)
        ecology.profiles["spec_lolium_perenne"] = replace(ecology.profiles["spec_lolium_perenne"], mature_height_m=0.9)
        crust = ecology._new_patch("spec_biomasser_13b", 400.0, 64.0, 3.0, 0.8, 0, "crust")
        grass = ecology._new_patch("spec_lolium_perenne", 400.0, 64.0, 3.0, 0.8, 0, "grass")
        crust.development_days = ecology.profiles[crust.species_id].maturity_days
        grass.development_days = ecology.profiles[grass.species_id].maturity_days
        self.assertGreater(ecology._stature_m(grass), ecology._stature_m(crust) + 0.3)
        competition_on_grass, grass_overtopped = ecology._competition_at_patch(grass)
        competition_on_crust, crust_overtopped = ecology._competition_at_patch(crust)
        self.assertAlmostEqual(competition_on_grass, 0.8 * ecology.UNDERSTOREY_COMPETITION)
        self.assertEqual(grass_overtopped, 0.0)
        self.assertAlmostEqual(competition_on_crust, 0.8 * 0.75)
        self.assertAlmostEqual(crust_overtopped, 0.8)

    def test_soil_organic_matter_holds_rain_and_lifts_dry_ground_towards_mesic(self):
        from simulations.biosphere.ecology import RETENTION_CEILING, moisture_retention_bonus

        self.assertEqual(moisture_retention_bonus(0.1, 0.0, 800.0), 0.0)
        self.assertAlmostEqual(moisture_retention_bonus(0.1, 1.0, 1000.0), (RETENTION_CEILING - 0.1) * 0.5)
        self.assertAlmostEqual(moisture_retention_bonus(0.1, 1.0, 250.0), (RETENTION_CEILING - 0.1) * 0.5 * 0.25)
        self.assertEqual(moisture_retention_bonus(0.6, 5.0, 1000.0), 0.0)  # already moist: nothing to add

        sim = self._sim(wetness=0.05)
        bare = sim.ecology.environment_at(400.0, 64.0)
        self.assertAlmostEqual(bare["soil_moisture"], 0.05)
        self._enrich(sim, 3.0)
        built = sim.ecology.environment_at(400.0, 64.0)
        self.assertAlmostEqual(built["abiotic_soil_moisture"], 0.05)
        self.assertAlmostEqual(built["soil_moisture"], 0.05 + (0.45 - 0.05) * 0.75 * 0.82)
        # Worldgen's own field is untouched.
        self.assertAlmostEqual(sim.ecology.abiotic_environment_at(400.0, 64.0)["soil_moisture"], 0.05)
        # The ryegrass that could not hold on the dry mineral ground now can.
        ryegrass = sim.ecology.profiles["spec_lolium_perenne"]
        self.assertTrue(sim.ecology.sustains(ryegrass, sim.diagnose("spec_lolium_perenne", 400.0, 64.0)["suitability"]))

    def test_a_canopy_eases_heat_for_what_grows_under_it(self):
        sim = self._sim(coldest_k=303.15, warmest_k=318.15)  # 45 C in the warmest month
        ryegrass = sim.ecology.profiles["spec_lolium_perenne"]
        open_ground = sim.ecology.environment_at(400.0, 64.0)
        self.assertEqual(open_ground["canopy_shade"], 0.0)
        self.assertAlmostEqual(thermal_response(ryegrass, open_ground)[0], 0.3)
        shaded = dict(open_ground, canopy_shade=1.0)
        self.assertAlmostEqual(thermal_response(ryegrass, shaded)[0], 0.9)
        self.assertEqual(sim.diagnose("spec_lolium_perenne", 400.0, 64.0)["scores"]["temperature"], 0.3)
        # Shade is no help against cold.
        cold = {"coldest_month_temperature_k": 250.0, "warmest_month_temperature_k": 277.0, "canopy_shade": 1.0}
        self.assertEqual(thermal_response(ryegrass, cold)[0], 0.0)

    def test_fronts_advance_only_over_ground_that_would_carry_the_species(self):
        sim = self._sim()
        sim.place_selected_species(400.0, 64.0)
        lichen = sim.ecology.patches[0]
        lichen.abundance = 0.8
        before = lichen.radius_m
        sim.ecology.advance(4)
        self.assertGreater(lichen.radius_m, before + 0.3)  # metres a year, not centimetres

        self._enrich(sim, 0.0)
        sim.select_species("spec_biomasser_13b")
        grass = sim.ecology._new_patch("spec_lolium_perenne", 402.0, 66.0, 0.5, 0.8, 0, "test")
        sim.ecology.advance(4)
        self.assertEqual(grass.radius_m, 0.5)  # raw mineral ground all round: it does not spread

    def test_populations_that_grow_into_each_other_are_fused(self):
        sim = self._sim()
        ecology = sim.ecology
        large = ecology._new_patch("spec_biomasser_13b", 400.0, 64.0, 3.0, 0.4, 0, "a")
        inside = ecology._new_patch("spec_biomasser_13b", 401.0, 64.0, 0.5, 0.6, 0, "b")
        apart = ecology._new_patch("spec_biomasser_13b", 404.0, 67.0, 0.5, 0.6, 0, "c")
        other = ecology._new_patch("spec_lolium_perenne", 400.5, 64.0, 0.5, 0.6, 0, "d")
        ecology._consolidate_patches()
        self.assertEqual({patch.patch_id for patch in ecology.patches}, {large.patch_id, apart.patch_id, other.patch_id})
        self.assertAlmostEqual(large.abundance, 0.4 + 0.6 * 0.25 / 9.0)
        self.assertEqual(large.radius_m, 3.0)

        ecology.MAX_PATCHES_PER_SPECIES = 1
        ecology._consolidate_patches()
        lichen = ecology.species_patches("spec_biomasser_13b")
        self.assertEqual(len(lichen), 1)
        self.assertAlmostEqual(lichen[0].radius_m, (9.0 + 0.25) ** 0.5)  # same total area
        self.assertEqual(len(ecology.species_patches("spec_lolium_perenne")), 1)

    def test_fast_forward_never_banks_seasons_and_few_organisms_are_regrown_per_season(self):
        sim = self._sim()
        sim.place_selected_species(400.0, 64.0)
        self.assertTrue(sim.set_builder_time_scale(64.0))
        sim.update(600.0)  # ten minutes in one frame
        self.assertEqual(sim.ecology.season, sim.MAX_SEASONS_PER_FRAME)
        self.assertLessEqual(sim._season_accumulator, sim.seconds_per_season)

        manager = sim.representatives
        manager.MAX_REGROWN_PER_SEASON = 1
        # Every organism is full-grown but stands in a half-grown body: all are due, one gets the turn.
        for rep in manager.items(alive_only=True):
            timing = manager.life_timing(rep)
            manager.grow_body(rep, timing.maturity_days * 0.5)
            rep.age_days = timing.maturity_days * 3.0
            rep.health = 0.9
        ages_before = {rep.representative_id: rep.age_days for rep in manager.items(alive_only=True)}
        bodies_before = {rep.representative_id: rep.body_age_days for rep in manager.items(alive_only=True)}
        self.assertGreaterEqual(len(ages_before), 3)
        sim.advance_seasons(1)
        regrown = [
            rep for rep in manager.items(alive_only=True)
            if rep.representative_id in bodies_before and rep.body_age_days != bodies_before[rep.representative_id]
        ]
        self.assertEqual(len(regrown), 1)
        self.assertTrue(all(rep.age_days > ages_before[rep.representative_id]
                            for rep in manager.items(alive_only=True) if rep.representative_id in ages_before))


OAK = {"id": "spec_test_oak", "_dataset": "species", "type": "species", "pretty_name": "English Oak - Quercus robur",
       "plant_growth_form": "tree", "moisture_preference": "moist"}
TENDER = {"id": "spec_test_tender", "_dataset": "species", "type": "species", "pretty_name": "Aaa Tender Grass",
          "plant_growth_form": "graminoid", "moisture_preference": "moist", "frost_tolerance": {"min_c": 20.0}}


class RefinementTests(unittest.TestCase):
    """Second pass: what the player reads and how the landscape is drawn."""

    def setUp(self):
        pygame.init()
        pygame.font.init()

    def _sim(self, *extra, **climate):
        world = _world(*extra, **climate)
        site = terrain_site.found_biosphere_site(world, REGION_ID, _region_point(400.0, 64.0), year=2400)
        return BiosphereSimulation(world, {"patch_location_id": site["id"], "year": 2400})

    def _stand(self, sim, species_id, x, y, radius, abundance, mature=True, height=None):
        from dataclasses import replace

        if height is not None:
            sim.ecology.profiles[species_id] = replace(sim.ecology.profiles[species_id], mature_height_m=height)
        patch = sim.ecology._new_patch(species_id, x, y, radius, abundance, 0, f"{species_id}:{x}:{y}")
        if mature:
            patch.development_days = sim.ecology.profiles[species_id].maturity_days
        return patch

    def test_names_in_status_lines_and_notes_drop_the_scientific_part(self):
        sim = self._sim(OAK)
        self.assertEqual(sim.short_label("spec_test_oak"), "English Oak")
        self.assertEqual(sim.short_label("spec_biomasser_13b"), "Biomasser 13B")
        self.assertEqual(sim.diagnose("spec_test_oak", 400.0, 64.0)["label"], "English Oak")
        sim.soil.organic_matter_rows = [[5.0] * sim.soil.columns for _ in range(sim.soil.rows)]
        sim.soil.revision += 1
        sim.select_species("spec_test_oak")
        sim.place_selected_species(400.0, 64.0)
        self.assertTrue(sim.get_field_notes(1)[0]["text"].startswith("Introduced English Oak"))
        self.assertEqual(sim.get_biosphere_dashboard_model()["selected_species"], "English Oak")

    def test_the_catalogue_lists_what_the_site_can_carry_before_what_it_cannot(self):
        sim = self._sim(TENDER)
        # Alphabetically the tender grass comes first; the site's winters rule it out.
        self.assertEqual(sim.get_species_climate_fit("spec_test_tender")["verdict"], "unfit")
        self.assertEqual(
            [profile.species_id for profile in sim.species_profiles],
            ["spec_biomasser_13b", "spec_lolium_perenne", "spec_test_tender"],
        )

    def test_how_well_a_species_would_do_is_judged_in_its_own_terms(self):
        sim = self._sim(OAK)
        lichen, oak = sim.ecology.profiles["spec_biomasser_13b"], sim.ecology.profiles["spec_test_oak"]
        # The same ground: a fast crust fills it, a slow tree settles thin.
        self.assertGreater(sim.ecology.expected_cover(lichen, 0.6), 0.85)
        self.assertLess(sim.ecology.expected_cover(oak, 0.6), 0.45)
        self.assertEqual(sim.ecology.expected_cover(oak, 0.3), 0.0)
        self.assertFalse(sim.ecology.sustains(oak, 0.3))
        self.assertTrue(sim.ecology.sustains(lichen, 0.3))

    def test_populations_are_listed_heaviest_first_with_their_trend_and_can_be_brought_into_view(self):
        sim = self._sim()
        self.assertEqual(sim.get_population_rows(), [])
        self._stand(sim, "spec_biomasser_13b", 400.0, 64.0, 3.0, 0.8)
        self._stand(sim, "spec_lolium_perenne", 398.0, 62.0, 1.0, 0.5)
        sim.representatives.sync_from_population(sim.ecology)
        sim._biomass_history = {"spec_biomasser_13b": [10.0, 20.0, 30.0, 40.0, 50.0, 60.0],
                                "spec_lolium_perenne": [9.0, 8.0, 7.0, 6.0, 5.0, 1.0]}
        rows = sim.get_population_rows()
        self.assertEqual([row["label"] for row in rows], ["Biomasser 13B", "Perennial Ryegrass"])
        self.assertEqual([row["stands"] for row in rows], [1, 1])
        self.assertGreater(rows[0]["biomass_kg"], rows[1]["biomass_kg"])
        self.assertEqual([row["representative_id"] is not None for row in rows], [True, True])

        sim.isometric_view_center = (380.0, 60.0)
        self.assertTrue(sim.focus_population("spec_lolium_perenne"))
        self.assertEqual(sim.isometric_view_center, (398.0, 62.0))
        selected = sim.representatives.get(sim.selected_representative_id)
        self.assertEqual(selected.species_id, "spec_lolium_perenne")
        self.assertTrue(next(row for row in sim.get_population_rows() if row["species_id"] == "spec_lolium_perenne")["selected"])
        self.assertFalse(sim.focus_population("spec_nothing_here"))

    def test_a_population_that_loses_a_third_of_its_best_is_reported_once_with_its_cause(self):
        sim = self._sim()
        crust = self._stand(sim, "spec_biomasser_13b", 400.0, 64.0, 3.0, 0.5, height=0.1)
        self._stand(sim, "spec_lolium_perenne", 400.0, 64.0, 3.0, 0.9, height=0.9)
        sim._established_species.update({"spec_biomasser_13b", "spec_lolium_perenne"})
        extent = (sim.bounds["max_x"] - sim.bounds["min_x"], sim.bounds["max_y"] - sim.bounds["min_y"])

        def season():
            sim._record_season_outcomes(sim._population_centres(), extent, sim._population_pressures())

        season()
        self.assertEqual([note for note in sim.field_notes if note["kind"] == "warning"], [])
        crust.abundance = 0.3  # 60 % of its best
        season()
        season()
        warnings = [note["text"] for note in sim.field_notes if note["kind"] == "warning"]
        self.assertEqual(warnings, ["Biomasser 13B is dwindling: overgrown by taller plants"])
        self.assertTrue(next(row for row in sim.get_population_rows() if row["species_id"] == "spec_biomasser_13b")["dwindling"])

        sim.ecology.patches.remove(crust)
        sim._record_season_outcomes({"spec_biomasser_13b": (400.0, 64.0)}, extent, {"spec_biomasser_13b": (0.6, 0.9)})
        self.assertEqual(sim.get_field_notes(1)[0]["text"], "Biomasser 13B died out: overgrown by taller plants")

    def test_with_an_area_tool_a_click_on_an_organism_sows_and_a_right_click_inspects(self):
        sim = self._sim()
        sim.place_selected_species(400.0, 64.0)
        renderer = BiosphereBuilderRenderer(SimpleNamespace())
        screen = pygame.Surface((1600, 900))
        renderer.draw(screen, sim)
        representative_id, hitbox = sim._representative_screen_hitboxes[-1]
        down = SimpleNamespace(type=sim.MOUSEBUTTONDOWN_EVENT_TYPE, button=1)
        up = SimpleNamespace(type=sim.MOUSEBUTTONUP_EVENT_TYPE, button=1)
        camera = SimpleNamespace(x=0.0, y=0.0, zoom=1.0, width=1600, height=900)

        sim.handle_pointer_event(down, camera, hitbox.center)
        sim.handle_pointer_event(up, camera, hitbox.center)
        self.assertEqual(sim.selected_representative_id, representative_id)  # by hand: inspect
        self.assertEqual(len(sim.ecology.introductions), 1)

        sim.selected_representative_id = None
        sim.seeding_brush_m = 5.0
        sim.handle_pointer_event(down, camera, hitbox.center)
        sim.handle_pointer_event(up, camera, hitbox.center)
        self.assertIsNone(sim.selected_representative_id)  # with a brush: the click sows
        self.assertEqual(len(sim.ecology.introductions), 2)

        sim.handle_pointer_event(SimpleNamespace(type=sim.MOUSEBUTTONDOWN_EVENT_TYPE, button=3), camera, hitbox.center)
        self.assertEqual(sim.selected_representative_id, representative_id)
        self.assertEqual(len(sim.ecology.introductions), 2)

    def test_a_wide_stand_is_judged_over_its_ground_not_only_its_centre(self):
        sim = self._sim()
        sim._set_domain({"min_x": 0.0, "max_x": 120.0, "min_y": 20.0, "max_y": 110.0})
        ecology = sim.ecology
        lichen = ecology.profiles["spec_biomasser_13b"]
        # Centred on the open water along the region's west edge, reaching well onto land.
        wide = self._stand(sim, "spec_biomasser_13b", 24.0, 64.0, 40.0, 0.5)
        self.assertEqual(ecology._suitability(lichen, ecology.environment_at(24.0, 64.0)), 0.0)
        ring_sum, ring_count = ecology._stand_ring(wide, lichen, 0.05)
        self.assertEqual(ring_count, 4)
        self.assertGreater(ring_sum, 0.0)
        small = self._stand(sim, "spec_biomasser_13b", 80.0, 64.0, 1.0, 0.5)
        ecology.advance(1)
        self.assertIsNotNone(wide.stand_ring)
        self.assertIsNone(small.stand_ring)  # a small patch is its centre
        # Fusing two stands makes the ground new: it is judged afresh.
        other = self._stand(sim, "spec_biomasser_13b", 110.0, 64.0, 5.0, 0.5)
        ecology._absorb(wide, other, keep_footprint=False)
        self.assertIsNone(wide.stand_ring)

    def test_a_growing_herb_is_regrown_every_season_and_a_grown_one_is_left_alone(self):
        sim = self._sim()
        self._stand(sim, "spec_lolium_perenne", 400.0, 64.0, 1.5, 0.8)
        manager = sim.representatives
        manager.sync_from_population(sim.ecology)
        organisms = manager.items(alive_only=True)
        self.assertEqual(len(organisms), 4)
        season = manager.DAYS_PER_SEASON
        timing = manager.life_timing(organisms[0])
        self.assertLess(timing.maturity_days, 2 * season)  # a grass is full-grown within two seasons
        grown_at = []
        for _ in range(9):
            for organism in organisms:
                organism.health, organism.alive = 0.9, True  # this test is about bodies, not about who survives
            manager.advance_season(sim.ecology)
            grown_at.append([organism.body_age_days for organism in organisms])
            # No body shows a stage of life its organism has left.
            self.assertTrue(all(manager.life_stage(organism.simulation, organism.age_days) == organism.body_stage
                                or manager.body_lag(organism) >= 1.0 for organism in organisms))
        # While it grows, three of the four get a new body each season (the quota).
        first = sum(a != b for a, b in zip(grown_at[0], [1.0] * 4))
        self.assertEqual(first, 3)
        # Full-grown and with no seasons to show, a body is left alone: it could not look different.
        self.assertFalse(manager.has_seasons(organisms[0].simulation))
        changes = sum(a != b for before, after in zip(grown_at[3:], grown_at[4:]) for a, b in zip(before, after))
        self.assertEqual(changes, 0)
        self.assertTrue(all(organism.simulation.render_snapshot.stats["maturity"] == 1.0 for organism in organisms))

    def test_a_tree_body_is_regrown_when_it_has_grown_not_every_season(self):
        sim = self._sim(OAK)
        self._stand(sim, "spec_test_oak", 400.0, 64.0, 1.5, 0.8, mature=False)
        manager = sim.representatives
        manager.sync_from_population(sim.ecology)
        organisms = manager.items(alive_only=True)
        timing = manager.life_timing(organisms[0])
        self.assertAlmostEqual(timing.maturity_days / 365.25, 30.0)  # generic tree: full-grown at a fifth of 150 years
        regrowths = 0
        for _ in range(40):  # ten years
            for organism in organisms:
                organism.health, organism.alive = 0.9, True
            before = [organism.body_age_days for organism in organisms]
            manager.advance_season(sim.ecology)
            regrowths += sum(a != organism.body_age_days for a, organism in zip(before, organisms))
            for organism in organisms:
                body = organism.simulation.render_snapshot.stats["maturity"]
                due = manager.developmental_days(organism, organism.age_days) / timing.developmental_maturity_days
                self.assertLess(due - body, 0.11)  # never more than a tenth of full size behind
        # Forty seasons, four organisms: a body every season would be 160.
        # A third of full size in ten years: a few regrowths each.
        self.assertLess(regrowths, 60)
        self.assertGreater(regrowths, 8)
        halfway = [organism.simulation.render_snapshot.stats["maturity"] for organism in organisms]
        self.assertTrue(all(0.22 < share < 0.36 for share in halfway), halfway)  # ten of thirty years, a regrowth behind at most

    def test_light_under_many_crowns_is_the_same_answer_computed_at_once(self):
        import random

        from simulations.species.forest_ecology import light_at

        sim = self._sim(OAK)
        sim._set_domain({"min_x": 300.0, "max_x": 500.0, "min_y": 10.0, "max_y": 250.0})
        ecology = sim.ecology
        rng = random.Random(11)
        for index in range(30):
            patch = self._stand(sim, "spec_test_oak", rng.uniform(320.0, 480.0), rng.uniform(30.0, 230.0),
                                rng.uniform(4.0, 25.0), rng.uniform(0.2, 1.0), height=20.0)
            patch.development_days *= rng.uniform(0.05, 1.0)  # crowns of every height
        canopies = ecology.canopy_footprints()
        self.assertGreaterEqual(len(canopies), ecology.CANOPY_ARRAY_MINIMUM)
        shaded = 0
        for _ in range(300):
            x, y, height = rng.uniform(310.0, 490.0), rng.uniform(20.0, 240.0), rng.choice((0.05, 1.5, 6.0, 25.0))
            exclude = rng.choice([None, canopies[rng.randrange(len(canopies))]["id"]])
            expected = light_at(x, y, height, canopies, exclude)
            self.assertAlmostEqual(ecology._canopy_light_at(x, y, height, canopies, exclude), expected, places=12)
            shaded += expected < 0.9
        self.assertGreater(shaded, 50)
        # A handful of crowns takes the plain loop: the same function, exactly.
        few = canopies[:3]
        self.assertEqual(ecology._canopy_light_at(400.0, 64.0, 0.05, few), light_at(400.0, 64.0, 0.05, few))

    def test_a_held_canopy_picture_is_released_afterwards(self):
        sim = self._sim(OAK)
        ecology = sim.ecology
        self._stand(sim, "spec_test_oak", 400.0, 64.0, 5.0, 0.8, height=20.0)
        self.assertIsNone(ecology._season_canopies)
        with ecology.canopies_held():
            held = ecology._season_canopies
            self.assertEqual(len(held), 1)
            with ecology.canopies_held():  # asked again inside: the same picture, not released early
                self.assertIs(ecology._season_canopies, held)
            self.assertIs(ecology._season_canopies, held)
            self.assertIs(ecology.canopy_footprints(), held)
        self.assertIsNone(ecology._season_canopies)
        with self.assertRaises(RuntimeError):
            with ecology.canopies_held():
                raise RuntimeError("stop")
        self.assertIsNone(ecology._season_canopies)

    def test_landscape_plants_are_drawn_to_scale_and_fade_to_cover_from_afar(self):
        height_for = BiosphereBuilderRenderer._target_height_for
        tree = {"growth_form": "tree", "abundance": 1.0}
        forb = {"growth_form": "forb", "abundance": 1.0}
        symbol = SimpleNamespace(zoom=10.0, sprite_height_cap=84)
        landscape = SimpleNamespace(zoom=10.0, sprite_height_cap=320, true_scale=True)
        self.assertEqual(height_for(20.0, tree, symbol, 1.0), 84)       # a map symbol stops at its cap
        self.assertEqual(height_for(20.0, tree, landscape, 1.0), 220)   # 20 m at 10 px/m, at full cover
        # A small plant is drawn at most half as tall again as it is: beside a tree drawn true it stays a herb.
        self.assertEqual(height_for(0.5, forb, landscape, 1.0), 9)
        far = SimpleNamespace(zoom=1.0, sprite_height_cap=320, true_scale=True)
        self.assertEqual(height_for(0.5, forb, SimpleNamespace(zoom=1.0, sprite_height_cap=84), 1.0), 22)
        self.assertLessEqual(height_for(0.5, forb, far, 1.0), 8)        # from afar it shrinks towards its real size
        self.assertLess(height_for(0.5, forb, far, 1.0), height_for(20.0, tree, far, 1.0))

    def test_a_stand_of_trees_is_the_plants_its_ground_has_room_for_in_any_view(self):
        from simulations.biosphere.vegetation import VegetationSampler

        sim = self._sim(OAK)
        stand = self._stand(sim, "spec_test_oak", 400.0, 64.0, 4.5, 0.9, height=40.0)
        self.assertEqual(sim.ecology.summary()["species"][0]["individuals"], 1)  # a 40 m tree needs about 11 m
        self.assertGreater(stand.radius_m, 4.5)  # and its stand is at least the ground it takes
        sampler = VegetationSampler()
        symbols = sampler.sample(sim.ecology, [])
        to_scale = sampler.sample(sim.ecology, [], true_scale=True)
        # The plants are recorded, not sampled: a view shows the one there is, whatever its scale.
        self.assertEqual(len(to_scale), 1)
        self.assertEqual([(plant["x"], plant["y"]) for plant in symbols], [(plant["x"], plant["y"]) for plant in to_scale])
        self.assertEqual(sampler.sample(sim.ecology, [], true_scale=True), to_scale)

    def test_display_abundance_for_many_points_equals_the_point_by_point_answer(self):
        import random

        from simulations.biosphere.vegetation import population_abundances

        sim = self._sim(OAK)
        sim._set_domain({"min_x": 340.0, "max_x": 460.0, "min_y": 10.0, "max_y": 118.0})
        ecology = sim.ecology
        self._stand(sim, "spec_test_oak", 400.0, 64.0, 18.0, 1.0, height=20.0)          # a closed canopy,
        self._stand(sim, "spec_test_oak", 402.0, 66.0, 18.0, 1.0)                       # two crowns deep
        self._stand(sim, "spec_lolium_perenne", 395.0, 60.0, 25.0, 0.6, mature=False)   # seedlings, some under it
        old = self._stand(sim, "spec_lolium_perenne", 415.0, 70.0, 12.0, 0.5)           # matured before the oak grew
        old.establishment_canopies = ()
        shaded = self._stand(sim, "spec_lolium_perenne", 405.0, 58.0, 9.0, 0.7)          # matured under it
        shaded.establishment_canopies = tuple(dict(canopy) for canopy in ecology.canopy_footprints())
        self.assertGreater(ecology.profiles["spec_lolium_perenne"].light_minimum, 0.0)
        rng = random.Random(3)
        points = [(rng.uniform(345.0, 455.0), rng.uniform(15.0, 113.0)) for _ in range(400)]
        for species_id in ("spec_lolium_perenne", "spec_test_oak"):
            together = population_abundances(ecology, species_id, [x for x, _y in points], [y for _x, y in points])
            one_by_one = [ecology.abundance_at(species_id, x, y, habitat_checked=True) for x, y in points]
            self.assertEqual(len(together), len(points))
            for a, b in zip(together.tolist(), one_by_one):
                self.assertAlmostEqual(a, b, places=12)
            self.assertGreater(max(one_by_one), 0.3)
        # The shade matters in this scene: seedlings fail under the oaks and take beside them.
        self.assertLess(ecology.recruitment_at("spec_lolium_perenne", 401.0, 65.0), 0.5)
        self.assertEqual(ecology.recruitment_at("spec_lolium_perenne", 372.0, 50.0), 1.0)

    def test_a_close_view_spends_the_display_budget_on_the_ground_it_shows(self):
        import random

        from simulations.biosphere.vegetation import VegetationSampler

        sim = self._sim()
        sim._set_domain({"min_x": 40.0, "max_x": 500.0, "min_y": 10.0, "max_y": 250.0})
        rng = random.Random(5)
        for index in range(40):
            self._stand(sim, "spec_lolium_perenne", rng.uniform(80.0, 460.0), rng.uniform(40.0, 220.0), 40.0, 0.8)
        self._stand(sim, "spec_lolium_perenne", 400.0, 64.0, 40.0, 0.8)
        sampler = VegetationSampler()
        near = lambda plants: [p for p in plants if abs(p["x"] - 400.0) <= 6.0 and abs(p["y"] - 64.0) <= 6.0]
        whole_site = sampler.sample(sim.ecology, [], true_scale=True)
        # A 24 m diamond around the point, in x - y and x + y.
        window = (400.0 - 64.0 - 12.0, 400.0 - 64.0 + 12.0, 400.0 + 64.0 - 12.0, 400.0 + 64.0 + 12.0)
        close = sampler.sample(sim.ecology, [], true_scale=True, window=window)
        self.assertGreater(len(near(close)), 8 * max(1, len(near(whole_site))))
        for plant in close:
            self.assertTrue(window[0] - 1.0 <= plant["x"] - plant["y"] <= window[1] + 1.0)
            self.assertTrue(window[2] - 1.0 <= plant["x"] + plant["y"] <= window[3] + 1.0)
        self.assertEqual(sampler.sample(sim.ecology, [], true_scale=True, window=window), close)
        # The canopy picture pinned for the sampling is released again.
        self.assertIsNone(sim.ecology._season_canopies)

    def test_the_plant_window_covers_the_screen_and_holds_still_under_a_small_pan(self):
        sim = self._sim()
        sim._set_domain({"min_x": 200.0, "max_x": 500.0, "min_y": 10.0, "max_y": 250.0})
        sim.isometric_view_zoom = 6.0
        renderer = BiosphereBuilderRenderer(SimpleNamespace())
        screen = pygame.Surface((1600, 900))
        renderer.draw(screen, sim)
        state = sim._isometric_projection_state
        window = renderer._vegetation_window(screen, state)
        for corner in ((0, 0), (1600, 0), (0, 900), (1600, 900), (800, 450)):
            x, y = state["substrate"].ground_screen_to_world(state, corner)
            self.assertTrue(window[0] <= x - y <= window[1], corner)
            self.assertTrue(window[2] <= x + y <= window[3], corner)
        # Not much larger than the ground whose plants can reach the screen (a tree stands on its lower edge and
        # is drawn at its size): the budget is not spent on ground out of sight.
        side, above, below = renderer._plant_reach(state)
        self.assertLess(window[1] - window[0], 1.7 * (1600 + 2 * side) / state["scale"])
        self.assertLess(window[3] - window[2], 1.8 * (900 + above + below) / (state["scale"] * 0.5))  # this ground also rises
        self.assertEqual(renderer._vegetation_window(screen, dict(state)), window)
        moved = dict(state, center_x=state["center_x"] + 0.5, center_y=state["center_y"] + 0.5)
        self.assertEqual(renderer._vegetation_window(screen, moved)[:2], window[:2])  # x - y did not change at all
        sizes = {round(renderer._vegetation_window(screen, dict(state, center_x=state["center_x"] + step))[1]
                       - renderer._vegetation_window(screen, dict(state, center_x=state["center_x"] + step))[0], 6)
                 for step in (0.0, 3.0, 7.0, 11.0, 19.0)}
        self.assertEqual(len(sizes), 1)  # one size per zoom: panning never changes the density

    def test_the_soil_tint_lies_on_the_ground_and_fades_in_at_its_edge(self):
        import numpy as np

        sim = self._sim()
        sim.isometric_view_zoom = 0.2
        renderer = BiosphereBuilderRenderer(SimpleNamespace())
        screen = pygame.Surface((800, 600))
        renderer.draw(screen, sim)
        state = sim._isometric_projection_state
        barren = tuple(screen.get_at((round(state["origin_x"]), round(state["origin_y"]))))[:3]

        world_x, world_y = renderer._ground_world_map(screen.get_size(), state, 4)
        row, column = round(state["origin_y"]) // 4, round(state["origin_x"]) // 4
        # The pixel at the projection origin looks at the view centre's own ground.
        self.assertAlmostEqual(world_x[row, column], state["center_x"], delta=4.0 / state["scale"])
        self.assertAlmostEqual(world_y[row, column], state["center_y"], delta=4.0 / state["scale"])

        soil = sim.soil
        soil.organic_matter_rows = [[2.0] * soil.columns for _ in range(soil.rows)]
        soil.revision += 1
        inside = renderer._sample_soil(soil, soil.organic_matter_rows, np.array([400.0]), np.array([64.0]))
        outside = renderer._sample_soil(soil, soil.organic_matter_rows, np.array([300.0]), np.array([64.0]))
        self.assertEqual((float(inside[0]), float(outside[0])), (2.0, 0.0))
        renderer.draw(screen, sim)
        tinted = tuple(screen.get_at((round(state["origin_x"]), round(state["origin_y"]))))[:3]
        self.assertNotEqual(tinted, barren)
        far_x, far_y = BiosphereBuilderRenderer._iso(state, 440.0, 64.0)
        if screen.get_rect().collidepoint(far_x, far_y):
            before = renderer._render_generated_ground(screen.get_size(), state["substrate"], state, renderer.GROUND_CELL_PX)
            self.assertEqual(tuple(screen.get_at((round(far_x), round(far_y))))[:3],
                             tuple(before.get_at((round(far_x), round(far_y))))[:3])  # beyond the soil: untouched

    def test_the_hud_speaks_in_tonnes_hectares_and_a_scale_bar(self):
        ui = UIManager()
        self.assertEqual([ui._biosphere_mass_label(v) for v in (0.0, 18.72, 556.2, 5767.0, 142185.0)],
                         ["0.0 kg", "18.7 kg", "556 kg", "5.8 t", "142 t"])
        self.assertEqual([ui._biosphere_area_label(v) for v in (10.5, 384.2, 61490.0)], ["10.5 m²", "384 m²", "6.15 ha"])
        self.assertEqual(ui._biosphere_scale_bar(2.59), (130, "50 m"))
        self.assertEqual(ui._biosphere_scale_bar(70.0)[1], "2 m")
        self.assertEqual(ui._biosphere_scale_bar(0.05)[1], "2 km")

        sim = self._sim()
        self._stand(sim, "spec_biomasser_13b", 400.0, 64.0, 3.0, 0.8)
        BiosphereBuilderRenderer(SimpleNamespace()).draw(pygame.Surface((1600, 900)), sim)
        scale, across = sim.get_view_scale()
        self.assertAlmostEqual(scale, sim._isometric_projection_state["scale"] * 2 ** 0.5)
        ui.rebuild_for_state(sim, 1600, 900, camera=None, world_model=sim.world_model)
        rows = [button for button in ui.buttons if button.id.startswith("biosphere_focus_population:")]
        self.assertEqual([button.population_row["label"] for button in rows], ["Biomasser 13B"])
        self.assertFalse(any(button.id.startswith("biosphere_select_representative:") for button in ui.buttons))
        ui.draw(pygame.Surface((1600, 900)), pygame.font.SysFont("consolas", 16))
        self.assertTrue(sim.draws_own_scale)

        from engine.window import SimWindow

        # The engine's bar measures the Map camera; a view with its own scale is left alone.
        engine = SimpleNamespace(get_active_simulation=lambda: sim)
        self.assertIsNone(SimWindow._draw_scale_bar(engine))


ROWAN = {"id": "spec_test_rowan", "_dataset": "species", "type": "species", "pretty_name": "Rowan - Sorbus aucuparia",
         "plant_growth_form": "tree", "moisture_preference": "moist",
         "maturity_age": {"typical_years": 15.0}, "longevity": {"typical_years": 80.0, "max_years": 150.0}}
POPPY = {"id": "spec_test_poppy", "_dataset": "species", "type": "species", "pretty_name": "Field Poppy",
         "plant_growth_form": "forb", "plant_lifespan": "annual"}


class LifeTimingTests(unittest.TestCase):
    """Real years to grow up and to live: authored where known, generic by class where not."""

    def setUp(self):
        pygame.init()
        pygame.font.init()

    def _timing(self, **entity):
        from simulations.species.plant_assets import PlantBlueprint
        from simulations.species.plant_life_timing import resolve_plant_life_timing

        entity = {"id": "spec_timing", **entity}
        return resolve_plant_life_timing(entity, PlantBlueprint.from_species_entity(entity, entity["id"]).growth)

    def _sim(self, *extra):
        world = _world(*extra)
        site = terrain_site.found_biosphere_site(world, REGION_ID, _region_point(400.0, 64.0), year=2400)
        return BiosphereSimulation(world, {"patch_location_id": site["id"], "year": 2400})

    def test_an_authored_figure_wins_and_a_missing_one_is_derived_from_the_species_classes(self):
        years = lambda timing: (round(timing.maturity_days / 365.25, 2), round(timing.lifespan_days / 365.25, 1))
        authored = self._timing(**{key: ROWAN[key] for key in ("plant_growth_form", "maturity_age", "longevity")})
        self.assertEqual(years(authored), (15.0, 80.0))
        self.assertEqual((authored.maturity_source, authored.lifespan_source), ("authored", "authored"))

        # Nothing authored but the form: the generic tree sets seed at 20 and is full-grown at a fifth of its life.
        tree = self._timing(plant_growth_form="tree")
        self.assertEqual(years(tree), (30.0, 150.0))
        self.assertAlmostEqual(tree.seed_days / 365.25, 20.0)
        slow = self._timing(plant_growth_form="tree", maturity_rate="slow", longevity_class="very_long")
        self.assertEqual(years(slow), (120.0, 600.0))
        self.assertAlmostEqual(slow.seed_days / 365.25, 40.0)
        # Where a fifth of its life comes before it sets seed, it is full-grown when it does.
        early = self._timing(plant_growth_form="tree", maturity_rate="slow")
        self.assertEqual(years(early), (40.0, 150.0))
        self.assertEqual(early.seed_days, early.maturity_days)
        self.assertEqual(slow.maturity_source, "generic for a slow-maturing tree")
        self.assertEqual(slow.lifespan_source, "generic for a very long-lived tree")
        self.assertEqual(years(self._timing(plant_growth_form="shrub", maturity_rate="fast", longevity_class="short")), (3.0, 15.0))
        # One figure authored, the other derived.
        mixed = self._timing(plant_growth_form="tree", maturity_age={"typical_years": 8}, longevity_class="short")
        self.assertEqual((years(mixed), mixed.maturity_source, mixed.lifespan_source),
                         ((8.0, 75.0), "authored", "generic for a short-lived tree"))
        # A class the tables do not know leaves the generic figure for the form.
        self.assertEqual(years(self._timing(plant_growth_form="shrub", maturity_rate="other_unknown")), (6.0, 30.0))

    def test_herbs_and_crusts_keep_the_season_or_two_their_own_clock_gives_them(self):
        grass = self._timing(plant_growth_form="graminoid", plant_lifespan="perennial", maturity_rate="fast")
        self.assertAlmostEqual(grass.maturity_days, 60.0)
        self.assertAlmostEqual(grass.lifespan_days / 365.25, 8.0)
        self.assertTrue(grass.real_clock)
        short = self._timing(plant_growth_form="graminoid", plant_lifespan="short_lived_perennial", longevity_class="short")
        self.assertAlmostEqual(short.lifespan_days / 365.25, 3.0)
        # A cycle that ends with reproduction already runs in real days.
        poppy = self._timing(plant_growth_form="forb", plant_lifespan="annual")
        self.assertFalse(poppy.real_clock)
        self.assertEqual(poppy.lifespan_days, 365.0)
        self.assertEqual(poppy.developmental_days(200.0), 200.0)
        self.assertEqual(poppy.maturity_source, "annual life cycle")

    def test_two_generic_figures_never_leave_a_plant_without_an_adult_life(self):
        odd = self._timing(plant_growth_form="tree", maturity_age={"typical_years": 90}, longevity={"typical_years": 60})
        self.assertGreaterEqual(odd.lifespan_days, odd.maturity_days * 1.5)
        self.assertGreater(odd.senescence_start_days, odd.maturity_days)

    def test_real_age_maps_onto_the_body_species_sim_grows(self):
        timing = self._timing(plant_growth_form="tree", maturity_rate="slow", longevity_class="very_long")
        year = 365.25
        grown, old, end = timing.developmental_maturity_days, timing.developmental_senescence_days, timing.developmental_end_days
        self.assertEqual(grown, 365.0)  # Species Sim's own slider
        self.assertAlmostEqual(timing.developmental_days(30 * year), grown * 0.25)
        self.assertAlmostEqual(timing.developmental_days(120 * year), grown)
        # Its life phases read on the real clock: adult when it sets seed, long before it is full-grown.
        history = timing.life_history_profile({})
        self.assertAlmostEqual(history["reproductive_start_days"] / year, 40.0)
        self.assertAlmostEqual(history["maturity_days"] / year, 40.0)
        self.assertAlmostEqual(timing.developmental_days(timing.senescence_start_days), old)
        self.assertAlmostEqual(timing.developmental_days(600 * year), end)
        self.assertEqual(timing.developmental_days(5000 * year), end)
        ages = [timing.developmental_days(years * year) for years in range(0, 700, 7)]
        self.assertEqual(ages, sorted(ages))
        # Senescence is the last fifth of the life after full size.
        self.assertAlmostEqual(timing.senescence_start_days / year, 120 + 0.8 * 480)

    def test_a_species_profile_carries_real_maturity_and_keeps_the_short_seedbed_stage(self):
        oak = profile_from_entity({"id": "spec_o", "plant_growth_form": "tree", "maturity_rate": "slow"})
        self.assertAlmostEqual(oak.maturity_days / 365.25, 40.0)
        self.assertEqual(oak.establishment_days, 365.0)
        self.assertEqual(oak.maturity_source, "generic for a slow-maturing tree")
        rowan = profile_from_entity(ROWAN)
        self.assertAlmostEqual(rowan.maturity_days / 365.25, 15.0)
        self.assertAlmostEqual(rowan.lifespan_days / 365.25, 80.0)
        self.assertEqual((rowan.maturity_source, rowan.lifespan_source), ("authored", "authored"))
        lichen = profile_from_entity(SPECIES[0])
        self.assertEqual(lichen.establishment_days, lichen.maturity_days)  # nothing to stretch

    def test_a_sown_wood_gains_height_and_biomass_over_years_and_sets_seed_only_when_grown(self):
        sim = self._sim(ROWAN)
        ecology = sim.ecology
        profile = ecology.profiles["spec_test_rowan"]
        sim._set_domain({"min_x": 340.0, "max_x": 460.0, "min_y": 10.0, "max_y": 118.0})
        soil = sim.soil
        soil.organic_matter_rows = [[6.0] * soil.columns for _ in range(soil.rows)]
        soil.revision += 1
        stand = ecology._new_patch("spec_test_rowan", 400.0, 64.0, 10.0, 0.6, 0, "wood")
        self.assertEqual(ecology.stature_share(stand), ecology.JUVENILE_BIOMASS_SHARE)  # seedlings weigh next to nothing
        stand.development_days = ecology.establishment_days(profile)  # past the seedbed stage
        young_biomass = ecology.summary()["living_biomass_kg"]
        radius_before = stand.radius_m

        def five_years():
            for _ in range(4 * 5):
                stand.abundance = 0.8  # dense enough to throw founders, if it sets seed at all
                ecology.advance(1)

        five_years()
        self.assertAlmostEqual(ecology._stature_m(stand) / profile.mature_height_m, (5.0 + ecology.establishment_days(profile) / 365.25) / 15.0, delta=0.01)
        self.assertEqual(len(ecology.species_patches("spec_test_rowan")), 1)  # no seed yet
        creep = stand.radius_m - radius_before
        self.assertGreater(creep, 0.0)
        self.assertGreater(ecology.summary()["living_biomass_kg"], 5 * young_biomass)

        stand.development_days = profile.maturity_days  # grown
        full = math.pi * stand.radius_m ** 2 * stand.abundance * profile.carrying_biomass_kg_m2
        # The founding cohort stands full-grown; the seedlings that rooted among it since do not yet.
        self.assertLessEqual(ecology.summary()["living_biomass_kg"], full * (1.0 + 1e-6))
        self.assertGreater(ecology.summary()["living_biomass_kg"], full * 0.85)
        radius_before = stand.radius_m
        five_years()
        self.assertGreater(len(ecology.species_patches("spec_test_rowan")), 1)  # founders
        founders = [patch for patch in ecology.species_patches("spec_test_rowan") if patch is not stand]
        self.assertTrue(all(patch.development_days < profile.maturity_days for patch in founders))
        # A stand that sets seed advances its front at the full rate: four times the creep.
        self.assertGreater(stand.radius_m - radius_before, 2.5 * creep)

    def test_litter_follows_the_height_a_stand_has_reached(self):
        import numpy as np

        sim = self._sim(ROWAN)
        ecology, soil = sim.ecology, sim.soil
        stand = ecology._new_patch("spec_test_rowan", 400.0, 64.0, 3.0, 0.6, 0, "wood")
        shape = (soil.rows, soil.columns)
        cell_x = soil.bounds["min_x"] + (np.arange(soil.columns) + 0.5) * soil.width / soil.columns
        cell_y = soil.bounds["min_y"] + (np.arange(soil.rows) + 0.5) * soil.height / soil.rows
        seedlings = soil._patch_inputs(ecology, shape, cell_x, cell_y)
        stand.development_days = ecology.profiles["spec_test_rowan"].maturity_days
        grown = soil._patch_inputs(ecology, shape, cell_x, cell_y)
        self.assertAlmostEqual(float(seedlings["litter"].sum()) / float(grown["litter"].sum()), ecology.JUVENILE_BIOMASS_SHARE)
        self.assertAlmostEqual(float(seedlings["cover"].sum()), float(grown["cover"].sum()))  # the ground covered is the same

    def test_an_organism_is_a_sapling_for_years_and_is_not_counted_as_sick_for_it(self):
        sim = self._sim(ROWAN)
        self.assertEqual(sim.ecology.profiles["spec_test_rowan"].maturity_source, "authored")
        manager = sim.representatives
        organism = manager._new_representative("spec_test_rowan", 400.0, 64.0)
        body = organism.simulation
        year = 365.25
        environment = {"water_stress": 0.1, "light_stress": 0.0, "temperature_stress": 0.0, "competition": 0.1}

        manager.grow_body(organism, 5 * year)
        self.assertEqual(body.life_state()["phase"], "juvenile")
        self.assertAlmostEqual(body.render_snapshot.stats["maturity"], 5.0 / 15.0, places=3)
        sapling_height = body.render_snapshot.bounds_m[5]
        sapling = manager.condition(organism, environment)
        self.assertAlmostEqual(sapling["maturity"], 0.3333, places=3)
        self.assertEqual(sapling["fecundity"], 0.0)
        # Species Sim's own reading scales with size; the organism's condition does not.
        self.assertLess(body.get_ecological_outcome(environment)["vitality"], 0.5 * sapling["vitality"])
        self.assertAlmostEqual(body.render_snapshot.stats["maturity"], 5.0 / 15.0, places=3)  # the body itself is left as grown

        manager.grow_body(organism, 30 * year)
        self.assertEqual(body.render_snapshot.stats["maturity"], 1.0)
        self.assertGreater(body.render_snapshot.bounds_m[5], 2.0 * sapling_height)
        adult = manager.condition(organism, environment)
        self.assertNotIn(adult["life_history"]["phase"], ("juvenile", "senescent", "dead"))
        self.assertAlmostEqual(adult["vitality"], sapling["vitality"], delta=0.02)
        self.assertGreater(adult["fecundity"], 0.0)

        manager.grow_body(organism, 78 * year)  # the last fifth of its adult life
        elder = manager.condition(organism, environment)
        self.assertEqual(elder["life_history"]["phase"], "senescent")
        self.assertLess(elder["vitality"], adult["vitality"])
        # The unmodified Species Sim rules, on its own clock, are untouched.
        from simulations.species.species_simulation import SpeciesSimulation

        plain = SpeciesSimulation(world_model=sim.world_model, species_id="spec_test_rowan", seed=1)
        self.assertLess(plain.mature_age_days, 400.0)

    def test_an_individual_dies_of_old_age_and_the_stand_goes_on(self):
        sim = self._sim()
        sward = sim.ecology._new_patch("spec_lolium_perenne", 400.0, 64.0, 1.5, 0.8, 0, "sward")
        sward.development_days = sim.ecology.profiles["spec_lolium_perenne"].maturity_days
        sim.soil.organic_matter_rows = [[2.0] * sim.soil.columns for _ in range(sim.soil.rows)]
        sim.soil.revision += 1
        manager = sim.representatives
        manager.sync_from_population(sim.ecology)
        organisms = manager.items(alive_only=True)
        spans = [manager.lifespan_days(organism) / 365.25 for organism in organisms]
        # The generic herb lives eight years; individuals between three quarters of that and all of it.
        self.assertTrue(all(6.0 - 1e-6 <= span <= 8.0 + 1e-6 for span in spans), spans)
        oldest = max(organisms, key=manager.lifespan_days)
        for organism in organisms:
            manager.grow_body(organism, manager.lifespan_days(organism) - 2 * manager.DAYS_PER_SEASON)
            organism.health = 0.9
        for _ in range(3):
            for organism in organisms:
                organism.health = max(organism.health, 0.5)
            sim.advance_seasons(1)
        self.assertTrue(all(not organism.alive and organism.death_cause == "old age" for organism in organisms))
        self.assertGreater(len(sim.ecology.species_patches("spec_lolium_perenne")), 0)
        heirs = manager.items("spec_lolium_perenne", alive_only=True)
        self.assertGreaterEqual(len(heirs), 3)
        self.assertTrue(all(heir.age_days < 2 * 365.25 for heir in heirs))
        self.assertNotIn(oldest.representative_id, [heir.representative_id for heir in heirs])
        # An annual ends itself; it has no age limit of this kind.
        world = _world(POPPY)
        other = RepresentativePopulationManagerProbe(world)
        self.assertEqual(other.lifespan_days(other._new_representative("spec_test_poppy", 0.0, 0.0)), math.inf)

    def test_the_player_is_told_that_a_wood_takes_years_and_when_it_starts_to_seed(self):
        sim = self._sim(ROWAN)
        soil = sim.soil
        soil.organic_matter_rows = [[6.0] * soil.columns for _ in range(soil.rows)]
        soil.revision += 1
        sim.select_species("spec_test_rowan")
        sim.place_selected_species(400.0, 64.0)
        self.assertEqual(sim.get_field_notes(1)[0]["text"], "Introduced Rowan; full size in about 15 years")
        sim.select_species("spec_lolium_perenne")
        sim.place_selected_species(402.0, 66.0)
        self.assertEqual(sim.get_field_notes(1)[0]["text"], "Introduced Perennial Ryegrass")  # a season: not worth saying

        wood = sim.ecology.species_patches("spec_test_rowan")[0]
        profile = sim.ecology.profiles["spec_test_rowan"]
        extent = (sim.bounds["max_x"] - sim.bounds["min_x"], sim.bounds["max_y"] - sim.bounds["min_y"])
        season = lambda: sim._record_season_outcomes(sim._population_centres(), extent, sim._population_pressures())
        wood.development_days = profile.maturity_days * 0.4
        season()
        row = next(row for row in sim.get_population_rows() if row["species_id"] == "spec_test_rowan")
        self.assertAlmostEqual(row["height_m"], profile.mature_height_m * 0.4)
        self.assertFalse(any("sets seed" in note["text"] for note in sim.field_notes))
        wood.development_days = profile.maturity_days
        season()
        season()
        seeding = [note["text"] for note in sim.field_notes if "sets seed" in note["text"]]
        self.assertEqual(seeding, ["Rowan is full-grown and sets seed"])  # said once, and never for the grass

        ui = UIManager()
        BiosphereBuilderRenderer(SimpleNamespace()).draw(pygame.Surface((1600, 900)), sim)
        ui.rebuild_for_state(sim, 1600, 900, camera=None, world_model=sim.world_model)
        ui.draw(pygame.Surface((1600, 900)), pygame.font.SysFont("consolas", 16))
        rows = {button.population_row["label"]: button.population_row for button in ui.buttons
                if button.id.startswith("biosphere_focus_population:")}
        self.assertGreater(rows["Rowan"]["height_m"], 1.0)

    def test_the_catalogue_says_how_long_a_species_takes_and_where_the_figure_comes_from(self):
        sim = self._sim(ROWAN, OAK)
        sim.open_species_picker()
        items = {item["id"]: item for item in sim.get_species_catalog_items()}
        rowan, oak = items["spec_test_rowan"]["trait_lines"], items["spec_test_oak"]["trait_lines"]
        self.assertIn("Full size: about 15 years (authored)", rowan)
        self.assertIn("Lifespan: about 80 years (authored)", rowan)
        self.assertIn("Full size: about 30 years (generic)", oak)
        self.assertIn("Sets seed: from about 20 years (generic)", oak)
        self.assertFalse(any(line.startswith("Sets seed") for line in rowan))  # authored: seed and full size together
        self.assertIn("Lifespan: about 150 years (generic)", oak)
        lichen = items["spec_biomasser_13b"]["trait_lines"]
        self.assertTrue(any(line.startswith("Full size: about ") and "weeks" in line for line in lichen), lichen)
        # The profile keeps the whole derivation for anyone who asks where a generic figure came from.
        self.assertEqual(sim.ecology.profiles["spec_test_oak"].maturity_source, "generic for a tree")

    def test_the_trait_schema_carries_both_figures_and_the_authoring_tool_accepts_them(self):
        from tools.author_plant_species import _validate_schema_type
        from world.plant_traits import PLANT_TRAIT_BEHAVIOR_PATHS, PLANT_TRAIT_SCHEMA_FIELDS

        for key in ("maturity_age", "longevity"):
            self.assertEqual(PLANT_TRAIT_SCHEMA_FIELDS[key]["type"], "dict")
            self.assertTrue(PLANT_TRAIT_SCHEMA_FIELDS[key]["optional"])
            self.assertEqual(PLANT_TRAIT_BEHAVIOR_PATHS[key][0], "Growth")
        _validate_schema_type("maturity_age", {"typical_years": 15.0})
        _validate_schema_type("longevity", {"typical_years": 80.0, "max_years": 150.0})


class MapWiringTests(unittest.TestCase):
    def setUp(self):
        pygame.init()
        pygame.font.init()
        self.world = _world()

    def _map_sim(self, root_id=REGION_ID):
        return MapSimulation(SimulationContext(year=2400, root_entity_id=root_id, world_model=self.world))

    def _click(self, sim, map_point, button=1):
        event = SimpleNamespace(type=sim.MOUSEBUTTONDOWN_EVENT_TYPE, button=button)
        camera = SimpleNamespace(x=0.0, y=0.0, zoom=1.0, width=1600, height=900,
                                 screen_to_world=lambda pos: pos, world_to_screen=lambda pos: pos)
        with mock.patch.object(sim, "_screen_to_world", return_value=map_point):
            sim.handle_pointer_event(event, camera, (0, 0))

    def test_a_region_map_offers_a_start_and_a_click_on_dry_ground_founds_the_site(self):
        sim = self._map_sim()
        self.assertEqual(sim.get_biosphere_start_action(), {"label": "Start Biosphere Here", "enabled": True})
        self.assertTrue(sim.begin_biosphere_start_pick())
        self.assertTrue(sim.is_map_editor_active())
        self.assertFalse(sim.can_finish_map_editor())
        self.assertIn("click the ground", sim.get_map_editor_status_label())

        self._click(sim, _region_point(8.0, 100.0))  # open water
        self.assertTrue(sim.is_picking_biosphere_start)
        self.assertIn("open water", sim.get_map_editor_status_label())
        self.assertIsNone(sim.consume_pending_navigation_action())
        self.assertEqual(terrain_site.sites_on_region(self.world, REGION_ID), [])

        self._click(sim, _region_point(300.0, 100.0))
        self.assertFalse(sim.is_picking_biosphere_start)
        sites = terrain_site.sites_on_region(self.world, REGION_ID)
        self.assertEqual(len(sites), 1)
        self.assertAlmostEqual(sites[0]["biosphere_founding_point_local_m"][0], 300.0, places=2)
        self.assertEqual(sim.consume_pending_navigation_action(), f"open_biosphere_site:{sites[0]['id']}")
        self.assertIsNone(sim.consume_pending_navigation_action())

    def test_escape_and_right_click_leave_the_pick_without_founding(self):
        sim = self._map_sim()
        sim.begin_biosphere_start_pick()
        self._click(sim, _region_point(300.0, 100.0), button=3)
        self.assertFalse(sim.is_picking_biosphere_start)
        sim.begin_biosphere_start_pick()
        self.assertTrue(sim.cancel_map_editor())
        self.assertFalse(sim.is_map_editor_active())
        self.assertEqual(terrain_site.sites_on_region(self.world, REGION_ID), [])

    def test_coarse_maps_say_what_is_missing_and_ordinary_maps_offer_nothing(self):
        coarse = _region("refined_lod3_coarse")
        coarse["heightmap_model"].update(region_width_m=20_000.0, region_height_m=10_000.0)
        self.world.loader.persist_entity(coarse)
        self.world.loader.persist_entity({"id": "loc_plain", "_dataset": "locations", "type": "location",
                                          "location_class": "region", "name": "Plain",
                                          "bounds": {"type": "bbox", "min_x": 0, "max_x": 1, "min_y": 0, "max_y": 1}})
        self.assertEqual(
            self._map_sim("refined_lod3_coarse").get_biosphere_start_action(),
            {"label": "Start Biosphere: refine to Site first", "enabled": False},
        )
        self.assertIsNone(self._map_sim("loc_plain").get_biosphere_start_action())

    def test_the_sidebar_shows_the_start_and_the_site_is_drawn_on_its_region(self):
        sim = self._map_sim()
        ui = UIManager()
        ui.rebuild_for_state(sim, 1600, 900, camera=None)
        button = next(button for button in ui.buttons if button.id == "start_biosphere_here")
        self.assertEqual((button.label, button.enabled), ("Start Biosphere Here", True))

        site = terrain_site.found_biosphere_site(self.world, REGION_ID, _region_point(300.0, 100.0))
        sim._invalidate_layer_cache()
        linked = [entity["id"] for entity, _footprint in sim._terrain_linked_locations()]
        self.assertEqual(linked, [site["id"]])
        sim.selected_entity_id = site["id"]
        payload = sim.get_selection_inspector_payload()
        self.assertEqual(payload["actions"][0], {"id": "open_region_map", "label": "Open Biosphere"})

    def test_navigation_arms_the_pick_and_opens_the_founded_site_as_a_biosphere(self):
        sim = self._map_sim()
        tabs = SimpleNamespace(tabs=[], active_index=0, add_tab=lambda tab: tabs.tabs.append(tab))
        app = SimpleNamespace(
            world_model=self.world, tab_manager=tabs, knowledge_layer_active=True,
            get_active_simulation=lambda: sim, camera=SimpleNamespace(),
            camera_controller=SimpleNamespace(setup_for_sim=lambda _sim: None),
            _render_frame=lambda: None,
        )
        navigation = NavigationController(app)
        navigation.focus_existing_tab_by_key = lambda _key: False

        self.assertTrue(navigation.handle_ui_action("start_biosphere_here", sim))
        self.assertTrue(sim.is_picking_biosphere_start)
        self._click(sim, _region_point(300.0, 100.0))
        action = sim.consume_pending_navigation_action()
        self.assertTrue(navigation.handle_ui_action(action, sim))

        self.assertEqual(len(tabs.tabs), 1)
        biosphere = tabs.tabs[0].sim_instance.simulation
        self.assertIsInstance(biosphere, BiosphereSimulation)
        self.assertEqual(tabs.tabs[0].name, "Biosphere: Biosphere 1")
        self.assertIsNotNone(biosphere.terrain)
        self.assertTrue(biosphere.auto_resolve_terrain)
        self.assertTrue(callable(biosphere.terrain_redraw))
        # Opening the site again from a map goes to the Biosphere, not to a flat map of it.
        opened = []
        navigation.launch_biosphere_tab = lambda entity_id: opened.append(entity_id) or True
        navigation.open_region_map_tab(biosphere.context.root_entity_id)
        self.assertEqual(opened, [biosphere.context.root_entity_id])


if __name__ == "__main__":
    unittest.main()
