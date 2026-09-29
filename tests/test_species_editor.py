import os
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame

from simulations.species.plant_assets import PlantBlueprint
from simulations.species.species_editor import (
    cycle_choice,
    editable_field_rows,
    new_editor_state,
    preview_entity,
    range_value,
    redo,
    set_range_handle,
    undo,
)
from simulations.species.species_renderer import SpeciesRenderer
from simulations.species.species_simulation import SpeciesSimulation
from ui.card import EntityCard
from ui.knowledge_browser_ui import KnowledgeBrowserUI
from world.plant_traits import normalised_plant_trait_range


class SpeciesEditorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pygame.init()

    @classmethod
    def tearDownClass(cls):
        pygame.quit()

    def setUp(self):
        self.entity = {
            "id": "spec_editor_birch",
            "type": "species",
            "_dataset": "species",
            "pretty_name": "Editor Birch",
            "plant_growth_form": "tree",
            "plant_growth_behaviour": "branched_woody",
            "plant_branching_rhythm": "diffuse",
            "plant_branch_droop": {
                "min": .60,
                "typical": .72,
                "max": .84,
                "status": "provisional_visual_calibration",
                "source": "test_reference",
            },
        }

    def test_ranges_preserve_typical_runtime_value_and_provenance(self):
        envelope = normalised_plant_trait_range(self.entity["plant_branch_droop"])
        self.assertEqual(.72, envelope["typical"])
        self.assertEqual("test_reference", envelope["source"])
        blueprint = PlantBlueprint.from_species_entity(self.entity)
        self.assertEqual(.72, blueprint.growth["branch_droop"])
        self.assertEqual(envelope, blueprint.growth["architecture_ranges"]["branch_droop"])

    def test_range_and_choice_edits_are_local_until_saved(self):
        state = new_editor_state(self.entity)
        self.assertTrue(set_range_handle(state, "plant_branch_droop", "typical", .76))
        self.assertEqual(.76, range_value(state, "plant_branch_droop")["typical"])
        self.assertEqual("species_editor_visual_fit", state["working_entity"]["plant_branch_droop"]["source"])
        self.assertEqual(.72, self.entity["plant_branch_droop"]["typical"])
        self.assertTrue(cycle_choice(state, "plant_branching_rhythm"))
        self.assertTrue(state["dirty"])

    def test_field_filter_exposes_both_range_and_dropdown_controls(self):
        rows = editable_field_rows(self.entity, "branch")
        kinds = {row["field"]: row["kind"] for row in rows}
        self.assertEqual("range", kinds["plant_branch_droop"])
        self.assertEqual("choice", kinds["plant_branching_rhythm"])

    def test_renderer_builds_three_pane_editor_and_asset_actions(self):
        surface = pygame.Surface((1680, 1000))
        sim = SpeciesSimulation(species_entity=self.entity, seed=303)
        sim.set_active_simulation_panel_tab("editor")
        sim.species_editor["query"] = "branch"
        SpeciesRenderer(None).draw(surface, sim)
        kinds = {hitbox["kind"] for hitbox in sim._species_editor_hitboxes}
        self.assertTrue({"paste", "save", "revert", "undo", "redo", "asset", "choice", "range",
                         "preview_mode", "field_group", "preview_only", "reference_control"}.issubset(kinds))
        roles = {hitbox.get("role") for hitbox in sim._species_editor_hitboxes if hitbox["kind"] == "asset"}
        self.assertTrue({"leaf", "stem", "flower"}.issubset(roles))
        preview = sim.get_species_editor_preview()
        self.assertEqual(preview.mature_age_days, preview.age_days)
        reference = pygame.Surface((80, 120), pygame.SRCALPHA)
        reference.fill((240, 240, 235, 255))
        pygame.draw.ellipse(reference, (34, 110, 52, 255), (18, 8, 44, 104))
        sim.species_editor.update({"reference_surface": reference, "reference_overlay": True,
                                   "reference_silhouette": True})
        SpeciesRenderer(None).draw(surface, sim)

    def test_preview_modes_resolve_endpoints_and_repeatable_variation(self):
        state = new_editor_state(self.entity)
        self.assertEqual(.60, preview_entity(state, "minimum")["plant_branch_droop"]["typical"])
        self.assertEqual(.84, preview_entity(state, "maximum")["plant_branch_droop"]["typical"])
        first = preview_entity(state, "variation", 2)["plant_branch_droop"]["typical"]
        second = preview_entity(state, "variation", 2)["plant_branch_droop"]["typical"]
        self.assertEqual(first, second)
        self.assertGreaterEqual(first, .60)
        self.assertLessEqual(first, .84)

    def test_undo_and_redo_restore_coupled_field_edits(self):
        state = new_editor_state(self.entity)
        set_range_handle(state, "plant_branch_droop", "typical", .76)
        self.assertTrue(undo(state))
        self.assertEqual(.72, range_value(state, "plant_branch_droop")["typical"])
        self.assertTrue(redo(state))
        self.assertEqual(.76, range_value(state, "plant_branch_droop")["typical"])

    def test_variation_mode_builds_four_reproducible_individuals(self):
        sim = SpeciesSimulation(species_entity=self.entity, seed=303)
        sim.set_active_simulation_panel_tab("editor")
        sim.species_editor["preview_mode"] = "variation"
        previews = sim.get_species_editor_previews()
        self.assertEqual([303, 304, 305, 306], [preview.seed for preview in previews])
        self.assertEqual(4, len(previews))

    def test_range_drag_defers_expensive_preview_rebuild_until_release(self):
        sim = SpeciesSimulation(species_entity=self.entity, seed=303)
        sim.set_active_simulation_panel_tab("editor")
        before = sim.get_species_editor_preview()
        sim.species_editor["preview_deferred"] = True
        set_range_handle(sim.species_editor, "plant_branch_droop", "typical", .80, record=False)
        self.assertIs(before, sim.get_species_editor_preview())
        sim.species_editor["preview_deferred"] = False
        sim._invalidate_species_editor_preview()
        self.assertIsNot(before, sim.get_species_editor_preview())

    def test_plant_species_card_exposes_editor_before_the_sim_lab(self):
        card = EntityCard.__new__(EntityCard)
        card.entity = self.entity
        card.dataset_name = "species"
        card.world_model = type("World", (), {
            "plant_catalogue": type("Catalogue", (), {"is_species": lambda self, entity_id: True})(),
        })()
        ids = [tool["id"] for tool in card._toolbelt_items()]
        self.assertLess(ids.index("species_visual_editor"), ids.index("species_sim_lab"))
        editor = next(tool for tool in card._toolbelt_items() if tool["id"] == "species_visual_editor")
        self.assertEqual("launch_species_editor", editor["action_id"])

    def test_open_editor_pulls_new_pixel_module_references_from_species_card(self):
        live = dict(self.entity)
        live["plant_leaf_module_ref"] = "assets/illustrations/new_leaf.png"
        world = type("World", (), {"get_entity": lambda self, entity_id: live})()
        sim = SpeciesSimulation(species_entity=self.entity, world_model=None, seed=303)
        sim.world_model = world
        sim.set_active_simulation_panel_tab("editor")
        sim.get_species_editor_preview()
        self.assertEqual(
            "assets/illustrations/new_leaf.png",
            sim.species_editor["working_entity"]["plant_leaf_module_ref"],
        )

    def test_pixel_button_reopens_an_existing_species_module(self):
        illustration = {
            "id": "illust_editor_birch_leaf",
            "type": "idea",
            "idea_class": "illustration",
            "parents": [self.entity["id"]],
            "plant_asset_role": "leaf",
            "media_path": "assets/illustrations/editor_birch_leaf.png",
        }
        ui = KnowledgeBrowserUI.__new__(KnowledgeBrowserUI)
        ui.world_model = type("World", (), {
            "get_entities_by_dataset": lambda self, dataset: [illustration],
            "get_entity": lambda world_self, entity_id: self.entity if entity_id == self.entity["id"] else None,
            "plant_catalogue": type("Catalogue", (), {"is_species": lambda self, entity_id: True})(),
        })()
        opened = []
        ui._open_pixel_art_editor = lambda entity_id: opened.append(entity_id) or True

        self.assertTrue(ui._create_or_open_plant_asset({"entity_id": self.entity["id"]}, "leaf"))
        self.assertEqual([illustration["id"]], opened)


if __name__ == "__main__":
    unittest.main()
