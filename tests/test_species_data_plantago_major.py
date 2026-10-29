import math
import unittest
from pathlib import Path

from simulations.species.plant_assets import PlantBlueprint
from simulations.species.species_simulation import SpeciesSimulation
from world.persistent_ontology_store import PersistentOntologyStore
from world.plant_catalogue import PlantCatalogue
from world.world_model import WorldModel


SPECIES_ID = "spec_plantago_major"


class PlantagoMajorDataAndVisualMechanismTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.world = WorldModel()
        cls.raw = cls.world.loader.get(SPECIES_ID)
        cls.resolved = cls.world.resolved_species_entity(SPECIES_ID)

    def make_reproductive_sim(self, entity=None, seed=303):
        sim = SpeciesSimulation(
            species_entity=entity or self.resolved,
            species_id=SPECIES_ID,
            seed=seed,
        )
        start = sim.blueprint.growth["life_history"]["reproductive_start_days"]
        sim.set_age(start + 5.0)
        return sim

    def test_is_live_plantae_species_under_plantago(self):
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
        self.assertEqual(["cladis_plantains_plantago"], entities[SPECIES_ID]["parents"])

    def test_visual_fields_and_leaf_asset_reach_the_blueprint(self):
        self.assertEqual("terminal", self.raw["plant_flowering_position"])
        self.assertEqual("spike", self.raw["plant_reproductive_structure"])
        asset_ref = self.raw["plant_leaf_module_ref"]
        self.assertTrue(Path(asset_ref).is_file())
        self.assertTrue(
            Path("assets/plants/illustrations/illust_plantago_major_leaf_module_pixel.layers.json.gz").is_file()
        )

        blueprint = PlantBlueprint.from_species_entity(self.resolved, SPECIES_ID)
        self.assertEqual(asset_ref, blueprint.module("leaf").asset_ref)
        self.assertEqual("terminal", blueprint.growth["flowering_position"])
        self.assertEqual("spike", blueprint.growth["reproductive_structure"])

        without_asset = dict(self.resolved)
        without_asset.pop("plant_leaf_module_ref", None)
        self.assertNotEqual(
            blueprint.fingerprint(),
            PlantBlueprint.from_species_entity(without_asset, SPECIES_ID).fingerprint(),
        )

    def test_reproductive_rosette_has_varied_leaf_cohorts_and_terminal_spikes(self):
        snapshot = self.make_reproductive_sim().render_snapshot
        leaves = [placement for placement in snapshot.placements if placement[0] == "leaf"]
        flowers = [placement for placement in snapshot.placements if placement[0] == "flower"]

        self.assertGreaterEqual(len(leaves), 8)
        self.assertGreater(max(leaf[6] for leaf in leaves) - min(leaf[6] for leaf in leaves), 0.4)
        self.assertLessEqual(max(math.hypot(leaf[2], leaf[3]) for leaf in leaves), 0.03)
        self.assertGreaterEqual(len(flowers), 1)
        self.assertTrue(all(snapshot.placements[int(flower[1])][0] == "stem_section" for flower in flowers))

        for index, placement in enumerate(snapshot.placements):
            parent = int(placement[1])
            self.assertTrue(parent == -1 or 0 <= parent < index)
            self.assertTrue(all(math.isfinite(float(value)) for value in placement[2:7]))

    def test_equal_inputs_are_deterministic_and_round_trip(self):
        first = self.make_reproductive_sim(seed=303)
        second = self.make_reproductive_sim(seed=303)
        self.assertEqual(first.render_snapshot.to_dict(), second.render_snapshot.to_dict())
        self.assertEqual(
            first.blueprint.to_dict(),
            PlantBlueprint.from_dict(first.blueprint.to_dict()).to_dict(),
        )
        snapshot = first.render_snapshot
        self.assertEqual(snapshot.to_dict(), type(snapshot).from_dict(snapshot.to_dict()).to_dict())

    def test_unresolved_reproductive_traits_do_not_invent_a_scape(self):
        unresolved = dict(self.resolved)
        unresolved.pop("plant_flowering_position", None)
        unresolved.pop("plant_reproductive_structure", None)
        sim = self.make_reproductive_sim(unresolved)
        self.assertFalse(any(placement[0] == "flower" for placement in sim.render_snapshot.placements))

    def test_unrelated_rosette_reuses_the_terminal_inflorescence_path(self):
        synthetic = {
            "id": "spec_synthetic_flowering_rosette",
            "plant_growth_form": "forb",
            "plant_growth_behaviour": "rosette_short_internode",
            "leaf_attachment_pattern": "basal_rosette",
            "plant_flowering_position": "terminal",
            "plant_reproductive_structure": "capitulum",
            "reproductive_mode": "sexual",
        }
        sim = SpeciesSimulation(species_entity=synthetic, seed=41)
        start = sim.blueprint.growth["life_history"]["reproductive_start_days"]
        sim.set_age(start + 5.0)
        self.assertTrue(any(placement[0] == "flower" for placement in sim.render_snapshot.placements))


if __name__ == "__main__":
    unittest.main()
