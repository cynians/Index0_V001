import unittest

from world.technology_schema import apply_technology_schema
from world.world_model import WorldModel
from world.yearer import Yearer


class _TechLoader:
    def __init__(self, entities):
        self.entities = entities
        self.datasets = {"schemas": []}

    def get(self, entity_id):
        return self.entities.get(entity_id)

    @staticmethod
    def _relation_ids(value):
        if isinstance(value, str):
            stripped = value.strip()
            return [stripped] if stripped else []
        if isinstance(value, dict):
            entity_id = str(value.get("id") or "").strip()
            return [entity_id] if entity_id else []
        if isinstance(value, list):
            ids = []
            for item in value:
                for entity_id in _TechLoader._relation_ids(item):
                    if entity_id not in ids:
                        ids.append(entity_id)
            return ids
        return []


class ApplyTechnologySchemaTests(unittest.TestCase):
    def test_adds_succession_and_forgotten_fields_idempotently(self):
        loader = _TechLoader(
            {
                "schema_technology": {
                    "id": "schema_technology",
                    "_dataset": "schemas",
                    "type": "schema",
                    "schema": "technology",
                    "fields": {"technology_class": {"type": "string", "optional": True}},
                }
            }
        )

        self.assertTrue(apply_technology_schema(loader))
        fields = loader.entities["schema_technology"]["fields"]
        self.assertEqual(fields["predecessor"]["target"], "technologies")
        self.assertEqual(fields["successor"]["type"], "entity_list")
        self.assertEqual(fields["forgotten_year"]["type"], "number")
        # Pre-existing field spec untouched.
        self.assertEqual(fields["technology_class"], {"type": "string", "optional": True})

        self.assertFalse(apply_technology_schema(loader))


class TechnologyTimelineItemTests(unittest.TestCase):
    def _model(self, entities):
        loader = _TechLoader(entities)
        model = WorldModel.__new__(WorldModel)
        model.loader = loader
        model.yearer = Yearer(loader)
        return model

    def test_forgotten_year_terminates_span_open_ended_otherwise(self):
        model = self._model(
            {
                "tech_open": {"id": "tech_open", "type": "technology", "start_year": 1200},
                "tech_lost": {
                    "id": "tech_lost",
                    "type": "technology",
                    "start_year": 700,
                    "forgotten_year": 1100,
                },
            }
        )
        items = {item["entity_id"]: item for item in model.get_timeline_items()}

        self.assertTrue(items["tech_open"]["technology_open_ended"])
        self.assertEqual(items["tech_open"]["end_year"], items["tech_open"]["start_year"])
        self.assertIsNone(items["tech_open"]["forgotten_year"])

        self.assertFalse(items["tech_lost"]["technology_open_ended"])
        self.assertEqual(1100, items["tech_lost"]["end_year"])
        self.assertEqual(1100, items["tech_lost"]["forgotten_year"])

    def test_superseded_year_from_successor_and_reverse_predecessor(self):
        model = self._model(
            {
                "tech_a": {"id": "tech_a", "type": "technology", "start_year": 100, "successor": ["tech_b"]},
                "tech_b": {"id": "tech_b", "type": "technology", "start_year": 400},
                "tech_c": {"id": "tech_c", "type": "technology", "start_year": 200},
                "tech_d": {
                    "id": "tech_d",
                    "type": "technology",
                    "start_year": 350,
                    "predecessor": ["tech_c"],
                },
            }
        )
        items = {item["entity_id"]: item for item in model.get_timeline_items()}

        self.assertEqual(400, items["tech_a"]["superseded_year"])  # from tech_a.successor
        self.assertEqual(350, items["tech_c"]["superseded_year"])  # from tech_d.predecessor
        self.assertIsNone(items["tech_b"]["superseded_year"])


if __name__ == "__main__":
    unittest.main()
