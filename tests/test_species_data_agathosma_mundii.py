import math
import unittest
from pathlib import Path

from world.persistent_ontology_store import PersistentOntologyStore
from world.plant_catalogue import PlantCatalogue
from world.world_model import WorldModel
from simulations.species.plant_assets import PlantBlueprint
from simulations.species.species_simulation import SpeciesSimulation

SPECIES_ID = "spec_agathosma_mundii"


class AgathosmaMundiiDataCompositionTests(unittest.TestCase):
    """Data-composition pass: exact field transport for a real ontology row.

    See docs/species_sim_agathosma_mundii_v001.md for the research and
    authoring record this test verifies.
    """

    @classmethod
    def setUpClass(cls):
        cls.world = WorldModel()
        cls.raw = cls.world.loader.get(SPECIES_ID)
        cls.resolved = cls.world.resolved_species_entity(SPECIES_ID)

    def test_is_a_plantae_species_under_agathosma(self):
        datasets = PersistentOntologyStore(Path("ontology/index0.owl")).load_datasets()
        entities = {
            row["id"]: row
            for rows in datasets.values()
            if isinstance(rows, list)
            for row in rows
            if isinstance(row, dict) and row.get("id")
        }
        catalogue = PlantCatalogue.build(entities)
        self.assertTrue(catalogue.is_species(SPECIES_ID))
        self.assertEqual(["cladis_agathosma"], entities[SPECIES_ID].get("parents"))

    def test_authored_fields_are_persisted_on_the_live_row(self):
        expected = {
            "plant_growth_form": "shrub",
            "plant_growth_behaviour": "branched_woody",
            "plant_lifespan": "perennial",
            "plant_woodiness": "woody",
            "mature_height_class": "dwarf",
            "leaf_phenology": "evergreen",
            "leaf_size_class": "very_small",
            "leaf_structure": "simple",
            "leaf_arrangement": "alternate",
            "photosynthesis_pathway": "c3",
            "nitrogen_fixation": "none",
            "moisture_preference": "dry",
        }
        for key, value in expected.items():
            with self.subTest(field=key):
                self.assertEqual(value, self.raw.get(key))
                self.assertEqual(value, self.resolved.get(key))
        self.assertEqual(1.0, self.raw["mature_height"]["max_m"])
        self.assertAlmostEqual(0.007, self.raw["leaf_length"]["typical_m"])

    def test_unresolved_fields_stay_other_unknown_rather_than_guessed(self):
        for key in ("root_architecture", "resprouting", "regeneration_strategy",
                    "mycorrhizal_type", "shade_tolerance", "seed_size_class"):
            with self.subTest(field=key):
                self.assertEqual("other_unknown", self.raw.get(key))

    def test_ontology_fields_transport_into_the_blueprint(self):
        blueprint = PlantBlueprint.from_species_entity(self.resolved, SPECIES_ID)
        self.assertEqual("shrub", blueprint.growth.get("shape"))
        self.assertEqual("branched_woody", blueprint.growth.get("growth_behaviour"))
        self.assertEqual("alternate", blueprint.growth.get("leaf_arrangement"))
        self.assertAlmostEqual(1.0, blueprint.growth.get("max_height_m"))
        self.assertAlmostEqual(0.007, blueprint.growth.get("leaf_length_m"))

    def test_fingerprint_differs_from_an_unauthored_blank_species(self):
        blank = PlantBlueprint.from_species_entity({"id": SPECIES_ID}, SPECIES_ID)
        authored = PlantBlueprint.from_species_entity(self.resolved, SPECIES_ID)
        self.assertNotEqual(blank.fingerprint(), authored.fingerprint())

    def test_growth_is_deterministic_for_equal_seed(self):
        first = SpeciesSimulation(world_model=self.world, species_id=SPECIES_ID,
                                   species_entity=self.resolved, seed=303)
        second = SpeciesSimulation(world_model=self.world, species_id=SPECIES_ID,
                                    species_entity=self.resolved, seed=303)
        first.set_age(first.mature_age_days)
        second.set_age(second.mature_age_days)
        self.assertEqual(first.render_snapshot.to_dict(), second.render_snapshot.to_dict())

    def test_mature_geometry_is_finite_and_bounded_by_authored_height(self):
        sim = SpeciesSimulation(world_model=self.world, species_id=SPECIES_ID,
                                 species_entity=self.resolved, seed=303)
        sim.set_age(sim.mature_age_days)
        placements = sim.render_snapshot.placements
        self.assertGreater(len(placements), 0)
        max_authored_height = self.raw["mature_height"]["max_m"]
        for module_id, parent, x, y, z, rotation, scale, level in placements:
            for value in (x, y, z, rotation, scale):
                self.assertTrue(math.isfinite(value))
            # Generous multiple of the authored height guards against runaway
            # geometry while allowing branch tips beyond the trunk apex.
            self.assertLess(z, max_authored_height * 3.0)

    def test_blueprint_and_snapshot_round_trip(self):
        blueprint = PlantBlueprint.from_species_entity(self.resolved, SPECIES_ID)
        self.assertEqual(blueprint.to_dict(), PlantBlueprint.from_dict(blueprint.to_dict()).to_dict())

        sim = SpeciesSimulation(world_model=self.world, species_id=SPECIES_ID,
                                 species_entity=self.resolved, seed=303)
        sim.set_age(sim.mature_age_days)
        snapshot = sim.render_snapshot
        round_tripped = type(snapshot).from_dict(snapshot.to_dict())
        self.assertEqual(snapshot.to_dict(), round_tripped.to_dict())


if __name__ == "__main__":
    unittest.main()
