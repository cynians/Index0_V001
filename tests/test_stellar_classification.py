import unittest

from simulations.space.stellar import is_valid_stellar_class, parse_stellar_class, stellar_profile_for_class
from ui.card import EntityCard


class StellarClassificationTests(unittest.TestCase):
    def test_numbered_main_sequence_class_is_parsed(self):
        parsed = parse_stellar_class("G2V")

        self.assertEqual("G", parsed["class_key"])
        self.assertEqual(2, parsed["subclass"])
        self.assertEqual("V", parsed["luminosity_class"])

    def test_giant_luminosity_suffix_is_parsed(self):
        parsed = parse_stellar_class("K1III")

        self.assertEqual("K", parsed["class_key"])
        self.assertEqual(1, parsed["subclass"])
        self.assertEqual("III", parsed["luminosity_class"])

    def test_invalid_suffix_is_rejected(self):
        self.assertFalse(is_valid_stellar_class("G6D"))

    def test_card_edit_rejects_invalid_stellar_class(self):
        entity = {"id": "star_alpha", "_dataset": "locations", "location_class": "star", "spectral_class": "G2V"}
        card_view = EntityCard(entity, dataset_name="locations")
        card = {
            "is_edit_mode": True,
            "active_edit_field": "spectral_class",
            "edit_original_value": "G2V",
            "edit_buffer": "G6D",
        }

        self.assertTrue(card_view.commit_edit_field(card))
        self.assertEqual("G2V", entity["spectral_class"])
        self.assertEqual("spectral_class", card["active_edit_field"])
        self.assertEqual("invalid", card["last_edit_action"])

    def test_numbered_class_changes_luminosity_and_habitable_zone(self):
        g2 = stellar_profile_for_class("G2V")
        k5 = stellar_profile_for_class("K5V")

        self.assertEqual("G2V", g2["spectral_class"])
        self.assertEqual("K5V", k5["spectral_class"])
        self.assertGreater(g2["luminosity_solar"], k5["luminosity_solar"])
        self.assertGreater(g2["habitable_zone_inner_au"], k5["habitable_zone_inner_au"])
        self.assertNotEqual(g2["card_color"], k5["card_color"])


if __name__ == "__main__":
    unittest.main()
