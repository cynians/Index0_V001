import unittest

from simulations.world_gen.geological_noise import fractal_noise_m, gradient_noise_m
from simulations.world_gen.heightmap import _mountain_morphology_mask


class GeologicalNoiseTests(unittest.TestCase):
    def test_physical_noise_is_deterministic(self):
        args = ("planet-seed", "relief", 123_456.7, 88_765.4, 35_000.0)
        self.assertEqual(gradient_noise_m(*args), gradient_noise_m(*args))

    def test_gradient_is_smooth_across_lattice_boundary(self):
        wavelength = 10_000.0
        epsilon = 0.1
        left = gradient_noise_m("seed", "relief", wavelength - epsilon, 2_345.0, wavelength)
        center = gradient_noise_m("seed", "relief", wavelength, 2_345.0, wavelength)
        right = gradient_noise_m("seed", "relief", wavelength + epsilon, 2_345.0, wavelength)
        left_derivative = (center - left) / epsilon
        right_derivative = (right - center) / epsilon
        self.assertAlmostEqual(left_derivative, right_derivative, places=4)

    def test_fractal_noise_reuses_global_coordinates(self):
        first = fractal_noise_m("seed", "mountain", 912_000.0, 411_000.0, 70_000.0)
        # A neighbouring refinement tile reaches the same physical point.
        second = fractal_noise_m("seed", "mountain", 912_000.0, 411_000.0, 70_000.0)
        self.assertEqual(first, second)


class MountainMorphologyMaskTests(unittest.TestCase):
    def test_flat_plain_is_not_mountainous(self):
        rows = [[250.0 for _x in range(11)] for _y in range(11)]
        land = [[True for _x in range(11)] for _y in range(11)]
        mask, _threshold = _mountain_morphology_mask(rows, land, 1_000.0)
        self.assertEqual(0.0, max(max(row) for row in mask))

    def test_relief_is_localized_to_the_resolved_range(self):
        rows = [[100.0 for _x in range(15)] for _y in range(11)]
        for y in range(3, 8):
            for x in range(5, 10):
                rows[y][x] += 1_800.0 - abs(x - 7) * 260.0 - abs(y - 5) * 220.0
        land = [[True for _x in range(15)] for _y in range(11)]
        mask, _threshold = _mountain_morphology_mask(rows, land, 5_000.0)
        self.assertGreater(mask[5][7], 0.35)
        self.assertEqual(0.0, mask[0][0])
        self.assertEqual(0.0, mask[10][14])


if __name__ == "__main__":
    unittest.main()
