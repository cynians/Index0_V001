import unittest

from world.tag_rows import row_values, tag_class_index, tag_rows


class FakeWorld:
    def __init__(self, *entities):
        self.entities = {entity["id"]: entity for entity in entities}

    def get_dataset(self, dataset_name):
        return [entity for entity in self.entities.values() if entity.get("_dataset") == dataset_name]


WORLD = FakeWorld(
    {"id": "tag_need_snack", "_dataset": "tags", "name": "Snack", "tag_class": "need"},
    {"id": "tag_trait_kind", "_dataset": "tags", "name": "Kind", "tag_class": "personality"},
    {"id": "tag_test_craft", "_dataset": "tags", "name": "test craft"},
)


class TagRowTests(unittest.TestCase):
    def test_general_tags_split_by_class_and_tag_fields_get_rows(self):
        entity = {
            "tags": ["Snack", "test craft", "cleanup"],
            "production_process_tags": ["smelting"],
        }
        rows = tag_rows(entity, {}, WORLD)
        index = tag_class_index(WORLD)

        self.assertEqual(["tags", "tags::need", "production_process_tags"], [row.key for row in rows])
        self.assertEqual(["General", "Needs", "Production process"], [row.label for row in rows])
        self.assertEqual(["test craft", "cleanup"], row_values(rows[0], entity, rows, index))
        self.assertEqual(["Snack"], row_values(rows[1], entity, rows, index))

    def test_schema_rows_show_even_when_empty_and_steer_suggestions(self):
        schema = {
            "tag_rows": [{"label": "Personality", "field": "personality_adjectives", "tag_class": "personality"}],
            "fields": {"personality_adjectives": {"type": "string_list"}},
        }
        rows = tag_rows({}, schema, WORLD)

        self.assertEqual(["tags", "personality_adjectives"], [row.key for row in rows])
        self.assertEqual(("Personality", "personality"), (rows[1].label, rows[1].tag_class))


if __name__ == "__main__":
    unittest.main()
