import unittest
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pygame

from ui.card import EntityCard
from ui.knowledge_browser_ui import KnowledgeBrowserUI


class DummyLoader:
    def __init__(self, entities):
        self.entities = entities
        self.datasets = {"ideas": list(entities.values())}
        self.reference_graph_rebuilt = False

    def build_reference_graph(self):
        self.reference_graph_rebuilt = True


class DummyTouches:
    def __init__(self):
        self.refreshed = False

    def refresh(self):
        self.refreshed = True


class KnowledgeBrowserHarness(KnowledgeBrowserUI):
    def __init__(self, entities=None, entry_dir=None):
        self.persisted_ids = []
        self.entry_dir = entry_dir
        loader = DummyLoader(entities or {})
        self.world_model = SimpleNamespace(
            loader=loader,
            touch_degrees=DummyTouches(),
            get_entity=lambda entity_id: loader.entities.get(entity_id),
        )
        self.card_drafts = {}
        self.cards = []
        self.selected_entity_id = None
        self.active_card_drag_id = None
        self.active_card_resize_id = None
        self.canvas_relation_link_source_id = None
        self.canvas_relation_status = ""
        self.relation_link_target = None
        self.relation_link_status = ""
        self.entry_name_prompt = None
        self.stellar_neighbourhood_prompt = None
        self.layout = None
        self.show_template_picker = False
        self.template_picker_search_active = False
        self.timeline_edit_target = None
        self.browser_search_active = False
        self.browser_search_query = ""
        self.browser_items = []

    def _persist_entity_to_repository(self, entity, previous_entity_id=None):
        self.persisted_ids.append((entity.get("id"), previous_entity_id))
        return True

    def _write_card_drafts(self):
        return True

    def _entry_file_path_for_dataset(self, dataset_name):
        if self.entry_dir is not None:
            return str(Path(self.entry_dir) / f"{dataset_name}.yaml")
        return super()._entry_file_path_for_dataset(dataset_name)

    def _build_browser_items(self, world_model):
        return []

    def _refresh_timeline_items(self):
        return None

    def _rebuild_browser_hitboxes(self):
        return None

    def _relayout_cards(self):
        return None

    def _close_relation_picker(self, card):
        card["relation_picker_open"] = False

    def _close_wiki_link_picker(self, card):
        card["wiki_link_picker_open"] = False

    def _handle_wiki_link_picker_keydown(self, card, event):
        return False

    def _handle_relation_picker_keydown(self, card, event):
        return False


