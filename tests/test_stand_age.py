"""Fire by climate, the ages of the ground it leaves, and what stands on young ground."""
import os
from dataclasses import replace

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import numpy as np

from simulations.biosphere.ecology import profile_from_entity
from simulations.biosphere.flora import BiomeFlora
from simulations.biosphere.potential_vegetation import (
    GAP_RETURN_YEARS, closure_years, fire_return_years, recovery_years, resident_vegetation, stand_age_years,
)
from tests import test_biome_flora as flora_fixtures
from tests import test_water_balance as water_fixtures


def test_a_climate_burns_as_often_as_it_grows_fuel_and_dries_it():
    assert fire_return_years(60, 2600, 0, 14) is None                 # desert: nothing to burn
    assert fire_return_years(2600, 1500, 150, 24) is None             # wet through the year: never dry enough
    assert fire_return_years(1100, 1800, 3, 20) == 4.0                # savanna: grass under a dry season
    assert fire_return_years(320, 1200, 12, -6) == 8.0                # steppe
    assert fire_return_years(520, 1150, 4, 8) == 35.0                 # dry-summer scrub
    assert fire_return_years(450, 380, 22, -22) == 150.0              # cold conifer wood
    assert fire_return_years(900, 700, 55, 3) == 400.0                # moist temperate wood: hardly ever
    assert fire_return_years(float("nan"), 700) is None and fire_return_years(900, None) is None


def test_ground_burnt_without_memory_is_mostly_young_and_the_same_from_every_map():
    places = np.random.default_rng(3).uniform(-3.0e6, 3.0e6, (3, 60_000))
    age = stand_age_years(places, 40.0, seed=7)
    assert abs(float(age.mean()) - 40.0) < 4.0
    assert abs(float((age < 40.0).mean()) - (1.0 - np.exp(-1.0))) < 0.03     # 63 % younger than the average
    np.testing.assert_array_equal(stand_age_years(places[:, :500], 40.0, seed=7), age[:500])
    assert not np.array_equal(stand_age_years(places[:, :500], 40.0, seed=8), age[:500])


class Steppe(water_fixtures.BalancedRiverGround):
    """The river fixture under a climate that burns every few years."""

    CLIMATE = {"annual_precipitation_mm": 320.0, "annual_potential_evaporation_mm": 1200.0,
               "driest_month_precipitation_mm": 12.0}

    def sample_array(self, key, x, y, default=0.0):
        if key in self.CLIMATE:
            return np.full(np.shape(x), self.CLIMATE[key])
        return super().sample_array(key, x, y, default)


def test_fire_keeps_trees_to_old_ground_and_leaves_what_grows_back_at_once():
    # An oak at home on all of this ground, sixty years in growing up.
    oak = replace(profile_from_entity(dict(flora_fixtures.OAK)), moisture_optimum=0.4, moisture_tolerance=0.8,
                  waterlogging_tolerance="high", root_depth_class="deep", maturity_days=60 * 4 * 91.3125)
    sprouter = replace(oak, species_id="spec_sprouting_oak", resprouting="strong")
    herb = replace(oak, species_id="spec_test_herb", growth_form="forb", mature_height_m=0.5, maturity_days=120.0)
    assert recovery_years(sprouter) < 0.2 * recovery_years(oak) and recovery_years(herb) <= 1.0 < closure_years(oak)
    bounds = dict(min_x=0.0, max_x=400.0, min_y=0.0, max_y=200.0)

    def grown(profile, **how):
        flora = BiomeFlora(flora_fixtures.PLANET, flora_fixtures.CFB)
        flora.record(profile.species_id, "dominant")
        return resident_vegetation(Steppe(), bounds, {profile.species_id: profile}, {flora_fixtures.CFB.key: flora},
                                   cells=80, **how)

    burnt, unburnt = grown(oak), grown(oak, disturbance=False)
    assert (burnt.fire_return_years, unburnt.fire_return_years, unburnt.stand_age) == (8.0, None, None)
    with_fire, without = burnt.cover[oak.species_id], unburnt.cover[oak.species_id]
    stood = without > 0.05
    assert stood.any() and float(with_fire[stood].mean()) < 0.5 * float(without[stood].mean())
    # What oak there is stands on the ground longest unburnt, and is young where the fire was not long ago.
    age = burnt.stand_age
    assert float((age * with_fire).sum() / with_fire.sum()) > 1.25 * float(age[stood].mean())
    x, y, share = burnt.plants(oak.species_id, 8.0)
    if len(x) > 20:
        young = burnt.between_cells(age, x, y) < np.median(burnt.between_cells(age, x, y))
        assert float(share[young].mean()) < float(share[~young].mean())
    # One that sprouts again from its stock holds far more of it; a herb is back within the year.
    assert float(grown(sprouter).cover[sprouter.species_id][stood].mean()) > 2.0 * float(with_fire[stood].mean())
    herbs, unburnt_herbs = grown(herb).cover[herb.species_id], grown(herb, disturbance=False).cover[herb.species_id]
    assert float(herbs.sum()) > 0.85 * float(unburnt_herbs.sum())
    # Under a climate that does not burn a wood still has its gaps: a little less than all of its canopy.
    moist, whole = (resident_vegetation(Rainy(), bounds, {oak.species_id: oak}, {flora_fixtures.CFB.key: _flora(oak)},
                                        cells=80, disturbance=flag) for flag in (True, False))
    assert moist.fire_return_years is None and moist.stand_age is None
    np.testing.assert_allclose(moist.cover[oak.species_id],
                               whole.cover[oak.species_id] * np.exp(-closure_years(oak) / GAP_RETURN_YEARS), rtol=0.05, atol=0.01)


class Rainy(Steppe):
    """The same ground wet through the year: nothing there is ever dry enough to burn."""

    CLIMATE = {"annual_precipitation_mm": 2600.0, "annual_potential_evaporation_mm": 1500.0,
               "driest_month_precipitation_mm": 150.0}

def _flora(profile):
    flora = BiomeFlora(flora_fixtures.PLANET, flora_fixtures.CFB)
    flora.record(profile.species_id, "dominant")
    return flora
