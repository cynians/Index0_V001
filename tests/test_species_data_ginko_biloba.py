import math
import unittest
from pathlib import Path

from world.persistent_ontology_store import PersistentOntologyStore
from world.plant_catalogue import PlantCatalogue
from world.world_model import WorldModel
from simulations.species.plant_assets import PlantBlueprint
from simulations.species.species_simulation import SpeciesSimulation

SPECIES_ID = "spec_ginko_biloba"


class GinkgoBilobaDataCompositionTests(unittest.TestCase):
    """Data-composition pass: exact field transport for a real ontology row.

    The live entity id/binomial/common_name are misspelled ("Ginko" not
    "Ginkgo") and were deliberately left unchanged for this pass; see
    docs/species_sim_ginko_biloba_v001.md for the research and authoring
    record this test verifies.
    """

    @classmethod
    def setUpClass(cls):
        cls.world = WorldModel()
        cls.raw = cls.world.loader.get(SPECIES_ID)
        cls.resolved = cls.world.resolved_species_entity(SPECIES_ID)

    def test_is_a_plantae_species_under_ginkgo(self):
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
        self.assertEqual(["cladis_ginkgo"], entities[SPECIES_ID].get("parents"))

    def test_authored_fields_are_persisted_on_the_live_row(self):
        expected = {
            "plant_growth_form": "tree",
            "plant_growth_behaviour": "branched_woody",
            "plant_lifespan": "perennial",
            "plant_life_form": "phanerophyte",
            "plant_woodiness": "woody",
            "mature_height_class": "canopy",
            "growth_rate": "moderate",
            "maturity_rate": "slow",
            "longevity_class": "very_long",
            "leaf_phenology": "deciduous",
            "leaf_size_class": "medium",
            "leaf_structure": "simple",
            "leaf_arrangement": "alternate",
            "leaf_attachment_pattern": "mixed",
            "leaf_clustering": "tufted",
            "plant_shoot_dimorphism": "long_and_short_shoots",
            "plant_leaf_distribution": "mixed_long_short_shoots",
            "photosynthesis_pathway": "c3",
            "root_architecture": "taproot",
            "root_depth_class": "deep",
            "reproductive_mode": "both",
            "seed_size_class": "large",
            "clonal_spread": "low",
            "resprouting": "strong",
            "regeneration_strategy": "mixed",
            "nitrogen_fixation": "none",
            "nutrition_mode": "autotrophic",
            "mycorrhizal_type": "arbuscular",
            "shade_tolerance": "low",
            "moisture_preference": "mesic",
            "waterlogging_tolerance": "low",
            "salinity_tolerance": "medium",
        }
        for key, value in expected.items():
            with self.subTest(field=key):
                self.assertEqual(value, self.raw.get(key))
                self.assertEqual(value, self.resolved.get(key))
        self.assertAlmostEqual(70.0, self.raw["mature_height"]["max_m"])
        self.assertAlmostEqual(5.0, self.raw["max_root_depth"]["max_m"])
        self.assertAlmostEqual(0.075, self.raw["leaf_length"]["typical_m"])
        self.assertEqual(["lignotuber"], self.raw["belowground_storage"])
        self.assertEqual(["wind"], self.raw["pollination"])
        self.assertEqual(["gravity", "animal_ingestion"], self.raw["dispersal"])

    def test_identity_text_left_unchanged(self):
        # The user explicitly asked to leave the pre-existing misspelling in
        # place for this pass rather than silently repair stable identity
        # data (see docs/Plant_Design_Process.md Sec. 13 precedent).
        self.assertEqual("Ginko biloba", self.raw.get("binomial_name"))
        self.assertEqual("Ginko - Ginko biloba", self.raw.get("common_name"))

    def test_unresolved_fields_stay_other_unknown_rather_than_guessed(self):
        # plant_axis_continuity was later authored as "monopodial" (a
        # later pass, docs/Plant_Design_Process.md Sec. 6c/species_sim_
        # morus_nigra_v001.md Sec. 7b) -- textbook, well-documented Ginkgo
        # architecture (Rauh's model, a persistently dominant single
        # leader), not a guess -- so it's excluded from this list now.
        for key in ("plant_branching_rhythm", "plant_branching_timing",
                    "plant_lateral_axis_orientation", "plant_flowering_position"):
            with self.subTest(field=key):
                self.assertNotIn(key, self.raw)
        self.assertEqual("monopodial", self.raw.get("plant_axis_continuity"))

    def test_ontology_fields_transport_into_the_blueprint(self):
        blueprint = PlantBlueprint.from_species_entity(self.resolved, SPECIES_ID)
        self.assertEqual("tree", blueprint.growth.get("shape"))
        self.assertEqual("branched_woody", blueprint.growth.get("growth_behaviour"))
        self.assertEqual("alternate", blueprint.growth.get("leaf_arrangement"))
        self.assertEqual("long_and_short_shoots", blueprint.growth.get("shoot_dimorphism"))
        self.assertAlmostEqual(70.0, blueprint.growth.get("max_height_m"))
        self.assertAlmostEqual(0.075, blueprint.growth.get("leaf_length_m"))
        self.assertAlmostEqual(5.0, blueprint.growth["root_profile"]["target_depth_m"])

    def test_visual_calibration_fields_transport_and_are_labelled(self):
        blueprint = PlantBlueprint.from_species_entity(self.resolved, SPECIES_ID)
        ranges = blueprint.growth["architecture_ranges"]
        self.assertAlmostEqual(0.36, ranges["crown_openness"]["typical"])
        self.assertEqual("provisional_visual_calibration", ranges["crown_openness"]["status"])
        self.assertAlmostEqual(0.85, ranges["apical_control"]["typical"])
        self.assertEqual("provisional_visual_calibration", ranges["apical_control"]["status"])

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
