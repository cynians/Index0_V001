import os
import unittest
from types import SimpleNamespace

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame

from app.navigation_controller import NavigationController
from simulations.city import city_site
from simulations.map.map_simulation import MapSimulation
from tests.test_blueprint_designer import BlueprintWorld
from tests.test_blueprint_placement import _PlacementFixture
from ui.ui_manager import UIManager
from world.simulation_context import SimulationContext


REGION_WIDTH_M = 2000.0
REGION_HEIGHT_M = 1500.0


def _region(region_id="refined_lod4_fixture", width_m=REGION_WIDTH_M, height_m=REGION_HEIGHT_M):
    # Elevation rises 10 m per column and 100 m per row, so a sample names
    # its own grid position.
    rows = [[100.0 * row + 10.0 * column for column in range(5)] for row in range(4)]
    return {
        "id": region_id, "_dataset": "locations", "type": "location",
        "name": "Fixture Site Patch", "location_class": "generated_region",
        "location_role": "map_refinement_region", "map_detail_level": 4,
        "map_detail_profile": {"id": "site", "label": "Site"},
        "refinement_root_planet_id": "planet_fixture",
        # Parent-map coordinates: nothing like metres.
        "bounds": {"type": "bbox", "min_x": 17.1, "max_x": 17.3, "min_y": 25.4, "max_y": 25.55},
        "display_color": [90, 100, 80],
        "heightmap_model": {
            "region_width_m": width_m, "region_height_m": height_m,
            "min_elevation_m": 0.0, "max_elevation_m": 340.0, "sea_level_m": -50.0,
            "source_heightfield_fingerprint": "fixture-a",
            "sample_grid": {"width": 5, "height": 4, "rows": rows},
        },
    }


class CityFoundingTests(unittest.TestCase):
    def setUp(self):
        self.world = BlueprintWorld([_region()])

    def test_only_walkable_refined_regions_can_be_founded_on(self):
        self.assertEqual(city_site.founding_report(_region()), (True, ""))
        self.assertFalse(city_site.founding_report(None)[0])
        self.assertFalse(city_site.founding_report({"id": "planet", "location_class": "planet"})[0])
        too_wide = _region(width_m=95_000.0, height_m=53_000.0)
        can_found, reason = city_site.founding_report(too_wide)
        self.assertFalse(can_found)
        self.assertEqual(reason, "refine below 30 km")
        self.assertFalse(city_site.founding_report(_region(width_m=40.0, height_m=40.0))[0])
        bare = _region()
        bare["heightmap_model"] = {"region_width_m": 2000.0, "region_height_m": 1500.0}
        self.assertFalse(city_site.founding_report(bare)[0])

    def test_a_city_is_a_metre_frame_site_that_points_at_its_region(self):
        city = city_site.found_city(self.world, "refined_lod4_fixture", year=2400)

        self.assertIs(self.world.get_entity(city["id"]), city)
        self.assertEqual(city["location_class"], "city")
        self.assertEqual(city["map_coordinate_space"], "site_meters")
        self.assertEqual(city["bounds"], {
            "type": "bbox", "min_x": 0.0, "max_x": REGION_WIDTH_M, "min_y": 0.0, "max_y": REGION_HEIGHT_M,
        })
        self.assertEqual(city["terrain_source_map_id"], "refined_lod4_fixture")
        self.assertEqual(city["terrain_source_fingerprint"], "fixture-a")
        self.assertEqual(city["terrain_root_planet_id"], "planet_fixture")
        self.assertEqual(city["geographic_source_bounds"]["min_x"], 17.1)
        # A structural parent would draw these metre bounds in its own frame.
        self.assertNotIn("parent_location", city)
        self.assertNotIn("parents", city)
        # The region's rasters are read through the link, never copied.
        self.assertNotIn("heightmap_model", city)

    def test_founding_is_refused_where_it_cannot_work(self):
        self.assertIsNone(city_site.found_city(self.world, "missing"))
        city = city_site.found_city(self.world, "refined_lod4_fixture")
        self.assertIsNone(city_site.found_city(self.world, city["id"]))

    def test_substrate_samples_the_region_in_city_metres(self):
        city = city_site.found_city(self.world, "refined_lod4_fixture")
        substrate = city_site.city_substrate(self.world, city)

        self.assertAlmostEqual(substrate.elevation(0.0, 0.0), 0.0)
        self.assertAlmostEqual(substrate.elevation(REGION_WIDTH_M, REGION_HEIGHT_M), 340.0)
        # One column east (500 m) and one row south (500 m) of the origin.
        self.assertAlmostEqual(substrate.elevation(500.0, 500.0), 110.0)
        self.assertAlmostEqual(substrate.elevation(250.0, 0.0), 5.0)

    def test_regenerating_the_region_marks_the_city_terrain_stale(self):
        city = city_site.found_city(self.world, "refined_lod4_fixture")
        self.assertFalse(city_site.terrain_is_stale(self.world, city))
        region = self.world.get_entity("refined_lod4_fixture")
        region["heightmap_model"]["source_heightfield_fingerprint"] = "fixture-b"
        self.assertTrue(city_site.terrain_is_stale(self.world, city))