class EntityIdUpdateTests(unittest.TestCase):
    def test_generated_id_uses_entry_name_slug(self):
        ui = KnowledgeBrowserHarness()
        template = {
            "dataset_name": "factions",
            "entity_type": "faction",
            "id_prefix": "fac",
        }

        entity_id = ui._requested_template_entity_id_from_name(template, "Blue Union")

        self.assertEqual("fac_blue_union", entity_id)

    def test_generated_id_uses_suffix_on_name_collision(self):
        ui = KnowledgeBrowserHarness(
            {
                "fac_blue_union": {
                    "id": "fac_blue_union",
                    "type": "faction",
                }
            }
        )
        template = {
            "dataset_name": "factions",
            "entity_type": "faction",
            "id_prefix": "fac",
        }

        entity_id = ui._requested_template_entity_id_from_name(template, "Blue Union")

        self.assertEqual("fac_blue_union_2", entity_id)

    def test_persisted_id_change_rewrites_entity_references(self):
        parent = {
            "id": "idea_parent_old",
            "type": "idea",
            "pretty_name": "Parent",
            "name": "Parent",
        }
        child = {
            "id": "idea_child",
            "type": "idea",
            "pretty_name": "Child",
            "name": "Child",
            "parents": ["idea_parent_old"],
            "offspring": [{"id": "idea_parent_old"}],
            "nested": {"ref": "idea_parent_old"},
        }
        ui = KnowledgeBrowserHarness(
            {
                "idea_parent_old": parent,
                "idea_child": child,
            }
        )
        card = {
            "entity_id": "idea_parent_old",
            "card_view": SimpleNamespace(entity=parent),
            "pending_entity_id_change": {
                "old": "idea_parent_old",
                "new": "idea_parent_new",
            },
            "draft_edit_buffers": {},
            "is_draft_entity": False,
        }
        parent["id"] = "idea_parent_new"

        self.assertTrue(ui._persist_card_entity(card))

        self.assertEqual(["idea_parent_new"], child["parents"])
        self.assertEqual([{"id": "idea_parent_new"}], child["offspring"])
        self.assertEqual({"ref": "idea_parent_new"}, child["nested"])
        self.assertIn("idea_parent_new", ui.world_model.loader.entities)
        self.assertNotIn("idea_parent_old", ui.world_model.loader.entities)
        self.assertIn(("idea_child", None), ui.persisted_ids)
        self.assertTrue(ui.world_model.touch_degrees.refreshed)
        self.assertTrue(ui.world_model.loader.reference_graph_rebuilt)

    def test_delete_card_entry_removes_repository_block_and_loader_entity(self):
        entity = {
            "id": "idea_delete_me",
            "type": "idea",
            "_dataset": "ideas",
            "pretty_name": "Delete Me",
            "name": "Delete Me",
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            entry_path = Path(temp_dir) / "ideas.yaml"
            entry_path.write_text(
                "- id: idea_keep\n"
                "  type: idea\n"
                "  name: Keep\n"
                "- id: idea_delete_me\n"
                "  type: idea\n"
                "  name: Delete Me\n",
                encoding="utf-8",
            )
            ui = KnowledgeBrowserHarness({"idea_delete_me": entity}, entry_dir=temp_dir)
            ui.card_drafts["idea_delete_me"] = {"entity": entity}
            card = {
                "entity_id": "idea_delete_me",
                "card_view": SimpleNamespace(entity=entity),
                "is_draft_entity": False,
            }
            ui.cards = [card]
            ui.selected_entity_id = "idea_delete_me"

            self.assertTrue(ui._delete_card_entry(card))

            text = entry_path.read_text(encoding="utf-8")
            self.assertIn("idea_keep", text)
            self.assertNotIn("idea_delete_me", text)
            self.assertNotIn("idea_delete_me", ui.world_model.loader.entities)
            self.assertEqual([], ui.world_model.loader.datasets["ideas"])
            self.assertNotIn("idea_delete_me", ui.card_drafts)
            self.assertEqual([], ui.cards)
            self.assertTrue(ui.world_model.touch_degrees.refreshed)
            self.assertTrue(ui.world_model.loader.reference_graph_rebuilt)

    def test_delete_draft_card_entry_does_not_require_repository_block(self):
        entity = {
            "id": "idea_draft_delete",
            "type": "idea",
            "_dataset": "ideas",
            "pretty_name": "Draft Delete",
            "name": "Draft Delete",
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            ui = KnowledgeBrowserHarness({"idea_draft_delete": entity}, entry_dir=temp_dir)
            card = {
                "entity_id": "idea_draft_delete",
                "card_view": SimpleNamespace(entity=entity),
                "is_draft_entity": True,
            }
            ui.cards = [card]

            self.assertTrue(ui._delete_card_entry(card))
            self.assertFalse((Path(temp_dir) / "ideas.yaml").exists())
            self.assertNotIn("idea_draft_delete", ui.world_model.loader.entities)
            self.assertEqual([], ui.cards)

    def test_delete_sparse_loader_entry_does_not_require_repository_block(self):
        entity = {
            "id": "idea_sparse_delete",
            "type": "idea",
            "name": "Sparse Delete",
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            ui = KnowledgeBrowserHarness({"idea_sparse_delete": entity}, entry_dir=temp_dir)
            card = {
                "entity_id": "idea_sparse_delete",
                "card_view": SimpleNamespace(entity=entity),
                "is_draft_entity": False,
            }
            ui.cards = [card]

            self.assertTrue(ui._delete_card_entry(card))

            self.assertNotIn("idea_sparse_delete", ui.world_model.loader.entities)
            self.assertEqual([], ui.world_model.loader.datasets["ideas"])
            self.assertEqual([], ui.cards)

    def test_pixel_art_editor_derives_canvas_and_saves_illustration_png(self):
        parent = {
            "id": "vehicle_parent",
            "type": "vehicle",
            "_dataset": "vehicles",
            "name": "Test Rover",
            "vehicle_class": "ground_vehicle",
        }
        illustration = {
            "id": "idea_rover_pixel",
            "type": "idea",
            "_dataset": "ideas",
            "name": "Rover Pixel",
            "idea_class": "illustration",
            "parents": ["vehicle_parent"],
            "media_path": "",
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            ui = KnowledgeBrowserHarness(
                {
                    "vehicle_parent": parent,
                    "idea_rover_pixel": illustration,
                },
                entry_dir=temp_dir,
            )
            ui.PROJECT_ROOT = Path(temp_dir)

            self.assertTrue(ui._open_pixel_art_editor("idea_rover_pixel"))
            ui.pixel_art_editor["metric_size_buffer"] = "4"
            self.assertTrue(ui._begin_pixel_art_canvas())

            self.assertEqual(80, ui.pixel_art_editor["canvas_width"])
            self.assertEqual(50, ui.pixel_art_editor["canvas_height"])
            ui.pixel_art_editor["pixels"][0][0] = (255, 0, 0)

            self.assertTrue(ui._save_pixel_art_editor())

            self.assertEqual("assets/illustrations/idea_rover_pixel_pixel.png", illustration["media_path"])
            self.assertEqual(4.0, illustration["depicted_size_m"])
            self.assertEqual(80, illustration["pixel_canvas_width"])
            self.assertEqual(50, illustration["pixel_canvas_height"])
            self.assertTrue((Path(temp_dir) / illustration["media_path"]).exists())

    def test_pixel_art_canvas_scale_uses_fifty_pixels_for_small_metric_objects(self):
        ui = KnowledgeBrowserHarness()

        self.assertEqual((50, 50), ui._pixel_canvas_size_for_entity({"type": "idea"}, 0.1))
        self.assertEqual((50, 50), ui._pixel_canvas_size_for_entity({"type": "idea"}, 1.0))
        self.assertEqual((75, 75), ui._pixel_canvas_size_for_entity({"type": "idea"}, 5.0))

    def test_pixel_art_reference_click_samples_color(self):
        illustration = {
            "id": "idea_reference_pixel",
            "type": "idea",
            "_dataset": "ideas",
            "name": "Reference Pixel",
            "idea_class": "illustration",
            "media_path": "",
        }
        ui = KnowledgeBrowserHarness({"idea_reference_pixel": illustration})
        self.assertTrue(ui._open_pixel_art_editor("idea_reference_pixel"))
        ui.pixel_art_editor["metric_size_buffer"] = "1"
        self.assertTrue(ui._begin_pixel_art_canvas())

        surface = pygame.Surface((2, 1), pygame.SRCALPHA)
        surface.set_at((0, 0), (10, 20, 30, 255))
        surface.set_at((1, 0), (200, 100, 50, 255))
        ui.pixel_art_editor["reference_surface"] = surface
        ui.pixel_art_editor["reference_rect"] = pygame.Rect(10, 10, 20, 10)

        self.assertTrue(ui._sample_pixel_reference_at((25, 15)))

        self.assertEqual((200, 100, 50), ui.pixel_art_editor["color"])

    def test_pixel_art_brush_size_and_eraser_update_pixel_cells(self):
        illustration = {
            "id": "idea_brush_pixel",
            "type": "idea",
            "_dataset": "ideas",
            "name": "Brush Pixel",
            "idea_class": "illustration",
            "media_path": "",
        }
        ui = KnowledgeBrowserHarness({"idea_brush_pixel": illustration})
        self.assertTrue(ui._open_pixel_art_editor("idea_brush_pixel"))
        ui.pixel_art_editor["metric_size_buffer"] = "1"
        self.assertTrue(ui._begin_pixel_art_canvas())
        ui.pixel_art_editor["canvas_rect"] = pygame.Rect(0, 0, 50, 50)
        ui.pixel_art_editor["color"] = (255, 0, 0)

        self.assertTrue(ui._set_pixel_editor_brush_size(3))
        self.assertTrue(ui._paint_pixel_editor_at((25, 25)))

        painted = sum(1 for row in ui.pixel_art_editor["pixels"] for pixel in row if pixel == (255, 0, 0))
        self.assertEqual(9, painted)

        self.assertTrue(ui._set_pixel_editor_tool("eraser"))
        self.assertTrue(ui._paint_pixel_editor_at((25, 25)))

        painted_after_erase = sum(1 for row in ui.pixel_art_editor["pixels"] for pixel in row if pixel == (255, 0, 0))
        self.assertEqual(0, painted_after_erase)

    def test_pixel_art_save_reports_missing_illustration(self):
        illustration = {
            "id": "idea_missing_pixel",
            "type": "idea",
            "_dataset": "ideas",
            "name": "Missing Pixel",
            "idea_class": "illustration",
            "media_path": "",
        }
        ui = KnowledgeBrowserHarness({"idea_missing_pixel": illustration})
        self.assertTrue(ui._open_pixel_art_editor("idea_missing_pixel"))
        ui.pixel_art_editor["metric_size_buffer"] = "1"
        self.assertTrue(ui._begin_pixel_art_canvas())
        ui.world_model.loader.entities.pop("idea_missing_pixel")

        self.assertFalse(ui._save_pixel_art_editor())

        self.assertEqual("Could not find illustration entry", ui.pixel_art_editor["status"])

    def test_relation_sync_skips_individual_repository_write_errors(self):
        idea = {
            "id": "idea_ok",
            "type": "idea",
            "_dataset": "ideas",
            "name": "Okay",
        }
        clade = {
            "id": "clade_bad",
            "type": "cladistics",
            "_dataset": "cladistics",
            "name": "Bad Clade",
        }
        ui = KnowledgeBrowserHarness({"idea_ok": idea, "clade_bad": clade})
        ui.world_model.loader.populate_offspring = lambda: {"idea_ok", "clade_bad"}

        def persist(entity, previous_entity_id=None):
            if entity.get("id") == "clade_bad":
                raise OSError(22, "Invalid argument")
            ui.persisted_ids.append((entity.get("id"), previous_entity_id))
            return True

        ui._persist_entity_to_repository = persist

        changed = ui._sync_bidirectional_relations(persist=True)

        self.assertEqual({"idea_ok", "clade_bad"}, changed)
        self.assertIn(("idea_ok", None), ui.persisted_ids)
        self.assertIn("clade_bad", ui.relation_link_status)
        self.assertTrue(ui.world_model.loader.reference_graph_rebuilt)

    def test_card_name_edit_consumes_typing_before_browser_search(self):
        entity = {
            "id": "idea_edit_name",
            "type": "idea",
            "_dataset": "ideas",
            "pretty_name": "Old",
            "name": "Old",
        }
        ui = KnowledgeBrowserHarness({"idea_edit_name": entity})
        card = {
            "entity_id": "idea_edit_name",
            "card_view": EntityCard(entity, dataset_name="ideas", world_model=ui.world_model),
            "is_edit_mode": True,
            "active_edit_field": "name",
            "edit_buffer": "",
            "edit_cursor": 0,
            "edit_original_value": "Old",
            "draft_edit_buffers": {},
        }
        ui.cards = [card]
        ui.browser_search_active = True
        ui.browser_search_query = ""

        result = ui._handle_keydown_event(SimpleNamespace(
            key=pygame.K_a,
            unicode="a",
            mod=0,
        ))

        self.assertEqual("__ui_consumed__", result)
        self.assertEqual("a", card["edit_buffer"])
        self.assertEqual("", ui.browser_search_query)

    def test_stellar_neighbour_link_selection_opens_distance_prompt(self):
        source = {
            "id": "system_alpha",
            "type": "location",
            "_dataset": "locations",
            "name": "Alpha",
            "location_class": "star_system",
        }
        target = {
            "id": "system_beta",
            "type": "location",
            "_dataset": "locations",
            "name": "Beta",
            "location_class": "star_system",
        }
        ui = KnowledgeBrowserHarness({"system_alpha": source, "system_beta": target})
        source_card = {
            "entity_id": "system_alpha",
            "card_view": SimpleNamespace(entity=source),
            "is_edit_mode": True,
        }
        ui.cards = [source_card]
        ui.relation_link_target = {
            "mode": "stellar_neighbourhood",
            "source_card": source_card,
            "source_entity_id": "system_alpha",
            "field_key": "stellar_neighbours",
            "target": "star_system",
        }

        linked = ui._link_relation_from_browser_entity("system_beta")

        self.assertTrue(linked)
        self.assertIsNone(ui.relation_link_target)
        self.assertEqual("distance", ui.stellar_neighbourhood_prompt["mode"])
        self.assertEqual("system_beta", ui.stellar_neighbourhood_prompt["selected_system_id"])

    def test_relations_tab_new_entry_context_links_to_active_card(self):
        source = {
            "id": "idea_source",
            "type": "idea",
            "_dataset": "ideas",
            "name": "Source",
        }
        ui = KnowledgeBrowserHarness({"idea_source": source})
        card_view = EntityCard(source, dataset_name="ideas", world_model=ui.world_model)
        card_view.set_active_tab("relations")
        ui.cards = [
            {
                "entity_id": "idea_source",
                "card_view": card_view,
                "is_edit_mode": True,
                "active_edit_field": "parents",
            }
        ]

        context = ui._relation_tab_new_entry_context()

        self.assertEqual("idea_source", context["link_source_entity_id"])
        self.assertEqual("parents", context["link_field_key"])

    def test_new_entry_prompt_selected_suggestion_opens_and_links_existing_entry(self):
        source = {
            "id": "idea_source",
            "type": "idea",
            "_dataset": "ideas",
            "name": "Source",
        }
        target = {
            "id": "entry_123",
            "type": "idea",
            "_dataset": "ideas",
            "name": "Entry 123",
            "card_color": "#4466aa",
        }
        ui = KnowledgeBrowserHarness({"idea_source": source, "entry_123": target})
        source_card = {
            "entity_id": "idea_source",
            "card_view": EntityCard(source, dataset_name="ideas", world_model=ui.world_model),
            "is_draft_entity": True,
        }
        ui.cards = [source_card]
        ui._open_entry_name_prompt(
            None,
            mode="new_entry",
            context={
                "link_source_entity_id": "idea_source",
                "link_field_key": "related",
            },
            initial_buffer="Entry 12",
        )
        ui.entry_name_prompt["suggestion_keyboard_active"] = True

        self.assertTrue(ui._select_entry_name_prompt_suggestion())

        self.assertIsNone(ui.entry_name_prompt)
        self.assertEqual(["entry_123"], source["related"])

    def test_new_entry_from_template_links_to_relations_tab_source(self):
        source = {
            "id": "idea_source",
            "type": "idea",
            "_dataset": "ideas",
            "name": "Source",
        }
        ui = KnowledgeBrowserHarness({"idea_source": source})
        source_card = {
            "entity_id": "idea_source",
            "card_view": EntityCard(source, dataset_name="ideas", world_model=ui.world_model),
            "is_draft_entity": True,
        }
        ui.cards = [source_card]
        ui.pending_new_entry_name = "Fresh Entry"
        ui.template_picker_context = {
            "link_source_entity_id": "idea_source",
            "link_field_key": "related",
        }
        template = {
            "dataset_name": "ideas",
            "entity_type": "idea",
            "id_prefix": "idea",
        }

        self.assertTrue(ui._create_new_entry_from_template(template))

        self.assertEqual(["idea_fresh_entry"], source["related"])
        self.assertIn("idea_fresh_entry", ui.world_model.loader.entities)

    def test_wiki_links_sync_into_related_not_wiki_mentions(self):
        source = {
            "id": "idea_source",
            "type": "idea",
            "_dataset": "ideas",
            "name": "Source",
            "wiki_entry": "See [[Entry 123]].",
            "related": ["idea_existing"],
            "wiki_mentions": ["old_wiki"],
            "derived_from": ["old_derived"],
        }
        target = {
            "id": "entry_123",
            "type": "idea",
            "_dataset": "ideas",
            "name": "Entry 123",
        }
        existing = {
            "id": "idea_existing",
            "type": "idea",
            "_dataset": "ideas",
            "name": "Existing",
        }
        ui = KnowledgeBrowserHarness({
            "idea_source": source,
            "entry_123": target,
            "idea_existing": existing,
        })
        card = {
            "entity_id": "idea_source",
            "card_view": EntityCard(source, dataset_name="ideas", world_model=ui.world_model),
        }

        self.assertTrue(ui._sync_card_wiki_mentions(card))

        self.assertEqual(["idea_existing", "old_derived", "old_wiki", "entry_123"], source["related"])
        self.assertNotIn("wiki_mentions", source)
        self.assertNotIn("derived_from", source)

    def test_stellar_neighbour_distance_prompt_survives_rebuild_reset(self):
        ui = KnowledgeBrowserHarness()
        ui.stellar_neighbourhood_prompt = {
            "mode": "distance",
            "source_entity_id": "system_alpha",
            "selected_system_id": "system_beta",
        }

        ui.reset()

        self.assertEqual("distance", ui.stellar_neighbourhood_prompt["mode"])
        self.assertEqual("system_beta", ui.stellar_neighbourhood_prompt["selected_system_id"])

    def test_stellar_neighbour_distance_confirmation_writes_bidirectional_rows(self):
        source = {
            "id": "system_alpha",
            "type": "location",
            "_dataset": "locations",
            "name": "Alpha",
            "location_class": "star_system",
        }
        target = {
            "id": "system_beta",
            "type": "location",
            "_dataset": "locations",
            "name": "Beta",
            "location_class": "star_system",
        }
        ui = KnowledgeBrowserHarness({"system_alpha": source, "system_beta": target})
        source_card = {
            "entity_id": "system_alpha",
            "card_view": SimpleNamespace(entity=source),
            "is_edit_mode": True,
        }
        ui.cards = [source_card]
        ui._save_or_persist_card_for_entity_id = lambda entity_id: True
        ui.stellar_neighbourhood_prompt = {
            "mode": "distance",
            "source_card": source_card,
            "source_entity_id": "system_alpha",
            "selected_system_id": "system_beta",
            "distance": "4.2",
        }

        confirmed = ui._confirm_stellar_neighbourhood_prompt()

        self.assertTrue(confirmed)
        self.assertEqual([{"system": "system_beta", "distance_ly": 4.2}], source["stellar_neighbours"])
        self.assertEqual([{"system": "system_alpha", "distance_ly": 4.2}], target["stellar_neighbours"])
        self.assertIsNone(ui.stellar_neighbourhood_prompt)


if __name__ == "__main__":
    unittest.main()
