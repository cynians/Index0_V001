"""Large JSON literals are kept packed and out of the value index; what is read from the store stays the same."""

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from world import ontology_repository
from world.ontology_repository import (
    PACKED_JSON_FROM_CHARS, PACKED_JSON_PREFIX, OntologyDependencyError, OntologyRepository, pack_json_text,
    unpack_json_text,
)
from world.persistent_ontology_store import PersistentOntologyStore
from tools.ontology_backup import BACKUP_FILE, backup_entities, read_backup, restore


GRID = {"rows": [[round(row * 1000.0 + column * 0.123456789, 9) for column in range(120)] for row in range(60)],
        "sea_level_m": 12.5, "note": "höhe"}
LONG_TEXT = "A long wiki entry. " * 400


def world_card(**fields):
    return {"id": "idea_world", "_dataset": "ideas", "type": "idea", "pretty_name": "World", **fields}


class PackedLiteralTests(unittest.TestCase):
    def test_a_small_literal_is_kept_as_it_is_and_a_large_one_packed(self):
        small = json.dumps({"default": "#223344"})
        self.assertEqual(small, pack_json_text(small))
        large = json.dumps(GRID, ensure_ascii=False)
        self.assertGreaterEqual(len(large), PACKED_JSON_FROM_CHARS)
        kept = pack_json_text(large)
        self.assertTrue(kept.startswith(PACKED_JSON_PREFIX))
        self.assertLess(len(kept), len(large) / 2)
        self.assertEqual(large, unpack_json_text(kept))
        self.assertEqual(small, unpack_json_text(small))
        # Whoever reads a literal takes both forms, and hands back a broken one as it is instead of failing.
        repository = OntologyRepository({})
        self.assertEqual(GRID, repository._decode_json_value(kept))
        self.assertEqual(GRID, repository._decode_json_value(large))
        self.assertEqual(PACKED_JSON_PREFIX + "###", repository._decode_json_value(PACKED_JSON_PREFIX + "###"))
        self.assertEqual([kept], repository._data_values(GRID))


class CompactStoreTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        root = Path(self.folder.name)
        self.ontology_path = root / "ontology" / "index0.owl"
        self.database_path = root / "store.sqlite3"

    def store(self, *entities):
        try:
            OntologyRepository({"ideas": list(entities)}).save_owl(self.ontology_path)
            return PersistentOntologyStore(self.ontology_path, database_path=self.database_path)
        except OntologyDependencyError as exc:
            self.skipTest(str(exc))

    def read_from_database(self):
        """What the store decodes from the database itself, not from its startup projection."""
        store = PersistentOntologyStore(self.ontology_path, database_path=self.database_path)
        store._invalidate_projection_cache()
        return {entity["id"]: dict(entity) for entity in store.load_datasets()["ideas"]}

    def literals(self):
        connection = sqlite3.connect(str(self.database_path))
        try:
            return [value for (value,) in connection.execute("SELECT o FROM datas WHERE typeof(o)='text'")]
        finally:
            connection.close()

    def index_sql(self):
        connection = sqlite3.connect(str(self.database_path))
        try:
            return connection.execute("SELECT sql FROM sqlite_master WHERE name='index_datas_op'").fetchone()[0]
        finally:
            connection.close()

    def test_a_model_written_to_the_store_is_packed_there_and_read_back_whole(self):
        store = self.store(world_card())
        self.assertTrue(store.persist_entity(world_card(heightmap_model=GRID, wiki_entry=LONG_TEXT)))
        packed = [value for value in self.literals() if value.startswith(PACKED_JSON_PREFIX)]
        self.assertEqual(1, len(packed))
        self.assertLess(len(packed[0]), len(json.dumps(GRID)) / 2)
        self.assertIn(LONG_TEXT, self.literals())  # a long plain text is no JSON literal and is kept as written
        read = self.read_from_database()["idea_world"]
        self.assertEqual(GRID, read["heightmap_model"])
        self.assertEqual(LONG_TEXT, read["wiki_entry"])
        # A point edit of the same field goes the same way.
        changed = dict(GRID, sea_level_m=99.0)
        entity = world_card(heightmap_model=changed, wiki_entry=LONG_TEXT)
        self.assertTrue(store.persist_entity_fields(entity, {"heightmap_model"}))
        self.assertEqual(changed, self.read_from_database()["idea_world"]["heightmap_model"])
        self.assertEqual(1, sum(value.startswith(PACKED_JSON_PREFIX) for value in self.literals()))

    def test_only_small_values_are_in_the_value_index_and_it_still_keeps_a_triple_single(self):
        store = self.store(world_card(heightmap_model=GRID))
        self.assertIn("WHERE length(o) <= 4096", self.index_sql())  # a freshly imported store is compacted at once
        connection = sqlite3.connect(str(self.database_path))
        try:
            row = connection.execute("SELECT c, s, p, o, d FROM datas WHERE typeof(o)='text' AND length(o) < 100").fetchone()
            before = connection.execute("SELECT count(*) FROM datas").fetchone()[0]
            connection.execute("INSERT OR IGNORE INTO datas VALUES (?,?,?,?,?)", row)
            connection.commit()
            self.assertEqual(before, connection.execute("SELECT count(*) FROM datas").fetchone()[0])
        finally:
            connection.close()
        connection = sqlite3.connect(str(self.database_path))
        try:
            self.assertFalse(store._apply_value_index_policy(connection))  # already as wanted
        finally:
            connection.close()

    def test_a_store_in_the_old_layout_is_brought_to_the_compact_one_without_changing_what_it_holds(self):
        with patch.object(ontology_repository, "pack_json_text", lambda text: text):
            store = self.store(world_card(heightmap_model=GRID, wiki_entry=LONG_TEXT, tags=["a", "b"]))
        connection = sqlite3.connect(str(self.database_path))
        connection.execute("DROP INDEX index_datas_op")
        connection.execute("CREATE UNIQUE INDEX index_datas_op ON datas(o,p,c,d,s)")  # as Owlready2 makes it
        connection.commit()
        connection.close()
        self.assertFalse(any(value.startswith(PACKED_JSON_PREFIX) for value in self.literals()))
        held_before = self.read_from_database()

        store = PersistentOntologyStore(self.ontology_path, database_path=self.database_path)
        store.load_datasets()  # a startup projection that is valid for the old file
        before = store.storage_report()
        self.assertEqual((1, 0, 1, False), (before["json_literals_plain"], before["json_literals_packed"],
                                            before["large_literals_not_json"], before["value_index_is_partial"]))
        done = store.optimize_storage()
        self.assertEqual((1, 1), (done["literals_packed"], done["large_literals_not_json"]))
        self.assertLess(done["chars_after"], done["chars_before"] / 2)
        self.assertLess(done["bytes_after"], done["bytes_before"])
        after = store.storage_report()
        self.assertEqual((0, 1, True), (after["json_literals_plain"], after["json_literals_packed"],
                                        after["value_index_is_partial"]))
        self.assertIn(LONG_TEXT, self.literals())
        # What was read before is what is read now, and the startup projection made before is still taken.
        self.assertTrue(done["projection_kept"])
        self.assertIsNotNone(store._load_projection_cache())
        self.assertEqual(held_before, self.read_from_database())
        # Done twice, nothing more happens.
        self.assertEqual(0, store.optimize_storage()["literals_packed"])
        self.assertEqual(held_before, self.read_from_database())

    def test_a_checkpoint_carries_packed_literals_and_a_store_rebuilt_from_it_holds_the_same(self):
        store = self.store(world_card())
        self.assertTrue(store.persist_entity(world_card(heightmap_model=GRID, tags=["a", "a", "b"])))
        held = self.read_from_database()
        self.assertTrue(store.export_rdfxml())
        self.assertIn(PACKED_JSON_PREFIX, self.ontology_path.read_text(encoding="utf-8"))
        from_checkpoint = OntologyRepository.from_owl(self.ontology_path).entities["idea_world"]
        self.assertEqual(GRID, from_checkpoint["heightmap_model"])
        self.assertTrue(store.reimport_rdfxml())
        self.assertEqual(held, self.read_from_database())
        self.assertIn("WHERE length(o) <= 4096", self.index_sql())

    def test_a_checkpoint_written_before_literals_were_packed_still_loads(self):
        with patch.object(ontology_repository, "pack_json_text", lambda text: text):
            self.store(world_card(heightmap_model=GRID))
        self.assertNotIn(PACKED_JSON_PREFIX, self.ontology_path.read_text(encoding="utf-8"))
        self.assertEqual(GRID, self.read_from_database()["idea_world"]["heightmap_model"])

    def test_a_run_keeps_only_what_it_replaces_or_removes_and_can_be_undone_from_that(self):
        other = {"id": "idea_other", "_dataset": "ideas", "type": "idea", "pretty_name": "Other"}
        store = self.store(world_card(heightmap_model=GRID), other)
        held = self.read_from_database()
        changed = world_card(heightmap_model=dict(GRID, sea_level_m=1.0), pretty_name="Renamed")
        new = {"id": "idea_new", "_dataset": "ideas", "type": "idea", "pretty_name": "New"}
        backup_dir = backup_entities(store, Path(self.folder.name) / "backups", [changed, new], ["idea_other"])
        # The backup is of the three entities the run touches, not of the store.
        self.assertEqual([BACKUP_FILE], [path.name for path in backup_dir.iterdir()])
        record = read_backup(backup_dir)
        self.assertEqual(["idea_world", "idea_other"], [entity["id"] for entity in record["replaced_or_removed"]])
        self.assertEqual(["idea_new"], record["created_by_the_run"])
        self.assertEqual(GRID, record["replaced_or_removed"][0]["heightmap_model"])
        store.apply_changes(entities=[changed, new], remove_entity_ids=["idea_other"])
        self.assertEqual({"idea_world", "idea_new"}, set(self.read_from_database()))
        self.assertEqual({"upserted": 2, "removed": 1}, restore(store, backup_dir))
        self.assertEqual(held, self.read_from_database())


if __name__ == "__main__":
    unittest.main()
