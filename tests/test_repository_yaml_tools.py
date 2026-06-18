import unittest

import yaml

from world.repository_yaml import (
    find_yaml_entity_block,
    format_yaml_entity_block,
    format_yaml_scalar,
)


class RepositoryYamlToolTests(unittest.TestCase):
    def test_scalar_quotes_yaml_sensitive_text(self):
        self.assertEqual("'true'", format_yaml_scalar("true"))
        self.assertEqual("'Alpha: Beta'", format_yaml_scalar("Alpha: Beta"))

    def test_entity_block_round_trips_nested_values(self):
        entity = {
            "id": "idea_test",
            "name": "Test",
            "type": "idea",
            "related": ["idea_parent"],
            "metadata": {"enabled": True},
            "_dataset": "ideas",
        }

        block = format_yaml_entity_block(entity, ["id", "name", "type"])

        self.assertEqual([entity | {"_dataset": "ideas"}], [yaml.safe_load(block)[0] | {"_dataset": "ideas"}])
        self.assertNotIn("_dataset", block)

    def test_find_entity_block_stops_before_next_entry(self):
        text = "- id: idea_one\n  name: One\n- id: idea_two\n  name: Two\n"

        start, end = find_yaml_entity_block(text, "idea_one")

        self.assertEqual("- id: idea_one\n  name: One\n", text[start:end])


if __name__ == "__main__":
    unittest.main()
