"""Element distribution -> material roster: formulas, background, availability, ontology chemistry."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))

from simulations.world_gen import material_chemistry as chem
from simulations.world_gen import natural_materials
from simulations.world_gen.crust import default_crust_composition
from simulations.world_gen.natural_materials import configure_material_catalog, derive_natural_material_model
from world.persistent_ontology_store import PersistentOntologyStore

_MATERIALS = []


def setUpModule():
    rows = PersistentOntologyStore(ROOT / "ontology" / "index0.owl").load_datasets().get("materials") or []
    _MATERIALS[:] = rows
    configure_material_catalog(rows)


def _crust(rows):
    return {"major_elements": [{"symbol": symbol, "abundance_percent": value} for symbol, value in rows]}


EARTH = [("O", 46.86), ("Si", 27.84), ("Al", 8.14), ("Fe", 5.03), ("Ca", 3.62), ("Na", 2.81), ("K", 2.61), ("Mg", 2.11)]
TAGS = ["natural_material_context", "silicate_crust", "active_hydrology", "weathered_surface", "plate_tectonic_surface", "oxidizing_surface"]


class FormulaTests(unittest.TestCase):
    def test_formulas_hydrates_and_solid_solutions(self):
        chalcopyrite = chem.formula_composition("CuFeS2")
        self.assertAlmostEqual(34.63, chalcopyrite["Cu"], delta=0.02)
        gypsum = chem.formula_composition("CaSO4*2H2O")
        self.assertAlmostEqual(23.28, gypsum["Ca"], delta=0.02)
        olivine = chem.formula_moles("(Mg,Fe)2SiO4")
        self.assertAlmostEqual(1.0, olivine["Mg"])
        self.assertAlmostEqual(1.0, olivine["Fe"])
        illite = chem.formula_moles("K0.65Al2(Al0.65Si3.35)O10(OH)2")
        self.assertAlmostEqual(2.65, illite["Al"])
        self.assertAlmostEqual(12.0, illite["O"])
        with self.assertRaises(chem.FormulaError):
            chem.formula_composition("felsic intrusive silicate rock")

    def test_endmembers_and_bulk_compositions_mix_by_mass(self):
        olivine = chem.endmember_composition([
            {"formula": "Mg2SiO4", "mass_fraction": 0.5},
            {"formula": "Fe2SiO4", "mass_fraction": 0.5},
        ])
        forsterite = chem.formula_composition("Mg2SiO4")
        fayalite = chem.formula_composition("Fe2SiO4")
        self.assertAlmostEqual((forsterite["Si"] + fayalite["Si"]) / 2.0, olivine["Si"])
        rock = chem.bulk_composition({"SiO2": 50.0, "CaCO3": 50.0})
        self.assertAlmostEqual(100.0, sum(rock.values()))
        self.assertAlmostEqual(0.5 * chem.formula_composition("CaCO3")["C"], rock["C"])


class DistributionTests(unittest.TestCase):
    def test_unlisted_elements_are_an_earth_like_background_and_a_listed_zero_is_absent(self):
        reference = {"Cu": 0.0028, "Zn": 0.0067, "K": 2.3}
        distribution = chem.planet_element_distribution(_crust([("O", 50.0), ("Si", 49.0), ("K", 0.0)]), reference)
        self.assertEqual(0.0, distribution["K"])
        self.assertEqual(0.0028, distribution["Cu"])
        # Listing more elements never inflates the background of the others.
        more = chem.planet_element_distribution(_crust([("O", 50.0), ("Si", 48.0), ("Zn", 1.0)]), reference)
        self.assertEqual(distribution["Cu"], more["Cu"])


class AvailabilityTests(unittest.TestCase):
    REFERENCE = {"O": 46.5, "Si": 27.6, "Al": 8.1, "Fe": 5.0, "Ca": 3.6, "Na": 2.8, "K": 2.6, "Mg": 2.1,
                 "Cu": 0.0028, "S": 0.035, "C": 0.32, "Ti": 0.38}

    def test_earth_like_crust_gives_one(self):
        granite = chem.bulk_composition({"SiO2": 71.3, "Al2O3": 14.3, "FeO": 2.7, "CaO": 1.8, "Na2O": 3.7, "K2O": 4.1})
        availability, limiting = chem.material_availability(granite, self.REFERENCE, self.REFERENCE)
        self.assertAlmostEqual(1.0, availability)
        self.assertIsNone(limiting)

    def test_essential_elements_gate_and_incidental_ones_do_not(self):
        no_potassium = dict(self.REFERENCE, K=0.0)
        granite = chem.bulk_composition({"SiO2": 71.3, "Al2O3": 14.3, "FeO": 2.7, "CaO": 1.8, "Na2O": 3.7, "K2O": 4.1})
        tonalite = chem.bulk_composition({"SiO2": 61.5, "Al2O3": 16.5, "FeO": 5.3, "MgO": 2.8, "CaO": 5.4, "Na2O": 3.9, "K2O": 1.4})
        self.assertEqual((0.0, "K"), chem.material_availability(granite, no_potassium, self.REFERENCE))
        self.assertGreater(chem.material_availability(tonalite, no_potassium, self.REFERENCE)[0], 0.9)

    def test_liebig_is_stoichiometric(self):
        chalcopyrite = chem.formula_composition("CuFeS2")
        copper_rich = dict(self.REFERENCE, Cu=0.0056)
        availability, _limiting = chem.material_availability(chalcopyrite, copper_rich, self.REFERENCE)
        self.assertAlmostEqual(2.0, availability, delta=0.01)
        # With copper plentiful, sulfur supply limits the mineral instead
        # (sulfur per unit of chalcopyrite drops below Earth's copper supply).
        copper_flooded_sulfur_poor = dict(self.REFERENCE, Cu=0.3, S=0.001)
        availability, limiting = chem.material_availability(chalcopyrite, copper_flooded_sulfur_poor, self.REFERENCE)
        self.assertEqual("S", limiting)
        self.assertLess(availability, 0.9)

    def test_a_crust_rich_in_an_element_dilutes_materials_without_it(self):
        basalt = chem.bulk_composition({"SiO2": 49.2, "Al2O3": 15.7, "FeO": 10.4, "MgO": 6.7, "CaO": 9.5, "Na2O": 2.9})
        sulfur_rich = dict(self.REFERENCE, S=12.0)
        availability, limiting, kind = chem.material_availability_detail(basalt, sulfur_rich, self.REFERENCE)
        self.assertLess(availability, 0.9)
        self.assertGreater(availability, chem.DEPLETION_FLOOR)
        self.assertEqual(("S", "diluted"), (limiting, kind))


class OntologyChemistryTests(unittest.TestCase):
    def test_every_roster_material_and_element_carries_chemistry(self):
        eligible = [
            material for material in _MATERIALS
            if material.get("material_subclass") in {"mineral", "rock", "sediment", "regolith", "ice"}
            and material.get("worldgen_participation") != "none"
        ]
        missing = sorted(material["id"] for material in eligible if not material.get("elemental_composition_wt"))
        self.assertEqual([], missing)
        elements = [material for material in _MATERIALS if material.get("material_subclass") == "element"]
        self.assertEqual(92, len(elements))
        self.assertTrue(all(float(element.get("earth_upper_crust_abundance_ppm") or 0.0) > 0.0 for element in elements))
        for material in eligible:
            self.assertAlmostEqual(100.0, sum(material["elemental_composition_wt"].values()), delta=0.05, msg=material["id"])

    def test_modal_mineralogy_reproduces_the_bulk_chemistry(self):
        import author_material_chemistry as authoring

        by_id = {material["id"]: material for material in _MATERIALS}
        for material_id, (bulk, modal, _basis) in authoring.BULK.items():
            (deviation, element), problem = authoring.modal_check(by_id, chem.bulk_composition(bulk), modal)
            self.assertIsNone(problem, material_id)
            self.assertLess(deviation, 8.0, f"{material_id}: {element}")


class RosterTests(unittest.TestCase):
    def _roster(self, rows, tags=TAGS):
        model = derive_natural_material_model(_crust(rows), tags)
        return {item["material_id"]: item for item in model["likely_materials"]}

    def test_earth_like_crust_reproduces_reference_availability(self):
        roster = self._roster(EARTH)
        availability = [item["availability_vs_earth"] for item in roster.values() if item.get("availability_vs_earth") is not None]
        self.assertGreater(len(availability), 180)
        self.assertTrue(all(0.95 <= value <= 1.05 for value in availability))

    def test_the_silicate_terrestrial_template_is_earth_like(self):
        # The template is Earth's whole surface inventory (oceans and air
        # included); the volatile budget removes the envelope, leaving rock.
        from simulations.world_gen.crust import estimate_crust_density_kg_m3
        from simulations.world_gen.planetary_physics import derive_planet_physics
        from simulations.world_gen.volatile_budget import apply_volatile_budget_to_seed, derive_volatile_budget
        from simulations.world_gen.world_gen_sim import WorldGenSimulation

        template = WorldGenSimulation.PLANET_TEMPLATES["silicate_terrestrial"]["major_elements"]
        seed = {
            "radius_earth": 1.0, "core_radius_fraction": 0.55, "crust_thickness_km": 35.0,
            "angular_velocity_deg_per_hour": 15.0, "tectonics_mode": "mobile_lid", "crust_composition": _crust(template),
        }
        physics = derive_planet_physics(seed, estimate_crust_density_kg_m3(seed["crust_composition"]))
        apply_volatile_budget_to_seed(seed, derive_volatile_budget(seed, physics, 1.0, 1.0))
        model = derive_natural_material_model(seed["crust_composition"], TAGS)
        roster = {item["material_id"]: item for item in model["likely_materials"]}
        values = [item["availability_vs_earth"] for item in roster.values() if item.get("availability_vs_earth") is not None]
        near_one = sum(0.9 <= value <= 1.1 for value in values)
        self.assertGreaterEqual(near_one / len(values), 0.95)

    def test_removing_potassium_removes_potassic_rocks_only(self):
        roster = self._roster([(symbol, 0.0 if symbol == "K" else value) for symbol, value in EARTH])
        for absent in ("mat_granite", "mat_orthoclase", "mat_microcline", "mat_sylvite"):
            self.assertNotIn(absent, roster)
        for present in ("mat_basalt", "mat_tonalite", "mat_quartz", "mat_limestone"):
            self.assertIn(present, roster)

    def test_enrichment_scales_ore_availability(self):
        roster = self._roster(EARTH + [("Cu", 0.03)])
        self.assertGreaterEqual(roster["mat_chalcopyrite"]["availability_vs_earth"], 5.0)

    def test_foundational_lithologies_follow_exotic_chemistry_not_deposits(self):
        carbon = [("O", 24.0), ("Si", 23.0), ("C", 18.0), ("Fe", 12.0), ("Mg", 9.0), ("Al", 5.0), ("Ca", 3.0), ("S", 2.0), ("Ni", 1.0)]
        roster = self._roster(carbon)
        self.assertTrue(roster["mat_graphite"]["foundational_lithology"])
        self.assertEqual(0, roster["mat_graphite"]["minimum_map_detail_level"])
        self.assertFalse(roster["mat_diamond"]["foundational_lithology"])
        self.assertFalse(self._roster(EARTH)["mat_graphite"]["foundational_lithology"])

    def test_reference_distribution_comes_from_the_ontology(self):
        reference = natural_materials.reference_element_distribution()
        earth = chem.planet_element_distribution(default_crust_composition(), natural_materials.reference_crust_percent())
        self.assertEqual(earth, reference)
        self.assertGreater(reference["Cu"], 0.0)


if __name__ == "__main__":
    unittest.main()