class CityMapTests(_PlacementFixture):
    def setUp(self):
        super().setUp()
        pygame.init()
        self.world = BlueprintWorld([_region(), self.blueprint_entity])

    def _map_sim(self, root_id):
        return MapSimulation(SimulationContext(year=2400, root_entity_id=root_id, world_model=self.world))

    def test_region_map_offers_founding_then_reopens_the_city(self):
        region_map = self._map_sim("refined_lod4_fixture")
        self.assertEqual(
            region_map.get_city_founding_action(),
            {"label": "Found City Here", "enabled": True, "city_id": None},
        )
        city_id = region_map.found_city()
        self.assertEqual(self.world.get_entity(city_id)["location_class"], "city")

        action = region_map.get_city_founding_action()
        self.assertEqual(action["city_id"], city_id)
        self.assertTrue(action["label"].startswith("Open "))
        self.assertEqual(region_map.found_city(), city_id)
        self.assertEqual(len(city_site.cities_on_region(self.world, "refined_lod4_fixture")), 1)

    def test_founding_is_not_offered_outside_refined_regions(self):
        city_id = self._map_sim("refined_lod4_fixture").found_city()
        self.assertIsNone(self._map_sim(city_id).get_city_founding_action())

    def test_oversized_region_shows_why_it_cannot_be_founded_on(self):
        self.world = BlueprintWorld([_region(width_m=95_000.0, height_m=53_000.0)])
        action = self._map_sim("refined_lod4_fixture").get_city_founding_action()
        self.assertFalse(action["enabled"])
        self.assertEqual(action["label"], "Found City: refine below 30 km")

    def test_city_map_is_in_metres_and_shows_the_region_terrain(self):
        city_id = self._map_sim("refined_lod4_fixture").found_city()
        city_map = self._map_sim(city_id)

        self.assertEqual(city_map.world_units_to_meters, 1.0)
        self.assertEqual(
            (city_map.bounds["max_x"] - city_map.bounds["min_x"], city_map.bounds["max_y"] - city_map.bounds["min_y"]),
            (REGION_WIDTH_M, REGION_HEIGHT_M),
        )
        region = self.world.get_entity("refined_lod4_fixture")
        self.assertIs(city_map._own_generated_region(city_map.get_root_entity()), region)

    def test_a_blueprint_can_be_placed_on_the_city(self):
        city_id = self._map_sim("refined_lod4_fixture").found_city()
        city_map = self._map_sim(city_id)
        self.assertTrue(city_map.begin_blueprint_placement("bp_hut"))
        # Camera centred 640 m east and 420 m south of the city origin.
        camera = SimpleNamespace(x=640.0, y=420.0, zoom=1.0, width=800, height=600,
                                 world_to_screen=lambda p: (p[0] - 240.0, p[1] - 120.0))
        screen_pos = (400, 300)
        city_map.handle_pointer_motion(
            pygame.event.Event(pygame.MOUSEMOTION, pos=screen_pos, rel=(0, 0), buttons=(0, 0, 0)), camera, screen_pos)
        city_map.handle_pointer_event(
            pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=screen_pos, button=1), camera, screen_pos)

        building = self.world.get_entity(city_map.selected_entity_id)
        self.assertEqual(building["building_blueprint"], "bp_hut")
        self.assertEqual(building["parent_location"], city_id)
        points = building["bounds"]["points"]
        centre_x = (min(p[0] for p in points) + max(p[0] for p in points)) / 2
        centre_y = (min(p[1] for p in points) + max(p[1] for p in points)) / 2
        self.assertAlmostEqual(centre_x, 640.0, places=3)
        self.assertAlmostEqual(centre_y, 420.0, places=3)
        # The building stands on ground the region supplies.
        ground = city_site.city_substrate(self.world, self.world.get_entity(city_id)).elevation(centre_x, centre_y)
        self.assertAlmostEqual(ground, 10.0 * (640.0 / 500.0) + 100.0 * (420.0 / 500.0), places=3)


