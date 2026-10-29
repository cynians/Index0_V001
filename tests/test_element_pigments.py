"""Element pigments: trace elements in rocks, their host minerals and the colours their weathering leaves."""

import unittest
from pathlib import Path

import numpy as np

from simulations.world_gen import element_pigments as ep
from simulations.world_gen.natural_materials import configure_material_catalog
from world.persistent_ontology_store import PersistentOntologyStore

ROOT = Path(__file__).resolve().parents[1]


def setUpModule():
    configure_material_catalog(PersistentOntologyStore(ROOT / "ontology" / "index0.owl").load_datasets().get("materials") or [])
    ep.clear_caches()


def _model(copper_percent):
    from simulations.world_gen.natural_materials import reference_element_distribution

    profile = dict(reference_element_distribution())
    profile["Cu"] = copper_percent
    return {"element_profile": profile}


def _env(copper_percent, o2_relative=1.0):
    return {
        "element_pigments": ep.pigment_systems(_model(copper_percent)),
        "o2_relative": o2_relative,
        "log_pco2_bar": -3.4,
        "chloride_ratio": 1.0,
    }


def _render(env, *, aridity, runoff_mm, carbonate=0.0, silica=1.0, wetness=0.3, deposit=None, temperature_k=295.0):
    shape = (4, 4)
    copper = env["element_pigments"][0]
    fields = {
        # Basalt (90 ppm on Earth) on this planet.
        "element_content_percent": {"Cu": ep.mix_content_percent(["mat_basalt"], np.ones((1,) + shape), copper)},
        "element_deposits": {"Cu": {key: np.full(shape, value, dtype=np.float32) for key, value in (deposit or {}).items()}},
        "rock_carbonate": np.full(shape, carbonate, dtype=np.float32),
        "rock_silica": np.full(shape, silica, dtype=np.float32),
        "aridity": np.full(shape, aridity, dtype=np.float32),
        "wetness": np.full(shape, wetness, dtype=np.float32),
        "temperature_k": np.full(shape, temperature_k, dtype=np.float32),
        "runoff_mm": np.full(shape, runoff_mm, dtype=np.float32),
    }
    fractions, diagnostics = ep.surface_minerals(
        env, fields, np.ones(shape, dtype=bool),
        residence_yr=np.full(shape, 2.0e5, dtype=np.float32),
        bedrock=np.zeros(shape, dtype=np.float32), slope=np.zeros(shape, dtype=np.float32),
    )
    return {key: float(value[0, 0]) for key, value in fractions.items()}, diagnostics.get("Cu") or {}


class OntologyDataTests(unittest.TestCase):
    def test_copper_behaviour_is_complete(self):
        systems = {system["element"]: system for system in ep.pigment_systems(_model(0.0028))}
        copper = systems["Cu"]
        self.assertGreaterEqual(len(copper["secondary_phases"]), 5)
        for phase in copper["secondary_phases"]:
            self.assertGreater(phase["element_wt_percent"], 30.0, phase["material_id"])
            for bounds in phase["niche"].values():
                self.assertEqual(4, len(bounds))
                self.assertEqual(sorted(bounds), bounds, phase["material_id"])
        self.assertEqual(0.009, ep.material_reference_percent("mat_basalt", "Cu"))
        self.assertIsNone(ep.material_reference_percent("mat_not_a_material", "Cu"))


class HostTests(unittest.TestCase):
    def test_sulfur_decides_the_primary_host(self):
        earth = {host["material_id"]: host["share"] for host in ep.pigment_systems(_model(0.0028))[0]["primary_hosts"]}
        self.assertEqual({"mat_chalcopyrite": 1.0}, earth)
        rich = {host["material_id"]: host["share"] for host in ep.pigment_systems(_model(2.0))[0]["primary_hosts"]}
        # Earth's sulfur holds a few percent of 2 % copper as chalcocite; the rest is native.
        self.assertGreater(rich["mat_native_copper"], 0.85)
        self.assertIn("mat_chalcocite", rich)


