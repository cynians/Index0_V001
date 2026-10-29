import unittest
from pathlib import Path

from world.persistent_ontology_store import PersistentOntologyStore
import tools.author_formation_squad_designer as tool

ONTOLOGY_PATH = Path(__file__).resolve().parents[1] / "ontology" / "index0.owl"


class SquadDesignerAuthoringTests(unittest.TestCase):
    """Structural checks -- the live ontology is expected to already carry the
    squad-designer schema fields and the GGO seed after the tool has run, so a
    second run must be a no-op."""

    @classmethod
    def setUpClass(cls):
        cls.datasets = PersistentOntologyStore(ONTOLOGY_PATH).load_datasets()
        cls.by_id = {
            e["id"]: e
            for entries in cls.datasets.values()
            for e in entries
            if isinstance(e, dict) and e.get("id")
        }

    def test_schema_formation_gains_roster_slots_and_doctrine(self):
        schema = self.by_id["schema_formation"]
        fields = schema.get("fields", {})
        self.assertEqual(fields["roster_slots"]["type"], "object_list")
        self.assertEqual(fields["doctrine"]["type"], "string")

    def test_ggo_sol_marines_seed_hierarchy_exists(self):
        for child_id, (label, parent_id, doctrine, slots) in tool.SOL_MARINE_TREE.items():
            entity = self.by_id.get(child_id)
            self.assertIsInstance(entity, dict, child_id)
            self.assertEqual(entity.get("parents"), [parent_id])
            self.assertEqual(entity.get("doctrine"), doctrine)
            self.assertEqual(len(entity.get("roster_slots") or []), len(slots))
        fire_team = self.by_id["form_ggo_1st_fire_team"]
        command = [s for s in fire_team["roster_slots"] if s.get("is_command")]
        self.assertEqual(len(command), 1)
        self.assertTrue(any(s["kind"] == "vehicle" for s in fire_team["roster_slots"]))

    def test_second_run_is_a_noop(self):
        self.assertEqual([], tool.build_transaction(self.datasets))


if __name__ == "__main__":
    unittest.main()
