"""Element distribution -> atmosphere, climate, seas and ices (volatile_budget)."""

import unittest
from pathlib import Path

from simulations.world_gen import material_chemistry as chem
from simulations.world_gen import natural_materials
from simulations.world_gen.atmosphere import derive_atmosphere_model
from simulations.world_gen.crust import estimate_crust_density_kg_m3
from simulations.world_gen.interior_regime import derive_interior_regime_model
from simulations.world_gen.planetary_physics import derive_planet_physics
from simulations.world_gen.terrain_seed import derive_terrain_seed_model
from simulations.world_gen.true_color import surface_liquid_colors
from simulations.world_gen.volatile_budget import (
    apply_volatile_budget_to_seed,
    budget_matches_inputs,
    derive_volatile_budget,
    hydrogen_percent_for_water_index,
    oxygen_demand_percent,
)
from simulations.world_gen.world_gen_sim import WorldGenSimulation
from world.persistent_ontology_store import PersistentOntologyStore

ROOT = Path(__file__).resolve().parents[1]

# Earth's crust plus oceans and air (0.45 % H, 0.022 % N).
EARTH = [("O", 48.5), ("Si", 27.0), ("Al", 7.9), ("Fe", 4.9), ("Ca", 3.5), ("Na", 2.7), ("K", 2.5), ("Mg", 2.05),
         ("H", 0.45), ("Ti", 0.37), ("C", 0.32), ("Mn", 0.075), ("P", 0.064), ("F", 0.055), ("Cl", 0.036),
         ("S", 0.034), ("N", 0.022)]
# Ice-rich, carbon- and nitrogen-bearing (Titan-like).
TITAN = [("O", 58.0), ("H", 7.3), ("Si", 10.0), ("Fe", 6.0), ("Mg", 5.0), ("C", 2.5), ("N", 1.8), ("S", 1.0),
         ("Na", 0.5), ("Cl", 0.3)]
# Taylor & McLennan average Martian crust.
MARS = [("O", 44.5), ("Si", 23.04), ("Fe", 14.15), ("Al", 5.56), ("Mg", 5.46), ("Ca", 4.95), ("Na", 2.20),
        ("S", 1.2), ("Ti", 0.59), ("Cl", 0.5), ("P", 0.39), ("K", 0.37), ("Mn", 0.28), ("Cr", 0.25), ("H", 0.2),
        ("Ni", 0.045), ("C", 0.01)]


def setUpModule():
    natural_materials.configure_material_catalog(
        PersistentOntologyStore(ROOT / "ontology" / "index0.owl").load_datasets().get("materials") or []
    )


def _seed(rows, **overrides):
    seed = {
        "radius_earth": 1.0, "core_radius_fraction": 0.55, "crust_thickness_km": 35.0,
        "angular_velocity_deg_per_hour": 15.0, "tectonics_mode": "unknown", "system_age_gyr": 4.5,
        "crust_composition": {"major_elements": [{"symbol": s, "abundance_percent": v} for s, v in rows]},
    }
    seed.update(overrides)
    return seed


def _physics(seed):
    return derive_planet_physics(seed, estimate_crust_density_kg_m3(seed["crust_composition"]))


def _budget(rows, au, **overrides):
    seed = _seed(rows, **overrides)
    return seed, derive_volatile_budget(seed, _physics(seed), 1.0, au)


TITAN_BODY = dict(radius_earth=0.404, core_radius_fraction=0.4, crust_thickness_km=100.0,
                  angular_velocity_deg_per_hour=0.94, tectonics_mode="inactive")
MARS_BODY = dict(radius_earth=0.532, core_radius_fraction=0.5, crust_thickness_km=50.0, tectonics_mode="stagnant_lid")


