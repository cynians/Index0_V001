"""What grows on a piece of ground is the planet's: the same patches and plants on every map of it."""
import math
import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import numpy as np

from simulations.biosphere.ecology import profile_from_entity
from simulations.biosphere.potential_vegetation import GroundFrame, planet_seed, resident_vegetation
from tests import test_biome_flora as flora_fixtures

CIRCUMFERENCE_M = 40_000_000.0


class Ground:
    """Level ground of one kind that says where on its planet it lies, as a generated map does."""

    def __init__(self, min_u, max_u, min_v, max_v, tell=True):
        latitude = (0.5 - 0.5 * (min_v + max_v)) * math.pi
        width = (max_u - min_u) * CIRCUMFERENCE_M * math.cos(latitude)
        height = (max_v - min_v) * 0.5 * CIRCUMFERENCE_M
        self.bounds = {"min_x": 0.0, "max_x": width, "min_y": 0.0, "max_y": height}
        if tell:
            self.heightmap = {"source_uv_bounds": {"min_u": min_u, "max_u": max_u, "min_v": min_v, "max_v": max_v},
                              "planet_circumference_m": CIRCUMFERENCE_M, "region_width_m": width, "region_height_m": height}

    def koppen_at(self, _x, _y):
        return flora_fixtures.CFB.climate, flora_fixtures.CFB.climate_label

    def sample_array(self, key, x, _y, default=0.0):
        return np.full(np.shape(x), {"soil_moisture": 0.45}.get(key, default), dtype=np.float64)

    def open_water_array(self, x, _y):
        return np.zeros(np.shape(x), dtype=bool)


SITE = (0.30, 0.30008, 0.30, 0.30004)          # about 2.6 km by 800 m at 36 degrees
PARCEL = (0.30003, 0.30005, 0.30001, 0.30002)  # 650 m by 200 m of it


def _plants():
    oak = profile_from_entity(flora_fixtures.OAK)
    heath = profile_from_entity(flora_fixtures.HEATH)
    return {oak.species_id: oak, heath.species_id: heath}


def _window(above, below):
    """The frame of ``below`` as a window of ``above``'s."""
    frame, inner = GroundFrame.of(above), GroundFrame.of(below)
    x, y = frame.from_uv(*inner.uv(np.array([0.0, below.bounds["max_x"]]), np.array([0.0, below.bounds["max_y"]])))
    return {"min_x": float(x[0]), "max_x": float(x[1]), "min_y": float(y[0]), "max_y": float(y[1])}


def test_a_map_says_where_on_its_planet_it_lies_and_ground_that_does_not_is_a_plane_of_its_own():
    site, parcel = Ground(*SITE), Ground(*PARCEL)
    frame, inner = GroundFrame.of(site), GroundFrame.of(parcel)
    assert not frame.flat and not inner.flat
    assert GroundFrame.of(Ground(*SITE, tell=False)).flat and GroundFrame.of(object()).flat
    # Bounds that are not the map's own metre frame cannot be laid on the planet.
    stretched = Ground(*SITE)
    stretched.bounds = dict(stretched.bounds, max_x=2.0 * stretched.bounds["max_x"])
    assert GroundFrame.of(stretched).flat
    # The same ground has the same place in the planet's space from either map, to well under a millimetre.
    x, y = np.array([0.0, 100.0, 650.0]), np.array([0.0, 50.0, 200.0])
    px, py = frame.from_uv(*inner.uv(x, y))
    for mine, theirs in zip(inner.world(x, y), frame.world(px, py)):
        np.testing.assert_allclose(mine, theirs, atol=1e-5)
    # A metre on the map is a metre in that space.
    step = np.hypot(*(np.diff(part) for part in frame.world(np.array([1000.0, 1001.0]), np.array([400.0, 400.0]))[:2]))
    east = np.sqrt(sum(np.diff(part) ** 2 for part in frame.world(np.array([1000.0, 1001.0]), np.array([400.0, 400.0]))))
    south = np.sqrt(sum(np.diff(part) ** 2 for part in frame.world(np.array([1000.0, 1000.0]), np.array([400.0, 401.0]))))
    assert step > 0 and abs(float(east[0]) - 1.0) < 1e-3 and abs(float(south[0]) - 1.0) < 1e-3
    # On a plane its metres are its world.
    flat = GroundFrame()
    assert [part.tolist() for part in flat.world(np.array([3.0]), np.array([4.0]))] == [[3.0], [4.0], [0.0]]