def _parent_region():
    """The LOD3 map the fixture region was refined from; same planet frame."""
    parent = _region("refined_lod3_fixture", width_m=20_000.0, height_m=15_000.0)
    parent.update({
        "name": "Fixture Local Patch", "map_detail_level": 3,
        "map_detail_profile": {"id": "local", "label": "Local"},
        "bounds": {"type": "bbox", "min_x": 16.0, "max_x": 18.0, "min_y": 25.0, "max_y": 26.5},
    })
    return parent


class CityOnParentMapTests(unittest.TestCase):
    def setUp(self):
        pygame.init()
        region = _region()
        region["refinement_parent_map_id"] = "refined_lod3_fixture"
        region["parent_location"] = "refined_lod3_fixture"
        unrelated = _region("refined_lod4_elsewhere")
        self.world = BlueprintWorld([_parent_region(), region, unrelated])
        self.city = city_site.found_city(self.world, "refined_lod4_fixture", name="Harrowmouth")

    def _map_sim(self, root_id):
        return MapSimulation(SimulationContext(year=2400, root_entity_id=root_id, world_model=self.world))

    def _city_layers(self, sim):
        return [layer for layer in sim.get_layers() if layer.get("entity_id") == self.city["id"]]

    def test_the_region_and_its_ancestors_draw_the_city(self):
        for root_id in ("refined_lod4_fixture", "refined_lod3_fixture"):
            layers = self._city_layers(self._map_sim(root_id))
            marker = next(layer for layer in layers if layer["shape"] == "marker")
            # Centre of the region's footprint, in the planet's map frame.
            self.assertAlmostEqual(marker["x"], 17.2)
            self.assertAlmostEqual(marker["y"], 25.475)
            self.assertEqual(marker["name"], "Harrowmouth")
            self.assertEqual(marker["min_zoom"], 0.0)
            outline = next(layer for layer in layers if layer["shape"] == "polygon")
            self.assertTrue(outline["outline_only"])
            self.assertFalse(outline["pickable"])
            xs = [point[0] for point in outline["points"]]
            self.assertAlmostEqual(min(xs), 17.1)
            self.assertAlmostEqual(max(xs), 17.3)
            # Drawn once the 0.2-unit footprint spans 18 px.
            self.assertAlmostEqual(outline["min_zoom"], 18.0 / 0.2)

    def test_other_maps_do_not_draw_it(self):
        self.assertEqual(self._city_layers(self._map_sim("refined_lod4_elsewhere")), [])
        # On its own map the city is the root, not an overlay of itself.
        self.assertEqual(
            [layer for layer in self._city_layers(self._map_sim(self.city["id"])) if layer["shape"] == "marker"], [])

    def test_the_city_is_listed_and_selectable_from_the_parent_map(self):
        region_map = self._map_sim("refined_lod3_fixture")
        self.assertIn(self.city["id"], [item["id"] for item in region_map.get_location_layer_tree_items()])
        self.assertIn(self.city["id"], [item["id"] for item in region_map.get_map_location_browser_items()])

        camera = SimpleNamespace(zoom=400.0)
        picked = region_map._pick_layer_at_world(17.2, 25.475, camera)
        self.assertEqual(picked["entity_id"], self.city["id"])
        # 12 px at this zoom is 0.03 map units; the far corner is not the city.
        missed = region_map._pick_layer_at_world(16.1, 25.1, camera)
        self.assertNotEqual((missed or {}).get("entity_id"), self.city["id"])

    def test_the_planet_draws_it_but_the_star_system_does_not(self):
        system = {"id": "system_fixture", "_dataset": "locations", "type": "location",
                  "name": "Fixture System", "location_class": "star_system"}
        planet = {"id": "planet_fixture", "_dataset": "locations", "type": "location", "name": "Fixture Planet",
                  "location_class": "planet", "parent_location": "system_fixture",
                  "bounds": {"type": "bbox", "min_x": -180.0, "max_x": 180.0, "min_y": -90.0, "max_y": 90.0}}
        self.world.persist_entity(system)
        self.world.persist_entity(planet)
        self.world.get_entity("refined_lod3_fixture")["refinement_parent_map_id"] = "planet_fixture"

        self.assertIn("marker", [layer["shape"] for layer in self._city_layers(self._map_sim("planet_fixture"))])
        # The footprint is in the planet's surface coordinates, not the system's.
        self.assertEqual(self._city_layers(self._map_sim("system_fixture")), [])

    def test_a_refined_window_is_a_patch_not_its_parents_surface(self):
        # Refinement appends the child to the parent's constituents.
        parent = self.world.get_entity("refined_lod3_fixture")
        parent["constituents"] = ["refined_lod4_fixture"]
        parent_map = self._map_sim("refined_lod3_fixture")

        self.assertIsNone(parent_map._own_generated_region(parent_map.get_root_entity()))
        self.assertEqual(
            [model["entity_id"] for model in parent_map._refined_region_models()], ["refined_lod4_fixture"])

    def test_up_from_the_city_leads_to_its_region(self):
        city_map = self._map_sim(self.city["id"])
        self.assertEqual(city_map.get_parent_root_entity_id(), "refined_lod4_fixture")
        self.assertEqual(
            city_map.get_scope_breadcrumb(),
            # Refined regions are shown by level, not by their stacked stored names.
            ["Local", "Site", "Harrowmouth"],
        )


