"""Assets read the same from loose files and from packs."""

import gzip
import json
import tempfile
import unittest
from pathlib import Path

import pygame

from engine import asset_files
from tools.pack_assets import build_packs, unpack


class AssetPacksTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        source = self.root / "assets"
        (source / "illustrations").mkdir(parents=True)
        (source / "plants" / "blueprints").mkdir(parents=True)
        (source / "plants" / "snapshots").mkdir(parents=True)
        surface = pygame.Surface((3, 2))
        surface.fill((10, 20, 30))
        pygame.image.save(surface, str(source / "illustrations" / "leaf_pixel.png"))
        with gzip.open(source / "plants" / "blueprints" / "spec_x.json.gz", "wt", encoding="utf-8") as handle:
            json.dump({"id": "spec_x"}, handle)
        (source / "plants" / "snapshots" / "cache.json.gz").write_bytes(b"cache")
        (source / "wood.json").write_text('{"bark": 1}', encoding="utf-8")
        self.outside = self.root / "outside.txt"
        self.outside.write_text("plain", encoding="utf-8")
        self.report = {row["pack"]: row for row in build_packs(source, self.root / "packs")}
        asset_files.use_packs(self.root / "packs")

    def tearDown(self):
        asset_files.use_loose()
        self.temp.cleanup()

    def test_one_pack_per_category_without_caches(self):
        self.assertEqual(set(self.report), {"illustrations.pak", "plants.pak", "common.pak"})
        self.assertEqual(self.report["plants.pak"]["files"], 1)

    def test_assets_read_from_packs_by_their_ontology_path(self):
        image = asset_files.load_image("assets/illustrations/leaf_pixel.png")
        self.assertEqual(image.get_size(), (3, 2))
        self.assertEqual(tuple(image.get_at((0, 0)))[:3], (10, 20, 30))
        with asset_files.open_gzip_text("assets/plants/blueprints/spec_x.json.gz") as handle:
            self.assertEqual(json.load(handle), {"id": "spec_x"})
        self.assertEqual(json.loads(asset_files.read_text(asset_files.ASSET_ROOT / "wood.json")), {"bark": 1})
        self.assertIsNotNone(asset_files.revision("assets/wood.json"))

    def test_missing_entry_is_a_missing_file(self):
        self.assertFalse(asset_files.exists("assets/illustrations/none.png"))
        self.assertIsNone(asset_files.revision("assets/illustrations/none.png"))
        with self.assertRaises(FileNotFoundError):
            asset_files.read_bytes("assets/plants/snapshots/cache.json.gz")

    def test_packed_run_does_not_read_loose_assets(self):
        loose = "assets/plants/preview/species_preview_wood.json"
        self.assertFalse(asset_files.exists(loose))
        asset_files.use_loose()
        self.assertTrue(asset_files.exists(loose))

    def test_paths_outside_assets_stay_plain_files(self):
        self.assertEqual(asset_files.read_text(self.outside), "plain")

    def test_same_files_give_the_same_pack(self):
        build_packs(self.root / "assets", self.root / "again")
        self.assertEqual((self.root / "packs" / "plants.pak").read_bytes(), (self.root / "again" / "plants.pak").read_bytes())

    def test_unchanged_files_leave_the_pack_alone(self):
        rows = build_packs(self.root / "assets", self.root / "packs")
        self.assertFalse(any(row["changed"] for row in rows))

    def test_unpack_restores_files_and_keeps_local_edits(self):
        restored = self.root / "restored"
        result = unpack(self.root / "packs", restored)
        self.assertIn("wood.json", result["written"])
        self.assertEqual((self.root / "assets" / "plants" / "blueprints" / "spec_x.json.gz").read_bytes(),
                         (restored / "plants" / "blueprints" / "spec_x.json.gz").read_bytes())
        (restored / "wood.json").write_text("edited", encoding="utf-8")
        self.assertEqual(unpack(self.root / "packs", restored)["kept"], ["wood.json"])
        self.assertEqual((restored / "wood.json").read_text(encoding="utf-8"), "edited")
        unpack(self.root / "packs", restored, force=True)
        self.assertEqual((restored / "wood.json").read_text(encoding="utf-8"), '{"bark": 1}')


if __name__ == "__main__":
    unittest.main()