class EarthLikeTests(unittest.TestCase):
    def test_earth_inventory_at_one_au_is_earth(self):
        _seed_, budget = _budget(EARTH, 1.0)
        self.assertAlmostEqual(288.0, budget["surface_temperature_k"], delta=6.0)
        self.assertAlmostEqual(1.0, budget["surface_pressure_bar"], delta=0.25)
        composition = budget["composition"]
        self.assertEqual("N2", next(iter(composition)))
        self.assertLess(composition.get("CO2", 0.0), 1e-3)
        self.assertLess(composition.get("O2", 0.0), 0.01)
        self.assertEqual("water", budget["surface_liquid"]["fluid"])
        self.assertTrue(1500.0 < budget["surface_liquid"]["global_depth_m"] < 4000.0)
        self.assertGreater(budget["carbonate_locked_co2_kg"], 1e20)
        self.assertFalse(budget["runaway_greenhouse"])
        self.assertEqual("temperate_nitrogen", budget["atmosphere_class"])
        self.assertEqual("earthlike", budget["derived_seed"]["volatile_inventory"])

    def test_same_inventory_at_venus_orbit_runs_away(self):
        _seed_, budget = _budget(EARTH, 0.723, tectonics_mode="stagnant_lid")
        self.assertTrue(budget["runaway_greenhouse"])
        self.assertEqual("CO2", next(iter(budget["composition"])))
        self.assertGreater(budget["surface_pressure_bar"], 20.0)
        self.assertGreater(budget["surface_temperature_k"], 500.0)
        self.assertIsNone(budget["surface_liquid"]["fluid"])
        self.assertEqual(0.0, budget["derived_seed"]["water_fraction"])

    def test_same_inventory_further_out_builds_co2_instead_of_freezing_solid(self):
        _seed_, near = _budget(EARTH, 1.0)
        _seed_, far = _budget(EARTH, 1.3)
        self.assertGreater(far["composition"].get("CO2", 0.0), 10.0 * near["composition"].get("CO2", 0.0))
        self.assertGreater(far["surface_temperature_k"], far["equilibrium_temperature_k"] + 40.0)

    def test_dense_nitrogen_warms_without_running_away(self):
        rows = [row if row[0] != "N" else ("N", 0.1) for row in EARTH]
        _seed_, budget = _budget(rows, 1.0)
        self.assertFalse(budget["runaway_greenhouse"])
        self.assertTrue(290.0 < budget["surface_temperature_k"] < 330.0)
        self.assertEqual("water", budget["surface_liquid"]["fluid"])

    def test_hydrogen_decides_the_oceans(self):
        dry = [row if row[0] != "H" else ("H", 0.12) for row in EARTH]
        _seed_, budget = _budget(dry, 1.0)
        self.assertLess(budget["surface_liquid"]["global_depth_m"], 100.0)
        wet = [row if row[0] != "H" else ("H", 0.9) for row in EARTH]
        _seed_, budget = _budget([row if row[0] != "O" else ("O", 52.0) for row in wet], 1.0)
        self.assertGreater(budget["surface_liquid"]["global_depth_m"], 5000.0)


class ExoticWorldTests(unittest.TestCase):
    def test_titan_inventory_gives_methane_seas_under_nitrogen(self):
        _seed_, budget = _budget(TITAN, 9.54, **TITAN_BODY)
        self.assertEqual("icy", budget["exchange_regime"])
        self.assertEqual("reducing", budget["speciation"]["redox_state"])
        self.assertEqual("N2", next(iter(budget["composition"])))
        self.assertTrue(0.01 < budget["composition"]["CH4"] < 0.15)
        self.assertTrue(80.0 < budget["surface_temperature_k"] < 110.0)
        self.assertEqual("methane_ethane", budget["surface_liquid"]["fluid"])
        self.assertEqual("methane_ethane", budget["derived_seed"]["surface_fluid"])
        self.assertNotIn("H2O", budget["condensates"], "the water ice crust is bedrock, not a sea")
        self.assertEqual("methane_nitrogen", budget["atmosphere_class"])

    def test_mars_inventory_keeps_thin_co2_and_ice(self):
        _seed_, budget = _budget(MARS, 1.524, **MARS_BODY)
        self.assertLess(budget["surface_pressure_bar"], 0.1)
        self.assertEqual("CO2", next(iter(budget["composition"])))
        self.assertIsNone(budget["surface_liquid"]["fluid"])
        self.assertEqual("ice", budget["condensates"]["H2O"]["phase"])

    def test_small_airless_body(self):
        _seed_, budget = _budget(EARTH, 1.0, radius_earth=0.27, crust_thickness_km=40.0, tectonics_mode="inactive")
        self.assertEqual("exosphere", budget["atmosphere_class"])
        self.assertEqual({}, budget["composition"])
        self.assertEqual("none", budget["derived_seed"]["volatile_inventory"])


