import re
import unittest
from pathlib import Path

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
        schema_path = PROJECT_ROOT / "schemas" / "schema_cities.yaml"
        schema_text = schema_path.read_text(encoding="utf-8")
        self.assertNotIn("FULL DIFF", schema_text)
        self.assertNotIn("NEW FILE", schema_text)
        self.assertRegex(schema_text, r"(?m)^schema:\s*cities\s*$")

    def test_referenced_project_assets_exist(self):
        missing = []
        for entry_path in (PROJECT_ROOT / "entries").rglob("*.yaml"):
            entry_text = entry_path.read_text(encoding="utf-8")
            for asset_ref in re.findall(r"assets/[^\s'\"\]]+", entry_text):
                asset_path = PROJECT_ROOT / asset_ref
                if not asset_path.exists():
                    missing.append(f"{entry_path.relative_to(PROJECT_ROOT)} -> {asset_ref}")
        self.assertEqual([], missing)

    def test_yaml_repository_files_parse_when_pyyaml_is_available(self):
        try:
            import yaml
        except ModuleNotFoundError:
            self.skipTest("PyYAML is not installed in this interpreter")

        for folder_name in ("schemas", "entries"):
            for yaml_path in (PROJECT_ROOT / folder_name).rglob("*.yaml"):
                with self.subTest(path=str(yaml_path.relative_to(PROJECT_ROOT))):
                    with yaml_path.open("r", encoding="utf-8") as handle:
                        yaml.safe_load(handle)

    def test_system_bodies_with_location_records_are_canonical_locations(self):
        try:
            import yaml
        except ModuleNotFoundError:
            self.skipTest("PyYAML is not installed in this interpreter")

        locations = yaml.safe_load((PROJECT_ROOT / "entries" / "locations.yaml").read_text(encoding="utf-8")) or []
        systems = yaml.safe_load((PROJECT_ROOT / "entries" / "systems.yaml").read_text(encoding="utf-8")) or []
        location_ids = {entry.get("id") for entry in locations if isinstance(entry, dict)}
        duplicate_systems = [
            entry.get("id")
            for entry in systems
            if isinstance(entry, dict) and entry.get("location_entity") in location_ids
        ]

        self.assertEqual([], duplicate_systems)

        model = WorldModel()
        self.assertEqual("planet_earth", model.get_entity("body_earth").get("id"))


if __name__ == "__main__":
    unittest.main()
