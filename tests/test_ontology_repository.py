import copy
import sqlite3
import tempfile
import unittest
import json
import shutil
import threading
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from simulations.map.map_simulation import MapSimulation
from simulations.person.person_simulation import PersonSimulation
from simulations.space.system import CelestialSystem
from world.entity_loader import EntityLoader
from world.simulation_context import SimulationContext
from world.ontology_repository import OntologyDependencyError, OntologyRepository
from world.persistent_ontology_store import LazyEntity, PersistentOntologyStore
from world.world_model import WorldModel


class OntologyRepositoryTests(unittest.TestCase):
    def test_decoded_projection_cache_is_reused_only_for_matching_store_signature(self):
        temp_path = Path(__file__).resolve().parents[1] / ".cache" / f"projection-test-{uuid.uuid4().hex}"
        temp_path.mkdir(parents=True, exist_ok=True)
        try:
            database_path = temp_path / "store.sqlite3"
            database_path.write_bytes(b"quadstore-v1")
            store = PersistentOntologyStore.__new__(PersistentOntologyStore)
            store.database_path = database_path
            store.projection_cache_path = temp_path / "projection.pickle"
            store.projection_manifest_path = temp_path / "projection.manifest.json"
            store.PROJECTION_CACHE_VERSION = 2
            store._operation_lock = threading.RLock()
            datasets = {"locations": [{"id": "planet_a", "heightmap_model": {"rows": [[1, 2]]}}]}

            self.assertTrue(store._write_projection_cache(datasets))
            loaded = store._load_projection_cache()
            self.assertIsInstance(loaded["locations"][0], LazyEntity)
            self.assertFalse(loaded["locations"][0].is_hydrated)
            self.assertEqual({"rows": [[1, 2]]}, loaded["locations"][0]["heightmap_model"])
            self.assertTrue(loaded["locations"][0].is_hydrated)

            database_path.write_bytes(b"quadstore-v2-with-a-different-size")
            self.assertIsNone(store._load_projection_cache())
        finally:
            shutil.rmtree(temp_path, ignore_errors=True)

    def test_lazy_entity_deepcopy_via_copy_avoids_lock_pickle_error(self):
        entity = LazyEntity(
            {"id": "planet_test", "heightmap_model": {"rows": [[1, 2]]}, "nested": {"a": [1, 2, 3]}},
            payload_path=Path("unused"),
            lazy_fields=(),
        )

        # Deep-copying a LazyEntity directly pickles its internal hydration
        # RLock and fails -- this is exactly what crashed regional
        # refinement (simulations/world_gen/regional_refinement.py) when
        # root_planet came back from world_model.get_entity() as a
        # LazyEntity rather than a plain dict.
        with self.assertRaises(TypeError):
            copy.deepcopy(entity)

        # .copy() -- LazyEntity's own hydrate-then-plain-dict method -- is
        # the fix: deep-copying its result works and preserves nested data.
        plain = copy.deepcopy(entity.copy())
        self.assertIs(type(plain), dict)
        self.assertEqual(plain["heightmap_model"], {"rows": [[1, 2]]})
        plain["nested"]["a"].append(4)
        self.assertEqual(entity["nested"]["a"], [1, 2, 3])

    def test_decoded_projection_cache_rejects_corrupt_payload(self):
        temp_path = Path(__file__).resolve().parents[1] / ".cache" / f"projection-test-{uuid.uuid4().hex}"
        temp_path.mkdir(parents=True, exist_ok=True)
        try:
            database_path = temp_path / "store.sqlite3"
            database_path.write_bytes(b"quadstore")
            store = PersistentOntologyStore.__new__(PersistentOntologyStore)
            store.database_path = database_path
            store.projection_cache_path = temp_path / "projection.pickle"
            store.projection_manifest_path = temp_path / "projection.manifest.json"
            store.PROJECTION_CACHE_VERSION = 2
            store.projection_cache_path.write_bytes(b"not-a-pickle")
            store.projection_manifest_path.write_text(json.dumps({
                "source_signature": store._projection_source_signature(),
            }), encoding="utf-8")

            self.assertIsNone(store._load_projection_cache())
            self.assertFalse(store.projection_cache_path.exists())
            self.assertFalse(store.projection_manifest_path.exists())
        finally:
            shutil.rmtree(temp_path, ignore_errors=True)

    def test_projection_cache_point_patch_preserves_lazy_location_payload(self):
        temp_path = Path(__file__).resolve().parents[1] / ".cache" / f"projection-test-{uuid.uuid4().hex}"
        temp_path.mkdir(parents=True, exist_ok=True)
        try:
            database_path = temp_path / "store.sqlite3"
            database_path.write_bytes(b"quadstore-v1")
            store = PersistentOntologyStore.__new__(PersistentOntologyStore)
            store.database_path = database_path
            store.projection_cache_path = temp_path / "projection.pickle"
            store.projection_manifest_path = temp_path / "projection.manifest.json"
            store.PROJECTION_CACHE_VERSION = 2
            datasets = {
                "locations": [{
                    "id": "planet_a",
                    "type": "location",
                    "pretty_name": "Before",
                    "heightmap_model": {"rows": [[1, 2]]},
                }],
            }
            self.assertTrue(store._write_projection_cache(datasets))
            previous_signature = store._projection_source_signature()
            database_path.write_bytes(b"quadstore-v2-with-new-transaction")
            changed_entity = {
                "id": "planet_a",
                "_dataset": "locations",
                "pretty_name": "After",
            }

            self.assertTrue(store._patch_projection_cache(
                entities=[changed_entity],
                field_names_by_id={"planet_a": {"pretty_name"}},
                previous_signature=previous_signature,
            ))
            loaded = store._load_projection_cache()["locations"][0]
            self.assertEqual("After", loaded["pretty_name"])
            self.assertFalse(loaded.is_hydrated)
            self.assertEqual({"rows": [[1, 2]]}, loaded["heightmap_model"])
        finally:
            shutil.rmtree(temp_path, ignore_errors=True)

    def test_successful_store_commit_invalidates_decoded_projection_cache(self):
        temp_path = Path(__file__).resolve().parents[1] / ".cache" / f"projection-test-{uuid.uuid4().hex}"
        temp_path.mkdir(parents=True, exist_ok=True)
        try:
            store = PersistentOntologyStore.__new__(PersistentOntologyStore)
            store.projection_cache_path = temp_path / "projection.pickle"
            store.projection_manifest_path = temp_path / "projection.manifest.json"
            store.database_path = temp_path / "store.sqlite3"
            store.database_path.write_bytes(b"quadstore")
            store.LOCK_RETRY_ATTEMPTS = 1
            store.projection_cache_path.write_bytes(b"cached")
            store.projection_manifest_path.write_text("{}", encoding="utf-8")
            world = SimpleNamespace(save=lambda: None)

            self.assertTrue(store._save_world(world))
            self.assertFalse(store.projection_cache_path.exists())
            self.assertFalse(store.projection_manifest_path.exists())
        finally:
            shutil.rmtree(temp_path, ignore_errors=True)

    def test_persistent_store_point_edit_survives_restart_without_touching_other_fields(self):
        ontology = OntologyRepository({
            "ideas": [{
                "id": "idea_one",
                "type": "idea",
                "pretty_name": "Original name",
                "card_color": "#111111",
                "wiki_field_colors": {"default": "#222222"},
            }],
        })
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            ontology_path = temp_path / "ontology" / "index0.owl"
            database_path = temp_path / "store.sqlite3"
            ontology.save_owl(ontology_path)
            original_owl = ontology_path.read_bytes()

            store = PersistentOntologyStore(ontology_path, database_path=database_path)
            entity = store.load_datasets()["ideas"][0]
            entity["card_color"] = "#abcdef"
            entity["wiki_field_colors"] = {"default": "#fedcba"}
            self.assertTrue(store.persist_entity_fields(entity, {"card_color", "wiki_field_colors"}))

            restarted = PersistentOntologyStore(ontology_path, database_path=database_path)
            reloaded = restarted.load_datasets()["ideas"][0]
            self.assertEqual("#abcdef", reloaded["card_color"])
            self.assertEqual({"default": "#fedcba"}, reloaded["wiki_field_colors"])
            self.assertEqual("Original name", reloaded["pretty_name"])
            self.assertEqual(original_owl, ontology_path.read_bytes())

            self.assertTrue(restarted.export_rdfxml())
            exported = OntologyRepository.from_owl(ontology_path).entities["idea_one"]
            self.assertEqual("#abcdef", exported["card_color"])

    def test_persistent_store_point_edit_updates_object_relation(self):
        ontology = OntologyRepository({
            "locations": [
                {
                    "id": "loc_parent",
                    "type": "location",
                    "pretty_name": "Parent",
                },
                {
                    "id": "loc_child",
                    "type": "location",
                    "pretty_name": "Child",
                    "parents": [],
                },
            ],
        })
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            ontology_path = temp_path / "ontology" / "index0.owl"
            database_path = temp_path / "store.sqlite3"
            ontology.save_owl(ontology_path)

            store = PersistentOntologyStore(
                ontology_path,
                database_path=database_path,
            )
            datasets = store.load_datasets()
            child = next(
                entity
                for entity in datasets["locations"]
                if entity["id"] == "loc_child"
            )
            child["parents"] = ["loc_parent"]
            self.assertTrue(store.persist_entity_fields(child, {"parents"}))

            restarted = PersistentOntologyStore(
                ontology_path,
                database_path=database_path,
            )
            reloaded = {
                entity["id"]: entity
                for entity in restarted.load_datasets()["locations"]
            }
            self.assertEqual(["loc_parent"], reloaded["loc_child"]["parents"])

    def test_palette_persistence_uses_small_restart_safe_override_journal(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            ontology_path = Path(temp_dir) / "ontology" / "index0.owl"
            ontology_path.parent.mkdir(parents=True)
            ontology_path.write_text("unchanged ontology", encoding="utf-8")
            entity = {"id": "planet_test", "card_color": "#123456", "wiki_link_color": "#legacy"}
            loader = EntityLoader.__new__(EntityLoader)
            loader.use_ontology = True
            loader.ontology_path = ontology_path
            loader.datasets = {"locations": [entity]}

            self.assertTrue(loader.persist_entity_palette(entity))
            self.assertEqual("unchanged ontology", ontology_path.read_text(encoding="utf-8"))
            self.assertTrue(loader._palette_overrides_path().exists())

            entity["card_color"] = "#000000"
            entity.pop("wiki_link_color")
            loader._apply_palette_overrides()

            self.assertEqual("#123456", entity["card_color"])
            self.assertEqual("#legacy", entity["wiki_link_color"])

    def test_palette_persistence_falls_back_when_quadstore_is_locked(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            ontology_path = Path(temp_dir) / "ontology" / "index0.owl"
            ontology_path.parent.mkdir(parents=True)
            ontology_path.write_text("unchanged ontology", encoding="utf-8")
            entity = {"id": "clade_test", "card_color": "#123456", "card_color_source": "derived_offspring"}
            loader = EntityLoader.__new__(EntityLoader)
            loader.use_ontology = True
            loader.ontology_path = ontology_path
            loader.datasets = {"cladistics": [entity]}
            loader._persistent_store = SimpleNamespace(
                persist_entity_fields=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                    sqlite3.OperationalError("database is locked")
                )
            )

            self.assertTrue(loader.persist_entity_palette(entity))

            overrides = loader._load_palette_overrides()
            self.assertEqual("#123456", overrides["clade_test"]["card_color"])
            self.assertEqual("derived_offspring", overrides["clade_test"]["card_color_source"])

    def test_entity_persistence_reports_lock_without_terminating_application(self):
        entity = {"id": "idea_locked", "type": "idea", "_dataset": "ideas"}
        loader = EntityLoader.__new__(EntityLoader)
        loader.use_ontology = True
        loader.ontology_path = Path("index0.owl")
        loader.entities = {}
        loader.datasets = {}
        loader._persistent_store = SimpleNamespace(
            persist_entity=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                sqlite3.OperationalError("database is locked")
            )
        )

        self.assertFalse(loader.persist_entity(entity))
        self.assertIs(entity, loader.entities["idea_locked"])

    def test_persistent_store_retries_locked_world_open(self):
        class FakeConnection:
            def __init__(self):
                self.closed = False

            def execute(self, _statement):
                return None

            def close(self):
                self.closed = True

        connections = []
        calls = []
        sentinel_world = object()

        def connect(*_args, **_kwargs):
            connection = FakeConnection()
            connections.append(connection)
            return connection

        def open_world(**kwargs):
            calls.append(kwargs)
            if len(calls) < 3:
                raise sqlite3.OperationalError("database is locked")
            return sentinel_world

        store = PersistentOntologyStore.__new__(PersistentOntologyStore)
        store.database_path = Path("retry-test.sqlite3")
        store.LOCK_RETRY_ATTEMPTS = 3
        store.SQLITE_BUSY_TIMEOUT_MS = 1
        store._import_owlready2 = lambda: SimpleNamespace(World=open_world)

        with patch("world.persistent_ontology_store.sqlite3.connect", side_effect=connect), patch(
            "world.persistent_ontology_store.time.sleep", return_value=None,
        ):
            world = store._open_world()

        self.assertIs(sentinel_world, world)
        self.assertEqual(3, len(calls))
        self.assertTrue(connections[0].closed)
        self.assertTrue(connections[1].closed)
        self.assertFalse(connections[2].closed)

    def test_persistent_store_falls_back_for_owlready2_without_connection_api(self):
        class FakeConnection:
            def __init__(self):
                self.closed = False

            def execute(self, _statement):
                return None

            def close(self):
                self.closed = True

        connection = FakeConnection()
        calls = []
        sentinel_world = object()

        def open_world(**kwargs):
            calls.append(kwargs)
            if "connection" in kwargs:
                raise TypeError(
                    "Graph.__init__() got an unexpected keyword argument 'connection'"
                )
            return sentinel_world

        store = PersistentOntologyStore.__new__(PersistentOntologyStore)
        store.database_path = Path("legacy-owlready2.sqlite3")
        store.LOCK_RETRY_ATTEMPTS = 1
        store.SQLITE_BUSY_TIMEOUT_MS = 1
        store._import_owlready2 = lambda: SimpleNamespace(World=open_world)

        with patch(
            "world.persistent_ontology_store.sqlite3.connect",
            return_value=connection,
        ):
            world = store._open_world(read_only=True)

        self.assertIs(sentinel_world, world)
        self.assertTrue(connection.closed)
        self.assertIn("connection", calls[0])
        self.assertNotIn("connection", calls[1])
        self.assertTrue(calls[1]["read_only"])

    def test_persistent_store_retries_locked_world_commit(self):
        save_calls = []

        def save():
            save_calls.append(True)
            if len(save_calls) < 3:
                raise sqlite3.OperationalError("database is locked")

        store = PersistentOntologyStore.__new__(PersistentOntologyStore)
        store.LOCK_RETRY_ATTEMPTS = 3
        world = SimpleNamespace(save=save)

        with patch(
            "world.persistent_ontology_store.time.sleep",
            return_value=None,
        ):
            self.assertTrue(store._save_world(world))

        self.assertEqual(3, len(save_calls))

    def test_entity_deletion_uses_restart_safe_journal_when_store_is_locked(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            ontology_path = Path(temp_dir) / "ontology" / "index0.owl"
            ontology_path.parent.mkdir(parents=True)
            ontology_path.write_text("unchanged ontology", encoding="utf-8")
            entity = {"id": "component_locked", "type": "component", "_dataset": "components"}
            loader = EntityLoader.__new__(EntityLoader)
            loader.use_ontology = True
            loader.ontology_path = ontology_path
            loader.entities = {entity["id"]: entity}
            loader.datasets = {"components": [entity]}
            loader._persistent_store = SimpleNamespace(
                remove_entity=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                    sqlite3.OperationalError("database is locked")
                )
            )

            self.assertTrue(
                loader.remove_entity("component_locked", dataset_name="components")
            )
            self.assertNotIn("component_locked", loader.entities)
            self.assertEqual([], loader.datasets["components"])
            self.assertEqual(
                {"component_locked"},
                loader._load_deletion_overrides(),
            )

            loader.datasets = {"components": [dict(entity)]}
            loader._reconcile_deletion_overrides()
            self.assertEqual([], loader.datasets["components"])
            self.assertEqual(
                {"component_locked"},
                loader._load_deletion_overrides(),
            )

            loader.datasets = {"components": [dict(entity)]}
            loader._persistent_store = SimpleNamespace(remove_entity=lambda *_args: True)
            loader._reconcile_deletion_overrides()
            self.assertEqual([], loader.datasets["components"])
            self.assertEqual(set(), loader._load_deletion_overrides())

    def test_deleting_linked_planet_removes_parent_object_reference(self):
        ontology = OntologyRepository({
            "locations": [
                {
                    "id": "system_tau_ceti",
                    "type": "location",
                    "name": "Tau Ceti",
                    "constituents": ["planet_tau_ceti_b"],
                },
                {
                    "id": "planet_tau_ceti_b",
                    "type": "location",
                    "name": "Tau Ceti b",
                    "parents": ["system_tau_ceti"],
                },
            ],
        })
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            entries_dir = temp_path / "entries"
            entries_dir.mkdir()
            ontology_path = temp_path / "ontology" / "index0.owl"
            try:
                ontology.save_owl(ontology_path)
                loader = EntityLoader(
                    entries_directory=entries_dir,
                    ontology_path=ontology_path,
                    use_ontology=True,
                )
                self.assertTrue(loader.remove_entity(
                    "planet_tau_ceti_b",
                    dataset_name="locations",
                ))
                reloaded = EntityLoader(
                    entries_directory=entries_dir,
                    ontology_path=ontology_path,
                    use_ontology=True,
                )
            except OntologyDependencyError as exc:
                self.skipTest(str(exc))

            self.assertNotIn("planet_tau_ceti_b", reloaded.entities)
            self.assertNotIn(
                "planet_tau_ceti_b",
                reloaded.entities["system_tau_ceti"].get("constituents", []),
            )

    def test_parent_relation_materializes_offspring_projection(self):
        ontology = OntologyRepository({
            "ideas": [
                {"id": "idea_parent", "type": "idea", "pretty_name": "Parent"},
                {
                    "id": "idea_child",
                    "type": "idea",
                    "pretty_name": "Child",
                    "parents": ["idea_parent"],
                },
            ],
        })

        entities = ontology.materialized_entities()

        self.assertEqual([{"id": "idea_child"}], entities["idea_parent"]["offspring"])
        self.assertEqual([], entities["idea_child"]["offspring"])

    def test_related_relation_is_reciprocal_on_set_and_remove(self):
        ontology = OntologyRepository({
            "ideas": [
                {"id": "idea_a", "type": "idea", "pretty_name": "A"},
                {"id": "idea_b", "type": "idea", "pretty_name": "B"},
            ],
        })

        changed = ontology.set_relation("idea_a", "related", "idea_b")

        self.assertEqual({"idea_a", "idea_b"}, changed)
        self.assertEqual(["idea_b"], ontology.entities["idea_a"]["related"])
        self.assertEqual(["idea_a"], ontology.entities["idea_b"]["related"])

        changed = ontology.remove_relation("idea_a", "related", "idea_b")

        self.assertEqual({"idea_a", "idea_b"}, changed)
        self.assertEqual([], ontology.entities["idea_a"]["related"])
        self.assertEqual([], ontology.entities["idea_b"]["related"])

    def test_materialized_entities_include_reciprocal_related_projection(self):
        ontology = OntologyRepository({
            "ideas": [
                {"id": "idea_a", "type": "idea", "pretty_name": "A", "related": ["idea_b"]},
                {"id": "idea_b", "type": "idea", "pretty_name": "B"},
            ],
        })

        entities = ontology.materialized_entities()

        self.assertEqual(["idea_b"], entities["idea_a"]["related"])
        self.assertEqual(["idea_a"], entities["idea_b"]["related"])

    def test_legacy_idea_parent_entity_materializes_offspring_projection(self):
        ontology = OntologyRepository({
            "ideas": [
                {"id": "idea_parent", "type": "idea", "pretty_name": "Parent"},
                {
                    "id": "idea_child",
                    "type": "idea",
                    "pretty_name": "Child",
                    "parent_entity": "idea_parent",
                },
            ],
        })

        entities = ontology.materialized_entities()

        self.assertEqual([{"id": "idea_child"}], entities["idea_parent"]["offspring"])

    def test_owlready2_declares_parent_offspring_inverse(self):
        ontology = OntologyRepository({
            "ideas": [
                {
                    "id": "idea_child",
                    "type": "idea",
                    "pretty_name": "Child",
                    "parents": ["idea_parent"],
                },
                {"id": "idea_parent", "type": "idea", "pretty_name": "Parent"},
            ],
        })

        try:
            onto = ontology.build_ontology()
        except OntologyDependencyError as exc:
            self.skipTest(str(exc))

        self.assertIs(onto.hasParent.inverse_property, onto.hasOffspring)
        child = onto.search_one(iri="https://index0.local/entity/idea_child")
        parent = onto.search_one(iri="https://index0.local/entity/idea_parent")
        self.assertEqual([parent], list(child.hasParent))
        self.assertEqual([child], list(parent.hasOffspring))

    def test_owlready2_declares_related_symmetric(self):
        ontology = OntologyRepository({
            "ideas": [
                {
                    "id": "idea_a",
                    "type": "idea",
                    "pretty_name": "A",
                    "related": ["idea_b"],
                },
                {"id": "idea_b", "type": "idea", "pretty_name": "B"},
            ],
        })

        try:
            onto = ontology.build_ontology()
            owlready2 = ontology._import_owlready2()
        except OntologyDependencyError as exc:
            self.skipTest(str(exc))

        self.assertIn(owlready2.SymmetricProperty, onto.relatedTo.is_a)
        idea_a = onto.search_one(iri="https://index0.local/entity/idea_a")
        idea_b = onto.search_one(iri="https://index0.local/entity/idea_b")
        self.assertEqual([idea_b], list(idea_a.relatedTo))

    def test_save_owl_creates_parent_directories(self):
        ontology = OntologyRepository({"ideas": [{"id": "idea_one", "type": "idea"}]})

        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "ontology" / "index0.owl"
            try:
                ontology.save_owl(output_path)
            except OntologyDependencyError as exc:
                self.skipTest(str(exc))

            self.assertTrue(output_path.exists())
            self.assertIn("Ontology", output_path.read_text(encoding="utf-8"))

    def test_save_owl_retries_transient_oserror(self):
        ontology = OntologyRepository({"ideas": [{"id": "idea_one", "type": "idea"}]})
        attempts = {"count": 0}

        class FakeOntology:
            def save(self, file, format="rdfxml"):
                attempts["count"] += 1
                if attempts["count"] == 1:
                    raise OSError(22, "Invalid argument")
                Path(file).write_bytes(b"<Ontology/>")

        ontology.build_ontology = lambda iri=None: FakeOntology()

        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "ontology" / "index0.owl"

            ontology.save_owl(output_path)

            self.assertEqual(2, attempts["count"])
            self.assertEqual(b"<Ontology/>", output_path.read_bytes())

    def test_save_owl_falls_back_when_windows_blocks_atomic_replace(self):
        ontology = OntologyRepository({"ideas": [{"id": "idea_one", "type": "idea"}]})

        class FakeOntology:
            def save(self, file, format="rdfxml"):
                Path(file).write_bytes(b"<Ontology>updated</Ontology>")

        ontology.build_ontology = lambda iri=None: FakeOntology()

        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "ontology" / "index0.owl"
            output_path.parent.mkdir(parents=True)
            output_path.write_bytes(b"<Ontology>old</Ontology>")

            with patch.object(Path, "replace", side_effect=PermissionError(5, "Access denied")), patch(
                "world.ontology_repository.time.sleep"
            ):
                ontology.save_owl(output_path)

            self.assertEqual(b"<Ontology>updated</Ontology>", output_path.read_bytes())
            self.assertFalse(list(output_path.parent.glob("*.rollback")))

    def test_owl_round_trip_preserves_repository_projection(self):
        ontology = OntologyRepository({
            "ideas": [
                {
                    "id": "idea_parent",
                    "type": "idea",
                    "pretty_name": "Parent",
                    "tags": ["root"],
                    "wiki_field_colors": {"default": "#223344"},
                },
                {
                    "id": "idea_child",
                    "type": "idea",
                    "pretty_name": "Child",
                    "parents": ["idea_parent"],
                    "related": ["idea_parent"],
                    "tags": ["child"],
                },
            ],
        })

        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "ontology" / "index0.owl"
            try:
                ontology.save_owl(output_path)
                loaded = OntologyRepository.from_owl(output_path)
            except OntologyDependencyError as exc:
                self.skipTest(str(exc))

            self.assertEqual({"ideas"}, set(loaded.datasets))
            self.assertEqual("Parent", loaded.entities["idea_parent"]["pretty_name"])
            self.assertEqual(["root"], loaded.entities["idea_parent"]["tags"])
            self.assertEqual(
                {"default": "#223344"},
                loaded.entities["idea_parent"]["wiki_field_colors"],
            )
            self.assertEqual(["idea_parent"], loaded.entities["idea_child"]["parents"])
            self.assertEqual(["idea_parent"], loaded.entities["idea_child"]["related"])
            self.assertEqual(["idea_child"], loaded.entities["idea_parent"]["related"])

    def test_owl_round_trip_preserves_ordered_scalar_lists_and_duplicates(self):
        ontology = OntologyRepository({
            "materials": [{
                "id": "mat_neutral_rock",
                "type": "material",
                "display_color": [112, 116, 112],
                "ordered_samples": [3, 1, 3, 2],
            }],
        })

        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "ontology" / "index0.owl"
            try:
                ontology.save_owl(output_path)
                loaded = OntologyRepository.from_owl(output_path)
            except OntologyDependencyError as exc:
                self.skipTest(str(exc))

        material = loaded.entities["mat_neutral_rock"]
        self.assertEqual([112, 116, 112], material["display_color"])
        self.assertEqual([3, 1, 3, 2], material["ordered_samples"])

    def test_non_core_entity_reference_field_round_trips_as_object_property(self):
        ontology = OntologyRepository({
            "producers": [
                {
                    "id": "prod_factory",
                    "type": "producer",
                    "pretty_name": "Factory",
                    "produced_items": ["item_plate"],
                },
            ],
            "items": [
                {
                    "id": "item_plate",
                    "type": "item",
                    "pretty_name": "Plate",
                },
            ],
        })

        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "ontology" / "index0.owl"
            try:
                onto = ontology.build_ontology()
                producer = onto.search_one(iri="https://index0.local/entity/prod_factory")
                item = onto.search_one(iri="https://index0.local/entity/item_plate")
                self.assertEqual([item], list(producer.relation_produced_items))
                ontology.save_owl(output_path)
                loaded = OntologyRepository.from_owl(output_path)
            except OntologyDependencyError as exc:
                self.skipTest(str(exc))

            self.assertEqual(
                ["item_plate"],
                loaded.entities["prod_factory"]["produced_items"],
            )

    def test_entity_loader_can_use_ontology_source(self):
        ontology = OntologyRepository({
            "ideas": [
                {"id": "idea_parent", "type": "idea", "pretty_name": "Parent"},
                {
                    "id": "idea_child",
                    "type": "idea",
                    "pretty_name": "Child",
                    "parents": ["idea_parent"],
                },
            ],
        })

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            entries_dir = temp_path / "entries"
            entries_dir.mkdir()
            output_path = temp_path / "ontology" / "index0.owl"
            try:
                ontology.save_owl(output_path)
                loader = EntityLoader(
                    entries_directory=entries_dir,
                    ontology_path=output_path,
                    use_ontology=True,
                )
            except OntologyDependencyError as exc:
                self.skipTest(str(exc))

            self.assertEqual("Child", loader.entities["idea_child"]["pretty_name"])
            self.assertEqual([{"id": "idea_child"}], loader.entities["idea_parent"]["offspring"])

    def test_world_model_can_be_explicitly_ontology_backed(self):
        ontology = OntologyRepository({
            "ideas": [
                {"id": "idea_from_owl", "type": "idea", "pretty_name": "From OWL"},
            ],
        })

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            entries_dir = temp_path / "entries"
            entries_dir.mkdir()
            output_path = temp_path / "ontology" / "index0.owl"
            try:
                ontology.save_owl(output_path)
                model = WorldModel(
                    entries_directory=entries_dir,
                    ontology_path=output_path,
                    use_ontology=True,
                )
            except OntologyDependencyError as exc:
                self.skipTest(str(exc))

            self.assertTrue(model.loader.use_ontology)
            self.assertEqual("From OWL", model.get_entity("idea_from_owl")["pretty_name"])

    def test_world_model_relation_api_updates_loader_projection(self):
        ontology = OntologyRepository({
            "ideas": [
                {"id": "idea_parent", "type": "idea", "pretty_name": "Parent"},
                {"id": "idea_child", "type": "idea", "pretty_name": "Child"},
            ],
        })

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            entries_dir = temp_path / "entries"
            entries_dir.mkdir()
            output_path = temp_path / "ontology" / "index0.owl"
            try:
                ontology.save_owl(output_path)
                model = WorldModel(
                    entries_directory=entries_dir,
                    ontology_path=output_path,
                    use_ontology=True,
                )
                changed = model.set_relation("idea_child", "parents", "idea_parent")
            except OntologyDependencyError as exc:
                self.skipTest(str(exc))

            self.assertEqual({"idea_child", "idea_parent"}, changed)
            self.assertEqual(["idea_parent"], model.get_entity("idea_child")["parents"])
            self.assertEqual([{"id": "idea_child"}], model.get_entity("idea_parent")["offspring"])

    def test_ontology_loader_persist_entity_round_trips_to_owl(self):
        ontology = OntologyRepository({
            "ideas": [
                {"id": "idea_parent", "type": "idea", "pretty_name": "Parent"},
            ],
        })

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            entries_dir = temp_path / "entries"
            entries_dir.mkdir()
            output_path = temp_path / "ontology" / "index0.owl"
            try:
                ontology.save_owl(output_path)
                loader = EntityLoader(
                    entries_directory=entries_dir,
                    ontology_path=output_path,
                    use_ontology=True,
                )
                child = {
                    "id": "idea_child",
                    "_dataset": "ideas",
                    "type": "idea",
                    "pretty_name": "Child",
                    "parents": ["idea_parent"],
                }
                self.assertTrue(loader.persist_entity(child))
                reloaded = EntityLoader(
                    entries_directory=entries_dir,
                    ontology_path=output_path,
                    use_ontology=True,
                )
            except OntologyDependencyError as exc:
                self.skipTest(str(exc))

            self.assertIn("idea_child", reloaded.entities)
            self.assertEqual(["idea_parent"], reloaded.entities["idea_child"]["parents"])
            self.assertEqual([{"id": "idea_child"}], reloaded.entities["idea_parent"]["offspring"])

    def test_ontology_loader_relation_api_round_trips_to_owl(self):
        ontology = OntologyRepository({
            "ideas": [
                {"id": "idea_parent", "type": "idea", "pretty_name": "Parent"},
                {"id": "idea_child", "type": "idea", "pretty_name": "Child"},
            ],
        })

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            entries_dir = temp_path / "entries"
            entries_dir.mkdir()
            output_path = temp_path / "ontology" / "index0.owl"
            try:
                ontology.save_owl(output_path)
                loader = EntityLoader(
                    entries_directory=entries_dir,
                    ontology_path=output_path,
                    use_ontology=True,
                )
                self.assertEqual(
                    {"idea_child", "idea_parent"},
                    loader.set_relation("idea_child", "parents", "idea_parent"),
                )
                self.assertEqual(
                    {"idea_child"},
                    loader.set_literal("idea_child", "pretty_name", "Child Prime"),
                )
                reloaded = EntityLoader(
                    entries_directory=entries_dir,
                    ontology_path=output_path,
                    use_ontology=True,
                )
            except OntologyDependencyError as exc:
                self.skipTest(str(exc))

            self.assertEqual(["idea_parent"], reloaded.entities["idea_child"]["parents"])
            self.assertEqual([{"id": "idea_child"}], reloaded.entities["idea_parent"]["offspring"])
            self.assertEqual("Child Prime", reloaded.entities["idea_child"]["pretty_name"])

    def test_ontology_loader_reciprocal_relation_api_round_trips_to_owl(self):
        ontology = OntologyRepository({
            "locations": [
                {"id": "loc_a", "type": "location", "_dataset": "locations", "name": "A"},
                {"id": "loc_b", "type": "location", "_dataset": "locations", "name": "B"},
            ],
        })

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            entries_dir = temp_path / "entries"
            entries_dir.mkdir()
            output_path = temp_path / "ontology" / "index0.owl"
            try:
                ontology.save_owl(output_path)
                loader = EntityLoader(
                    entries_directory=entries_dir,
                    ontology_path=output_path,
                    use_ontology=True,
                )
                self.assertEqual(
                    {"loc_a", "loc_b"},
                    loader.set_relation("loc_a", "neighbours", "loc_b", reciprocal_field="neighbours"),
                )
                self.assertEqual(
                    {"loc_a", "loc_b"},
                    loader.remove_relation("loc_a", "neighbours", "loc_b", reciprocal_field="neighbours"),
                )
                reloaded = EntityLoader(
                    entries_directory=entries_dir,
                    ontology_path=output_path,
                    use_ontology=True,
                )
            except OntologyDependencyError as exc:
                self.skipTest(str(exc))

            self.assertEqual([], reloaded.entities["loc_a"].get("neighbours", []))
            self.assertEqual([], reloaded.entities["loc_b"].get("neighbours", []))

    def test_location_topology_fields_round_trip_to_owl(self):
        ontology = OntologyRepository({
            "locations": [
                {"id": "loc_switzerland", "type": "location", "_dataset": "locations", "name": "Switzerland"},
                {"id": "loc_alps", "type": "location", "_dataset": "locations", "name": "The Alps"},
                {"id": "loc_canton", "type": "location", "_dataset": "locations", "name": "Canton"},
            ],
        })

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            entries_dir = temp_path / "entries"
            entries_dir.mkdir()
            output_path = temp_path / "ontology" / "index0.owl"
            try:
                ontology.save_owl(output_path)
                loader = EntityLoader(
                    entries_directory=entries_dir,
                    ontology_path=output_path,
                    use_ontology=True,
                )
                location = loader.entities["loc_switzerland"]
                location["neighbours"] = ["loc_alps"]
                location["overlaps"] = ["loc_alps"]
                location["constituents"] = ["loc_canton"]
                self.assertTrue(loader.persist_entity(location))
                reloaded = EntityLoader(
                    entries_directory=entries_dir,
                    ontology_path=output_path,
                    use_ontology=True,
                )
            except OntologyDependencyError as exc:
                self.skipTest(str(exc))

            self.assertEqual(["loc_alps"], reloaded.entities["loc_switzerland"]["neighbours"])
            self.assertEqual(["loc_alps"], reloaded.entities["loc_switzerland"]["overlaps"])
            self.assertEqual(["loc_canton"], reloaded.entities["loc_switzerland"]["constituents"])

    def test_ontology_loader_persist_entity_rename_removes_old_id(self):
        ontology = OntologyRepository({
            "ideas": [
                {"id": "idea_old", "type": "idea", "pretty_name": "Old"},
            ],
        })

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            entries_dir = temp_path / "entries"
            entries_dir.mkdir()
            output_path = temp_path / "ontology" / "index0.owl"
            try:
                ontology.save_owl(output_path)
                loader = EntityLoader(
                    entries_directory=entries_dir,
                    ontology_path=output_path,
                    use_ontology=True,
                )
                renamed = {
                    "id": "idea_new",
                    "_dataset": "ideas",
                    "type": "idea",
                    "pretty_name": "New",
                }
                self.assertTrue(loader.persist_entity(renamed, previous_entity_id="idea_old"))
                reloaded = EntityLoader(
                    entries_directory=entries_dir,
                    ontology_path=output_path,
                    use_ontology=True,
                )
            except OntologyDependencyError as exc:
                self.skipTest(str(exc))

            self.assertIn("idea_new", reloaded.entities)
            self.assertNotIn("idea_old", reloaded.entities)

    def test_ontology_loader_remove_entity_updates_owl(self):
        ontology = OntologyRepository({
            "ideas": [
                {"id": "idea_keep", "type": "idea", "pretty_name": "Keep"},
                {"id": "idea_remove", "type": "idea", "pretty_name": "Remove"},
            ],
        })

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            entries_dir = temp_path / "entries"
            entries_dir.mkdir()
            output_path = temp_path / "ontology" / "index0.owl"
            try:
                ontology.save_owl(output_path)
                loader = EntityLoader(
                    entries_directory=entries_dir,
                    ontology_path=output_path,
                    use_ontology=True,
                )
                self.assertTrue(loader.remove_entity("idea_remove", dataset_name="ideas"))
                reloaded = EntityLoader(
                    entries_directory=entries_dir,
                    ontology_path=output_path,
                    use_ontology=True,
                )
            except OntologyDependencyError as exc:
                self.skipTest(str(exc))

            self.assertIn("idea_keep", reloaded.entities)
            self.assertNotIn("idea_remove", reloaded.entities)

    def test_persistent_store_applies_mixed_changes_in_one_commit(self):
        ontology = OntologyRepository({
            "ideas": [
                {"id": "idea_keep", "type": "idea", "pretty_name": "Keep"},
                {"id": "idea_remove", "type": "idea", "pretty_name": "Remove"},
            ],
        })

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            ontology_path = temp_path / "ontology" / "index0.owl"
            database_path = temp_path / "cache" / "index0.sqlite3"
            try:
                ontology.save_owl(ontology_path)
                store = PersistentOntologyStore(
                    ontology_path,
                    database_path=database_path,
                )
                result = store.apply_changes(
                    entities=[
                        {
                            "id": "idea_keep",
                            "_dataset": "ideas",
                            "type": "idea",
                            "pretty_name": "Updated",
                        },
                        {
                            "id": "idea_new",
                            "_dataset": "ideas",
                            "type": "idea",
                            "pretty_name": "New",
                        },
                    ],
                    remove_entity_ids=["idea_remove", "idea_missing"],
                )
                datasets = store.load_datasets()
            except OntologyDependencyError as exc:
                self.skipTest(str(exc))

            ideas = {
                entity["id"]: entity
                for entity in datasets.get("ideas", [])
            }
            self.assertEqual(
                {"upserted": 2, "removed": 1},
                result,
            )
            self.assertEqual("Updated", ideas["idea_keep"]["pretty_name"])
            self.assertIn("idea_new", ideas)
            self.assertNotIn("idea_remove", ideas)

    def test_map_simulation_ontology_location_save_uses_parent_relation(self):
        ontology = OntologyRepository({
            "locations": [
                {
                    "id": "loc_root",
                    "type": "location",
                    "pretty_name": "Root",
                    "location_class": "planet",
                },
            ],
        })

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            entries_dir = temp_path / "entries"
            entries_dir.mkdir()
            output_path = temp_path / "ontology" / "index0.owl"
            try:
                ontology.save_owl(output_path)
                loader = EntityLoader(
                    entries_directory=entries_dir,
                    ontology_path=output_path,
                    use_ontology=True,
                )
                world_model = SimpleNamespace(
                    loader=loader,
                    get_entity=lambda entity_id: loader.entities.get(entity_id),
                    get_active_entities=lambda year, dataset_name=None, entity_type=None: [
                        entity
                        for entity in loader.entities.values()
                        if (dataset_name is None or entity.get("_dataset") == dataset_name)
                        and (entity_type is None or entity.get("type") == entity_type)
                    ],
                    get_active_locations=lambda year: [
                        entity
                        for entity in loader.entities.values()
                        if entity.get("_dataset") == "locations" and entity.get("type") == "location"
                    ],
                    refresh=lambda: loader.refresh(),
                )
                sim = MapSimulation(SimulationContext(
                    year=0,
                    root_entity_id="loc_root",
                    world_model=world_model,
                ))
                sim._append_location_record({
                    "id": "loc_child",
                    "type": "location",
                    "pretty_name": "Child",
                    "location_class": "region",
                })
                self.assertTrue(sim._append_offspring_reference_to_location("loc_root", "loc_child"))
                reloaded = EntityLoader(
                    entries_directory=entries_dir,
                    ontology_path=output_path,
                    use_ontology=True,
                )
            except OntologyDependencyError as exc:
                self.skipTest(str(exc))

            self.assertEqual(["loc_root"], reloaded.entities["loc_child"]["parents"])
            self.assertEqual(["loc_child"], reloaded.entities["loc_root"]["constituents"])
            self.assertEqual([{"id": "loc_child"}], reloaded.entities["loc_root"]["offspring"])

    def test_person_simulation_ontology_update_persists_to_owl(self):
        ontology = OntologyRepository({
            "people": [
                {
                    "id": "person_ada",
                    "type": "person",
                    "pretty_name": "Ada",
                    "name": "Ada",
                },
            ],
        })

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            entries_dir = temp_path / "entries"
            entries_dir.mkdir()
            output_path = temp_path / "ontology" / "index0.owl"
            try:
                ontology.save_owl(output_path)
                loader = EntityLoader(
                    entries_directory=entries_dir,
                    ontology_path=output_path,
                    use_ontology=True,
                )
                world_model = SimpleNamespace(
                    loader=loader,
                    get_entity=lambda entity_id: loader.entities.get(entity_id),
                    refresh=lambda: loader.refresh(),
                )
                sim = PersonSimulation(
                    world_model=world_model,
                    person_entity_id="person_ada",
                    year=2400,
                )
                self.assertTrue(sim._persist_person_updates(
                    loader.entities["person_ada"],
                    {"pretty_name": "Ada Prime", "name": "Ada Prime"},
                ))
                reloaded = EntityLoader(
                    entries_directory=entries_dir,
                    ontology_path=output_path,
                    use_ontology=True,
                )
            except OntologyDependencyError as exc:
                self.skipTest(str(exc))

            self.assertEqual("Ada Prime", reloaded.entities["person_ada"]["pretty_name"])

    def test_space_system_ontology_anchor_creation_persists_to_owl(self):
        ontology = OntologyRepository({
            "systems": [
                {
                    "id": "body_blue",
                    "type": "system",
                    "pretty_name": "Blue",
                    "name": "Blue",
                    "system_role": "orbital_body",
                    "body_class": "planet",
                    "radius_m": 6371000,
                },
            ],
        })

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            entries_dir = temp_path / "entries"
            entries_dir.mkdir()
            output_path = temp_path / "ontology" / "index0.owl"
            try:
                ontology.save_owl(output_path)
                loader = EntityLoader(
                    entries_directory=entries_dir,
                    ontology_path=output_path,
                    use_ontology=True,
                )
                world_model = SimpleNamespace(
                    loader=loader,
                    get_entity=lambda entity_id: loader.entities.get(entity_id),
                )
                system = CelestialSystem()
                location_id, created = system.ensure_location_anchor_for_body_entity(
                    loader.entities["body_blue"],
                    world_model=world_model,
                )
                reloaded = EntityLoader(
                    entries_directory=entries_dir,
                    ontology_path=output_path,
                    use_ontology=True,
                )
            except OntologyDependencyError as exc:
                self.skipTest(str(exc))

            self.assertTrue(created)
            self.assertEqual("planet_blue", location_id)
            self.assertIn("planet_blue", reloaded.entities)
            self.assertEqual("planet_blue", reloaded.entities["body_blue"]["location_entity"])


if __name__ == "__main__":
    unittest.main()
