import unittest

from ui.wiki_link_tools import (
    build_entity_link_matches,
    choose_link_target,
    find_link_seed,
    insert_wiki_link,
)


class WikiLinkToolTests(unittest.TestCase):
    def test_seed_finds_identifier_at_cursor(self):
        self.assertEqual(("alpha-beta", 4, 14), find_link_seed("See alpha-beta now", 9))

    def test_unmatched_query_becomes_link_target(self):
        self.assertEqual("New Topic", choose_link_target([], 0, " New Topic "))

    def test_selected_match_uses_canonical_id(self):
        matches = [{"id": "idea_first"}, {"id": "idea_second"}]
        self.assertEqual("idea_second", choose_link_target(matches, 1, "second"))

    def test_insert_replaces_seed_and_preserves_surrounding_spacing(self):
        result = insert_wiki_link(
            "Before placeholder after",
            "New Topic",
            replace_range=(7, 18),
            cursor=18,
        )
        self.assertEqual(("Before [[New Topic]] after", 20), result)

    def test_entity_matches_are_filtered_and_sorted(self):
        entities = [
            {"id": "idea_z", "name": "Zeta", "type": "idea"},
            {"id": "idea_a", "name": "Alpha", "type": "idea", "start_year": "10"},
        ]
        matches = build_entity_link_matches(
            entities,
            "a",
            display_label=lambda entity, fallback: entity.get("name", fallback),
            coerce_year=lambda value: int(value) if value is not None else None,
        )
        self.assertEqual(["idea_a", "idea_z"], [match["id"] for match in matches])
        self.assertEqual(10, matches[0]["start_year"])


if __name__ == "__main__":
    unittest.main()