class WeatheringTests(unittest.TestCase):
    def test_earth_copper_leaves_no_visible_minerals(self):
        minerals, diagnostics = _render(_env(0.0028), aridity=0.8, runoff_mm=5.0)
        self.assertLess(sum(minerals.values()), 0.01)
        self.assertLess(diagnostics["pigment_visible_mean"], 0.01)

    def test_dry_silicate_ground_shows_chrysocolla(self):
        minerals, diagnostics = _render(_env(2.0), aridity=0.8, runoff_mm=5.0)
        self.assertGreater(diagnostics["pigment_visible_mean"], 0.2)
        self.assertEqual("mat_chrysocolla", max(minerals, key=minerals.get))
        self.assertLess(sum(minerals.values()), 1.0)

    def test_humid_ground_loses_its_copper(self):
        _dry, dry = _render(_env(2.0), aridity=0.8, runoff_mm=5.0)
        _wet, wet = _render(_env(2.0), aridity=0.05, runoff_mm=800.0, wetness=0.9)
        self.assertLess(wet["pigment_visible_mean"], 0.2 * dry["pigment_visible_mean"])

    def test_carbonate_buffer_keeps_copper_in_humid_ground(self):
        _silicate, silicate = _render(_env(2.0), aridity=0.05, runoff_mm=800.0, wetness=0.9)
        _carbonate, carbonate = _render(_env(2.0), aridity=0.05, runoff_mm=800.0, wetness=0.9, carbonate=0.8, silica=0.2)
        self.assertGreater(carbonate["retained_mean"], 5.0 * silicate["retained_mean"])
        self.assertGreater(carbonate["phase_mean_wt_percent"]["mat_malachite"], 0.0)

    def test_massive_copper_keeps_its_patina_in_rain(self):
        # Water saturates over the patina and carries off only what it can
        # dissolve: a copper world's humid ground stays green.
        minerals, diagnostics = _render(_env(45.0), aridity=0.05, runoff_mm=800.0, wetness=0.9)
        self.assertGreater(diagnostics["retained_mean"], 0.5)
        self.assertGreater(diagnostics["pigment_visible_mean"], 0.5)
        self.assertEqual("mat_malachite", max(minerals, key=minerals.get))

    def test_reducing_air_keeps_the_fresh_hosts(self):
        minerals, diagnostics = _render(_env(2.0, o2_relative=0.0), aridity=0.8, runoff_mm=5.0)
        self.assertEqual(0.0, diagnostics["oxidized_mean"])
        self.assertEqual(0.0, diagnostics["pigment_visible_mean"])
        self.assertGreater(diagnostics["fresh_host_mean_wt_percent"], 1.0)
        self.assertGreater(minerals.get("mat_native_copper", 0.0), 0.0)
        self.assertNotIn("mat_chrysocolla", minerals)


# A porphyry ore body over 40 % of the cell: 0.8 % Cu as chalcopyrite (2.3 wt%)
# with twice its mass of pyrite.
PORPHYRY = {"share": 0.4, "content_percent": 0.4 * 0.8, "pyrite_wt": 0.4 * 4.6}
IRON_OXIDES = ("mat_goethite", "mat_hematite")
COPPER_MINERALS = ("mat_malachite", "mat_azurite", "mat_chrysocolla", "mat_atacamite", "mat_brochantite", "mat_tenorite")


def _sum(minerals, ids):
    return sum(minerals.get(material_id, 0.0) for material_id in ids)


class OreSystemTests(unittest.TestCase):
    """An ore body weathers by the same rules: leached cap, oxide zone or fresh sulfides."""

    def test_a_pyritic_deposit_on_silicate_rock_leaves_a_leached_cap(self):
        minerals, diagnostics = _render(_env(0.0028), aridity=0.4, runoff_mm=300.0, deposit=PORPHYRY)
        self.assertGreater(_sum(minerals, IRON_OXIDES), 0.1)
        self.assertGreater(_sum(minerals, IRON_OXIDES), 5.0 * _sum(minerals, COPPER_MINERALS))
        self.assertLess(diagnostics["retained_mean"], 0.1)

    def test_over_carbonate_the_copper_stays(self):
        silicate, _ = _render(_env(0.0028), aridity=0.4, runoff_mm=300.0, deposit=PORPHYRY)
        carbonate, _ = _render(_env(0.0028), aridity=0.4, runoff_mm=300.0, deposit=PORPHYRY, carbonate=0.8, silica=0.2)
        self.assertGreater(_sum(carbonate, COPPER_MINERALS), 3.0 * _sum(silicate, COPPER_MINERALS))
        self.assertGreater(carbonate.get("mat_malachite", 0.0), 0.0)

    def test_warm_dry_caps_are_red_humid_ones_yellow_brown(self):
        dry, _ = _render(_env(0.0028), aridity=0.85, runoff_mm=10.0, deposit=PORPHYRY, temperature_k=300.0)
        humid, _ = _render(_env(0.0028), aridity=0.1, runoff_mm=600.0, wetness=0.8, deposit=PORPHYRY)
        self.assertGreater(dry.get("mat_hematite", 0.0), dry.get("mat_goethite", 0.0))
        self.assertGreater(humid.get("mat_goethite", 0.0), humid.get("mat_hematite", 0.0))

    def test_reducing_air_keeps_the_ore_fresh(self):
        minerals, _ = _render(_env(0.0028, o2_relative=0.0), aridity=0.4, runoff_mm=300.0, deposit=PORPHYRY)
        self.assertGreater(minerals.get("mat_pyrite", 0.0), minerals.get("mat_chalcopyrite", 0.0))
        self.assertGreater(minerals.get("mat_chalcopyrite", 0.0), 0.0)
        self.assertEqual(0.0, _sum(minerals, IRON_OXIDES + COPPER_MINERALS))