def _patch(patch_id="refined_lod5_fixture"):
    """A LOD5 patch covering the region's north-west quarter, 1 m higher than its parent."""
    patch = _region(patch_id, width_m=REGION_WIDTH_M / 2, height_m=REGION_HEIGHT_M / 2)
    patch.update({
        "name": "Fixture Parcel Patch", "map_detail_level": 5,
        "refinement_parent_map_id": "refined_lod4_fixture", "parent_location": "refined_lod4_fixture",
        "bounds": {"type": "bbox", "min_x": 17.1, "max_x": 17.2, "min_y": 25.4, "max_y": 25.475},
    })
    patch["heightmap_model"]["sample_grid"] = {"width": 3, "height": 3, "rows": [[501.0] * 3 for _ in range(3)]}
    return patch


class CityRefinedPatchTests(unittest.TestCase):
    def setUp(self):
        pygame.init()
        self.world = BlueprintWorld([_region(), _patch(), _region("refined_lod4_elsewhere")])
        self.city = city_site.found_city(self.world, "refined_lod4_fixture")
        self.city_map = MapSimulation(
            SimulationContext(year=2400, root_entity_id=self.city["id"], world_model=self.world))

    def test_patches_of_the_source_region_are_composited_into_the_city_map(self):
        models = self.city_map._refined_region_models()
        self.assertEqual([model["entity_id"] for model in models], ["refined_lod5_fixture"])
        uv = models[0]["uv_bounds"]
        for key, expected in (("min_u", 0.0), ("max_u", 0.5), ("min_v", 0.0), ("max_v", 0.5)):
            self.assertAlmostEqual(uv[key], expected)

    def test_patch_footprint_is_known_in_city_metres(self):
        (patch, bounds_m), = city_site.refined_patches(self.world, self.city)
        self.assertEqual(patch["id"], "refined_lod5_fixture")
        self.assertAlmostEqual(bounds_m["max_x"], REGION_WIDTH_M / 2)
        self.assertAlmostEqual(bounds_m["max_y"], REGION_HEIGHT_M / 2)

    def test_substrate_prefers_the_finest_patch(self):
        substrate = city_site.city_substrate(self.world, self.city)
        self.assertEqual(substrate.detail_level_at(400.0, 300.0), 5)
        self.assertAlmostEqual(substrate.elevation(400.0, 300.0), 501.0)
        # Outside the patch the region's own grid answers.
        self.assertEqual(substrate.detail_level_at(1500.0, 1000.0), 4)
        self.assertAlmostEqual(substrate.elevation(1500.0, 1000.0), 10.0 * 3 + 100.0 * 2)

    def test_the_city_map_can_refine_the_ground_it_stands_on(self):
        self.assertTrue(self.city_map.can_regenerate_region())
        calls = []

        def fake_generate(world_model, parent, bounds, **kwargs):
            calls.append((parent, bounds))
            return {"id": "refined_lod5_new", "bounds": {"type": "bbox", **bounds}}

        from simulations.world_gen import regional_refinement
        original = regional_refinement.generate_refined_region
        regional_refinement.generate_refined_region = fake_generate
        try:
            # Viewport showing the 500 m square from (1000, 750) to (1500, 1250) of the city.
            camera = SimpleNamespace(x=1250.0, y=1000.0, zoom=1.0, width=500, height=500,
                                     world_to_screen=lambda p: (p[0] - 1000.0, p[1] - 750.0))
            region = self.city_map.regenerate_visible_region(camera, 500, 500)
        finally:
            regional_refinement.generate_refined_region = original

        self.assertEqual(region["id"], "refined_lod5_new")
        (parent, bounds), = calls
        # The patch is a child of the source region, in that region's frame.
        self.assertEqual(parent["id"], "refined_lod4_fixture")
        self.assertAlmostEqual(parent["bounds"]["min_x"], 17.1)
        self.assertAlmostEqual(bounds["min_x"], 17.1 + 0.2 * 1000.0 / REGION_WIDTH_M)
        self.assertAlmostEqual(bounds["max_x"], 17.1 + 0.2 * 1500.0 / REGION_WIDTH_M)
        self.assertAlmostEqual(bounds["min_y"], 25.4 + 0.15 * 750.0 / REGION_HEIGHT_M)
        self.assertAlmostEqual(bounds["max_y"], 25.4 + 0.15 * 1250.0 / REGION_HEIGHT_M)


