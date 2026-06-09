import unittest

import pygame

from simulations.space.system import CelestialSystem
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


if __name__ == "__main__":
    unittest.main()
