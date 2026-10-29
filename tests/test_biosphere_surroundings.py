"""The isometric Biosphere shows what the map of its ground shows round the living area."""
import os
import unittest
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import numpy as np
import pygame

from simulations.biosphere import terrain_site
from simulations.biosphere.biosphere_renderer import BiosphereBuilderRenderer
from simulations.biosphere.biosphere_simulation import BiosphereSimulation
from simulations.biosphere.flora import biome_flora
from simulations.biosphere.plant_pictures import MAP_VARIANTS
from simulations.biosphere.potential_vegetation import planet_seed
from simulations.biosphere.resident_start import RESIDENT_ORGANIC_MATTER_KG_M2
from simulations.biosphere.surroundings import EXACT_WITHIN_M, FAR_STAGES, PATCH_PLANT_SHARE, SWARD_PLANTS_FROM_PX
from simulations.city.city_vegetation import PlantField, city_vegetation
from tests import test_biome_flora as flora_fixtures
from tests import test_biosphere_terrain_site as site_fixtures

OAK, GRASS = flora_fixtures.OAK["id"], flora_fixtures.GRASS
WIDE = {"min_x": 200.0, "max_x": 320.0, "min_y": 10.0, "max_y": 118.0}
ALL = 10 ** 9


def _inside(bounds, x, y):
    return (x >= bounds["min_x"]) & (x <= bounds["max_x"]) & (y >= bounds["min_y"]) & (y <= bounds["max_y"])


def _whole(frame):
    """A view of all the ground, as ``(u0, u1, v0, v1)`` in ``x - y`` and ``x + y``."""
    return (frame["min_x"] - frame["max_y"], frame["max_x"] - frame["min_y"],
            frame["min_x"] + frame["min_y"], frame["max_x"] + frame["max_y"])


def _places(x, y):
    return {(round(float(px), 4), round(float(py), 4)) for px, py in zip(x, y)}


