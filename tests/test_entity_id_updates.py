import unittest
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pygame

from ui.card import EntityCard
from ui.entry_name_prompt_ui import EntryNamePromptUI
from ui.knowledge_canvas_controller import KnowledgeCanvasController
from ui.knowledge_browser_ui import KnowledgeBrowserUI
from ui.pixel_art_editor_ui import PixelArtEditorUI
from ui.knowledge_repository_service import KnowledgeRepositoryService
from ui.stellar_neighbour_prompt_ui import StellarNeighbourPromptUI


class DummyLoader:
    def __init__(self, entities):
        self.entities = entities
        self.datasets = {"ideas": list(entities.values())}
        self.reference_graph_rebuilt = False

    def build_reference_graph(self):
        self.reference_graph_rebuilt = True

    def persist_entity(self, entity, previous_entity_id=None):
        entity_id = entity.get("id")
        if not entity_id:
            return False
        previous_entity_id = previous_entity_id or None
        if previous_entity_id and previous_entity_id != entity_id:
            self.entities.pop(previous_entity_id, None)
        dataset_name = entity.get("_dataset") or entity.get("type") or "ideas"
        entity["_dataset"] = dataset_name
        dataset = self.datasets.setdefault(dataset_name, [])
        dataset[:] = [
            item for item in dataset
            if not (isinstance(item, dict) and item.get("id") in {entity_id, previous_entity_id})
        ]
        dataset.append(entity)
        self.entities[entity_id] = entity
        return True

    def remove_entity(self, entity_id, dataset_name=None):
        removed = self.entities.pop(entity_id, None) is not None
        dataset_names = [dataset_name] if dataset_name else list(self.datasets)
        for candidate_name in dataset_names:
            dataset = self.datasets.get(candidate_name, [])
            before_count = len(dataset)
            dataset[:] = [
                item for item in dataset
                if not (isinstance(item, dict) and item.get("id") == entity_id)
            ]
            removed = removed or len(dataset) != before_count
        return removed


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
        self.active_card_color_slider = None
        self.active_timeline_resize = False
        self.active_timeline_pan = False
        self.timeline_resize_start_mouse_y = None
        self.timeline_resize_start_height = None
        self.timeline_splitter_click_pending = False
        self.timeline_splitter_pending_mouse_pos = None
        self.timeline_collapsed = False
        self.timeline_pan_last_mouse_x = None
        self.active_canvas_pan = False
        self.card_drag_mouse_offset = (0, 0)
        self.card_drag_last_mouse_pos = None
        self.card_resize_start_mouse = None
        self.card_resize_start_size = None
        self.card_resize_start_position = None
        self.card_resize_edges = None
        self.canvas_pan_start_mouse = None
        self.canvas_pan_start_offset = None
        self.canvas_relation_link_source_id = None
        self.canvas_relation_status = ""
        self.relation_link_target = None
        self.relation_link_status = ""
        self.entry_name_prompt = None
        self.stellar_neighbourhood_prompt = None
        self.layout = None
        self.font_for_layout = None
        self.show_template_picker = False
        self.template_picker_search_active = False
        self.timeline_edit_target = None
        self.browser_search_active = False
        self.browser_search_query = ""
        self.browser_items = []
        self.relayout_count = 0

    def _persist_entity_to_repository(self, entity, previous_entity_id=None):
        self.persisted_ids.append((entity.get("id"), previous_entity_id))
        return True

    def _write_card_drafts(self):
        return True

    def _build_browser_items(self, world_model):
        return []

    def _refresh_timeline_items(self):
        return None

    def _rebuild_browser_hitboxes(self):
        return None

    def _relayout_cards(self):
        self.relayout_count += 1
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
    def test_rich_card_header_drag_starts_before_body_hit_testing(self):
        pygame.font.init()
        ui = KnowledgeBrowserHarness({"rich_card": {"id": "rich_card", "type": "idea"}})
        ui.layout = {
            "right_rect": pygame.Rect(300, 80, 700, 520),
        }
        ui.canvas_zoom = 1.0
        ui.canvas_offset_x = 0
        ui.canvas_offset_y = 0
        ui.canvas_content_width = 0
        ui.canvas_content_height = 0
        ui.compact_canvas_zoom_threshold = 0.62
        ui.card_font_cache = {}
        ui.font_for_layout = pygame.font.SysFont("consolas", 16)
        ui.timeline_ui = SimpleNamespace(
            set_open_canvas_entity_ids=lambda _ids: False,
            rebuild_layout=lambda: None,
        )
        ui.canvas_relation_edges = []
        ui.relation_tree_neighbor_cache = {}
        ui.cards = [
            {
                "entity_id": "rich_card",
                "canvas_x": 24,
                "canvas_y": 84,
                "canvas_w": 420,
                "canvas_h": 1200,
                "auto_canvas_h": True,
                "rect": pygame.Rect(324, 164, 420, 1200),
                "header_drag_rect": pygame.Rect(324, 164, 420, 66),
                "close_rect": None,
                "resize_hitboxes": [],
                "resize_handle_rect": pygame.Rect(728, 1348, 14, 14),
                "card_view": None,
                "relation_hitboxes": [
                    ({"kind": "existing", "entity_id": f"ref_{index}"}, pygame.Rect(330, 240 + index * 20, 360, 18))
                    for index in range(200)
                ],
            }
        ]

        result = ui._canvas_controller()._handle_card_canvas_click((340, 180), ui.layout["right_rect"])

        self.assertEqual("__ui_consumed__", result)
        self.assertEqual("rich_card", ui.active_card_drag_id)
        self.assertEqual((340, 180), ui.card_drag_last_mouse_pos)

    def test_active_card_drag_moves_existing_layout_without_full_relayout(self):
        ui = KnowledgeBrowserHarness({"rich_card": {"id": "rich_card", "type": "idea"}})
        ui.layout = {
            "right_rect": pygame.Rect(300, 80, 700, 520),
        }
        ui.canvas_zoom = 1.0
        ui.canvas_offset_x = 0
        ui.canvas_offset_y = 0
        ui.canvas_relation_edges = []
        ui.active_card_drag_id = "rich_card"
        ui.card_drag_mouse_offset = (16, 16)
        ui.card_drag_last_mouse_pos = (340, 180)
        ui.cards = [
            {
                "entity_id": "rich_card",
                "canvas_x": 24,
                "canvas_y": 84,
                "rect": pygame.Rect(324, 164, 420, 520),
                "header_drag_rect": pygame.Rect(324, 164, 420, 66),
                "canvas_relation_add_rect": pygame.Rect(700, 390, 28, 28),
            }
        ]
        before_relayout_count = ui.relayout_count

        result = ui._handle_mousemotion_event(SimpleNamespace(pos=(360, 205)))

        self.assertEqual("__ui_consumed__", result)
        self.assertEqual(before_relayout_count, ui.relayout_count)
        self.assertEqual(pygame.Rect(344, 189, 420, 520), ui.cards[0]["rect"])
        self.assertEqual((360, 205), ui.card_drag_last_mouse_pos)

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

    def test_header_rebuild_does_not_create_launch_vehicle_test_button(self):
        ui = KnowledgeBrowserHarness()
        ui.header_button = SimpleNamespace(button_id="launch_vehicle_test")
        ui.layout = {
            "header_rect": pygame.Rect(0, 0, 900, 52),
            "right_rect": pygame.Rect(300, 80, 600, 400),
        }
        ui.contemporary_spawn_count = 1
        ui.contemporary_spawn_min = 0
        ui.contemporary_spawn_max = 12
        ui.relation_tree_touch_degree = 2
        ui.relation_tree_min_touch_degree = 1
        ui.relation_tree_max_touch_degree = 6

        ui._build_header_button()

        self.assertIsNone(ui.header_button)
        button_ids = {
            button.id
            for button in (
                ui.new_entry_button,
                ui.random_task_button,
                ui.random_entry_button,
                ui.clear_canvas_button,
            )
            if button is not None
        }
        self.assertNotIn("launch_vehicle_test", button_ids)

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

    def test_delete_card_entry_removes_repository_entity_and_loader_entity(self):
        entity = {
            "id": "idea_delete_me",
            "type": "idea",
            "_dataset": "ideas",
            "pretty_name": "Delete Me",
            "name": "Delete Me",
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            keep = {"id": "idea_keep", "type": "idea", "_dataset": "ideas", "name": "Keep"}
            ui = KnowledgeBrowserHarness({"idea_keep": keep, "idea_delete_me": entity}, entry_dir=temp_dir)
            ui.card_drafts["idea_delete_me"] = {"entity": entity}
            card = {
                "entity_id": "idea_delete_me",
                "card_view": SimpleNamespace(entity=entity),
                "is_draft_entity": False,
            }
            ui.cards = [card]
            ui.selected_entity_id = "idea_delete_me"

            self.assertTrue(ui._delete_card_entry(card))

            self.assertIn("idea_keep", ui.world_model.loader.entities)
            self.assertNotIn("idea_delete_me", ui.world_model.loader.entities)
            self.assertEqual(["idea_keep"], [item["id"] for item in ui.world_model.loader.datasets["ideas"]])
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

            self.assertIsInstance(ui._repository_service(), KnowledgeRepositoryService)
            self.assertTrue(ui._delete_card_entry(card))
            self.assertEqual([], list(Path(temp_dir).iterdir()))
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
            self.assertIsInstance(ui._pixel_art_editor_controller(), PixelArtEditorUI)
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

    def test_derived_clade_color_sets_full_card_palette(self):
        root = {
            "id": "clade_root",
            "type": "cladistics",
            "_dataset": "cladistics",
            "name": "Root",
        }
        species_a = {
            "id": "species_a",
            "type": "species",
            "_dataset": "species",
            "name": "Species A",
            "parents": ["clade_root"],
            "card_color": "#000000",
            "card_header_color": "#100000",
            "wiki_field_colors": {"default": "#001000", "alternate": "#000010"},
        }
        species_b = {
            "id": "species_b",
            "type": "species",
            "_dataset": "species",
            "name": "Species B",
            "parents": ["clade_root"],
            "card_color": "#202020",
            "card_header_color": "#302020",
            "wiki_field_colors": {"default": "#203020", "alternate": "#202030"},
        }
        ui = KnowledgeBrowserHarness({
            "clade_root": root,
            "species_a": species_a,
            "species_b": species_b,
        })

        changed = ui._update_derived_clade_color("clade_root", persist=True)

        self.assertTrue(changed)
        self.assertEqual("#101010", root["card_color"])
        self.assertEqual("#201010", root["card_header_color"])
        self.assertEqual({"default": "#102010", "alternate": "#101020"}, root["wiki_field_colors"])
        self.assertEqual("derived_offspring", root["card_color_source"])
        self.assertIn(("clade_root", None), ui.persisted_ids)

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

    def test_person_quote_edit_consumes_typing_before_browser_search(self):
        entity = {
            "id": "person_quote_edit",
            "type": "person",
            "_dataset": "people",
            "pretty_name": "Quote Person",
            "name": "Quote Person",
        }
        ui = KnowledgeBrowserHarness({"person_quote_edit": entity})
        card_view = EntityCard(entity, dataset_name="people", world_model=ui.world_model)
        card_view.set_active_tab("simulation")
        card = {
            "entity_id": "person_quote_edit",
            "card_view": card_view,
            "is_edit_mode": True,
            "person_quote_buffers": {"quote": "", "date": "", "context": ""},
        }
        card_view._set_person_quote_active_field(card, card_view.PERSON_QUOTE_TEXT_FIELD)
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
        self.assertEqual(0, ui.relayout_count)
        self.assertEqual("", ui.browser_search_query)

    def test_person_conversation_edit_consumes_typing_before_browser_search(self):
        entity = {
            "id": "person_conversation_edit",
            "type": "person",
            "_dataset": "people",
            "pretty_name": "Quote Person",
            "name": "Quote Person",
        }
        ui = KnowledgeBrowserHarness({"person_conversation_edit": entity})
        card_view = EntityCard(entity, dataset_name="people", world_model=ui.world_model)
        card_view.set_active_tab("simulation")
        card = {
            "entity_id": "person_conversation_edit",
            "card_view": card_view,
            "is_edit_mode": True,
            "person_quote_capture_mode": "conversations",
            "person_quote_buffers": {
                "conversation_speaker": "Quote Person",
                "conversation_date": "",
                "conversation_message": "",
            },
        }
        card_view._set_person_quote_active_field(card, card_view.PERSON_CONVERSATION_MESSAGE_FIELD)
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
        self.assertEqual(0, ui.relayout_count)
        self.assertEqual("", ui.browser_search_query)

    def test_card_draft_keystroke_does_not_refresh_timeline(self):
        entity = {
            "id": "idea_edit_name",
            "type": "idea",
            "_dataset": "ideas",
            "pretty_name": "Old",
            "name": "Old",
        }
        ui = KnowledgeBrowserHarness({"idea_edit_name": entity})
        refresh_count = {"value": 0}
        ui._refresh_timeline_items = lambda: refresh_count.__setitem__("value", refresh_count["value"] + 1)
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

        result = ui._handle_keydown_event(SimpleNamespace(
            key=pygame.K_a,
            unicode="a",
            mod=0,
        ))

        self.assertEqual("__ui_consumed__", result)
        self.assertEqual(0, refresh_count["value"])

    def test_save_card_draft_does_not_sync_wiki_mentions(self):
        entity = {
            "id": "idea_source",
            "type": "idea",
            "_dataset": "ideas",
            "name": "Source",
            "wiki_entry": "See [[Entry 123]].",
        }
        ui = KnowledgeBrowserHarness({"idea_source": entity})
        ui._sync_card_wiki_mentions = lambda card, wiki_text=None: self.fail("draft save should not scan wiki mentions")
        card = {
            "entity_id": "idea_source",
            "card_view": EntityCard(entity, dataset_name="ideas", world_model=ui.world_model),
            "is_edit_mode": True,
            "active_edit_field": "wiki_entry",
            "edit_buffer": "See [[Entry 123]].",
            "edit_cursor": 18,
            "draft_edit_buffers": {},
        }

        self.assertTrue(ui._save_card_draft(card))

    def test_card_color_slider_click_defers_repository_persist(self):
        entity = {
            "id": "idea_color",
            "type": "idea",
            "_dataset": "ideas",
            "name": "Color",
            "card_color": "#4466aa",
        }
        ui = KnowledgeBrowserHarness({"idea_color": entity})
        slider_rect = pygame.Rect(40, 30, 120, 10)
        hit_rect = slider_rect.inflate(6, 8)
        card = {
            "entity_id": "idea_color",
            "card_view": SimpleNamespace(
                entity=entity,
                handle_location_click=lambda card_arg, mouse_pos: False,
                handle_production_click=lambda card_arg, mouse_pos: False,
                handle_timeline_click=lambda card_arg, mouse_pos: False,
                handle_phylogeny_click=lambda card_arg, mouse_pos: False,
                handle_pixeltile_click=lambda card_arg, mouse_pos: False,
            ),
            "toolbelt_hitboxes": [
                (
                    {
                        "kind": "color_picker",
                        "control": "slider",
                        "channel": "h",
                        "slider_rect": slider_rect,
                    },
                    hit_rect,
                )
            ],
        }
        ui.cards = [card]

        result = ui._handle_card_canvas_click((slider_rect.x + 72, slider_rect.centery), pygame.Rect(0, 0, 260, 180))

        self.assertEqual("__ui_consumed__", result)
        self.assertEqual([], ui.persisted_ids)
        self.assertTrue(card.get("pending_color_persist"))
        self.assertIsNotNone(ui.active_card_color_slider)

    def test_card_color_slider_motion_stays_in_memory_without_relayout(self):
        entity = {
            "id": "idea_color",
            "type": "idea",
            "_dataset": "ideas",
            "name": "Color",
            "card_color": "#4466aa",
        }
        ui = KnowledgeBrowserHarness({"idea_color": entity})
        slider_rect = pygame.Rect(40, 30, 120, 10)
        card = {
            "entity_id": "idea_color",
            "card_view": SimpleNamespace(entity=entity),
        }
        ui.cards = [card]
        ui.active_card_color_slider = {
            "entity_id": "idea_color",
            "channel": "s",
            "slider_rect": slider_rect,
            "role": "body",
            "section_id": None,
        }

        result = ui._handle_mousemotion_event(SimpleNamespace(pos=(slider_rect.x + 84, slider_rect.centery)))

        self.assertEqual("__ui_consumed__", result)
        self.assertEqual([], ui.persisted_ids)
        self.assertTrue(card.get("pending_color_persist"))
        self.assertEqual(0, ui.relayout_count)

    def test_card_color_slider_release_persists_once_without_draft_snapshot(self):
        entity = {
            "id": "idea_color",
            "type": "idea",
            "_dataset": "ideas",
            "name": "Color",
            "card_color": "#4466aa",
        }
        ui = KnowledgeBrowserHarness({"idea_color": entity})
        card = {
            "entity_id": "idea_color",
            "card_view": SimpleNamespace(entity=entity),
            "pending_color_persist": True,
        }
        ui.cards = [card]
        ui.active_card_color_slider = {"entity_id": "idea_color"}

        result = ui._handle_mousebuttonup_event(SimpleNamespace(button=1))

        self.assertEqual("__ui_consumed__", result)
        self.assertEqual([("idea_color", None)], ui.persisted_ids)
        self.assertNotIn("idea_color", ui.card_drafts)
        self.assertFalse(card.get("pending_color_persist", False))
        self.assertIsNone(ui.active_card_color_slider)

    def test_draft_card_color_slider_release_saves_only_draft(self):
        entity = {
            "id": "idea_color",
            "type": "idea",
            "_dataset": "ideas",
            "name": "Color",
            "card_color": "#4466aa",
        }
        ui = KnowledgeBrowserHarness({"idea_color": entity})
        card = {
            "entity_id": "idea_color",
            "card_view": SimpleNamespace(entity=entity),
            "is_draft_entity": True,
            "pending_color_persist": True,
        }
        ui.cards = [card]
        ui.active_card_color_slider = {"entity_id": "idea_color"}

        result = ui._handle_mousebuttonup_event(SimpleNamespace(button=1))

        self.assertEqual("__ui_consumed__", result)
        self.assertEqual([], ui.persisted_ids)
        self.assertIn("idea_color", ui.card_drafts)
        self.assertFalse(card.get("pending_color_persist", False))

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
        self.assertIsInstance(ui._entry_name_prompt_controller(), EntryNamePromptUI)
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

        self.assertIsInstance(ui._canvas_controller(), KnowledgeCanvasController)
        self.assertTrue(ui._create_new_entry_from_template(template))

        self.assertEqual("entry_description", ui.entry_name_prompt["mode"])
        ui.entry_name_prompt["buffer"] = "Notebook Seed"
        ui.entry_name_prompt["cursor"] = len("Notebook Seed")
        self.assertTrue(ui._submit_entry_name_prompt())

        self.assertEqual(["idea_fresh_entry"], source["related"])
        self.assertIn("idea_fresh_entry", ui.world_model.loader.entities)
        self.assertEqual(
            "Notebook Seed",
            ui.world_model.loader.entities["idea_fresh_entry"]["three_word_description"],
        )

    def test_new_entry_from_template_allows_blank_description(self):
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
        self.assertEqual("entry_description", ui.entry_name_prompt["mode"])
        self.assertTrue(ui._submit_entry_name_prompt())

        self.assertIsNone(ui.entry_name_prompt)
        self.assertEqual(["idea_fresh_entry"], source["related"])
        self.assertIn("idea_fresh_entry", ui.world_model.loader.entities)
        self.assertEqual(
            "",
            ui.world_model.loader.entities["idea_fresh_entry"].get("three_word_description", ""),
        )

    def test_relation_create_chip_uses_new_entry_route(self):
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
            "is_edit_mode": True,
            "is_draft_entity": True,
        }
        ui.cards = [source_card]
        relation_info = {
            "kind": "create",
            "field_key": "related",
            "target": "entity",
            "label": "Create entry",
        }

        self.assertTrue(ui._handle_relation_chip_click(source_card, relation_info))
        self.assertEqual("new_entry", ui.entry_name_prompt["mode"])
        self.assertEqual("idea_source", ui.entry_name_prompt["context"]["link_source_entity_id"])
        self.assertNotIn("idea_1", ui.world_model.loader.entities)

        ui.entry_name_prompt["buffer"] = "Fresh Vehicle"
        ui.entry_name_prompt["cursor"] = len("Fresh Vehicle")
        self.assertTrue(ui._submit_entry_name_prompt())
        self.assertTrue(ui.show_template_picker)

        vehicle_template = {
            "dataset_name": "vehicles",
            "entity_type": "vehicle",
            "id_prefix": "veh",
        }
        self.assertTrue(ui._create_new_entry_from_template(vehicle_template))
        self.assertEqual("entry_description", ui.entry_name_prompt["mode"])
        self.assertTrue(ui._submit_entry_name_prompt())

        self.assertEqual(["veh_fresh_vehicle"], source["related"])
        self.assertIn("veh_fresh_vehicle", ui.world_model.loader.entities)
        self.assertNotIn("idea_fresh_vehicle", ui.world_model.loader.entities)

    def test_entry_description_suggestions_are_scoped_to_selected_class(self):
        vehicle = {
            "id": "veh_existing",
            "type": "vehicle",
            "_dataset": "vehicles",
            "name": "Existing Vehicle",
            "vehicle_class": "ground_vehicle",
            "three_word_description": "Medium Range SUV",
        }
        animal = {
            "id": "species_existing",
            "type": "species",
            "_dataset": "species",
            "common_name": "Existing Animal",
            "species_class": "natural_vertebrate",
            "three_word_description": "Medium Seabird",
        }
        ui = KnowledgeBrowserHarness({
            "veh_existing": vehicle,
            "species_existing": animal,
        })
        ui.world_model.loader.datasets = {
            "vehicles": [vehicle],
            "species": [animal],
        }
        template = {
            "dataset_name": "vehicles",
            "entity_type": "vehicle",
            "label": "Ground Vehicle",
            "subclass_field": "vehicle_class",
            "subclass_value": "ground_vehicle",
            "initial_fields": {"vehicle_class": "ground_vehicle"},
        }
        ui._open_entry_description_prompt(template, "New Rover")

        matches = ui._entry_name_prompt_matches("Medium")

        self.assertEqual(["Medium Range SUV"], [match["label"] for match in matches])

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
        self.assertIsInstance(
            ui._stellar_neighbour_prompt_controller(),
            StellarNeighbourPromptUI,
        )

        confirmed = ui._confirm_stellar_neighbourhood_prompt()

        self.assertTrue(confirmed)
        self.assertEqual([{"system": "system_beta", "distance_ly": 4.2}], source["stellar_neighbours"])
        self.assertEqual([{"system": "system_alpha", "distance_ly": 4.2}], target["stellar_neighbours"])
        self.assertIsNone(ui.stellar_neighbourhood_prompt)

    def test_star_system_creation_opens_only_system_card(self):
        ui = KnowledgeBrowserHarness()
        ui.schema_entry_templates = [
            {
                "dataset_name": "locations",
                "entity_type": "location",
                "label": "Location",
                "initial_fields": {},
            }
        ]
        opened_ids = []
        saved_ids = []
        ui._populate_required_schema_fields = lambda entity, template: None
        ui._place_new_card_in_canvas_view = lambda card: None
        ui._save_card_draft = lambda card: saved_ids.append(card.get("entity_id")) or True

        def ensure_card(entity, relayout=True, bring_to_front=True):
            opened_ids.append(entity["id"])
            card = {"entity_id": entity["id"], "card_view": SimpleNamespace(entity=entity)}
            ui.cards.append(card)
            return card

        ui._ensure_card = ensure_card

        created = ui._create_star_system_from_class(
            ui.schema_entry_templates[0],
            "Alpha System",
            "G2V",
        )

        self.assertEqual("system_alpha_system", created["id"])
        self.assertEqual(["system_alpha_system"], opened_ids)
        self.assertEqual(["system_alpha_system"], saved_ids)
        self.assertIn("star_alpha_system_primary", ui.world_model.loader.entities)


if __name__ == "__main__":
    unittest.main()
