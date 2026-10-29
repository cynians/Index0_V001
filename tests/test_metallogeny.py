"""Ore districts: where a planet's ore-forming processes gather an element."""

import math
import unittest
from pathlib import Path

import numpy as np

from simulations.world_gen import element_pigments as ep
from simulations.world_gen import metallogeny
from simulations.world_gen.natural_materials import configure_material_catalog
from world.persistent_ontology_store import PersistentOntologyStore

ROOT = Path(__file__).resolve().parents[1]
CARD = {"district_share": 0.3, "districts": {"arc_magmatism": 0.68, "rift_basin": 0.22, "spreading_ridge": 0.06, "mantle_plume": 0.04}}


def _tectonics():
    system = {
        "id": "andes", "mechanism": "ocean_continent_subduction",
        "forcing_profile": {"volcanic_construction_peak_m": 3000.0, "rock_uplift_peak_m": 4000.0, "tectonic_subsidence_peak_m": 2000.0,
                            "reference_width": 0.028, "along_strike_variation": {"phase": 0.3, "frequency": 4.0}},
        "sides": {"overriding_normal_side": 1},
    }
    segments = [
        {"id": f"s{index}", "kind": "subduction", "orogen_system_id": "andes", "x1": 0.20 + 0.05 * index, "y1": 0.55,
         "x2": 0.25 + 0.05 * index, "y2": 0.55, "normal_x": 0.0, "normal_y": 1.0, "influence_width": 0.028, "activity_scale": 1.0}
        for index in range(6)
    ]
    return {"map_seed": "test", "boundary_segments": segments, "orogen_system_model": {"systems": [system]}}


class DistrictTests(unittest.TestCase):
    def setUp(self):
        metallogeny._MEAN_CACHE.clear()

    def test_districts_move_copper_without_making_it(self):
        u = (np.arange(256) + 0.5) / 256
        v = (np.arange(128) + 0.5) / 128
        factor = metallogeny.enrichment(u, v, _tectonics(), CARD, "seed")
        area = np.cos((0.5 - v) * math.pi)[:, None] * np.ones_like(factor)
        self.assertAlmostEqual(1.0, float(np.average(factor, weights=area)), delta=0.03)
        self.assertGreater(float(factor.max()), 3.0)
        self.assertAlmostEqual(0.7, float(factor.min()), delta=0.01)

    def test_the_arc_on_the_overriding_plate_gathers_it(self):
        u = np.linspace(0.2, 0.5, 300)
        v = np.linspace(0.45, 0.75, 300)
        factor = metallogeny.enrichment(u, v, _tectonics(), CARD, "seed")
        rows = np.argmax(factor.max(axis=1))
        # The richest row lies on the overriding side (v > trench), off the trench.
        self.assertGreater(v[rows], 0.56)
        self.assertLess(float(factor[-1].max()), 1.0)

    def test_no_district_data_no_districts(self):
        u = np.linspace(0.2, 0.5, 40)
        v = np.linspace(0.45, 0.75, 30)
        np.testing.assert_array_equal(metallogeny.enrichment(u, v, _tectonics(), {}, "seed"), np.ones((30, 40)))

    def test_a_window_reads_the_same_factor(self):
        u = np.linspace(0.2, 0.5, 301)
        v = np.linspace(0.45, 0.75, 301)
        whole = metallogeny.enrichment(u, v, _tectonics(), CARD, "seed")
        window = metallogeny.enrichment(u[100:200], v[50:150], _tectonics(), CARD, "seed")
        np.testing.assert_allclose(window, whole[50:150, 100:200], atol=1e-9)


class PigmentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        configure_material_catalog(PersistentOntologyStore(ROOT / "ontology" / "index0.owl").load_datasets().get("materials") or [])
        ep.clear_caches()

    def _run(self, carbonate, factor=None):
        from simulations.world_gen.natural_materials import reference_element_distribution

        profile = dict(reference_element_distribution())
        profile["Cu"] = 2.0
        env = {"element_pigments": ep.pigment_systems({"element_profile": profile}), "o2_relative": 1.0, "log_pco2_bar": -3.4, "chloride_ratio": 1.0}
        shape = (2, 2)
        district = np.full(shape, factor) if factor is not None else None
        fields = {
            "element_content_percent": {"Cu": ep.mix_content_percent(["mat_basalt"], np.ones((1,) + shape), env["element_pigments"][0], district)},
            "rock_carbonate": np.full(shape, carbonate), "rock_silica": np.full(shape, 1.0 - carbonate), "aridity": np.full(shape, 0.8),
            "wetness": np.full(shape, 0.3), "temperature_k": np.full(shape, 295.0), "runoff_mm": np.full(shape, 5.0),
        }
        kwargs = dict(residence_yr=np.full(shape, 2e5), bedrock=np.zeros(shape), slope=np.zeros(shape))
        return ep.surface_minerals(env, fields, np.ones(shape, bool), **kwargs)[1]["Cu"]

    def test_a_district_holds_more_copper(self):
        self.assertGreater(self._run(0.0, 5.0)["content_mean_wt_percent"], 3.0 * self._run(0.0)["content_mean_wt_percent"])

    def test_over_carbonate_a_district_shows_more_copper_minerals(self):
        self.assertGreater(self._run(0.6, 5.0)["pigment_visible_mean"], self._run(0.6)["pigment_visible_mean"])

    def test_over_unbuffered_rock_its_sulfides_leach_it(self):
        # The district's sulfides make acid: the water carries the copper off
        # (a leached cap), where the same copper over carbonate stays.
        unbuffered, buffered = self._run(0.0, 5.0), self._run(0.6, 5.0)
        self.assertLess(unbuffered["retained_mean"], 0.5 * buffered["retained_mean"])


