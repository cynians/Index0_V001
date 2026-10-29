"""A crust holds stone and ground too thin to root in, where nothing that roots covers it."""
import os
from dataclasses import replace

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import numpy as np

from simulations.biosphere.ecology import profile_from_entity
from simulations.biosphere.potential_vegetation import CRUST_SOIL_DEPTH_M, resident_vegetation
from tests import test_biome_flora as fixtures

CRUST = "spec_test_crust"


class Stony:
    """A ground with a strip of bare stone and a strip of a hand of soil along its west side."""

    def __init__(self, ground):
        self._ground = ground

    def __getattr__(self, name):
        return getattr(self._ground, name)

    def sample_array(self, key, x, y, default=0.0):
        values = self._ground.sample_array(key, x, y, default)
        if key in ("soil_depth_m", "rootable_depth_m"):
            x = np.asarray(x, dtype=np.float64)
            return np.where(x < 60.0, 0.0, np.where(x < 120.0, 0.10, values))
        return values


def test_a_crust_holds_thin_ground_left_bare_and_none_that_is_deep_or_covered():
    world = fixtures._world(fixtures.HEATH)
    _root, ground = fixtures.site(world)
    ground = Stony(ground)
    bounds = dict(min_x=0.0, max_x=512.0, min_y=0.0, max_y=256.0)
    heath = replace(profile_from_entity(fixtures.HEATH), clonal_spread="high")
    crust = replace(heath, species_id=CRUST, growth_form="lichen", mature_height_m=0.0,
                    surface_growth_profile={"thallus_form": "crustose"})
    alone = resident_vegetation(ground, bounds, {CRUST: crust}, fixtures.floras_of(**{CRUST: "dominant"}), cells=96)
    x, y = alone.x, alone.y
    depth = np.asarray(ground.sample_array("soil_depth_m", x, y, np.nan), dtype=np.float64)
    land = ~np.asarray(ground.open_water_array(x, y), dtype=bool)
    thin, deep = land & (depth < 0.8 * CRUST_SOIL_DEPTH_M), land & (depth > CRUST_SOIL_DEPTH_M)
    assert thin.any() and deep.any()
    cover = alone.cover[CRUST]
    assert alone.layers[CRUST] == "ground"
    assert float(cover[thin].min()) > 0.05 and float(cover[deep].max()) == 0.0 and float(cover[~land].max()) == 0.0
    # The thinner the ground, the more of it is the crust's.
    thinner = thin & (depth <= np.median(depth[thin]))
    assert float(cover[thinner].mean()) >= float(cover[thin].mean())
    # A plant that roots there takes its share first, and the crust what that leaves.
    both = resident_vegetation(ground, bounds, {CRUST: crust, heath.species_id: heath},
                               fixtures.floras_of(**{CRUST: "dominant", heath.species_id: "dominant"}), cells=96)
    with_heath = both.cover.get(CRUST, np.zeros(x.shape))
    assert (with_heath <= cover + 1e-9).all()
    shared = land & (both.cover[heath.species_id] > 0.2) & (cover > 0.0)
    if shared.any():
        assert float(with_heath[shared].mean()) < float(cover[shared].mean())
    assert float((with_heath + both.cover[heath.species_id]).max()) <= 1.0 + 1e-9
