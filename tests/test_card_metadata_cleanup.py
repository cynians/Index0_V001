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
