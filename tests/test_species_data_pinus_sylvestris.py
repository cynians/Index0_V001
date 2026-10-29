import gzip
import json
import math
import unittest
from pathlib import Path

from world.persistent_ontology_store import PersistentOntologyStore
from world.plant_catalogue import PlantCatalogue
from world.world_model import WorldModel
from simulations.species.plant_assets import PlantBlueprint
from simulations.species.species_simulation import SpeciesSimulation

SPECIES_ID = "spec_pinus_sylvestris"


class PinusSylvestrisDataCompositionTests(unittest.TestCase):
    """Saved Scots pine composition, including its photograph-based refinement.

    The mature display has a deeper, open irregular crown on a clear bole.
    See docs/species_sim_pinus_sylvestris_v001.md for the design record.
    """

    @classmethod
    def setUpClass(cls):
        cls.world = WorldModel()
        cls.raw = cls.world.loader.get(SPECIES_ID)
        cls.resolved = cls.world.resolved_species_entity(SPECIES_ID)

    def test_is_a_plantae_species_under_pinus(self):
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
        self.assertEqual(["cladis_pines_pinus"], entities[SPECIES_ID].get("parents"))

    def test_authored_fields_are_persisted_on_the_live_row(self):
        expected = {
            "plant_growth_form": "tree",
            "plant_growth_behaviour": "branched_woody",
            "longevity_class": "very_long",
            "leaf_phenology": "evergreen",
            "leaf_fascicle_size": 2,
            "plant_axis_continuity": "monopodial",
            "plant_self_pruning": "moderate",
            "plant_crown_shape": "irregular",
            "shade_tolerance": "low",
            "resprouting": "absent",
        }
        for key, value in expected.items():
            with self.subTest(field=key):
                self.assertEqual(value, self.raw.get(key))
                self.assertEqual(value, self.resolved.get(key))

    def test_approved_pixel_modules_reach_the_blueprint_at_physical_scale(self):
        expected = {
            "leaf": ("plant_leaf_module_ref", "illust_pinus_sylvestris_leaf_module", 0.060),
            "flower": ("plant_flower_module_ref", "illust_pinus_sylvestris_young_cone_module", 0.0055),
            "fruit": ("plant_fruit_module_ref", "illust_pinus_sylvestris_mature_cone_module", 0.045),
            "stem_section": ("plant_stem_module_ref", "illust_pinus_sylvestris_stem_module", None),
            "branch_section": ("plant_branch_module_ref", "illust_pinus_sylvestris_branch_module", None),
        }
        blueprint = PlantBlueprint.from_species_entity(self.resolved, SPECIES_ID)
        for module_id, (field, illustration_id, depicted_size) in expected.items():
            with self.subTest(module=module_id):
                module = blueprint.module(module_id)
                self.assertEqual(self.raw[field], module.asset_ref)
                self.assertTrue(Path(module.asset_ref).is_file())
                illustration = self.world.loader.get(illustration_id)
                self.assertIsNotNone(illustration)
                self.assertEqual(module.asset_ref, illustration.get("media_path"))
                self.assertEqual("in_engine_pixel_editor", illustration.get("pixel_art_source"))
                document_path = Path(illustration["pixel_document_path"])
                self.assertTrue(document_path.is_file())
                with gzip.open(document_path, "rt", encoding="utf-8") as handle:
                    document = json.load(handle)
                self.assertEqual(2, document.get("version"))
                self.assertEqual("single", document.get("mode"))
                self.assertEqual(
                    [illustration["pixel_canvas_width"], illustration["pixel_canvas_height"]],
                    [document.get("width"), document.get("height")],
                )
                if depicted_size is not None:
                    self.assertAlmostEqual(
                        depicted_size,
                        blueprint.module(module_id).visual.get("depicted_size_m", depicted_size),
                    )

        self.assertAlmostEqual(0.060, blueprint.module("leaf").length_m)
        self.assertEqual((0.5, 0.9324), blueprint.module("leaf").attachment_point)
        self.assertEqual((0.0, -1.0), blueprint.module("leaf").growth_axis)
        self.assertEqual((0.5, 0.9459), blueprint.module("flower").attachment_point)
        self.assertEqual((0.5, 0.9595), blueprint.module("fruit").attachment_point)

    def test_mature_tree_retains_clear_bole_and_a_deeper_live_crown(self):
        sim = SpeciesSimulation(world_model=self.world, species_id=SPECIES_ID,
                                 species_entity=self.resolved, seed=303)
        sim.set_age(sim.mature_age_days)
        height = max(p[4] for p in sim.render_snapshot.placements if p[0] == "stem_section" and p[7] == 1)
        branches = [p for p in sim.render_snapshot.placements if p[0] == "branch_section" and p[7] == 2]
        branch_starts = [p[4] for p in branches]
        self.assertGreater(min(branch_starts) / height, 0.35,
                            "the mature display should retain a substantial clear lower bole")
        self.assertLess(min(branch_starts) / height, 0.55,
                         "the live crown should no longer be compressed into the old top band")
        crown_span = (max(branch_starts) - min(branch_starts)) / height
        self.assertGreater(crown_span, 0.45)
        self.assertLess(crown_span, 0.65,
                         "a deeper crown should not erase the clear lower bole")

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
