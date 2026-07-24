import json
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch

from simulations.world_gen.headless_runner import HeadlessWorldGenConfig, run_isolated_headless_worldgen
from simulations.world_gen.storage_policy import WorldGenStoragePolicy, require_within
from simulations.world_gen.worldgen_bundle import (
    read_worldgen_bundle_json,
    validate_worldgen_bundle,
    write_worldgen_bundle,
)


@dataclass
class _Result:
    output_root: str
    planet_id: str
    input_contract_path: str
    summary_path: str
    planet_path: str
    regional_region_path: str = ""
    regional_materials_path: str = ""
    stage_screenshots: list = None
    layer_images: list = None
    regional_layer_images: list = None
    contact_sheet: str = ""
    regional_contact_sheet: str = ""


class WorldGenStorageTests(unittest.TestCase):
    def test_isolated_run_persists_only_one_bundle_and_cleans_temporary_repository(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            destination = project / "artifacts" / "worldgen" / "pinned" / "gas.i0wg"
            result = run_isolated_headless_worldgen(
                HeadlessWorldGenConfig(randomize_mode="gas_giant", randomizer_seed=44, render_outputs=False),
                bundle_path=destination,
                retention="pinned",
                project_root=project,
            )
            self.assertEqual(str(destination.resolve()), result.bundle_path)
            self.assertTrue(destination.is_file())
            cache_root = project / ".cache" / "worldgen"
            self.assertEqual([], list(cache_root.iterdir()))

    def test_isolated_run_cleans_temporary_repository_after_handled_failure(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            with patch("simulations.world_gen.headless_runner.HeadlessWorldGenRunner.run", side_effect=RuntimeError("fixture")):
                with self.assertRaises(RuntimeError):
                    run_isolated_headless_worldgen(project_root=project)
            self.assertEqual([], list((project / ".cache" / "worldgen").iterdir()))

    def test_bundle_is_single_validated_file_and_atomic_replacement_is_stable(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            run = root / "run"
            run.mkdir()
            for name, payload in (("input_contract.json", {"seed": "x"}), ("summary.json", {"ok": True}), ("planet.json", {"id": "planet_x"})):
                (run / name).write_text(json.dumps(payload), encoding="utf-8")
            result = _Result(
                output_root=str(run), planet_id="planet_x",
                input_contract_path=str(run / "input_contract.json"),
                summary_path=str(run / "summary.json"),
                planet_path=str(run / "planet.json"),
                stage_screenshots=[], layer_images=[], regional_layer_images=[],
            )
            destination = root / "retained" / "planet_x.i0wg"
            write_worldgen_bundle(destination, result=result)
            write_worldgen_bundle(destination, result=result)
            self.assertEqual([destination], list(destination.parent.glob("*.i0wg")))
            self.assertEqual("index0_worldgen_bundle", validate_worldgen_bundle(destination)["format"])
            self.assertEqual("planet_x", read_worldgen_bundle_json(destination, "planet.json")["id"])
            self.assertEqual([], list(destination.parent.glob("*.tmp-*")))

    def test_policy_rejects_cleanup_outside_generated_roots(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            policy = WorldGenStoragePolicy.for_project(temp_dir)
            with self.assertRaises(ValueError):
                policy.validate_generated_target(Path(temp_dir) / "world" / "entities.json")
            with self.assertRaises(ValueError):
                require_within(temp_dir, policy.diagnostic_cache_root)


if __name__ == "__main__":
    unittest.main()
