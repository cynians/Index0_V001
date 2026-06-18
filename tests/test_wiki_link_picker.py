import unittest

from ui.knowledge_browser_ui import KnowledgeBrowserUI


class WikiLinkPickerTests(unittest.TestCase):
    def setUp(self):
        self.ui = KnowledgeBrowserUI.__new__(KnowledgeBrowserUI)
        self.saved_cards = []
        self.ui._save_card_draft = lambda card: self.saved_cards.append(card.copy())

    @staticmethod
    def _card(**overrides):
        card = {
            "edit_buffer": "Before placeholder after",
            "edit_cursor": 18,
            "wiki_link_picker_open": True,
            "wiki_link_query": "New Topic",
            "wiki_link_matches": [],
            "wiki_link_selected_index": 0,
            "wiki_link_replace_range": (7, 18),
        }
        card.update(overrides)
        return card

    def test_no_matches_inserts_query_as_unresolved_wiki_link(self):
        card = self._card()

        inserted = self.ui._insert_wiki_link_from_picker(card)

        self.assertTrue(inserted)
        self.assertEqual("Before [[New Topic]] after", card["edit_buffer"])
        self.assertEqual(len("Before [[New Topic]]"), card["edit_cursor"])
        self.assertEqual("draft", card["last_edit_action"])
        self.assertFalse(card["wiki_link_picker_open"])
        self.assertEqual(1, len(self.saved_cards))

    def test_match_still_inserts_selected_entity_id(self):
        card = self._card(
            wiki_link_query="Topic",
            wiki_link_matches=[{"id": "idea_existing_topic"}],
        )

        inserted = self.ui._insert_wiki_link_from_picker(card)

        self.assertTrue(inserted)
        self.assertEqual("Before [[idea_existing_topic]] after", card["edit_buffer"])

    def test_blank_query_without_matches_is_not_inserted(self):
        card = self._card(wiki_link_query="   ")

        inserted = self.ui._insert_wiki_link_from_picker(card)

        self.assertFalse(inserted)
        self.assertEqual("Before placeholder after", card["edit_buffer"])
        self.assertTrue(card["wiki_link_picker_open"])
        self.assertEqual([], self.saved_cards)


if __name__ == "__main__":
    unittest.main()
