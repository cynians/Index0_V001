"""Rock units and faults anchored to the planet: every map of the same ground draws the same ones."""

import unittest

import numpy as np

from simulations.world_gen import crust_units as cu

RADIUS = 6_371_000.0


def _tile(u0=0.243, v0=0.378, du=0.007, dv=0.009, columns=257, rows=155):
    return np.meshgrid(np.linspace(u0, u0 + du, columns), np.linspace(v0, v0 + dv, rows))


class UnitTests(unittest.TestCase):
    def test_a_window_of_a_map_draws_the_same_units_as_the_map(self):
        u, v = _tile()
        keys, _centres = cu.unit_cells(u, v, unit_scale_m=6_000.0, radius_m=RADIUS, seed=11)
        sub, _sub_centres = cu.unit_cells(u[40:90, 60:160], v[40:90, 60:160], unit_scale_m=6_000.0, radius_m=RADIUS, seed=11)
        np.testing.assert_array_equal(sub, keys[40:90, 60:160])

    def test_draws_are_uniform_over_many_units(self):
        u, v = _tile(du=0.05, dv=0.08, columns=400, rows=400)
        keys, centres = cu.unit_cells(u, v, unit_scale_m=6_000.0, radius_m=RADIUS, seed=5)
        draws = cu.unit_draws(keys, centres, ["mat_a"], unit_scale_m=6_000.0, seed=5)[0]
        _unique, first = np.unique(keys, return_index=True)
        per_unit = draws.ravel()[first]
        self.assertGreater(per_unit.size, 500)
        quartiles = np.percentile(per_unit, [25, 50, 75])
        np.testing.assert_allclose(quartiles, [0.25, 0.5, 0.75], atol=0.06)

    def test_units_are_longer_along_strike_where_the_crust_is_shortened(self):
        u, v = _tile(du=0.02, dv=0.04, columns=300, rows=300)
        east, south = np.ones(u.shape), np.zeros(u.shape)

        def runs(anisotropy):
            keys, _c = cu.unit_cells(u, v, unit_scale_m=6_000.0, radius_m=RADIUS, seed=3,
                                     strike_east=east, strike_south=south, anisotropy=np.full(u.shape, anisotropy))
            same_east = float((keys[:, 1:] == keys[:, :-1]).mean())
            same_south = float((keys[1:, :] == keys[:-1, :]).mean())
            return same_east, same_south

        flat_east, flat_south = runs(1.0)
        belt_east, belt_south = runs(cu.UNIT_ANISOTROPY)
        # Cells are ~78 m east, ~ 222 m south here: compare the change, not the values.
        self.assertGreater(belt_east, flat_east)
        self.assertLess(belt_south, flat_south)

    def test_the_rung_follows_the_cells(self):
        self.assertEqual(cu.unit_scale_for(585.0), 6_000.0)
        self.assertEqual(cu.unit_scale_for(104.0), 1_200.0)
        self.assertEqual(cu.unit_scale_for(48_000.0), 600_000.0)


class FaultTests(unittest.TestCase):
    def test_a_window_sees_the_same_faults(self):
        u, v = _tile()
        strain = lambda fu, fv: np.full(np.shape(fu), 0.5)
        shift, heave, faults = cu.planet_faults(u, v, unit_scale_m=6_000.0, radius_m=RADIUS, seed=9, strain_at=strain)
        sub_shift, sub_heave, _faults = cu.planet_faults(u[40:90, 60:160], v[40:90, 60:160], unit_scale_m=6_000.0, radius_m=RADIUS, seed=9, strain_at=strain)
        self.assertTrue(faults)
        np.testing.assert_allclose(sub_shift, shift[:, 40:90, 60:160], atol=1e-6)
        np.testing.assert_allclose(sub_heave, heave[40:90, 60:160], atol=1e-6)

    def test_strained_crust_has_more_faults(self):
        u, v = _tile(du=0.05, dv=0.08, columns=60, rows=60)
        quiet = cu.planet_faults(u, v, unit_scale_m=6_000.0, radius_m=RADIUS, seed=9, strain_at=lambda a, b: np.zeros(np.shape(a)))[2]
        busy = cu.planet_faults(u, v, unit_scale_m=6_000.0, radius_m=RADIUS, seed=9, strain_at=lambda a, b: np.ones(np.shape(a)))[2]
        self.assertGreater(len(busy), 1.6 * len(quiet))


if __name__ == "__main__":
    unittest.main()
