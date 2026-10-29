import math
import unittest
from pathlib import Path

from world.persistent_ontology_store import PersistentOntologyStore
from world.plant_catalogue import PlantCatalogue
from world.world_model import WorldModel
from simulations.species.plant_assets import PlantBlueprint
from simulations.species.species_simulation import SpeciesSimulation

SPECIES_ID = "spec_morus_nigra"


class MorusNigraDataCompositionTests(unittest.TestCase):
    """Data-composition pass on a real ontology row, and the first real
    (non-synthetic) test of the trunk-multiplicity/lean mechanism from
    docs/species_sim_tree_architecture_variety_v001.md.

    See docs/species_sim_morus_nigra_v001.md for the research and
    authoring record this test verifies.
    """

    @classmethod
    def setUpClass(cls):
        cls.world = WorldModel()
        cls.raw = cls.world.loader.get(SPECIES_ID)
        cls.resolved = cls.world.resolved_species_entity(SPECIES_ID)

    def test_is_a_plantae_species_under_morus(self):
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
        self.assertEqual(["cladis_mulberries_morus"], entities[SPECIES_ID].get("parents"))

    def test_authored_fields_are_persisted_on_the_live_row(self):
        expected = {
            "plant_growth_form": "tree",
            "plant_growth_behaviour": "branched_woody",
            "growth_rate": "slow",
            "longevity_class": "very_long",
            "leaf_phenology": "deciduous",
            "nitrogen_fixation": "none",
            "plant_flowering_position": "lateral",
            "plant_lateral_axis_orientation": "plagiotropic",
        }
        for key, value in expected.items():
            with self.subTest(field=key):
                self.assertEqual(value, self.raw.get(key))
                self.assertEqual(value, self.resolved.get(key))
        self.assertAlmostEqual(0.35, self.raw["plant_apical_control"]["typical"])

    def test_weak_apical_control_produces_real_per_individual_trunk_variety(self):
        # This is the actual point of choosing Black Mulberry: verify the
        # tree_shoots.py trunk-multiplicity mechanism against a real
        # authored species (apical_control=0.35, "weak-to-moderate" per
        # the research), not only the synthetic fixtures in
        # test_species_simulation.py.
        def trunk_count(seed):
            sim = SpeciesSimulation(world_model=self.world, species_id=SPECIES_ID,
                                     species_entity=self.resolved, seed=seed)
            sim.set_age(sim.mature_age_days)
            return sum(1 for p in sim.render_snapshot.placements if p[0] == "stem_section" and p[1] == 0)

        counts = [trunk_count(seed) for seed in range(1, 13)]
        self.assertTrue(any(count > 1 for count in counts),
                         "expected at least one multi-trunk individual across 12 seeds")
        self.assertTrue(any(count == 1 for count in counts),
                         "expected at least one single-trunk individual too")
        # Determinism: same seed always gives the same trunk count.
        self.assertEqual(trunk_count(3), trunk_count(3))

    def test_mature_trunk_is_visibly_more_gnarled_than_a_young_one(self):
        # Real black mulberries are classically described as developing a
        # distinctly gnarled, twisted trunk with age -- ours used to render
        # the same smooth tube at every age. authored longevity_class=
        # very_long + resprouting=moderate should drive a real, measurable
        # increase in trunk waviness between young and mature individuals.
        # See docs/species_sim_morus_nigra_v001.md for the reference photo.
        def tortuosity(age_fraction):
            # path length walked / straight-line distance start->end -- 1.0
            # is a perfectly straight trunk, higher is more gnarled/winding.
            sim = SpeciesSimulation(world_model=self.world, species_id=SPECIES_ID,
                                     species_entity=self.resolved, seed=303)
            sim.set_age(round(sim.mature_age_days * age_fraction))
            trunk = [p for p in sim.render_snapshot.placements if p[0] == "stem_section" and p[7] == 1]
            points = [(0.0, 0.0, -0.08)] + [(p[2], p[3], p[4]) for p in trunk]
            path_len = sum(math.dist(points[i], points[i + 1]) for i in range(len(points) - 1))
            straight = math.dist(points[0], points[-1])
            return path_len / straight if straight else 1.0

        young_tort = tortuosity(0.15)
        mature_tort = tortuosity(1.0)
        self.assertGreater(mature_tort, young_tort * 1.3,
                            "a mature mulberry trunk should wind clearly more than a young one")
        self.assertLess(young_tort, 1.15, "a young trunk should still read as close to straight")

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
        self.assertGreater(snapshot.stats.get("estimated_leaf_count", 0), 1000)
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