class PipelineTests(unittest.TestCase):
    def test_atmosphere_regime_and_terrain_follow_the_budget(self):
        seed = _seed(TITAN, orbital_body_class="planet", **TITAN_BODY)
        physics = _physics(seed)
        atmosphere = derive_atmosphere_model(seed, physics, 1.0, 9.54)
        budget = atmosphere["volatile_budget"]
        self.assertAlmostEqual(budget["surface_pressure_bar"], atmosphere["surface_pressure_bar"])
        self.assertAlmostEqual(budget["surface_temperature_k"], atmosphere["estimated_surface_temperature_k"])
        self.assertEqual("N2", atmosphere["composition"][0]["molecule"])
        self.assertEqual("methane_haze_and_clouds", atmosphere["cloud_model"]["cloud_class"])
        regime = derive_interior_regime_model(seed, physics, atmosphere)
        surface = regime["surface_processes"]
        self.assertFalse(surface["liquid_water_possible"])
        self.assertTrue(surface["alternate_surface_fluid_possible"])
        terrain = derive_terrain_seed_model(seed, physics, atmosphere, regime)
        hydrology = terrain["hydrology"]
        self.assertEqual("methane_ethane", hydrology["surface_fluid"])
        self.assertAlmostEqual(budget["surface_liquid"]["global_depth_m"], hydrology["equivalent_global_water_depth_m"], delta=budget["surface_liquid"]["global_depth_m"] * 0.07)

    def test_stored_budget_is_reused_only_while_inputs_match(self):
        seed = _seed(EARTH)
        budget = derive_volatile_budget(seed, _physics(seed), 1.0, 1.0)
        apply_volatile_budget_to_seed(seed, budget)
        self.assertTrue(budget_matches_inputs(budget, seed, 1.0, 1.0))
        self.assertFalse(budget_matches_inputs(budget, seed, 1.0, 1.2))
        self.assertEqual(budget["derived_seed"]["water_fraction"], seed["water_fraction"])

    def test_rock_chemistry_excludes_the_oceans(self):
        seed = _seed(EARTH)
        apply_volatile_budget_to_seed(seed, derive_volatile_budget(seed, _physics(seed), 1.0, 1.0))
        reference = natural_materials.reference_crust_percent()
        inventory = chem.planet_element_distribution(seed["crust_composition"], reference, rock_only=False)
        rock = chem.planet_element_distribution(seed["crust_composition"], reference)
        self.assertAlmostEqual(0.45, inventory["H"], delta=0.01)
        self.assertTrue(0.1 < rock["H"] < 0.22, rock["H"])
        self.assertAlmostEqual(100.0, sum(value for key, value in rock.items() if key in dict(EARTH)), delta=1.5)

    def test_hydrogen_for_water_index_round_trips(self):
        hydrogen = hydrogen_percent_for_water_index(0.71, 35.0)
        self.assertAlmostEqual(0.45, hydrogen, delta=0.03)
        rows = [row if row[0] != "H" else ("H", hydrogen) for row in EARTH]
        _seed_, budget = _budget(rows, 1.0)
        self.assertAlmostEqual(0.71, budget["derived_seed"]["water_fraction"], delta=0.05)

    def test_randomizer_keeps_the_template_redox(self):
        base = [{"symbol": symbol, "abundance_percent": value} for symbol, value in EARTH]
        jittered = [dict(row, abundance_percent=row["abundance_percent"] * (1.2 if row["symbol"] in {"Fe", "Ca"} else 0.9)) for row in base]
        WorldGenSimulation._rebalance_oxygen(jittered, base)

        def ratio(rows):
            values = {row["symbol"]: row["abundance_percent"] for row in rows}
            return values["O"] / oxygen_demand_percent({key: value for key, value in values.items() if key != "O"})

        self.assertAlmostEqual(ratio(base), ratio(jittered), places=6)

    def test_every_earth_like_template_makes_an_ocean_planet(self):
        for template_id in ("silicate_terrestrial", "oxygenated_ocean_plate_world", "ocean_world"):
            rows = WorldGenSimulation.PLANET_TEMPLATES[template_id]["major_elements"]
            _seed_, budget = _budget(rows, 1.0, tectonics_mode="mobile_lid")
            with self.subTest(template_id):
                self.assertEqual("water", budget["surface_liquid"]["fluid"])
                self.assertEqual("oxidized", budget["speciation"]["redox_state"])
                self.assertTrue(275.0 < budget["surface_temperature_k"] < 305.0)

    def test_ice_sheets_are_limited_by_the_water_inventory(self):
        from simulations.world_gen.world_gen_sim import ice_cover_limit, ice_mask_with_freezing_climate

        _seed_, mars = _budget(MARS, 1.524, **MARS_BODY)
        limit = ice_cover_limit({"volatile_budget": mars})
        self.assertLess(limit, 0.05)
        rows = [[False] * 16 for _ in range(8)]
        warmest = [[200.0 + abs(y - 3.5) * -4.0 for _x in range(16)] for y in range(8)]
        capped, _changed = ice_mask_with_freezing_climate(rows, warmest, max_ice_fraction=0.2)
        uncapped, _changed = ice_mask_with_freezing_climate(rows, warmest)
        self.assertEqual(16 * 8, sum(map(sum, uncapped)))
        self.assertLess(sum(map(sum, capped)), 16 * 8 * 0.5)
        self.assertTrue(all(capped[0]) and not any(capped[4]), "the coldest (polar) cells freeze first")
        _seed_, titan = _budget(TITAN, 9.54, **TITAN_BODY)
        self.assertIsNone(ice_cover_limit({"volatile_budget": titan}), "an ice crust is bedrock, not a limited sheet")

    def test_thin_frozen_inventory_is_polar_ice_not_a_frozen_sea(self):
        regime = {"interior": {"tectonic_regime": "stagnant_lid"}, "surface_processes": {"hydrologic_cycle": "none"}}
        physics = {"radius_earth": 0.53, "radius_m": 3_390_000.0, "surface_gravity_g": 0.38}

        def terrain(frozen_depth):
            atmosphere = {"surface_pressure_bar": 0.02, "estimated_surface_temperature_k": 215.0, "volatile_budget": {
                "derived_seed": {"water_fraction": 0.3, "surface_fluid": "water", "surface_liquid_depth_m": 0.0,
                                 "frozen_ocean_depth_m": frozen_depth}}}
            return derive_terrain_seed_model({"map_seed": "frozen"}, physics, atmosphere, regime)["hydrology"]

        self.assertEqual(0.0, terrain(12.0)["equivalent_global_water_depth_m"])
        self.assertFalse(terrain(12.0)["frozen_ocean_possible"])
        self.assertGreater(terrain(2800.0)["equivalent_global_water_depth_m"], 2500.0)
        self.assertTrue(terrain(2800.0)["frozen_ocean_possible"])

    def test_liquid_colours_follow_the_fluid(self):
        water = surface_liquid_colors("water")[1]
        methane = surface_liquid_colors("methane_ethane")[1]
        self.assertLess(sum(methane), sum(water))
        self.assertGreater(water[2], water[0], "deep water is blue")
        self.assertEqual(surface_liquid_colors("methane_ethane"), surface_liquid_colors("liquid methane"))


