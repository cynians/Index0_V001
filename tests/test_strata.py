"""Layered rock anchored to the planet: folds, nested beds, children and neighbours that agree."""

import math
import unittest

import numpy as np

from simulations.world_gen import strata

CIRCUMFERENCE = 40_000_000.0
TECTONICS = {"boundary_segments": [
    {"kind": "collision", "x1": 0.30, "y1": 0.45, "x2": 0.36, "y2": 0.45, "orogen_system_id": "belt"},
    {"kind": "collision", "x1": 0.36, "y1": 0.45, "x2": 0.42, "y2": 0.452, "orogen_system_id": "belt"},
]}


def _grid(u0, u1, v0, v1, columns, rows):
    u = np.linspace(u0, u1, columns)
    v = np.linspace(v0, v1, rows)
    return np.broadcast_to(u[None, :], (rows, columns)), np.broadcast_to(v[:, None], (rows, columns))


def _folds(u_grid, v_grid, cell_m, shortening=1.0):
    return strata.fold_surface(
        u_grid, v_grid, np.full(u_grid.shape, shortening), tectonic_model=TECTONICS,
        circumference_m=CIRCUMFERENCE, seed="test-planet", cell_m=cell_m,
    )


class FoldTests(unittest.TestCase):
    def test_unshortened_crust_stays_flat(self):
        u, v = _grid(0.33, 0.37, 0.44, 0.46, 200, 80)
        self.assertEqual(0.0, float(np.abs(_folds(u, v, 600.0, shortening=0.0)).max()))

    def test_folds_plunge_out_along_strike(self):
        # One train: a 16 km band across strike (about one wavelength), 4800 km along the belt.
        u, v = _grid(0.30, 0.42, 0.4496, 0.4504, 1600, 30)
        amplitude = np.abs(_folds(u, v, 600.0)).max(axis=0)
        self.assertGreater(float(amplitude.max()), 0.6 * strata.FOLD_AMPLITUDE_RATIO * 15_000.0)
        self.assertLess(float(np.percentile(amplitude, 10)), 0.2 * float(amplitude.max()))

    def test_fold_axes_wander(self):
        # 0.12 of the circumference along the belt, 0.004 across: ~4800 x 80 km at 600 m.
        u, v = _grid(0.30, 0.42, 0.448, 0.452, 1600, 140)
        fold = _folds(u, v, 600.0)
        amplitude = np.abs(fold).max(axis=0)
        strong = amplitude > 0.5 * amplitude.max()
        crest_rows = np.argmax(fold, axis=0)[strong]
        self.assertGreater(float(np.std(crest_rows)), 2.0)


class AnchoringTests(unittest.TestCase):
    def _horizon(self, u, v, cell_m):
        return strata.reference_horizon(u, v, tectonic_model=TECTONICS, circumference_m=CIRCUMFERENCE,
                                        seed="test-planet", cell_m=cell_m, forcing={"crustal_thickening_index": np.ones(u.shape)})

    def test_neighbouring_maps_agree_at_their_edge(self):
        left_u, left_v = _grid(0.34, 0.35, 0.445, 0.455, 120, 60)
        right_u, right_v = _grid(0.35, 0.36, 0.445, 0.455, 120, 60)
        left = self._horizon(left_u, left_v, 600.0)
        right = self._horizon(right_u, right_v, 600.0)
        np.testing.assert_allclose(left[:, -1], right[:, 0], atol=1e-6)

    def test_child_keeps_parent_surface_and_adds_only_finer_folds(self):
        parent_u, parent_v = _grid(0.34, 0.36, 0.446, 0.454, 161, 61)
        parent = self._horizon(parent_u, parent_v, 600.0)
        child_u, child_v = parent_u[20:41, 40:81], parent_v[20:41, 40:81]
        child = self._horizon(child_u, child_v, 150.0)
        coarse_again = self._horizon(child_u, child_v, 600.0)
        np.testing.assert_allclose(coarse_again, parent[20:41, 40:81], atol=1e-6)
        added = [w for w in strata.fold_wavelengths(150.0) if w not in strata.fold_wavelengths(600.0)]
        bound = sum(strata.FOLD_AMPLITUDE_RATIO * w * strata.PARASITIC_AMPLITUDE_DECAY ** strata.FOLD_WAVELENGTHS_M.index(w) for w in added)
        self.assertLessEqual(float(np.abs(child - parent[20:41, 40:81]).max()), bound + 1e-6)


