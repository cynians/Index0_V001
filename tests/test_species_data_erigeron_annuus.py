import math
import json
import unittest
from pathlib import Path

from simulations.species.plant_assets import PlantBlueprint
from simulations.species.plant_reproduction import resolve_reproductive_assurance
from simulations.species.species_simulation import SpeciesSimulation
from world.persistent_ontology_store import PersistentOntologyStore
from world.plant_catalogue import PlantCatalogue
from world.world_model import WorldModel


SPECIES_ID = "spec_erigeron_annuus"


class ErigeronAnnuusDataAndMechanismTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.world = WorldModel()
        cls.raw = cls.world.loader.get(SPECIES_ID)
        cls.resolved = cls.world.resolved_species_entity(SPECIES_ID)

    def make_sim(self, entity=None, seed=303):
        sim = SpeciesSimulation(
            species_entity=entity or self.resolved,
            species_id=SPECIES_ID,
            seed=seed,
        )
        reproductive_start = sim.blueprint.growth["life_history"]["reproductive_start_days"]
        sim.set_age(reproductive_start + 5.0)
        return sim

    def test_is_live_plantae_species_under_erigeron(self):
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
        self.assertEqual(["cladis_berufkraut_erigeron"], entities[SPECIES_ID]["parents"])

    def test_researched_fields_are_authored_and_reach_blueprint(self):
        expected = {
            "plant_growth_form": "forb",
            "plant_growth_behaviour": "determinate_sympodial",
            "plant_lifespan": "annual",
            "plant_life_form": "therophyte",
            "plant_woodiness": "herbaceous",
            "leaf_arrangement": "alternate",
            "leaf_attachment_pattern": "mixed",
            "plant_flowering_position": "terminal",
            "plant_reproductive_structure": "capitulum",
            "reproductive_mode": "apomictic",
            "root_architecture": "mixed",
            "regeneration_strategy": "disturbance_colonization",
            "mycorrhizal_type": "arbuscular",
            "dispersal": ["wind"],
        }
        for key, value in expected.items():
            with self.subTest(field=key):
                self.assertEqual(value, self.raw.get(key))
                self.assertEqual(value, self.resolved.get(key))

        blueprint = PlantBlueprint.from_species_entity(self.resolved, SPECIES_ID)
        self.assertEqual("determinate_sympodial", blueprint.growth["growth_behaviour"])
        self.assertEqual("apomictic", blueprint.growth["reproductive_mode"])
        self.assertEqual("annual", blueprint.growth["life_history"]["class"])
        self.assertEqual(1.0, blueprint.growth["root_profile"]["target_depth_m"])

    def test_reproductive_mode_changes_blueprint_fingerprint(self):
        apomictic = PlantBlueprint.from_species_entity(self.resolved, SPECIES_ID)
        sexual_entity = dict(self.resolved, reproductive_mode="sexual")
        sexual = PlantBlueprint.from_species_entity(sexual_entity, f"{SPECIES_ID}_sexual")
        self.assertNotEqual(apomictic.fingerprint(), sexual.fingerprint())

    def test_sympodial_grammar_has_lateral_axes_and_terminal_flowers(self):
        sim = self.make_sim()
        snapshot = sim.render_snapshot
        self.assertGreater(snapshot.stats["sympodial_lateral_axis_count"], 0)
        self.assertGreater(snapshot.stats["sympodial_terminal_count"], 1)
        self.assertEqual(
            snapshot.stats["sympodial_flower_count"],
            sum(1 for placement in snapshot.placements if placement[0] == "flower"),
        )
        self.assertTrue(any(placement[0] == "branch_section" for placement in snapshot.placements))
        for index, placement in enumerate(snapshot.placements):
            parent = int(placement[1])
            self.assertTrue(parent == -1 or 0 <= parent < index)
            self.assertTrue(all(math.isfinite(float(value)) for value in placement[2:7]))

    def test_apomixis_preserves_fecundity_under_explicit_low_pollination(self):
        apomictic = self.make_sim()
        sexual = self.make_sim(dict(self.resolved, reproductive_mode="sexual"))
        environment = {"pollination_availability": 0.1}
        apomictic_outcome = apomictic.get_ecological_outcome(environment)
        sexual_outcome = sexual.get_ecological_outcome(environment)

        self.assertEqual(1.0, apomictic_outcome["reproductive_assurance"])
        self.assertEqual(0.1, sexual_outcome["reproductive_assurance"])
        self.assertGreater(apomictic_outcome["fecundity"], sexual_outcome["fecundity"])
        self.assertEqual(apomictic_outcome["vitality"], sexual_outcome["vitality"])

    def test_missing_and_nonfinite_pollination_are_neutral(self):
        for environment in ({}, {"pollination_availability": float("nan")}):
            with self.subTest(environment=environment):
                result = resolve_reproductive_assurance(
                    {"reproductive_mode": "other_unknown"}, environment
                )
                self.assertEqual(1.0, result["reproductive_assurance"])
                self.assertEqual(1.0, result["pollination_availability"])

    def test_equal_inputs_are_deterministic_and_round_trip(self):
        first = self.make_sim(seed=303)
        second = self.make_sim(seed=303)
        self.assertEqual(first.render_snapshot.to_dict(), second.render_snapshot.to_dict())

        blueprint = first.blueprint
        self.assertEqual(
            blueprint.to_dict(),
            PlantBlueprint.from_dict(blueprint.to_dict()).to_dict(),
        )
        snapshot = first.render_snapshot
        self.assertEqual(
            snapshot.to_dict(),
            type(snapshot).from_dict(snapshot.to_dict()).to_dict(),
        )

    def test_ecological_metrics_are_stable_across_lods(self):
        sim = self.make_sim()
        outcomes = []
        for lod in (0, 1, 2):
            sim.set_lod(lod)
            outcomes.append(sim.get_ecological_outcome({"pollination_availability": 0.1}))
        for key in ("vitality", "fecundity", "reproductive_assurance", "root_depth_m"):
            self.assertEqual(outcomes[0][key], outcomes[1][key])
            self.assertEqual(outcomes[1][key], outcomes[2][key])

    def test_unrelated_synthetic_sympodial_species_reuses_grammar(self):
        entity = {
            "id": "spec_synthetic_sympodial",
            "plant_growth_form": "forb",
            "plant_growth_behaviour": "determinate_sympodial",
            "plant_lifespan": "annual",
            "plant_flowering_position": "terminal",
            "reproductive_mode": "sexual",
            "mature_height": {"min_m": 0.2, "max_m": 0.8},
        }
        sim = SpeciesSimulation(species_entity=entity, seed=41)
        age = sim.blueprint.growth["life_history"]["reproductive_start_days"] + 5.0
        sim.set_age(age)
        self.assertGreater(sim.render_snapshot.stats["sympodial_terminal_count"], 0)
        self.assertTrue(any(p[0] == "flower" for p in sim.render_snapshot.placements))

    def test_refinement_packet_is_saved_and_transported(self):
        packet=json.loads(Path('assets/species_trait_specs/spec_erigeron_annuus.json').read_text(encoding='utf-8'))
        for key,value in packet['updates'].items():
            self.assertEqual(value,self.raw[key])
            self.assertEqual(value,self.resolved[key])
        bp=PlantBlueprint.from_species_entity(self.resolved,SPECIES_ID)
        self.assertEqual(1,bp.growth['sympodial_herb_version'])
        self.assertEqual(.08,bp.module('leaf').length_m)
        self.assertEqual(.026,bp.module('flower').length_m)

    def test_saved_native_modules_reopen_with_reviewed_pixels(self):
        import pygame
        from tools.author_plant_assets import PixelEditorHost,load_manifest,render_module
        from ui.pixel_art_editor_ui import PixelArtEditorUI
        pygame.init()
        try:
            host=PixelEditorHost(self.world.loader)
            manifest=load_manifest(Path('assets/plant_asset_specs/spec_erigeron_annuus.json'))
            for module in manifest['modules']:
                illustration=self.world.loader.get(module['illustration_id'])
                self.assertEqual([SPECIES_ID],illustration['parents'])
                self.assertEqual(illustration['media_path'],self.raw[f"plant_{module['role']}_module_ref"])
                saved=pygame.image.load(illustration['media_path'])
                self.assertEqual((75,75),saved.get_size())
                self.assertEqual(pygame.image.tobytes(saved,'RGBA'),pygame.image.tobytes(render_module(module),'RGBA'))
                self.assertTrue(PixelArtEditorUI(host).open(illustration['id']))
        finally:
            pygame.quit()


if __name__ == "__main__":
    unittest.main()
