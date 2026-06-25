import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from simulations.map.map_simulation import MapSimulation
from simulations.person.person_simulation import PersonSimulation
from simulations.space.system import CelestialSystem
from world.entity_loader import EntityLoader
from world.simulation_context import SimulationContext
from world.ontology_repository import OntologyDependencyError, OntologyRepository
from world.world_model import WorldModel


class OntologyRepositoryTests(unittest.TestCase):
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
