import re
import unittest
from pathlib import Path
from types import SimpleNamespace

from world.ontology_repository import OntologyRepository
from world.world_model import WorldModel


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class RepositoryIntegrityTests(unittest.TestCase):
    def test_task_ids_are_unique_and_do_not_self_depend(self):
        task_text = (PROJECT_ROOT / "text" / "tasks.txt").read_text(encoding="utf-8")
        task_ids = re.findall(r"^TASK-\d+\b", task_text, flags=re.MULTILINE)
        duplicates = sorted({task_id for task_id in task_ids if task_ids.count(task_id) > 1})
        self.assertEqual([], duplicates)

        blocks = re.split(r"(?=^TASK-\d+\b)", task_text, flags=re.MULTILINE)
        for block in blocks:
            task_match = re.match(r"^(TASK-\d+)\b", block)
            if not task_match:
                continue
            task_id = task_match.group(1)
            requires_match = re.search(r"^Requires:\s*(.+)$", block, flags=re.MULTILINE)
            if not requires_match:
                continue
            required_ids = re.findall(r"TASK-\d+", requires_match.group(1))
            self.assertNotIn(task_id, required_ids, f"{task_id} depends on itself")

    def test_city_schema_uses_canonical_schema_key(self):
        model = WorldModel()
        city_schema = model.schemas.schemas.get("cities")
        self.assertIsNotNone(city_schema)
        self.assertEqual("cities", city_schema.get("schema"))

    def test_collection_schema_is_available_from_ontology(self):
        model = WorldModel()
        collection_schema = model.schemas.schemas.get("collections")

        self.assertIsNotNone(collection_schema)
        self.assertEqual("collections", collection_schema.get("schema"))
        self.assertEqual("Collections", model.get_entity("schema_collections").get("pretty_name"))
        field_keys = set(collection_schema.get("fields", {}).keys())
        self.assertIn("collection_class", field_keys)
        self.assertIn("includes", field_keys)
        self.assertIn("featured_entries", field_keys)

    def test_star_system_neighbourhoods_are_present_in_ontology(self):
        model = WorldModel()
        systems = [
            entity for entity in model.loader.entities.values()
            if isinstance(entity, dict)
            and (
                entity.get("location_class") == "star_system"
                or entity.get("location_role") == "star_system"
                or entity.get("system_role") == "star_system"
            )
        ]
        system_ids = {entity.get("id") for entity in systems}
        systems_with_neighbours = [
            entity for entity in systems
            if entity.get("stellar_neighbours")
        ]

        self.assertGreaterEqual(len(systems), 39)
        self.assertGreaterEqual(len(systems_with_neighbours), 25)
        self.assertEqual(
            [
                {"distance_ly": 9.08, "system": "system_leskim_system"},
                {"distance_ly": 12.71, "system": "system_oka_system"},
                {"distance_ly": 4.24, "system": "system_p_taurini_system"},
                {"distance_ly": 8.25, "system": "system_ross_system"},
                {"distance_ly": 11.74, "system": "system_tau_ceti_system"},
            ],
            model.get_entity("system_sol").get("stellar_neighbours"),
        )
        self.assertEqual(
            [
                {"distance_ly": 7.41, "system": "loc_shinogo_system"},
                {"distance_ly": 8.25, "system": "system_sol"},
            ],
            model.get_entity("system_ross_system").get("stellar_neighbours"),
        )
        self.assertEqual(
            "system_ross_system",
            model.get_entity("star_ross_system_primary").get("parent_location"),
        )
        self.assertEqual(
            "system_ross_system",
            model.get_entity("star_ross_system_primary").get("star_system"),
        )

        referenced_neighbour_ids = {
            row.get("system")
            for entity in systems
            for row in (entity.get("stellar_neighbours") or [])
            if isinstance(row, dict)
        }
        self.assertEqual(set(), referenced_neighbour_ids - system_ids)

    def test_referenced_project_assets_exist(self):
        model = WorldModel()
        missing = []

        def collect_asset_refs(value):
            if isinstance(value, str):
                return re.findall(r"assets/[^\s'\"\]]+", value)
            if isinstance(value, dict):
                refs = []
                for item in value.values():
                    refs.extend(collect_asset_refs(item))
                return refs
            if isinstance(value, list):
                refs = []
                for item in value:
                    refs.extend(collect_asset_refs(item))
                return refs
            return []

        for entity in model.loader.entities.values():
            for asset_ref in collect_asset_refs(entity):
                asset_path = PROJECT_ROOT / asset_ref
                if not asset_path.exists():
                    missing.append(f"{entity.get('id')} -> {asset_ref}")
        self.assertEqual([], missing)

    def test_ontology_repository_loads_entities_and_schemas(self):
        repository = OntologyRepository.from_owl(PROJECT_ROOT / "ontology" / "index0.owl")
        self.assertGreaterEqual(len(repository.entities), 1300)
        self.assertGreaterEqual(len(repository.get_dataset("schemas")), 30)

    def test_system_bodies_with_location_records_are_canonical_locations(self):
        model = WorldModel()
        self.assertEqual([], model.loader.datasets.get("systems", []))
        self.assertEqual("planet_earth", model.get_entity("body_earth").get("id"))

    def test_spatial_feature_projection_includes_state_and_quarter_locations(self):
        entities = [
            {"id": "loc_region", "location_class": "region", "geometry": {"type": "polygon"}},
            {"id": "loc_state", "location_class": "state", "geometry": {"type": "polygon"}},
            {"id": "loc_quarter", "location_class": "quarter", "layer_kind": "districts"},
            {"id": "loc_building", "location_class": "building", "geometry": {"type": "polygon"}},
            {"id": "loc_city", "location_class": "city"},
        ]
        model = WorldModel.__new__(WorldModel)
        model.loader = SimpleNamespace(get_dataset=lambda dataset_name: entities if dataset_name == "locations" else [])

        spatial_ids = {entity["id"] for entity in model.get_entities_by_dataset("spatial_features")}

        self.assertEqual({"loc_region", "loc_state", "loc_quarter"}, spatial_ids)


if __name__ == "__main__":
    unittest.main()
