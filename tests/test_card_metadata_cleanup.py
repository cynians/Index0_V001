import unittest
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pygame

from simulations.space.system import CelestialSystem
from simulations.phylogeny.phylogeny_renderer import PhylogenyRenderer
from ui.card import EntityCard


class CardMetadataCleanupTests(unittest.TestCase):
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