class MixContentTests(unittest.TestCase):
    """Each material of the mix brings its own copper."""

    def _content(self, material_id, copper_percent=2.0, factor=None):
        system = ep.pigment_systems(_model(copper_percent))[0]
        district = np.full((1, 1), factor) if factor is not None else None
        return float(ep.mix_content_percent([material_id], np.ones((1, 1, 1)), system, district)[0, 0])

    def test_districts_enrich_rock_not_wind_blown_cover(self):
        self.assertGreater(self._content("mat_basalt", factor=4.0), 3.0 * self._content("mat_basalt"))
        self.assertAlmostEqual(self._content("mat_loess"), self._content("mat_loess", factor=4.0), places=6)

    def test_a_material_without_data_is_the_mean_crust(self):
        self.assertAlmostEqual(2.0, self._content("mat_not_a_material"), places=4)

    def test_a_mineral_keeps_its_formula(self):
        earth = self._content("mat_chalcopyrite", copper_percent=0.0028)
        self.assertAlmostEqual(earth, self._content("mat_chalcopyrite", copper_percent=2.0), places=4)
        self.assertGreater(earth, 30.0)


class MapLayerTests(unittest.TestCase):
    def test_minerals_take_their_share_and_the_rest_gives_way(self):
        from simulations.world_gen.material_lod import _overlay_element_minerals

        visible = np.stack([np.full((3, 3), 0.7), np.full((3, 3), 0.3)])
        ids, layers = _overlay_element_minerals(["mat_basalt", "mat_loess"], visible, ["mat_chrysocolla"], np.full((1, 3, 3), 0.2))
        self.assertEqual(ids, ["mat_basalt", "mat_loess", "mat_chrysocolla"])
        np.testing.assert_allclose(layers.sum(axis=0), 1.0, atol=1e-6)
        np.testing.assert_allclose(layers[0], 0.56, atol=1e-6)

    def test_a_visible_share_is_not_boosted_as_a_coating(self):
        from simulations.world_gen.true_color import _mix_areal_endmembers
        import pygame

        pygame.init()
        size = (2, 2)

        def layer(material_id, alpha, green, mode, **extra):
            surface = pygame.Surface(size, pygame.SRCALPHA)
            surface.fill((0, 0, 0, int(round(alpha * 255))))
            colour = {"red_650nm": 0.1, "green_550nm": green, "blue_450nm": 0.1}
            return {"material_id": material_id, "surface": surface, "fraction_semantics": "areal_surface_fraction",
                    "optical_surface_profile": {"visible_reflectance": colour, "weathered_visible_reflectance": colour,
                                                "weathering_color_response": 0.0, "mixing_mode": mode,
                                                "optical_coloring_power": 2.2, "optical_opacity_depth_mm": 2.0}, **extra}

        exposure = {"one": np.ones((2, 2))}
        rock = layer("mat_test_rock", 0.8, 0.1, "intimate")
        plain, _ = _mix_areal_endmembers([rock, layer("mat_test_mineral", 0.2, 0.5, "coating", visible_fraction=True)], (0.1, 0.1, 0.1), exposure, size)
        boosted, _ = _mix_areal_endmembers([rock, layer("mat_test_mineral", 0.2, 0.5, "coating")], (0.1, 0.1, 0.1), exposure, size)
        # As a visible share the mineral weighs exactly its 20 % (0.8 x 0.1 + 0.2 x 0.5); as a coating more.
        self.assertAlmostEqual(float(plain[0, 0, 1]), 0.18, delta=0.005)
        self.assertGreater(float(boosted[0, 0, 1]), float(plain[0, 0, 1]) + 0.005)

if __name__ == "__main__":
    unittest.main()
