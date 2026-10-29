import math
import unittest
from types import SimpleNamespace

from simulations.logistics.capabilities import Shortfall, is_eligible, shortfalls
from simulations.logistics.links import INTERPLANETARY, link_from_transfer_window
from simulations.logistics.vehicle_profiles import design_propulsion_state, space_profile_from_design
from simulations.space.propulsion import G0, Engine, PropulsionState
from simulations.space.transfer import find_direct_windows
from tests.test_space_transfer import body, seconds

YEAR_S = 365.25 * 86_400.0


def component(component_id, categories, mass_kg, **fields):
    return {"id": component_id, "type": "component", "name": component_id, "satisfies_categories": categories,
            "mass_kg": mass_kg, "dimension_length_m": 1.0, "dimension_width_m": 1.0, "dimension_height_m": 1.0,
            **fields}


def craft(*parts, structural_features=()):
    """A vehicle design with one installed instance of each part, and the world it lives in."""
    installed = [
        {"instance_id": f"slot_{index}", "catalog_id": part["id"],
         "local_rect_m": {"x": float(index), "y": 0.0, "w": 1.0, "h": 1.0}}
        for index, part in enumerate(parts)
    ]
    vehicle = {"id": "veh_test_craft", "type": "vehicle", "name": "Test Craft",
               "component_catalog": [part["id"] for part in parts], "installed_components": installed,
               "structural_features": list(structural_features)}
    entities = {part["id"]: part for part in parts}
    return vehicle, SimpleNamespace(get_entity=entities.get)


ENGINE = component("comp_test_engine", ["propulsion_space"], 1500.0, thrust_n=100_000.0, specific_impulse_s=450.0)
TANK = component("comp_test_tank", ["fuel_storage"], 2000.0, propellant_capacity_kg=20_000.0)
SHIELD = component("comp_test_shield", ["structure"], 3000.0, shielding_class="deep_space")
LIFE_SUPPORT = component("comp_test_life_support", ["life_support"], 1500.0, life_support_s=YEAR_S)
DOCKING = component("comp_test_docking", ["docking"], 500.0, docking=True)


class PropulsionTests(unittest.TestCase):
    def test_rocket_equation(self):
        state = PropulsionState(dry_mass_kg=10_000.0, propellant_kg=20_000.0, engines=(Engine(100_000.0, 450.0),))
        self.assertAlmostEqual(450.0 * G0 * math.log(3.0), state.delta_v_m_s(), places=6)

    def test_engines_firing_together_share_one_specific_impulse(self):
        state = PropulsionState(1.0, 1.0, (Engine(100_000.0, 300.0), Engine(100_000.0, 450.0)))
        self.assertAlmostEqual(360.0, state.specific_impulse_s, places=9)

    def test_burns_spend_the_budget_and_add_up(self):
        state = PropulsionState(dry_mass_kg=10_000.0, propellant_kg=20_000.0, engines=(Engine(100_000.0, 450.0),))
        after = state.after_burn(1500.0)
        self.assertAlmostEqual(state.delta_v_m_s(), 1500.0 + after.delta_v_m_s(), places=6)
        used = state.propellant_kg - after.propellant_kg
        self.assertAlmostEqual(used * 450.0 * G0 / 100_000.0, state.burn_time_s(1500.0), places=6)


class ShortfallTests(unittest.TestCase):
    NEEDS = {"delta_v_m_s": 5680.0, "shielding_class": "deep_space", "life_support_s": 2.7e7, "docking": True}

    def test_a_profile_that_meets_every_requirement_is_eligible(self):
        profile = {"delta_v_m_s": 6000.0, "shielding_class": "deep_space", "life_support_s": 3.0e7, "docking": True}
        self.assertTrue(is_eligible(profile, self.NEEDS))

    def test_each_kind_of_term_reports_what_is_short(self):
        profile = {"delta_v_m_s": 4400.0, "shielding_class": "orbital", "docking": False}
        self.assertEqual([
            Shortfall("delta_v_m_s", 5680.0, 4400.0),
            Shortfall("shielding_class", "deep_space", "orbital"),
            Shortfall("life_support_s", 2.7e7, None),
            Shortfall("docking", True, False),
        ], shortfalls(profile, self.NEEDS))
        self.assertTrue(shortfalls(profile, self.NEEDS)[2].unknown)


class DesignProfileTests(unittest.TestCase):
    def test_a_design_profile_reads_the_components_typed_fields(self):
        vehicle, world = craft(ENGINE, TANK, SHIELD, LIFE_SUPPORT, DOCKING)
        profile = space_profile_from_design(vehicle, world)
        dry = 1500.0 + 2000.0 + 3000.0 + 1500.0 + 500.0
        self.assertAlmostEqual(450.0 * G0 * math.log((dry + 20_000.0) / dry), profile["delta_v_m_s"], places=6)
        self.assertEqual("deep_space", profile["shielding_class"])
        self.assertEqual(YEAR_S, profile["life_support_s"])
        self.assertTrue(profile["docking"])
        self.assertFalse(profile["atmosphere_entry"])
        self.assertEqual(20_000.0, design_propulsion_state(vehicle, world).propellant_kg)

    def test_an_engine_without_a_tank_feeding_it_adds_no_delta_v(self):
        vehicle, world = craft(ENGINE, SHIELD)
        self.assertNotIn("delta_v_m_s", space_profile_from_design(vehicle, world))

    def test_untyped_components_leave_terms_unknown_and_a_hull_can_shield(self):
        plain_engine = component("comp_plain_engine", ["propulsion_space"], 1500.0)
        vehicle, world = craft(plain_engine, TANK, structural_features=[
            {"id": "hull", "shielding_class": "orbital", "atmosphere_entry": True},
        ])
        profile = space_profile_from_design(vehicle, world)
        self.assertNotIn("delta_v_m_s", profile)
        self.assertNotIn("life_support_s", profile)
        self.assertEqual("orbital", profile["shielding_class"])
        self.assertTrue(profile["atmosphere_entry"])


class SpaceLinkTests(unittest.TestCase):
    def test_a_transfer_window_becomes_a_link_that_sorts_craft(self):
        window = find_direct_windows(body("Earth"), body("Mars"), seconds("2026-01-01"), count=1)[0]
        link = link_from_transfer_window(window)
        self.assertEqual(INTERPLANETARY, link.domain)
        self.assertEqual(("Earth", "Mars"), (link.origin_id, link.target_id))
        self.assertAlmostEqual(5680.0, link.requirements["delta_v_m_s"], delta=10.0)
        self.assertEqual("deep_space", link.requirements["shielding_class"])
        self.assertEqual(window.leg.tof, link.requirements["life_support_s"])

        # 8.5 t dry, 20 t propellant at 450 s: about 5.34 km/s, short of the window
        vehicle, world = craft(ENGINE, TANK, SHIELD, LIFE_SUPPORT, DOCKING)
        missing = shortfalls(space_profile_from_design(vehicle, world), link.requirements)
        self.assertEqual(["delta_v_m_s"], [item.key for item in missing])

        # a second tank carries it over
        second_tank = dict(TANK, id="comp_test_tank_2")
        vehicle, world = craft(ENGINE, TANK, second_tank, SHIELD, LIFE_SUPPORT, DOCKING)
        self.assertTrue(is_eligible(space_profile_from_design(vehicle, world), link.requirements))


if __name__ == "__main__":
    unittest.main()
