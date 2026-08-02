import unittest
from types import SimpleNamespace

from world.relationship_graph import TouchDegrees


class RelationshipGraphIncrementalTests(unittest.TestCase):
    def test_remove_entity_prunes_incoming_and_outgoing_edges(self):
        loader = SimpleNamespace(entities={
            "system": {
                "id": "system",
                "type": "location",
                "constituents": ["planet"],
            },
            "planet": {
                "id": "planet",
                "type": "location",
                "parents": ["system"],
                "related": ["note"],
            },
            "note": {
                "id": "note",
                "type": "idea",
                "related": ["planet"],
            },
        })
        graph = TouchDegrees(loader)

        self.assertIn("planet", graph.get_neighbors("system"))
        self.assertIn("note", graph.get_neighbors("planet"))
        self.assertTrue(graph.remove_entity("planet"))

        self.assertEqual([], graph.get_touches("planet"))
        self.assertEqual([], graph.get_incoming_touches("planet"))
        self.assertNotIn("planet", graph.get_neighbors("system"))
        self.assertNotIn("planet", graph.get_neighbors("note"))


if __name__ == "__main__":
    unittest.main()
