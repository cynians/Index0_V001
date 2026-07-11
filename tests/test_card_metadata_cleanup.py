import unittest
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pygame

from simulations.space.system import CelestialSystem
from simulations.phylogeny.phylogeny_renderer import PhylogenyRenderer
from ui.card import EntityCard
from ui.knowledge_browser_ui import KnowledgeBrowserUI


class CardMetadataCleanupTests(unittest.TestCase):
    def _world_with_locations(self):
        entities = {
            "loc_planet_x": {
                "id": "loc_planet_x",
                "_dataset": "locations",
                "type": "location",
                "name": "Planet X",
                "location_class": "planet",
            },
            "loc_northern_spain": {
                "id": "loc_northern_spain",
                "_dataset": "locations",
                "type": "location",
                "name": "Northern Spain",
                "location_class": "region",
            },
            "loc_alps": {
                "id": "loc_alps",
                "_dataset": "locations",
                "type": "location",
                "name": "The Alps",
                "location_class": "bioregion",
            },
            "event_not_location": {
                "id": "event_not_location",
                "_dataset": "events",
                "name": "Planet X Incident",
            },
        }
        return SimpleNamespace(
            loader=SimpleNamespace(entities=entities),
            get_entity=lambda entity_id: entities.get(entity_id),
        )

    def test_description_notes_are_not_metadata_rows(self):
        card = EntityCard(
            {
                "id": "evt_test",
                "pretty_name": "Test Event",
                "name": "Test Event",
                "type": "event",
                "_dataset": "events",
                "description": "Old short description.",
                "notes": "Old notes.",
                "tags": ["cleanup"],
            },
            dataset_name="events",
        )

        metadata_keys = [key for key, _ in card._sectioned_fields()["Metadata"]]

        self.assertNotIn("description", metadata_keys)
        self.assertNotIn("notes", metadata_keys)
        self.assertIn("tags", metadata_keys)

    def test_location_history_syncs_associated_locations(self):
        entity = {
            "id": "ship_class_test",
            "_dataset": "vehicles",
            "type": "vehicle",
        }
        card_view = EntityCard(entity, dataset_name="vehicles", world_model=self._world_with_locations())
        card = {
            "location_start_buffer": "2016",
            "location_end_buffer": "2100",
            "location_matches": [{"id": "loc_planet_x", "label": "Planet X"}],
            "location_selected_index": 0,
        }

        self.assertTrue(card_view.add_location_history_entry(card))

        self.assertEqual(
            [{"location_id": "loc_planet_x", "start_year": 2016, "end_year": 2100}],
            entity["location_history"],
        )
        self.assertEqual(["loc_planet_x"], entity["associated_locations"])

    def test_location_matches_only_location_entries(self):
        card_view = EntityCard(
            {"id": "evt_test", "_dataset": "events", "type": "event"},
            dataset_name="events",
            world_model=self._world_with_locations(),
        )

        matches = card_view._build_location_matches("Planet X")

        self.assertEqual(["loc_planet_x"], [match["id"] for match in matches])

    def test_people_default_to_exclusive_location_mode(self):
        person_card = EntityCard(
            {"id": "person_alpha", "_dataset": "people", "type": "person"},
            dataset_name="people",
        )
        vehicle_card = EntityCard(
            {"id": "vehicle_class_alpha", "_dataset": "vehicles", "type": "vehicle"},
            dataset_name="vehicles",
        )

        self.assertEqual("exclusive", person_card._location_mode_value())
        self.assertEqual("multiple", vehicle_card._location_mode_value())

    def test_person_cards_expose_quote_simulation_subtab(self):
        person_card = EntityCard(
            {"id": "person_alpha", "_dataset": "people", "type": "person"},
            dataset_name="people",
        )

        self.assertIn("simulation", person_card._tab_order())

        person_card.set_active_tab("simulation")

        self.assertEqual("quotes", person_card.active_simulation_subtab)
        self.assertEqual(["quotes", "data"], person_card._active_subtab_order())
        self.assertEqual([], person_card._visible_sections())

    def test_person_quote_capture_writes_structured_record(self):
        entity = {"id": "person_alpha", "_dataset": "people", "type": "person"}
        person_card = EntityCard(entity, dataset_name="people")
        person_card.set_active_tab("simulation")
        card = {
            "is_edit_mode": True,
            "selected_year": 2401,
        }

        person_card._set_person_quote_active_field(card, "quote")
        card["edit_buffer"] = "The bridge remembers us."
        card["person_quote_buffers"]["date"] = "2401-04-02"
        card["person_quote_buffers"]["context"] = "Said after docking."

        self.assertTrue(person_card.add_person_quote_from_buffers(card))

        self.assertEqual(
            [
                {
                    "quote": "The bridge remembers us.",
                    "date": "2401-04-02",
                    "context": "Said after docking.",
                }
            ],
            entity["person_quotes"],
        )
        self.assertEqual("commit", card["last_edit_action"])
        self.assertEqual("person_quotes", card["last_committed_field"])
        self.assertEqual("", card["person_quote_buffers"]["quote"])

    def test_person_quote_context_does_not_inherit_quote_draft(self):
        entity = {"id": "person_alpha", "_dataset": "people", "type": "person"}
        person_card = EntityCard(entity, dataset_name="people")
        card = {"is_edit_mode": True}

        self.assertTrue(person_card._set_person_quote_active_field(card, "quote"))
        card["edit_buffer"] = "Quote draft."

        self.assertTrue(person_card._set_person_quote_active_field(card, "context"))

        self.assertEqual("Quote draft.", card["person_quote_buffers"]["quote"])
        self.assertEqual("", card["person_quote_buffers"]["context"])
        self.assertEqual("", card["edit_buffer"])

    def test_person_conversation_capture_writes_structured_message(self):
        entity = {"id": "person_alpha", "_dataset": "people", "type": "person", "name": "Person Alpha"}
        person_card = EntityCard(entity, dataset_name="people")
        person_card.set_active_tab("simulation")
        card = {
            "is_edit_mode": True,
            "person_quote_capture_mode": "conversations",
        }

        person_card._set_person_quote_active_field(card, person_card.PERSON_CONVERSATION_MESSAGE_FIELD)
        card["edit_buffer"] = "We should leave before dawn."
        card["person_quote_buffers"]["conversation_speaker"] = "Scout"
        card["person_quote_buffers"]["conversation_date"] = "2402"

        self.assertTrue(person_card.add_person_conversation_from_buffers(card))

        self.assertEqual(
            [{"message": "We should leave before dawn.", "speaker": "Scout", "date": "2402"}],
            entity["person_conversations"],
        )
        self.assertEqual("commit", card["last_edit_action"])
        self.assertEqual("person_conversations", card["last_committed_field"])

    def test_person_conversation_layout_uses_chat_rows(self):
        pygame.font.init()
        font = pygame.font.SysFont("consolas", 14)
        entity = {
            "id": "person_alpha",
            "_dataset": "people",
            "type": "person",
            "name": "Person Alpha",
            "person_conversations": [
                {"speaker": "Person Alpha", "date": "2402", "message": "I will hold the west gate."},
                {"speaker": "Scout", "date": "2402", "message": "Then I will take the ridge."},
            ],
        }
        person_card = EntityCard(entity, dataset_name="people")
        person_card.set_active_tab("simulation")
        card = {
            "entity_id": "person_alpha",
            "is_edit_mode": True,
            "person_quote_capture_mode": "conversations",
            "layout_font": font,
            "years": [],
        }

        person_card.layout_card(card, pygame.Rect(0, 0, 500, 760))

        self.assertIn(person_card.PERSON_CONVERSATION_MESSAGE_FIELD, card["person_quote_input_rects"])
        self.assertEqual(2, len(card["person_quote_rows"]))
        self.assertTrue(all(row.get("mode") == "conversation" for row in card["person_quote_rows"]))
        self.assertTrue(card["person_quote_rows"][0]["mine"])
        self.assertFalse(card["person_quote_rows"][1]["mine"])

    def test_person_quote_layout_creates_capture_and_remove_hitboxes(self):
        pygame.font.init()
        font = pygame.font.SysFont("consolas", 14)
        entity = {
            "id": "person_alpha",
            "_dataset": "people",
            "type": "person",
            "person_quotes": [
                {
                    "quote": "The bridge remembers us.",
                    "date": "2401",
                    "context": "Said after docking.",
                }
            ],
        }
        person_card = EntityCard(entity, dataset_name="people")
        person_card.set_active_tab("simulation")
        card = {
            "entity_id": "person_alpha",
            "is_edit_mode": True,
            "layout_font": font,
            "years": [],
        }

        person_card.layout_card(card, pygame.Rect(0, 0, 440, 680))

        self.assertIn(person_card.PERSON_QUOTE_TEXT_FIELD, card["person_quote_input_rects"])
        self.assertIn(person_card.PERSON_QUOTE_CONTEXT_FIELD, card["person_quote_input_rects"])
        self.assertIsNotNone(card["person_quote_add_rect"])
        self.assertEqual(1, len(card["person_quote_rows"]))
        self.assertIsNotNone(card["person_quote_rows"][0]["remove_rect"])

    def test_person_quote_remove_commits_person_quotes_field(self):
        entity = {
            "id": "person_alpha",
            "_dataset": "people",
            "type": "person",
            "person_quotes": [
                {"quote": "First", "date": "2400"},
                {"quote": "Second", "date": "2401"},
            ],
        }
        person_card = EntityCard(entity, dataset_name="people")
        card = {}

        self.assertTrue(person_card.remove_person_quote_at_index(card, 0))

        self.assertEqual([{"quote": "Second", "date": "2401", "context": ""}], entity["person_quotes"])
        self.assertEqual("commit", card["last_edit_action"])

    def test_location_topology_neighbours_are_reciprocal(self):
        world = self._world_with_locations()
        planet = world.get_entity("loc_planet_x")
        card_view = EntityCard(planet, dataset_name="locations", world_model=world)
        card = {}

        self.assertTrue(card_view.add_location_topology_relation(card, "neighbours", "loc_northern_spain"))

        self.assertEqual(["loc_northern_spain"], planet["neighbours"])
        self.assertEqual(["loc_planet_x"], world.get_entity("loc_northern_spain")["neighbours"])
        self.assertEqual(["loc_northern_spain"], card["location_related_entity_update_ids"])

    def test_location_topology_constituents_set_child_parent(self):
        world = self._world_with_locations()
        planet = world.get_entity("loc_planet_x")
        child = world.get_entity("loc_northern_spain")
        card_view = EntityCard(planet, dataset_name="locations", world_model=world)
        card = {}

        self.assertTrue(card_view.add_location_topology_relation(card, "constituents", "loc_northern_spain"))

        self.assertEqual(["loc_northern_spain"], planet["constituents"])
        self.assertEqual(["loc_planet_x"], child["parents"])
        self.assertEqual("loc_planet_x", child["parent_location"])
        self.assertEqual(["loc_northern_spain"], card["location_related_entity_update_ids"])

    def test_location_topology_overlaps_are_reciprocal(self):
        world = self._world_with_locations()
        region = world.get_entity("loc_northern_spain")
        card_view = EntityCard(region, dataset_name="locations", world_model=world)
        card = {}

        self.assertTrue(card_view.add_location_topology_relation(card, "overlaps", "loc_alps"))

        self.assertEqual(["loc_alps"], region["overlaps"])
        self.assertEqual(["loc_northern_spain"], world.get_entity("loc_alps")["overlaps"])

    def test_location_topology_uses_relation_link_field(self):
        world = self._world_with_locations()
        region = world.get_entity("loc_northern_spain")
        card_view = EntityCard(region, dataset_name="locations", world_model=world)
        field_key = card_view._location_topology_virtual_field("overlaps")
        card = {"active_edit_field": field_key}

        self.assertTrue(card_view.is_relation_edit_field(field_key))
        self.assertEqual("locations", card_view._relation_field_target(field_key))
        self.assertTrue(card_view.insert_relation_reference(card, "loc_alps"))

        self.assertEqual(["loc_alps"], region["overlaps"])
        self.assertEqual(["loc_northern_spain"], world.get_entity("loc_alps")["overlaps"])
        self.assertEqual(["loc_alps"], card["location_related_entity_update_ids"])

    def test_switching_edit_fields_preserves_uncommitted_drafts(self):
        entity = {
            "id": "idea_alpha",
            "type": "idea",
            "_dataset": "ideas",
            "name": "Original",
            "short_description": "Old description",
        }
        card_view = EntityCard(entity, dataset_name="ideas")
        card = {"is_edit_mode": True, "draft_edit_buffers": {}}

        self.assertTrue(card_view.begin_edit_field(card, "name"))
        card["edit_buffer"] = "Draft name"
        card["edit_cursor"] = len(card["edit_buffer"])

        self.assertTrue(card_view.begin_edit_field(card, "short_description"))

        self.assertEqual("Original", entity["name"])
        self.assertEqual("Draft name", card["draft_edit_buffers"]["name"]["text"])
        self.assertEqual("short_description", card["active_edit_field"])

        self.assertTrue(card_view.begin_edit_field(card, "name"))

        self.assertEqual("Draft name", card["edit_buffer"])
        self.assertEqual(len("Draft name"), card["edit_cursor"])

    def test_location_topology_matches_only_locations(self):
        world = self._world_with_locations()
        card_view = EntityCard(
            world.get_entity("loc_planet_x"),
            dataset_name="locations",
            world_model=world,
        )
        card = {
            "location_topology_active_field": "constituents",
            "location_topology_query": "Planet",
        }

        matches = card_view._build_location_topology_matches(card)

        self.assertEqual([], [match["id"] for match in matches])

    def test_relation_picker_location_target_filters_to_locations(self):
        world = self._world_with_locations()
        ui = KnowledgeBrowserUI.__new__(KnowledgeBrowserUI)
        ui.world_model = world

        matches = ui._build_relation_picker_matches({"relation_picker_target": "locations"}, "Planet")

        self.assertEqual(["loc_planet_x"], [match["id"] for match in matches])

    def test_location_topology_place_button_emits_navigation_action(self):
        world = self._world_with_locations()
        card_view = EntityCard(
            world.get_entity("loc_northern_spain"),
            dataset_name="locations",
            world_model=world,
        )
        card = {
            "entity_id": "loc_northern_spain",
            "is_edit_mode": True,
            "location_topology_place_rect": pygame.Rect(10, 10, 120, 24),
        }

        self.assertTrue(card_view.handle_location_topology_click(card, (20, 20)))

        self.assertEqual(
            {
                "id": "knowledge_place_location_on_parent",
                "entity_id": "loc_northern_spain",
            },
            card["pending_location_action"],
        )
        self.assertIsNone(card["last_edit_action"])

    def test_working_year_stub_appears_in_timeline_snapshot_front(self):
        entity = {
            "id": "evt_test",
            "_dataset": "events",
            "type": "event",
            "pretty_name": "Northern Campaign",
            "wiki_entry": "Existing note.",
        }
        card_view = EntityCard(entity, dataset_name="events")
        card = {"title": "Northern Campaign", "working_year_range": (2016, 2016)}

        wiki_text = card_view._timeline_snapshot_text(card)

        self.assertTrue(wiki_text.startswith("Northern Campaign in the Year 2016"))
        self.assertEqual("Existing note.", card_view._get_general_wiki_text(card))

    def test_timeline_snapshot_commit_writes_separate_field(self):
        entity = {
            "id": "evt_test",
            "_dataset": "events",
            "type": "event",
            "pretty_name": "Northern Campaign",
            "wiki_entry": "General note.",
        }
        card_view = EntityCard(entity, dataset_name="events")
        card = {
            "title": "Northern Campaign",
            "working_year_range": (2016, 2016),
            "is_edit_mode": True,
        }

        self.assertTrue(card_view.begin_edit_field(card, card_view.TIMELINE_SNAPSHOT_FIELD))
        card["edit_buffer"] = "Snapshot note."
        self.assertTrue(card_view.commit_edit_field(card))

        self.assertEqual("General note.", entity["wiki_entry"])
        self.assertEqual(
            [{"start_year": 2016, "end_year": 2016, "wiki_entry": "Snapshot note."}],
            entity["timeline_snapshots"],
        )

    def test_timeline_snapshot_text_prefers_draft_buffer(self):
        entity = {
            "id": "evt_test",
            "_dataset": "events",
            "type": "event",
            "pretty_name": "Northern Campaign",
        }
        card_view = EntityCard(entity, dataset_name="events")
        card = {
            "title": "Northern Campaign",
            "working_year_range": (2016, 2016),
            "draft_edit_buffers": {
                card_view.TIMELINE_SNAPSHOT_FIELD: {
                    "text": "Draft [[loc_northern_spain]] note.",
                    "cursor": 30,
                },
            },
        }

        self.assertEqual("Draft [[loc_northern_spain]] note.", card_view._timeline_snapshot_text(card))

    def test_timeline_snapshot_drafts_are_scoped_to_year_range(self):
        entity = {
            "id": "evt_test",
            "_dataset": "events",
            "type": "event",
            "pretty_name": "Northern Campaign",
        }
        card_view = EntityCard(entity, dataset_name="events")
        card = {
            "title": "Northern Campaign",
            "working_year_range": (2016, 2016),
            "is_edit_mode": True,
            "draft_edit_buffers": {},
        }

        self.assertTrue(card_view.begin_edit_field(card, card_view.TIMELINE_SNAPSHOT_FIELD))
        card["edit_buffer"] = "Draft for 2016."
        card["edit_cursor"] = len(card["edit_buffer"])

        card["working_year_range"] = (2017, 2017)
        self.assertTrue(card_view._sync_timeline_snapshot_edit_range(card))
        self.assertIn(
            f"{card_view.TIMELINE_SNAPSHOT_FIELD}:2016:2016",
            card["draft_edit_buffers"],
        )
        self.assertNotEqual("Draft for 2016.", card["edit_buffer"])
        self.assertTrue(card["edit_buffer"].startswith("Northern Campaign in the Year 2017"))

        card["edit_buffer"] = "Draft for 2017."
        card["edit_cursor"] = len(card["edit_buffer"])
        card["working_year_range"] = (2016, 2016)
        self.assertTrue(card_view._sync_timeline_snapshot_edit_range(card))
        self.assertEqual("Draft for 2016.", card["edit_buffer"])

        self.assertTrue(card_view.commit_edit_field(card))
        self.assertEqual(
            [{"start_year": 2016, "end_year": 2016, "wiki_entry": "Draft for 2016."}],
            entity["timeline_snapshots"],
        )
        self.assertIn(
            f"{card_view.TIMELINE_SNAPSHOT_FIELD}:2017:2017",
            card["draft_edit_buffers"],
        )

    def test_image_fields_are_media_rows(self):
        card = EntityCard(
            {
                "id": "veh_test",
                "pretty_name": "Test Vehicle",
                "name": "Test Vehicle",
                "type": "vehicle",
                "_dataset": "vehicles",
                "card_image": "assets/cards/vehicles/test.png",
                "card_image_front": "assets/cards/vehicles/test_front.png",
                "image_path": "legacy.png",
                "media_layers": {},
            },
            dataset_name="vehicles",
        )
        sections = card._sectioned_fields()

        metadata_keys = [key for key, _ in sections["Metadata"]]
        media_keys = [key for key, _ in sections["Media"]]

        self.assertNotIn("card_image", metadata_keys)
        self.assertNotIn("card_image_front", metadata_keys)
        self.assertNotIn("image_path", metadata_keys)
        self.assertIn("card_image", media_keys)
        self.assertIn("card_image_front", media_keys)
        self.assertIn("image_path", media_keys)
        self.assertIn("media_layers", media_keys)

    def test_card_image_loader_resolves_assets_from_project_root(self):
        previous_root = EntityCard.PROJECT_ROOT
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                asset_path = root / "assets" / "illustrations" / "test_pixel.png"
                asset_path.parent.mkdir(parents=True, exist_ok=True)
                if not pygame.display.get_init():
                    pygame.display.init()
                if pygame.display.get_surface() is None:
                    pygame.display.set_mode((1, 1))
                surface = pygame.Surface((2, 2), pygame.SRCALPHA)
                surface.fill((255, 0, 0, 255))
                pygame.image.save(surface, str(asset_path))

                EntityCard.PROJECT_ROOT = str(root)
                card = EntityCard(
                    {
                        "id": "idea_image",
                        "type": "idea",
                        "_dataset": "ideas",
                        "name": "Image",
                        "media_path": "assets/illustrations/test_pixel.png",
                    },
                    dataset_name="ideas",
                )

                loaded = card._load_card_image_surface("assets/illustrations/test_pixel.png")

                self.assertIsNotNone(loaded)
                self.assertEqual((2, 2), loaded.get_size())
        finally:
            EntityCard.PROJECT_ROOT = previous_root

    def test_card_header_icon_uses_linked_illustration_image(self):
        pygame.font.init()
        font = pygame.font.SysFont("consolas", 14)
        parent = {
            "id": "vehicle_parent",
            "type": "vehicle",
            "_dataset": "vehicles",
            "name": "Parent Vehicle",
        }
        illustration = {
            "id": "idea_vehicle_picture",
            "type": "idea",
            "_dataset": "ideas",
            "name": "Vehicle Picture",
            "idea_class": "illustration",
            "parents": ["vehicle_parent"],
            "media_path": "assets/illustrations/vehicle_picture.png",
        }
        world_model = SimpleNamespace(
            get_entities_by_dataset=lambda dataset_name: [illustration] if dataset_name == "ideas" else []
        )
        card_view = EntityCard(parent, dataset_name="vehicles", world_model=world_model)
        card = {
            "entity_id": "vehicle_parent",
            "is_edit_mode": False,
            "layout_font": font,
            "years": [],
        }

        card_view.layout_card(card, pygame.Rect(0, 0, 420, 340))

        self.assertEqual("assets/illustrations/vehicle_picture.png", card["header_icon_ref"])
        self.assertIsNotNone(card["header_icon_rect"])
        self.assertGreater(card["title_edit_rect"].x, 10)

    def test_space_sim_fields_are_simulation_rows(self):
        card = EntityCard(
            {
                "id": "planet_test",
                "pretty_name": "Test Planet",
                "name": "Test Planet",
                "type": "location",
                "_dataset": "locations",
                "location_class": "planet",
                "system_role": "orbital_body",
                "body_class": "planet",
                "mass_kg": 5.0,
                "radius_m": 10.0,
                "semi_major_axis_m": 100.0,
                "mean_anomaly_deg_at_epoch": 45.0,
            },
            dataset_name="locations",
        )
        sections = card._sectioned_fields()

        space_keys = [key for key, _ in sections["Simulation / Space Sim"]]
        temporal_keys = [key for key, _ in sections["Temporal"]]

        self.assertIn("system_role", space_keys)
        self.assertIn("body_class", space_keys)
        self.assertIn("mass_kg", space_keys)
        self.assertIn("mean_anomaly_deg_at_epoch", space_keys)
        self.assertNotIn("mean_anomaly_deg_at_epoch", temporal_keys)

    def test_simulation_tab_layout_uses_orbital_subtab_width(self):
        pygame.font.init()
        font = pygame.font.SysFont("consolas", 14)
        card_view = EntityCard(
            {
                "id": "planet_test",
                "pretty_name": "Test Planet",
                "name": "Test Planet",
                "type": "location",
                "_dataset": "locations",
                "location_class": "planet",
                "mass_kg": 5.0,
                "radius_m": 10.0,
                "semi_major_axis_m": 100.0,
            },
            dataset_name="locations",
        )
        card_view.set_active_tab("simulation")
        card = {
            "entity_id": "planet_test",
            "is_edit_mode": False,
            "layout_font": font,
            "years": [],
        }

        card_view.layout_card(card, pygame.Rect(0, 0, 460, 420))

        subtab_names = [subtab_name for _tab_name, subtab_name, _rect in card["subtab_hitboxes"]]
        self.assertIn("orbital", subtab_names)

    def test_map_and_world_gen_fields_are_simulation_rows(self):
        card = EntityCard(
            {
                "id": "loc_test",
                "pretty_name": "Test Region",
                "name": "Test Region",
                "type": "location",
                "_dataset": "locations",
                "coords": {"type": "point", "x": 1, "y": 2},
                "bounds": {"type": "bbox", "min_x": 0, "max_x": 1, "min_y": 0, "max_y": 1},
                "map_image_path": "assets/maps/test.png",
                "environment_summary": {"status": "generated"},
            },
            dataset_name="locations",
        )
        sections = card._sectioned_fields()

        map_keys = [key for key, _ in sections["Simulation / Map Sim"]]
        world_keys = [key for key, _ in sections["Simulation / World Gen"]]
        media_keys = [key for key, _ in sections["Media"]]

        self.assertIn("coords", map_keys)
        self.assertIn("bounds", map_keys)
        self.assertIn("environment_summary", world_keys)
        self.assertIn("map_image_path", media_keys)
        self.assertNotIn("map_image_path", map_keys)

    def test_planet_material_fields_are_materials_simulation_rows(self):
        card = EntityCard(
            {
                "id": "planet_test",
                "pretty_name": "Test Planet",
                "type": "location",
                "_dataset": "locations",
                "location_class": "planet",
                "natural_material_model": {
                    "status": "inferred",
                    "likely_materials": [
                        {
                            "material_id": "mat_basalt",
                            "name": "Basalt",
                            "chemical_formula": "mafic silicate rock",
                            "display_color": [72, 76, 70],
                            "confidence": 0.91,
                            "occurrence": "common",
                        }
                    ],
                },
                "materials_summary": {
                    "status": "natural_materials_inferred",
                    "likely_material_count": 1,
                },
            },
            dataset_name="locations",
        )

        card.set_active_tab("simulation")
        sections = card._sectioned_fields()
        material_keys = [key for key, _ in sections["Simulation / Materials"]]
        data_keys = [key for key, _ in sections["Simulation / Data"]]

        self.assertEqual("materials", card.active_simulation_subtab)
        self.assertIn("natural_material_model", material_keys)
        self.assertIn("materials_summary", material_keys)
        self.assertNotIn("natural_material_model", data_keys)

    def test_plant_ecology_fields_are_simulation_rows(self):
        card = EntityCard(
            {
                "id": "spec_plantago_major",
                "common_name": "Broadleaf Plantain",
                "binomial_name": "Plantago major",
                "type": "species",
                "_dataset": "species",
                "plant_growth_form": "perennial_forb_rosette",
                "worldgen_suitability_profile": {
                    "soil_types": ["loam"],
                    "moisture": {"min": 0.1, "optimum": 0.4, "max": 0.8},
                },
            },
            dataset_name="species",
        )

        self.assertIn("simulation", card._tab_order())
        card.set_active_tab("simulation")
        self.assertEqual("plant_ecology", card.active_simulation_subtab)

        sections = card._sectioned_fields()
        plant_keys = [key for key, _ in sections["Simulation / Plant Ecology"]]

        self.assertIn("plant_growth_form", plant_keys)
        self.assertIn("worldgen_suitability_profile", plant_keys)

    def test_biosphere_roster_collection_fields_are_relation_rows(self):
        card = EntityCard(
            {
                "id": "coll_micro",
                "pretty_name": "Micro Roster",
                "type": "collections",
                "_dataset": "collections",
                "collection_class": "localized_biosphere_species_roster",
                "biosphere_location": "loc_patch",
                "sessile_life_species": ["spec_plantago_major"],
            },
            dataset_name="collections",
        )

        card.set_active_tab("relations")
        sections = card._sectioned_fields()
        roster_keys = [key for key, _ in sections["Biosphere Species Roster"]]

        self.assertIn("biosphere_location", roster_keys)
        self.assertIn("sessile_life_species", roster_keys)
        self.assertIn("microfauna_species", roster_keys)
        self.assertIn("Biosphere Species Roster", card._visible_sections())
        self.assertTrue(card.is_relation_edit_field("sessile_life_species"))
        self.assertEqual("species", card._relation_field_target("sessile_life_species"))
        self.assertTrue(card.is_relation_edit_field("biosphere_location"))
        self.assertEqual("locations", card._relation_field_target("biosphere_location"))

    def test_biosphere_patch_collection_link_is_roster_relation_row(self):
        card = EntityCard(
            {
                "id": "loc_patch",
                "pretty_name": "Patch",
                "type": "location",
                "_dataset": "locations",
                "location_class": "biosphere_patch",
                "biosphere_species_collection": "coll_roster",
            },
            dataset_name="locations",
        )

        card.set_active_tab("relations")
        sections = card._sectioned_fields()
        roster_keys = [key for key, _ in sections["Biosphere Species Roster"]]

        self.assertIn("biosphere_species_collection", roster_keys)
        self.assertTrue(card.is_relation_edit_field("biosphere_species_collection"))
        self.assertEqual("collections", card._relation_field_target("biosphere_species_collection"))

    def test_tag_confirm_prefers_typed_value_over_partial_suggestion(self):
        world_model = SimpleNamespace(
            loader=SimpleNamespace(
                entities={
                    "loc_ring": {
                        "id": "loc_ring",
                        "_dataset": "locations",
                        "type": "location",
                        "tags": ["ring_city"],
                    }
                }
            )
        )
        card_view = EntityCard(
            {"id": "loc_test", "type": "location", "_dataset": "locations", "tags": []},
            dataset_name="locations",
            world_model=world_model,
        )
        card = {"edit_buffer": "city", "tag_selected_index": 0}

        self.assertTrue(card_view.confirm_tag_search(card))

        self.assertEqual(["city"], card_view.entity["tags"])

    def test_tag_confirm_uses_keyboard_selected_suggestion(self):
        world_model = SimpleNamespace(
            loader=SimpleNamespace(
                entities={
                    "loc_ring": {
                        "id": "loc_ring",
                        "_dataset": "locations",
                        "type": "location",
                        "tags": ["ring_city"],
                    }
                }
            )
        )
        card_view = EntityCard(
            {"id": "loc_test", "type": "location", "_dataset": "locations", "tags": []},
            dataset_name="locations",
            world_model=world_model,
        )
        card = {
            "edit_buffer": "city",
            "tag_selected_index": 0,
            "tag_keyboard_selection_active": True,
        }

        self.assertTrue(card_view.confirm_tag_search(card))

        self.assertEqual(["ring_city"], card_view.entity["tags"])

    def test_stellar_toolbelt_action_uses_full_row_hitbox(self):
        pygame.font.init()
        font = pygame.font.SysFont("consolas", 14)
        card_view = EntityCard(
            {
                "id": "system_alpha",
                "pretty_name": "Alpha",
                "name": "Alpha",
                "type": "location",
                "_dataset": "locations",
                "location_class": "star_system",
                "location_role": "star_system",
            },
            dataset_name="locations",
        )
        card = {
            "entity_id": "system_alpha",
            "is_edit_mode": True,
            "layout_font": font,
            "active_tab": "general",
            "years": [],
        }

        card_view.layout_card(card, pygame.Rect(0, 0, 420, 340))

        neighbourhood_rect = next(
            rect
            for tool, rect in card["toolbelt_hitboxes"]
            if tool.get("id") == "stellar_define_neighbourhood"
        )

        self.assertGreaterEqual(neighbourhood_rect.height, 48)
        self.assertTrue(neighbourhood_rect.collidepoint(neighbourhood_rect.centerx, neighbourhood_rect.bottom - 4))

    def test_planet_launch_strip_exposes_existing_workspace_modes(self):
        pygame.font.init()
        font = pygame.font.SysFont("consolas", 14)
        card_view = EntityCard(
            {
                "id": "planet_alpha",
                "pretty_name": "Alpha I",
                "name": "Alpha I",
                "type": "location",
                "_dataset": "locations",
                "location_class": "planet",
                "system_role": "orbital_body",
                "body_class": "planet",
                "star_system": "system_alpha",
                "map_canvas_width_px": 2048,
                "map_canvas_height_px": 1024,
            },
            dataset_name="locations",
        )
        card = {
            "entity_id": "planet_alpha",
            "is_edit_mode": False,
            "layout_font": font,
            "active_tab": "general",
            "years": [],
        }

        card_view.layout_card(card, pygame.Rect(0, 0, 420, 380))

        mode_tools = {
            option.get("mode"): option.get("label")
            for option, _rect in card["launch_mode_hitboxes"]
        }
        self.assertEqual(
            {
                "space": "Space",
                "world_gen": "World Gen",
                "map": "Map",
            },
            mode_tools,
        )

    def test_undefined_child_location_launches_as_parent_placement(self):
        card_view = EntityCard(
            {
                "id": "loc_child",
                "pretty_name": "Undefined Child",
                "name": "Undefined Child",
                "type": "location",
                "_dataset": "locations",
                "location_class": "region",
                "parent_location": "loc_parent",
            },
            dataset_name="locations",
        )

        options = card_view._launch_mode_options()

        self.assertEqual(1, len(options))
        self.assertEqual("place_parent", options[0]["mode"])
        self.assertEqual("Place on Parent", options[0]["label"])

    def test_star_display_color_falls_back_to_stellar_class_profile(self):
        system = CelestialSystem()
        color = system._entity_display_color(
            {
                "id": "star_alpha_primary",
                "type": "location",
                "_dataset": "locations",
                "location_class": "star",
                "spectral_class": "K",
                "card_color": "#112233",
            }
        )

        self.assertEqual((255, 210, 161), color)

    def test_relation_chip_existing_entry_uses_referenced_card_color(self):
        target = {
            "id": "idea_target",
            "type": "idea",
            "_dataset": "ideas",
            "name": "Target",
            "card_color": "#336699",
        }
        world_model = SimpleNamespace(get_entity=lambda entity_id: target if entity_id == "idea_target" else None)
        card = EntityCard(
            {
                "id": "idea_source",
                "type": "idea",
                "_dataset": "ideas",
                "name": "Source",
                "related": ["idea_target"],
            },
            dataset_name="ideas",
            world_model=world_model,
        )

        fill, border, text = card._relation_chip_colors({"kind": "existing", "entity_id": "idea_target"})

        self.assertEqual((31, 52, 77), fill)
        self.assertEqual((102, 141, 180), border)
        self.assertEqual((238, 244, 252), text)

    def test_wiki_link_color_uses_referenced_card_color(self):
        target = {
            "id": "idea_target",
            "type": "idea",
            "_dataset": "ideas",
            "name": "Target",
            "card_color": "#336699",
        }
        world_model = SimpleNamespace(get_entity=lambda entity_id: target if entity_id == "idea_target" else None)
        card = EntityCard(
            {
                "id": "idea_source",
                "type": "idea",
                "_dataset": "ideas",
                "name": "Source",
            },
            dataset_name="ideas",
            world_model=world_model,
        )

        self.assertEqual((31, 52, 77), card._resolve_wiki_link_color("idea_target"))

    def test_link_palette_uses_referenced_body_header_and_wiki_colors(self):
        target = {
            "id": "idea_target",
            "type": "idea",
            "_dataset": "ideas",
            "name": "Target",
            "card_color": "#336699",
            "card_header_color": "#993333",
            "wiki_field_colors": {"default": "#339966"},
        }
        world_model = SimpleNamespace(get_entity=lambda entity_id: target if entity_id == "idea_target" else None)
        card = EntityCard(
            {
                "id": "idea_source",
                "type": "idea",
                "_dataset": "ideas",
                "name": "Source",
            },
            dataset_name="ideas",
            world_model=world_model,
        )

        palette = card._resolve_wiki_link_palette("idea_target")

        self.assertEqual((31, 52, 77), palette["fill"])
        self.assertEqual((176, 104, 107), palette["border"])
        self.assertEqual((51, 153, 102), palette["band"])

    def test_card_tab_palette_alternates_wiki_colors(self):
        card = EntityCard(
            {
                "id": "idea_source",
                "type": "idea",
                "_dataset": "ideas",
                "name": "Source",
                "wiki_field_colors": {
                    "default": "#123456",
                    "alternate": "#abcdef",
                },
            },
            dataset_name="ideas",
        )

        first_fill, first_border, first_text = card._card_button_palette(0)
        second_fill, second_border, second_text = card._card_button_palette(1)
        selected_fill, _selected_border, selected_text = card._card_button_palette(0, selected=True)

        self.assertEqual((18, 52, 86), first_fill)
        self.assertEqual((171, 205, 239), second_fill)
        self.assertNotEqual(first_border, first_fill)
        self.assertNotEqual(second_border, second_fill)
        self.assertNotEqual(first_text, second_text)
        self.assertNotEqual(selected_fill, first_fill)
        self.assertIn(selected_text, ((246, 248, 252), (20, 24, 32)))

    def test_phylogeny_rows_use_referenced_card_color(self):
        target = {
            "id": "clade_target",
            "type": "cladistics",
            "_dataset": "cladistics",
            "name": "Target Clade",
            "card_color": "#336699",
        }
        world_model = SimpleNamespace(get_entity=lambda entity_id: target if entity_id == "clade_target" else None)
        card = EntityCard(
            {
                "id": "clade_source",
                "type": "cladistics",
                "_dataset": "cladistics",
                "name": "Source",
            },
            dataset_name="cladistics",
            world_model=world_model,
        )

        fill, border, text = card._phylogeny_row_colors({"id": "clade_target"})

        self.assertEqual((31, 54, 79), fill)
        self.assertEqual((99, 138, 178), border)
        self.assertEqual((238, 244, 252), text)

    def test_phylogeny_row_palette_uses_header_border_and_wiki_band(self):
        target = {
            "id": "clade_target",
            "type": "cladistics",
            "_dataset": "cladistics",
            "name": "Target Clade",
            "card_color": "#336699",
            "card_header_color": "#993333",
            "wiki_field_colors": {"default": "#339966"},
        }
        world_model = SimpleNamespace(get_entity=lambda entity_id: target if entity_id == "clade_target" else None)
        card = EntityCard(
            {
                "id": "clade_source",
                "type": "cladistics",
                "_dataset": "cladistics",
                "name": "Source",
            },
            dataset_name="cladistics",
            world_model=world_model,
        )

        palette = card._phylogeny_row_palette({"id": "clade_target"})

        self.assertEqual((31, 54, 79), palette["fill"])
        self.assertEqual((174, 100, 103), palette["border"])
        self.assertEqual((51, 153, 102), palette["band"])

    def test_phylogeny_renderer_nodes_use_payload_card_color(self):
        renderer = PhylogenyRenderer(SimpleNamespace())

        fill, border = renderer._node_colors(
            "clade_target",
            {"card_color": "#336699"},
            {"selected_id": "", "hover_id": "", "focus_id": ""},
        )

        self.assertEqual((31, 54, 79), fill)
        self.assertEqual((99, 138, 178), border)

    def test_phylogeny_renderer_nodes_use_header_border_and_wiki_band(self):
        renderer = PhylogenyRenderer(SimpleNamespace())

        fill, border = renderer._node_colors(
            "clade_target",
            {
                "card_color": "#336699",
                "card_header_color": "#993333",
                "wiki_field_colors": {"default": "#339966"},
            },
            {"selected_id": "", "hover_id": "", "focus_id": ""},
        )
        band = renderer._node_band_color(
            {
                "card_color": "#336699",
                "card_header_color": "#993333",
                "wiki_field_colors": {"default": "#339966"},
            }
        )

        self.assertEqual((31, 54, 79), fill)
        self.assertEqual((174, 100, 103), border)
        self.assertEqual((51, 153, 102), band)


if __name__ == "__main__":
    unittest.main()