class CityPlacementGroundTests(_PlacementFixture):
    def setUp(self):
        super().setUp()
        pygame.init()
        region = _region()
        # The western half of the region is open water.
        region["water_cycle_model"] = {"surface_water_grid": {
            "water_presence_rows": [[1, 1, 0, 0, 0] for _ in range(4)],
        }}
        self.world = BlueprintWorld([region, self.blueprint_entity])
        self.city = city_site.found_city(self.world, "refined_lod4_fixture")
        self.city_map = MapSimulation(
            SimulationContext(year=2400, root_entity_id=self.city["id"], world_model=self.world))
        self.assertTrue(self.city_map.begin_blueprint_placement("bp_hut"))

    def test_a_building_cannot_be_placed_on_open_water(self):
        placement = self.city_map.blueprint_placement
        placement.set_cursor((300.0, 700.0))
        self.assertEqual(placement.ground_problem(), "open water")
        self.assertIn("cannot build on open water", placement.status_label())
        self.assertFalse(self.city_map.finish_blueprint_placement())
        # Refusal keeps the ghost on the cursor so the player can move on.
        self.assertIs(self.city_map.blueprint_placement, placement)
        self.assertEqual([e for e in self.world.entities.values() if e.get("building_blueprint")], [])

    def test_the_same_building_is_accepted_on_dry_ground(self):
        placement = self.city_map.blueprint_placement
        placement.set_cursor((1500.0, 700.0))
        self.assertIsNone(placement.ground_problem())
        self.assertTrue(self.city_map.finish_blueprint_placement())
        building = self.world.get_entity(self.city_map.selected_entity_id)
        self.assertEqual(building["parent_location"], self.city["id"])

    def test_authored_sites_without_terrain_place_as_before(self):
        site = {"id": "loc_site", "_dataset": "locations", "type": "location", "name": "Site",
                "location_class": "site", "map_coordinate_space": "site_meters",
                "bounds": {"type": "bbox", "min_x": -40, "max_x": 40, "min_y": -30, "max_y": 30}}
        world = BlueprintWorld([site, self.blueprint_entity])
        site_map = MapSimulation(SimulationContext(year=2400, root_entity_id="loc_site", world_model=world))
        self.assertIsNone(site_map.get_ground_substrate())
        self.assertTrue(site_map.begin_blueprint_placement("bp_hut"))
        site_map.blueprint_placement.set_cursor((0.0, 0.0))
        self.assertIsNone(site_map.blueprint_placement.ground_problem())