def _roster(rows, au, planet_id="planet_generated", **overrides):
    seed = _seed(rows, planet_id=planet_id, **overrides)
    apply_volatile_budget_to_seed(seed, derive_volatile_budget(seed, _physics(seed), 1.0, au))
    tags = natural_materials.derive_planet_material_tags(seed)
    model = natural_materials.derive_natural_material_model(seed["crust_composition"], tags)
    return {item["material_id"]: item for item in model["likely_materials"]}, set(tags)


class SurfaceConsistencyTests(unittest.TestCase):
    """Roadmap phase 1: the rocks and ices agree with the budget."""

    def test_biogenic_rocks_only_on_earth(self):
        generated, _tags = _roster(EARTH, 1.0, tectonics_mode="mobile_lid")
        earth, tags = _roster(EARTH, 1.0, planet_id="planet_earth", tectonics_mode="mobile_lid")
        self.assertIn("biosphere_history", tags)
        for material_id in ("mat_chalk", "mat_coquina", "mat_lignite", "mat_oil_shale"):
            with self.subTest(material_id):
                self.assertNotIn(material_id, generated)
                self.assertIn(material_id, earth)
        self.assertIn("mat_limestone", generated, "abiotic carbonate stays")

    def test_reducing_world_has_no_oxidized_phases(self):
        roster, tags = _roster(TITAN, 9.54, **TITAN_BODY)
        self.assertIn("reducing_surface", tags)
        self.assertNotIn("oxidizing_surface", tags)
        self.assertNotIn("weathered_surface", tags, "methane rain does not weather rock into clays")
        for material_id in ("mat_limestone", "mat_marble", "mat_gypsum", "mat_hematite", "mat_goethite",
                            "mat_calcrete", "mat_carbon_dioxide_ice"):
            with self.subTest(material_id):
                self.assertNotIn(material_id, roster)
        self.assertIn("mat_graphite", roster)
        self.assertIn("mat_water_ice", roster)

    def test_oxidized_desert_keeps_sulfates_iron_oxides_and_its_ices(self):
        roster, tags = _roster(MARS, 1.524, **MARS_BODY)
        self.assertIn("oxidizing_surface", tags)
        self.assertIn("volatile_ice_co2", tags, "winter poles cold-trap CO2")
        for material_id in ("mat_gypsum", "mat_hematite", "mat_water_ice", "mat_carbon_dioxide_ice"):
            with self.subTest(material_id):
                self.assertIn(material_id, roster)

    def test_ices_need_a_condensing_volatile(self):
        earth, tags = _roster(EARTH, 1.0, tectonics_mode="mobile_lid")
        self.assertIn("mat_water_ice", earth)
        self.assertNotIn("mat_carbon_dioxide_ice", earth)
        venus, _tags = _roster(EARTH, 0.723, tectonics_mode="stagnant_lid")
        self.assertNotIn("mat_water_ice", venus)

    def test_climate_contrast_follows_the_atmosphere(self):
        from simulations.world_gen.volatile_budget import meridional_contrast_factor

        self.assertAlmostEqual(1.0, meridional_contrast_factor(1.0, 1.0, 288.0), delta=0.05)
        self.assertLess(meridional_contrast_factor(1.0, 0.14, 93.0), 0.1, "Titan: a few kelvin pole to equator")
        self.assertGreater(meridional_contrast_factor(0.006, 0.38, 210.0), 1.3, "Mars: larger than Earth")

    def test_planet_climate_grid_averages_to_the_budget_temperature(self):
        from simulations.world_gen.water_cycle import _anchor_area_weighted_mean

        rows = [[250.0 + 10.0 * y for _x in range(4)] for y in range(6)]
        anchored = _anchor_area_weighted_mean(rows, 288.0)
        import math

        weights = [math.cos((0.5 - (y + 0.5) / 6) * math.pi) for y in range(6)]
        mean = sum(anchored[y][0] * weights[y] for y in range(6)) / sum(weights)
        self.assertAlmostEqual(288.0, mean, places=2)


