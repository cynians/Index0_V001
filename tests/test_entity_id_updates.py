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


if __name__ == "__main__":
    unittest.main()