class SurroundingsTests(unittest.TestCase):
    def setUp(self):
        pygame.init()

    def _sim(self, flora=True, **context):
        world = site_fixtures._world(dict(flora_fixtures.OAK))
        if flora:
            resident = biome_flora(world, flora_fixtures.PLANET, flora_fixtures.CFB)
            resident.record(OAK, "common")
            resident.record(GRASS, "dominant")
        site = terrain_site.found_biosphere_site(world, site_fixtures.REGION_ID, site_fixtures._region_point(260.0, 64.0), year=2400)
        sim = BiosphereSimulation(world, {"patch_location_id": site["id"], "year": 2400, **context})
        if sim.surroundings is not None:
            # The colours a map sees the two in, without growing either to look at it from above.
            sim.surroundings._colours = {OAK: np.array((20.0, 70.0, 30.0)), GRASS: np.array((90.0, 160.0, 60.0))}
        return world, sim

    def test_ground_that_opens_bare_has_no_surroundings(self):
        _world, bare = self._sim(flora=False)
        self.assertIsNone(bare.surroundings)
        _world, asked = self._sim(start_bare=True)
        self.assertIsNone(asked.surroundings)

    def test_the_plants_a_map_of_the_ground_shows_stand_round_the_living_area(self):
        world, sim = self._sim()
        scenery, frame, domain = sim.surroundings, sim.terrain_frame, dict(sim.bounds)
        plants = scenery.plants(_whole(frame), budget=ALL)
        self.assertGreater(len(plants), 20)
        # (The sward's tufts are too many to set out over all the ground: see the narrower view below.)
        self.assertEqual({plant["species_id"] for plant in plants}, {OAK})
        self.assertEqual(scenery.shown[GRASS], 0.0)
        x, y = np.array([plant["x"] for plant in plants]), np.array([plant["y"] for plant in plants])
        self.assertEqual(len(_places(x, y)), len(plants))                    # each stands once
        self.assertFalse(_inside(domain, x, y).any())                        # the living area's plants are its own
        self.assertTrue(_inside(frame, x, y).all())
        self.assertEqual(scenery.shown[OAK], 1.0)
        # Beyond the ground read for the residents they are, place for place, the trees a city's map of this
        # ground draws (``city_vegetation``).
        near = sim.resident_flora.vegetation().bounds
        self.assertLess(near["max_x"] - near["min_x"], frame["max_x"] - frame["min_x"])
        city = {"terrain_root_planet_id": flora_fixtures.PLANET, "bounds": dict(frame)}
        vegetation, profiles, spacing = city_vegetation(world, city, sim.substrate)
        field = PlantField(vegetation, profiles, spacing, None, planet_seed(flora_fixtures.PLANET), overview_long_side_px=32)
        _kind, map_x, map_y, _crown = field.plants_in((frame["min_x"], frame["min_y"], frame["max_x"], frame["max_y"]))
        # (A map sets out the plants of every cell its ground touches, a few of them past its edge.)
        far_off = ~_inside(near, map_x, map_y) & _inside(frame, map_x, map_y)
        self.assertGreater(int(far_off.sum()), 10)
        beyond = ~_inside(near, x, y)
        self.assertEqual(_places(x[beyond], y[beyond]), _places(map_x[far_off], map_y[far_off]))
        # Close by each is drawn as the individual it is; further off as one of the few a map keeps, at three sizes.
        away = np.maximum(np.maximum(domain["min_x"] - x, x - domain["max_x"]), np.maximum(domain["min_y"] - y, y - domain["max_y"]))
        for plant, distance in zip(plants, away):
            if distance > EXACT_WITHIN_M:
                self.assertLess(plant["variant"], MAP_VARIANTS)
                self.assertIn(plant["display_maturity"], FAR_STAGES)
        # A second look at the same view is the same plants; a narrower one holds those of them that lie in it,
        # and of the sward, which is drawn as the ground it covers, a few plants to stand on it.
        self.assertIs(scenery.plants(_whole(frame), budget=ALL), plants)
        part = scenery.plants((-40.0, 260.0, 300.0, 380.0), budget=ALL)
        trees = [plant for plant in part if plant["species_id"] == OAK]
        self.assertTrue(0 < len(trees) < len(plants))
        self.assertTrue(_places([p["x"] for p in trees], [p["y"] for p in trees]) <= _places(x, y))
        tufts = [plant for plant in part if plant["species_id"] == GRASS]
        self.assertGreater(len(tufts), len(trees))
        self.assertEqual({plant["growth_form"] for plant in tufts}, {"structural_graminoid"})   # the grass's own picture
        self.assertTrue(scenery.grows_in_patches(GRASS) and not scenery.grows_in_patches(OAK))
        self.assertEqual(scenery.shown[GRASS], PATCH_PLANT_SHARE)
        # Seen from so far that a tuft would be a pixel, the sward is left to the ground again.
        far_off = scenery.plants((-40.0, 260.0, 300.0, 380.0), px_per_m=1.0, budget=ALL)
        self.assertEqual({plant["species_id"] for plant in far_off}, {OAK})
        self.assertEqual(scenery.shown[GRASS], 0.0)

    def test_close_in_a_sward_is_its_tufts_and_not_a_patch(self):
        _world, sim = self._sim()
        scenery, frame, domain = sim.surroundings, sim.terrain_frame, sim.bounds
        window = (-40.0, 260.0, 300.0, 380.0)
        height = sim.ecology.profiles[GRASS].mature_height_m
        x, y = np.meshgrid(np.linspace(frame["min_x"] + 2.0, frame["max_x"] - 2.0, 60),
                           np.linspace(frame["min_y"] + 2.0, frame["max_y"] - 2.0, 30))
        # Tufts half as tall again as the least a sward is drawn plant by plant at: every tuft, and no patch.
        close = [p for p in scenery.plants(window, px_per_m=1.5 * SWARD_PLANTS_FROM_PX / height, budget=ALL)
                 if p["species_id"] == GRASS]
        self.assertEqual((scenery.shown[GRASS], GRASS in scenery.as_plants), (1.0, True))
        self.assertNotIn(GRASS, scenery.patch_cover(x, y))
        # Half as tall: the sward is its patch again, with a few of its plants on it.
        further = [p for p in scenery.plants(window, px_per_m=0.5 * SWARD_PLANTS_FROM_PX / height, budget=ALL)
                   if p["species_id"] == GRASS]
        self.assertEqual((scenery.shown[GRASS], GRASS in scenery.as_plants), (PATCH_PLANT_SHARE, False))
        self.assertGreater(float(scenery.patch_cover(x, y)[GRASS][~_inside(domain, x, y)].mean()), 0.15)
        self.assertLess(len(further), len(close))

    def test_the_living_area_grows_over_them_and_they_are_its_residents(self):
        _world, sim = self._sim()
        scenery, first = sim.surroundings, dict(sim.bounds)
        before = {(round(plant["x"], 4), round(plant["y"], 4)): plant
                  for plant in scenery.plants(_whole(sim.terrain_frame), budget=ALL)}
        sim._set_domain(WIDE)
        oaks = sim.ecology.species_individuals(OAK)
        taken = _inside(WIDE, oaks["x"], oaks["y"]) & ~_inside(first, oaks["x"], oaks["y"])
        self.assertGreater(int(taken.sum()), 3)
        for x, y, variant in zip(oaks["x"][taken], oaks["y"][taken], oaks["variant"][taken]):
            seen = before[(round(float(x), 4), round(float(y), 4))]        # it stood there as scenery
            away = max(first["min_x"] - x, x - first["max_x"], first["min_y"] - y, y - first["max_y"])
            self.assertEqual(seen["variant"], int(variant) if away <= EXACT_WITHIN_M else int(variant) % MAP_VARIANTS)
        # What the living area took is no longer drawn round it.
        after = scenery.plants(_whole(sim.terrain_frame), budget=ALL)
        x, y = np.array([plant["x"] for plant in after]), np.array([plant["y"] for plant in after])
        self.assertFalse(_inside(WIDE, x, y).any())
        self.assertEqual(len(after), len(before) - int(_inside(WIDE, *np.array(list(before)).T).sum()))

    def test_what_a_view_does_not_show_plant_by_plant_colours_the_ground(self):
        _world, sim = self._sim()
        scenery, frame, domain = sim.surroundings, sim.terrain_frame, sim.bounds
        x, y = np.meshgrid(np.linspace(frame["min_x"] + 2.0, frame["max_x"] - 2.0, 60),
                           np.linspace(frame["min_y"] + 2.0, frame["max_y"] - 2.0, 30))
        inside = _inside(domain, x, y)
        self.assertTrue(inside.any())
        every = scenery.plants(_whole(frame), budget=ALL)
        colour, cover, organic = scenery.ground(x, y)
        sward = scenery.patch_cover(x, y)[GRASS]
        # Nothing in the living area, whose ground is its own.  Round it the soil the vegetation stands on, and
        # the sward as ground of its own (a patch), not as a colour among the plants; every tree is drawn, so
        # there is nothing else to colour the ground with.
        self.assertEqual((float(organic[inside].max()), float(sward[inside].max()), float(cover.max())), (0.0, 0.0, 0.0))
        self.assertGreater(float(sward[~inside].mean()), 0.15)
        self.assertGreater(float(organic[~inside].mean()), 0.5 * RESIDENT_ORGANIC_MATTER_KG_M2)
        # (A moving view, which draws no patches, has the sward among the plants' colours.)
        blended, share, _soil = scenery.ground(x, y, patches_too=True)
        grassy = ~inside & (share > 0.05)
        np.testing.assert_allclose(blended[grassy], np.broadcast_to((90.0, 160.0, 60.0), blended[grassy].shape), atol=0.5)
        np.testing.assert_array_equal(scenery.ground(frame["max_x"] + 50.0, frame["min_y"] - 50.0)[1], 0.0)   # off the map
        # A view that can show only some of the trees shows a share of them, the same ones, and the ground
        # takes the colour of the rest.
        revision = scenery.revision
        some = scenery.plants(_whole(frame), budget=12)
        share = scenery.shown[OAK]
        self.assertTrue(0.0 < share < 1.0)
        self.assertTrue(0 < len(some) < len(every))
        self.assertTrue(_places([p["x"] for p in some], [p["y"] for p in some])
                        <= _places([p["x"] for p in every], [p["y"] for p in every]))
        self.assertEqual(scenery.revision, revision + 1)
        tinted, more, _soil = scenery.ground(x, y)
        self.assertTrue((more >= cover - 1e-6).all())
        self.assertGreater(float((more - cover).max()), 0.02)
        self.assertLess(float(tinted[~inside & (more > cover + 0.02)][:, 1].mean()), 160.0)   # darker: oak in it

    def test_the_plants_of_a_new_view_are_set_out_a_little_each_frame(self):
        _world, sim = self._sim()
        scenery, window = sim.surroundings, _whole(sim.terrain_frame)
        self.assertEqual(scenery.plants(window, budget=ALL, within_ms=0.0), [])   # one step done, more to do
        self.assertEqual((scenery.shown, scenery.revision), ({}, 0))
        for _frame in range(8):
            plants = scenery.plants(window, budget=ALL, within_ms=0.0)
        self.assertGreater(len(plants), 20)
        self.assertEqual((scenery.shown[OAK], scenery.revision), (1.0, 1))
        _world, other = self._sim()
        at_once = other.surroundings.plants(window, budget=ALL)
        self.assertEqual(_places([p["x"] for p in plants], [p["y"] for p in plants]),
                         _places([p["x"] for p in at_once], [p["y"] for p in at_once]))

    def _drawn(self, zoom=0.2):
        _world, sim = self._sim()
        sim.isometric_fullscreen_preview = True
        sim.isometric_view_zoom = zoom
        renderer = BiosphereBuilderRenderer(SimpleNamespace())
        renderer.GROUND_SETTLE_SECONDS = 0.0
        screen = pygame.Surface((640, 400))
        renderer.draw(screen, sim)
        return sim, renderer, screen

    def test_the_isometric_view_draws_them(self):
        sim, renderer, screen = self._drawn()
        state = sim._isometric_projection_state
        layer = renderer._rest_layers["plants"]
        self.assertGreater(sim._surroundings_render_count, 20)
        self.assertEqual(sim._surroundings_render_count, layer["count"])
        # They are one picture, painted from the far edge to the near; every plant of the view on the screen is in it.
        groups = sim.surroundings.groups(renderer._vegetation_window(screen, state), state["scale"])
        self.assertLessEqual(layer["count"], sum(len(group["x"]) for group in groups))
        depth = layer["plants"]["depth"]
        self.assertTrue((np.diff(depth) >= 0.0).all())
        # Ground outside the living area is not the bare ground it is without them.
        outside = renderer._iso(state, sim.bounds["max_x"] + 12.0, sim.bounds["max_y"] + 12.0)
        with_them = pygame.surfarray.array3d(screen).astype(int)
        again = pygame.Surface((640, 400))
        renderer.draw(again, sim)
        self.assertIs(renderer._rest_layers["plants"], layer)                  # kept, not painted again
        np.testing.assert_array_equal(pygame.surfarray.array3d(again), with_them)
        sim.surroundings = None
        bare = pygame.Surface((640, 400))
        renderer.draw(bare, sim)
        self.assertEqual(sim._surroundings_render_count, 0)
        without = pygame.surfarray.array3d(bare).astype(int)
        px, py = round(outside[0]), round(outside[1])
        patch = (slice(px - 6, px + 7), slice(py - 6, py + 7))
        self.assertGreater(float(np.abs(with_them[patch] - without[patch]).mean()), 4.0)
        self.assertGreater(float(np.abs(with_them - without).mean()), 2.0)

    def test_the_ground_is_drawn_in_blocks_that_stay_on_the_ground(self):
        sim, renderer, screen = self._drawn()
        block = renderer.GROUND_PIXEL_PX
        for name in ("soil", "surroundings"):
            layer = renderer._rest_layers[name]
            picture = pygame.surfarray.array3d(layer["surface"]).astype(int)
            alpha = pygame.surfarray.array_alpha(layer["surface"]).astype(int)
            self.assertEqual((picture.shape[0] % block, picture.shape[1] % block), (0, 0))
            # Every block is one colour, clear or not: nothing is blended.
            for values in (picture[..., 0], picture[..., 1], picture[..., 2], alpha):
                blocks = values.reshape(values.shape[0] // block, block, values.shape[1] // block, block)
                self.assertEqual(int((blocks.max(axis=(1, 3)) - blocks.min(axis=(1, 3))).max()), 0)
            self.assertGreater(len(np.unique(picture[alpha > 0].reshape(-1, 3), axis=0)), 2)   # and of several tones
        # The sward round the living area is a patch of that ground: opaque blocks in the tones of its own picture.
        patch = pygame.surfarray.array_alpha(renderer._rest_layers["surroundings"]["surface"]) == 255
        self.assertGreater(float(patch.mean()), 0.05)
        # The blocks are the ground's: a view moved by a block's worth of ground shows the same blocks one
        # further along, and one whose middle lies a block's worth higher shows them one further down.
        state = dict(sim._isometric_projection_state)
        _left, _top, _x, _y, numbers = renderer._ground_pixels(screen.get_size(), state)
        aside = dict(state, center_x=state["center_x"] + 0.5 * block / state["scale"],
                     center_y=state["center_y"] - 0.5 * block / state["scale"])
        _left, _top, _x, _y, moved = renderer._ground_pixels(screen.get_size(), aside)
        np.testing.assert_array_equal(moved[0][:, :-1], numbers[0][:, 1:])
        higher = dict(state, datum_m=state["datum_m"] + block / (state["vertical_scale"] * state["scale"]))
        _left, _top, _x, _y, moved = renderer._ground_pixels(screen.get_size(), higher)
        np.testing.assert_array_equal(moved[0][1:, :], numbers[0][:-1, :])

    def test_a_moving_view_carries_the_picture_of_them_along(self):
        sim, renderer, screen = self._drawn()
        layer = renderer._rest_layers["plants"]
        renderer.GROUND_SETTLE_SECONDS = 1000.0                               # from here on the view does not rest
        still = pygame.surfarray.array3d(screen).astype(int)
        for change in ({"isometric_view_center": (sim.founding_point()[0] + 6.0, sim.founding_point()[1] - 3.0)},
                       {"isometric_view_zoom": 0.26}):
            for name, value in change.items():
                setattr(sim, name, value)
            moved = pygame.Surface((640, 400))
            renderer.draw(moved, sim)
            self.assertIs(renderer._rest_layers["plants"], layer)              # moved with the ground, not painted
            self.assertGreater(float(np.abs(pygame.surfarray.array3d(moved).astype(int) - still).mean()), 1.0)
            self.assertEqual(sim._surroundings_render_count, layer["count"])


    def test_a_kept_plants_picture_is_painted_once_and_kept_between_sessions(self):
        import tempfile

        sim, renderer, screen = self._drawn()
        pictures = sim.plant_pictures
        with tempfile.TemporaryDirectory() as folder:
            pictures.map_sprite_dir = folder
            try:
                first = BiosphereBuilderRenderer(SimpleNamespace())
                first.GROUND_SETTLE_SECONDS = 0.0
                first.draw(pygame.Surface((640, 400)), sim)
                kept = list(Path(folder).rglob("isometric/*.png"))
                self.assertGreater(len(kept), 2)
                self.assertEqual(len(kept), len(list(Path(folder).rglob("isometric/*.json"))))
                # Another session finds them there: no plant is grown or painted to draw the same view.
                later = BiosphereBuilderRenderer(SimpleNamespace())
                later.GROUND_SETTLE_SECONDS = 0.0
                later._render_sprite_surface = lambda *args, **kwargs: self.fail("a kept plant was painted again")
                again = pygame.Surface((640, 400))
                later.draw(again, sim)
                self.assertEqual(sim._surroundings_render_count, renderer._rest_layers["plants"]["count"])
                np.testing.assert_array_equal(pygame.surfarray.array3d(again), pygame.surfarray.array3d(screen))
            finally:
                pictures.map_sprite_dir = None


if __name__ == "__main__":
    unittest.main()