class DepositTests(unittest.TestCase):
    """Regional copper deposits are weighted by the same district factor."""

    @classmethod
    def setUpClass(cls):
        configure_material_catalog(PersistentOntologyStore(ROOT / "ontology" / "index0.owl").load_datasets().get("materials") or [])

    def setUp(self):
        metallogeny._MEAN_CACHE.clear()

    def test_the_tile_reads_the_planet_factor(self):
        from simulations.world_gen import natural_materials
        from simulations.world_gen.regional_materials import DISTRICT_GRID_NODES, _district_grids

        card = next(item["metallogeny"] for item in natural_materials.MATERIAL_BY_ID.values()
                    if item.get("material_subclass") == "element" and item.get("element_symbol") == "Cu")
        bounds = {"min_u": 0.25, "max_u": 0.45, "min_v": 0.5, "max_v": 0.7}
        grids = _district_grids(_tectonics(), bounds, "seed")
        u = np.linspace(0.25, 0.45, DISTRICT_GRID_NODES)
        v = np.linspace(0.5, 0.7, DISTRICT_GRID_NODES)
        np.testing.assert_allclose(np.asarray(grids["Cu"]["factor"]), metallogeny.enrichment(u, v, _tectonics(), card, "seed"), atol=1e-9)
        self.assertEqual({"arc_magmatism"}, {name for name, rows in grids["Cu"]["contributions"].items() if np.max(rows) > 0.0})
        self.assertEqual({}, _district_grids(_tectonics(), bounds, None))

    def test_copper_minerals_are_copper_deposits(self):
        from simulations.world_gen.regional_materials import _defined_by

        self.assertTrue(_defined_by({"material_id": "mat_chalcopyrite"}, "Cu"))
        self.assertTrue(_defined_by({"material_id": "mat_malachite"}, "Cu"))
        self.assertFalse(_defined_by({"material_id": "mat_quartz"}, "Cu"))

    def _systems(self, copper_percent=0.0028):
        from simulations.world_gen.natural_materials import reference_element_distribution
        from simulations.world_gen.regional_materials import _district_grids, _ore_systems

        profile = dict(reference_element_distribution())
        profile["Cu"] = copper_percent
        grids = _district_grids(_tectonics(), {"min_u": 0.25, "max_u": 0.45, "min_v": 0.5, "max_v": 0.7}, "seed")
        return _ore_systems({"element_profile": profile}, grids), grids

    def test_one_ore_system_its_other_minerals_are_zones(self):
        from simulations.world_gen.regional_materials import _ore_zone

        systems, _grids = self._systems()
        hosts = {system["deposit_host"]: element for element, system in systems.items()}
        self.assertEqual({"mat_chalcopyrite": "Cu"}, hosts)
        for zone in ("mat_malachite", "mat_chalcocite", "mat_covellite", "mat_malachite_azurite_gossan"):
            self.assertTrue(_ore_zone({"material_id": zone}, systems, hosts), zone)
        self.assertFalse(_ore_zone({"material_id": "mat_chalcopyrite"}, systems, hosts))
        self.assertFalse(_ore_zone({"material_id": "mat_galena"}, systems, hosts))

    def test_an_arc_deposit_is_a_pyritic_porphyry(self):
        from simulations.world_gen.regional_materials import _ore_system

        systems, grids = self._systems()
        factor = np.asarray(grids["Cu"]["factor"])
        row, column = np.unravel_index(np.argmax(factor), factor.shape)
        x, y = column / (factor.shape[1] - 1), row / (factor.shape[0] - 1)
        ore = _ore_system(systems["Cu"], grids["Cu"], x, y, seed="tile", material_id="mat_chalcopyrite")
        self.assertEqual(("porphyry_copper", "arc_magmatism"), (ore["style"], ore["district_type"]))
        self.assertTrue(0.3 <= ore["grade_wt_percent"] <= 1.0)
        host_wt = ore["grade_wt_percent"] * 100.0 / systems["Cu"]["primary_hosts"][0]["element_wt_percent"]
        self.assertAlmostEqual(2.0 * host_wt, ore["pyrite_wt_percent"], places=3)

    def test_without_sulfur_to_spare_the_ore_has_no_pyrite(self):
        from simulations.world_gen.regional_materials import _ore_system

        systems, grids = self._systems(copper_percent=2.0)
        self.assertEqual("mat_native_copper", systems["Cu"]["deposit_host"])
        # Outside every district the element's largest district share decides the style.
        empty = {**grids["Cu"], "contributions": {}}
        ore = _ore_system(systems["Cu"], empty, 0.5, 0.5, seed="tile", material_id="mat_native_copper")
        self.assertEqual("porphyry_copper", ore["style"])
        self.assertEqual(0.0, ore["pyrite_wt_percent"])
        self.assertGreater(ore["grade_wt_percent"], 10.0)


if __name__ == "__main__":
    unittest.main()