def test_the_planets_places_for_plants_are_the_same_from_every_map_and_window():
    site, parcel = Ground(*SITE), Ground(*PARCEL)
    frame, inner = GroundFrame.of(site), GroundFrame.of(parcel)
    window = _window(site, parcel)
    x, y, key = frame.places((window["min_x"], window["min_y"], window["max_x"], window["max_y"]), 4.0)
    cx, cy, ckey = inner.places((0.0, 0.0, parcel.bounds["max_x"], parcel.bounds["max_y"]), 4.0)
    # One place to a cell of four metres: as many as the ground has room for.
    area = parcel.bounds["max_x"] * parcel.bounds["max_y"]
    assert abs(len(cx) - area / 16.0) < 0.05 * area / 16.0
    # The Site's places on the Parcel's ground are the Parcel's own, key for key.
    px, py = inner.from_uv(*frame.uv(x, y))
    mine = {int(k): (round(float(a), 3), round(float(b), 3)) for k, a, b in zip(ckey, cx, cy)}
    theirs = {int(k): (round(float(a), 3), round(float(b), 3)) for k, a, b in zip(key, px, py)}
    shared = set(mine) & set(theirs)
    assert len(shared) > 0.97 * len(mine)
    assert all(abs(mine[k][0] - theirs[k][0]) < 0.01 and abs(mine[k][1] - theirs[k][1]) < 0.01 for k in shared)
    # A window of a map holds the places the whole map has there.
    piece = (100.0, 40.0, 180.0, 90.0)
    wx, wy, wkey = inner.places(piece, 4.0)
    inside = (cx >= piece[0]) & (cx < piece[2]) & (cy >= piece[1]) & (cy < piece[3])
    assert inside.any() and set(ckey[inside].tolist()) <= set(wkey.tolist())
    # A plane has places too, and no window asks for more than can be held.
    fx, fy, _fkey = GroundFrame().places((0.0, 0.0, 100.0, 50.0), 2.0)
    assert abs(len(fx) - 1250) < 130
    assert len(GroundFrame().places((0.0, 0.0, 1.0e6, 1.0e6), 0.01)[0]) == 0
    assert planet_seed("planet_a") == planet_seed("planet_a") != planet_seed("planet_b")


def test_a_parcel_shows_the_woods_and_the_trees_its_site_shows_there():
    site, parcel = Ground(*SITE), Ground(*PARCEL)
    profiles = _plants()
    floras = flora_fixtures.floras_of(**{flora_fixtures.OAK["id"]: "common", flora_fixtures.HEATH["id"]: "occasional"})
    seed = planet_seed("planet_fixture")
    window = _window(site, parcel)
    above = resident_vegetation(site, window, profiles, floras, cells=96, seed=seed)
    here = resident_vegetation(parcel, parcel.bounds, profiles, floras, cells=96, seed=seed)
    assert above.x.shape == here.x.shape
    for species_id in profiles:
        a, b = above.cover[species_id] > 0.0, here.cover[species_id] > 0.0
        assert a.any() and not a.all()                       # in patches, on either map
        assert float((a == b).mean()) > 0.99, species_id     # and the same patches
        np.testing.assert_allclose(above.cover[species_id], here.cover[species_id], atol=0.05)
    # The single trees: every one set out from the Site stands on the Parcel at the same spot.
    oak = flora_fixtures.OAK["id"]
    ax, ay, a_grown = above.plants(oak, 8.0, seed=seed)
    bx, by, b_grown = here.plants(oak, 8.0, seed=seed)
    px, py = GroundFrame.of(parcel).from_uv(*GroundFrame.of(site).uv(ax, ay))
    assert len(ax) > 50
    mine = {(round(float(x), 2), round(float(y), 2)): float(g) for x, y, g in zip(bx, by, b_grown)}
    theirs = {(round(float(x), 2), round(float(y), 2)): float(g) for x, y, g in zip(px, py, a_grown)}
    shared = set(mine) & set(theirs)
    assert len(shared) > 0.95 * max(len(mine), len(theirs))
    assert all(mine[spot] == theirs[spot] for spot in shared)   # as tall on both
    # Another planet has other woods on ground that is otherwise the same.
    elsewhere = resident_vegetation(parcel, parcel.bounds, profiles, floras, cells=96, seed=planet_seed("planet_other"))
    assert float(((elsewhere.cover[oak] > 0) == (here.cover[oak] > 0)).mean()) < 0.9
    # And a window of the Parcel asked for alone holds the same trees as the whole Parcel does there.
    piece = (100.0, 40.0, 300.0, 160.0)
    wx, wy, _grown = here.plants(oak, 8.0, seed=seed, window=piece)
    inside = (bx >= piece[0]) & (bx < piece[2]) & (by >= piece[1]) & (by < piece[3])
    assert inside.any()
    assert {(round(float(x), 3), round(float(y), 3)) for x, y in zip(bx[inside], by[inside])} <= {
        (round(float(x), 3), round(float(y), 3)) for x, y in zip(wx, wy)}