class CityFoundingWiringTests(_PlacementFixture):
    """The sidebar button and its navigation action, through the real UI classes."""

    def setUp(self):
        super().setUp()
        pygame.init()
        pygame.font.init()

    def _app(self, entities):
        tabs = SimpleNamespace(tabs=[], active_index=0)
        tabs.activate_tab_by_key = lambda key: False
        tabs.add_tab = lambda tab: tabs.tabs.append(tab)
        app = SimpleNamespace(
            world_model=BlueprintWorld(entities),
            tab_manager=tabs,
            knowledge_layer_active=True,
            camera_controller=SimpleNamespace(setup_for_sim=lambda sim: None),
        )
        app.get_active_simulation = lambda: (
            tabs.tabs[tabs.active_index].sim_instance.simulation if tabs.tabs else None
        )
        return app

    def test_region_sidebar_shows_the_founding_button(self):
        world = BlueprintWorld([_region()])
        region_map = MapSimulation(SimulationContext(year=2400, root_entity_id="refined_lod4_fixture", world_model=world))
        ui = UIManager()
        ui.rebuild_for_state(region_map, 1600, 900, camera=None)

        buttons = {button.id: button for button in ui.buttons}
        self.assertIn("found_city", buttons)
        self.assertEqual(buttons["found_city"].label, "Found City Here")
        self.assertTrue(buttons["found_city"].enabled)
        self.assertIn("TERRAIN", [section["label"] for section in ui.map_sidebar_sections])

    def test_found_city_action_opens_the_city_map(self):
        app = self._app([_region()])
        navigation = NavigationController(app)
        region_map = MapSimulation(
            SimulationContext(year=2400, root_entity_id="refined_lod4_fixture", world_model=app.world_model))

        # Sidebar buttons report their id as a plain string.
        self.assertTrue(navigation.handle_ui_action("found_city", region_map))

        city_map = app.get_active_simulation()
        self.assertIsInstance(city_map, MapSimulation)
        city = city_map.get_root_entity()
        self.assertEqual(city["location_class"], "city")
        self.assertEqual(city["terrain_source_map_id"], "refined_lod4_fixture")
        self.assertFalse(app.knowledge_layer_active)


if __name__ == "__main__":
    unittest.main()
