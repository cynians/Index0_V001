import unittest

from world.temporal_succession_fields import apply_temporal_succession_schema


class _StubLoader:
    def __init__(self, entities):
        self.entities = entities


class ApplyTemporalSuccessionSchemaTests(unittest.TestCase):
    def test_adds_predecessors_and_successors_to_entity_core(self):
        loader = _StubLoader(
            {
                "schema_entity_core": {
                    "id": "schema_entity_core",
                    "_dataset": "schemas",
                    "type": "schema",
                    "schema": "entity_core",
                    "fields": {
                        "start_year": {"type": "number", "section": "Temporal", "optional": True},
                        "related": {"type": "entity_list", "target": "entity_core", "section": "Relations"},
                    },
                }
            }
        )

        self.assertTrue(apply_temporal_succession_schema(loader))
        fields = loader.entities["schema_entity_core"]["fields"]
        self.assertEqual(fields["predecessors"]["type"], "entity_list")
        self.assertEqual(fields["predecessors"]["target"], "entity_core")
        self.assertEqual(fields["predecessors"]["section"], "Temporal")
        self.assertEqual(fields["successors"]["section"], "Temporal")
        # Pre-existing fields untouched.
        self.assertEqual(fields["start_year"], {"type": "number", "section": "Temporal", "optional": True})

        # Re-running is a no-op: nothing changed, second call reports no change.
        self.assertFalse(apply_temporal_succession_schema(loader))

    def test_never_overwrites_a_field_already_named_predecessors(self):
        loader = _StubLoader(
            {
                "schema_entity_core": {
                    "id": "schema_entity_core",
                    "fields": {
                        "predecessors": {"type": "string", "section": "Custom"},
                    },
                }
            }
        )

        # successors is still missing and gets added, but the pre-existing
        # predecessors field spec (however it got there) is left alone.
        self.assertTrue(apply_temporal_succession_schema(loader))
        fields = loader.entities["schema_entity_core"]["fields"]
        self.assertEqual(fields["predecessors"], {"type": "string", "section": "Custom"})
        self.assertIn("successors", fields)

    def test_missing_entity_core_schema_is_a_no_op(self):
        loader = _StubLoader({})

        self.assertFalse(apply_temporal_succession_schema(loader))
        self.assertEqual(loader.entities, {})


if __name__ == "__main__":
    unittest.main()
