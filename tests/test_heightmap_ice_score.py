import unittest

from simulations.world_gen.heightmap import _ice_score


class IceScoreTests(unittest.TestCase):
    """Regression coverage for the equatorial-glaciation bug: a merely-tall
    equatorial peak used to outrank genuine polar cells in the top-N ice
    quota selection (heightmap.py's target_ice_fraction selector), because
    elevation contributed to the score flatly instead of being gated by
    latitude. See tests/test_bioregion_simulation.py-adjacent session notes
    for the reproduction (planet_test_9's "Island Slice Subregion").
    """

    def test_max_elevation_at_equator_does_not_outrank_low_elevation_pole(self):
        # ny=0.5 is the true equator; nx/map_seed only drive a small +-0.16
        # noise term, so pin them for a deterministic comparison.
        equatorial_peak_score = _ice_score(
            0.5, 0.5, elevation=1000.0, min_elevation=0.0, max_elevation=1000.0,
            map_seed="test",
        )
        polar_lowland_score = _ice_score(
            0.5, 0.0, elevation=0.0, min_elevation=0.0, max_elevation=1000.0,
            map_seed="test",
        )
        # Even worst-case noise (+-0.16 total across both ridge terms) must
        # not let the equatorial peak win.
        self.assertLess(equatorial_peak_score + 0.16, polar_lowland_score - 0.16)

    def test_elevation_contributes_little_at_the_true_equator(self):
        equatorial_lowland = _ice_score(
            0.5, 0.5, elevation=0.0, min_elevation=0.0, max_elevation=1000.0,
            map_seed="test",
        )
        equatorial_peak = _ice_score(
            0.5, 0.5, elevation=1000.0, min_elevation=0.0, max_elevation=1000.0,
            map_seed="test",
        )
        # Elevation is gated by latitude_polarity (0 at the equator), so the
        # equatorial elevation swing should stay within the noise term's
        # range rather than meaningfully separating the two scores.
        self.assertLess(abs(equatorial_peak - equatorial_lowland), 0.34)

    def test_elevation_still_matters_at_high_latitude(self):
        polar_lowland = _ice_score(
            0.5, 0.05, elevation=0.0, min_elevation=0.0, max_elevation=1000.0,
            map_seed="test",
        )
        polar_peak = _ice_score(
            0.5, 0.05, elevation=1000.0, min_elevation=0.0, max_elevation=1000.0,
            map_seed="test",
        )
        self.assertGreater(polar_peak, polar_lowland)


if __name__ == "__main__":
    unittest.main()
