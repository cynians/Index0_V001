import math
import unittest
from pathlib import Path

from world.persistent_ontology_store import PersistentOntologyStore
from world.plant_catalogue import PlantCatalogue
from world.world_model import WorldModel
from simulations.species.plant_assets import PlantBlueprint
from simulations.species.species_simulation import SpeciesSimulation

SPECIES_ID = "spec_abies_nordmanniana"


class AbiesNordmannianaDataCompositionTests(unittest.TestCase):
    """New species (tools/author_abies_nordmanniana.py), added specifically
    to exercise plant_crown_shape=conical on a species that *keeps* that
    dense, symmetric shape into full maturity -- unlike Eastern White Pine,
    which is conical young but opens up with age. Also creates the missing
    Abies (fir) genus/subfamily clade chain under Pinaceae.

    See docs/species_sim_morus_nigra_v001.md Sec7g for the design record.
    """

    @classmethod
    def setUpClass(cls):
        cls.world = WorldModel()
        cls.raw = cls.world.loader.get(SPECIES_ID)
        cls.resolved = cls.world.resolved_species_entity(SPECIES_ID)

    def test_is_a_plantae_species_under_abies(self):
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
        self.assertEqual(["cladis_firs_abies"], entities[SPECIES_ID].get("parents"))
        self.assertEqual(["cladis_abietoideae"], entities["cladis_firs_abies"].get("parents"))
        self.assertEqual(["cladis_pine_family_pinaceae"], entities["cladis_abietoideae"].get("parents"))

    def test_authored_fields_are_persisted_on_the_live_row(self):
        expected = {
            "plant_growth_form": "tree",
            "plant_growth_behaviour": "branched_woody",
            "longevity_class": "very_long",
            "leaf_phenology": "evergreen",
            "plant_axis_continuity": "monopodial",
            "plant_self_pruning": "none",
            "plant_crown_shape": "conical",
            "shade_tolerance": "high",
            "resprouting": "absent",
        }
        for key, value in expected.items():
            with self.subTest(field=key):
                self.assertEqual(value, self.raw.get(key))
                self.assertEqual(value, self.resolved.get(key))

    def test_stays_conical_and_dense_at_maturity_unlike_white_pine(self):
        # The point of this species: it should widen toward the base and
        # taper to a point (conical), holding foliage close to the ground
        # (self_pruning=none) even at full maturity.
        sim = SpeciesSimulation(world_model=self.world, species_id=SPECIES_ID,
                                 species_entity=self.resolved, seed=303)
        sim.set_age(sim.mature_age_days)
        height = max(p[4] for p in sim.render_snapshot.placements if p[0] == "stem_section" and p[7] == 1)
        branches = [p for p in sim.render_snapshot.placements if p[0] == "branch_section" and p[7] == 2]
        low = [math.hypot(p[2], p[3]) for p in branches if p[4] / height < 0.35]
        high = [math.hypot(p[2], p[3]) for p in branches if p[4] / height > 0.75]
        self.assertTrue(low, "a non-self-pruning conical species should have branches near the base")
        self.assertGreater(sum(low) / len(low), sum(high) / len(high),
                            "a conical crown should reach further near the base than near the top")
        self.assertLess(min(p[4] for p in branches) / height, 0.25,
                         "self_pruning=none should keep branches close to the ground even at maturity")

    def test_growth_is_deterministic_for_equal_seed(self):
        first = SpeciesSimulation(world_model=self.world, species_id=SPECIES_ID,
                                   species_entity=self.resolved, seed=303)
        second = SpeciesSimulation(world_model=self.world, species_id=SPECIES_ID,
                                    species_entity=self.resolved, seed=303)
        first.set_age(first.mature_age_days)
        second.set_age(second.mature_age_days)
        self.assertEqual(first.render_snapshot.to_dict(), second.render_snapshot.to_dict())

    def test_mature_canopy_is_finite_and_populated(self):
        sim = SpeciesSimulation(world_model=self.world, species_id=SPECIES_ID,
                                 species_entity=self.resolved, seed=303)
        sim.set_age(sim.mature_age_days)
        snapshot = sim.render_snapshot
        self.assertGreater(snapshot.stats.get("estimated_leaf_count", 0), 500)
        max_authored_height = self.raw["mature_height"]["max_m"]
        for module_id, parent, x, y, z, rotation, scale, level in snapshot.placements:
            for value in (x, y, z, rotation, scale):
                self.assertTrue(math.isfinite(value))
            self.assertLess(z, max_authored_height * 1.5)

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