class NobleMetalOxygenTests(unittest.TestCase):
    def test_copper_does_not_take_the_volatiles_oxygen(self):
        """Copper oxides are less stable than water: a copper-heavy crust keeps Earth's redox."""
        from simulations.world_gen.volatile_budget import _speciate

        earth = dict(WorldGenSimulation.PLANET_TEMPLATES["silicate_terrestrial"]["major_elements"])
        copper = {symbol: value * 0.7 for symbol, value in earth.items()}
        copper["Cu"] = 0.3 * sum(earth.values())
        _species, earth_info = _speciate(earth)
        species, copper_info = _speciate(copper)
        self.assertEqual(earth_info["redox_state"], copper_info["redox_state"])
        self.assertEqual(0.0, species["CH4"])

    def test_native_copper_keeps_the_air_poorer_in_oxygen(self):
        """Metal the budget cannot oxidize stays native and is a surface sink for abiotic O2."""
        from simulations.world_gen.volatile_budget import _speciate, abiotic_oxygen

        earth = dict(WorldGenSimulation.PLANET_TEMPLATES["silicate_terrestrial"]["major_elements"])
        copper = {symbol: value * 0.55 for symbol, value in earth.items()}
        copper["Cu"] = 0.45 * sum(earth.values())
        _species, earth_info = _speciate(earth)
        _species, copper_info = _speciate(copper)
        self.assertEqual(0.0, earth_info["native_metal_mol_per_100g"])
        self.assertGreater(copper_info["native_metal_mol_per_100g"], 0.1)
        self.assertLess(abiotic_oxygen(0.01, copper_info), 0.1 * abiotic_oxygen(0.01, earth_info))


if __name__ == "__main__":
    unittest.main()