class InheritanceTests(unittest.TestCase):
    def test_a_child_shows_its_parents_beds_on_mixed_folded_rock(self):
        ids = ["mat_sandstone", "mat_shale", "mat_limestone"]
        seed, n, scale = "test-planet", 120, 4
        parent_u, parent_v = _grid(0.34, 0.344, 0.447, 0.451, n, n)
        forcing = {"crustal_thickening_index": np.ones(parent_u.shape)}
        hills = 400.0 * np.sin(np.linspace(0, 6.0, n))[None, :] * np.cos(np.linspace(0, 4.0, n))[:, None]
        horizon = strata.reference_horizon(parent_u, parent_v, tectonic_model=TECTONICS, circumference_m=CIRCUMFERENCE, seed=seed, cell_m=600.0, forcing=forcing)
        mix = np.stack([np.full(parent_u.shape, share) for share in (0.4, 0.35, 0.25)])
        depth = horizon - hills
        parent, _beds = strata.bed_materials(depth, mix, ids, order=strata.resolved_order(depth, 600.0), seed=seed)
        # A child over the middle: four cells per parent cell, the ground
        # interpolated, the composition its parent's (82 % the drawn rock).
        r0, c0, size = 45, 45, 30
        rows = np.linspace(r0, r0 + size - 1, size * scale)
        columns = np.linspace(c0, c0 + size - 1, size * scale)
        child_u = np.interp(columns, np.arange(n), parent_u[0])[None, :] * np.ones((rows.size, 1))
        child_v = np.interp(rows, np.arange(n), parent_v[:, 0])[:, None] * np.ones((1, columns.size))
        near_r, near_c = np.rint(rows).astype(int)[:, None], np.rint(columns).astype(int)[None, :]
        child_hills = 400.0 * np.sin(columns / (n - 1) * 6.0)[None, :] * np.cos(rows / (n - 1) * 4.0)[:, None]
        child_horizon = strata.reference_horizon(child_u, child_v, tectonic_model=TECTONICS, circumference_m=CIRCUMFERENCE, seed=seed, cell_m=150.0,
                                                 forcing={"crustal_thickening_index": np.ones(child_u.shape)})
        onehot = np.stack([(parent[near_r, near_c] == index).astype(float) for index in range(3)])
        child_mix = 0.82 * onehot + 0.18 * np.stack([np.full(child_u.shape, share) for share in (0.4, 0.35, 0.25)])
        child_depth = child_horizon - child_hills
        child, _beds = strata.bed_materials(child_depth, child_mix, ids, order=strata.resolved_order(child_depth, 150.0), seed=seed)
        mode = np.zeros((size, size), dtype=int)
        for i in range(size):
            for j in range(size):
                mode[i, j] = np.bincount(child[i * scale:(i + 1) * scale, j * scale:(j + 1) * scale].ravel(), minlength=3).argmax()
        window = parent[r0:r0 + size, c0:c0 + size]
        self.assertGreater(len(np.unique(window)), 1)
        agreement = float(np.mean(mode == window))
        chance = float(np.mean(mode == parent[r0 + size:r0 + 2 * size, c0:c0 + size]))
        self.assertGreater(agreement, 0.85)
        self.assertLess(chance, agreement - 0.25)


class BedTests(unittest.TestCase):
    def test_finer_beds_nest_and_mostly_keep_their_formation(self):
        depth = np.linspace(-3000.0, 3000.0, 20_000)[None, :]
        composition = np.stack([np.full(depth.shape, 0.5), np.full(depth.shape, 0.3), np.full(depth.shape, 0.2)])
        ids = ["mat_sandstone", "mat_shale", "mat_limestone"]
        coarse, coarse_beds = strata.bed_materials(depth, composition, ids, order=0, seed="test-planet")
        fine, fine_beds = strata.bed_materials(depth, composition, ids, order=2, seed="test-planet")
        np.testing.assert_array_equal(coarse_beds[0], fine_beds[0])
        np.testing.assert_array_equal(fine_beds[2] // strata.BED_ORDER_RATIO ** 2, fine_beds[0])
        self.assertGreater(float(np.mean(fine == coarse)), 0.5)
        self.assertLess(float(np.mean(fine == coarse)), 0.99)

    def test_order_follows_cell_size_and_bedding_slope(self):
        x = np.linspace(0.0, 1.0, 64)
        gentle = np.add.outer(x, x) * 50.0  # ~1 m per 600 m cell
        steep = np.add.outer(x, x) * 20_000.0
        self.assertGreater(strata.resolved_order(gentle, 600.0), strata.resolved_order(steep, 600.0))
        self.assertGreaterEqual(strata.resolved_order(gentle, 150.0), strata.resolved_order(gentle, 600.0))

    def test_planet_seed_is_the_same_on_every_map(self):
        planet = {"id": "planet_x", "world_gen_seed": {"resolved_map_seed": "seed-1"}}
        region = {"id": "refined_lod2_abc", "refinement_root_planet_id": "planet_x", "world_gen_seed": {"resolved_map_seed": "seed-1"}}
        self.assertEqual(strata.planet_strata_seed(planet), strata.planet_strata_seed(region))


if __name__ == "__main__":
    unittest.main()
