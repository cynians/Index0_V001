"""Behavior checks for element-owned material bodies."""

import unittest
import time
from unittest.mock import Mock, patch
from pathlib import Path

from simulations.world_gen import natural_materials
from simulations.world_gen.geochemical_placement import (
    _body_card,
    _local_element_profiles,
    derive_planetary_material_placements,
    occurrence_entity,
    regional_material_inventory,
)


def _remove_empty_output_tree(root):
    for path in (
        root / "assets/maps/material_heatmaps",
        root / "assets/maps",
        root / "assets",
        root,
    ):
        try:
            path.rmdir()
        except OSError:
            pass


def _province(province_id, center_u, *, silicon, copper=0.0, body_id=None, material_id="mat_silicate"):
    return {
        "id": province_id,
        "setting_id": "continental_platform",
        "center_u": center_u,
        "center_v": 0.5,
        "center_x": center_u,
        "center_y": 0.5,
        "area_fraction": 0.5,
        "material_id": material_id,
        "body_id": body_id,
        "elements": {"O": 55.0, "Si": silicon, "Cu": copper},
    }


class GeochemicalPlacementTests(unittest.TestCase):
    def setUp(self):
        self.materials = {
            "mat_silicate": {
                "id": "mat_silicate",
                "required_element_thresholds": {"Si": 10},
                "mechanical_class": "resistant_silicate",
            },
            "mat_copper": {
                "id": "mat_copper",
                "required_element_thresholds": {"Cu": 0.5},
            },
        }
        self.catalog_patch = patch.object(natural_materials, "MATERIAL_BY_ID", self.materials)
        self.catalog_patch.start()
        self.addCleanup(self.catalog_patch.stop)
        self.candidates = {
            "likely_materials": [
                {"material_id": "mat_copper", "name": "Copper rock",
                 "spatial_representation": "bedrock_unit", "prevalence_score": 1.0},
                {"material_id": "mat_silicate", "name": "Silicate rock",
                 "spatial_representation": "bedrock_unit", "prevalence_score": 0.7},
            ]
        }
        self.provinces = {
            "status": "generated",
            "provinces": [
                _province("province_west", 0.25, silicon=40.0, copper=0.8, body_id="geounit_test_01"),
                _province("province_east", 0.75, silicon=30.0, copper=0.0, body_id="geounit_test_02"),
            ],
        }

    def test_element_partition_conserves_the_crust_inventory(self):
        global_elements = {"O": 50.0, "Si": 28.0, "Fe": 5.0, "Mg": 2.0}
        sources = [
            {"id": "continental", "area_fraction": 0.6, "continentality": 0.95},
            {"id": "oceanic", "area_fraction": 0.4, "continentality": 0.1},
        ]
        profiles = _local_element_profiles(global_elements, sources, "stable-seed")
        for symbol, global_value in global_elements.items():
            reconstructed = sum(
                source["area_fraction"] * profile[symbol]
                for source, profile in zip(sources, profiles)
            )
            self.assertAlmostEqual(global_value, reconstructed, places=8)
        self.assertGreater(profiles[0]["Si"], profiles[1]["Si"])
        self.assertGreater(profiles[1]["Fe"], profiles[0]["Fe"])

    def test_prior_supplies_relief_retention_without_cards(self):
        tectonics = {"plates": [], "boundary_segments": []}
        model, cards = derive_planetary_material_placements(
            "planet_test", {"major_elements": [{"symbol": "Si", "abundance_percent": 30}]},
            self.candidates, tectonics, "stable-seed",
        )
        self.assertEqual("tectonic_prior", model["status"])
        self.assertEqual([], cards)
        self.assertEqual([], model["body_ids"])
        rows = model["relief_retention_rows"]
        self.assertGreater(len(rows), 8)
        self.assertTrue(all(0.94 <= value <= 1.06 for row in rows for value in row))

    def test_occurrence_has_card_identity(self):
        occurrence = occurrence_entity("region_a", {
            "id": "deposit_a", "name": "Copper prospect", "material_id": "mat_copper",
            "occurrence_role": "ore_or_mineral_prospect",
        })
        self.assertEqual("material_deposit", occurrence["location_class"])
        self.assertEqual("region_a", occurrence["parent_location"])
        self.assertEqual("deposit_a", occurrence["id"])

    def test_region_inherits_the_chemistry_of_provinces_in_its_footprint(self):
        west = regional_material_inventory(
            self.candidates, self.provinces,
            {"min_u": 0.20, "max_u": 0.30, "min_v": 0.45, "max_v": 0.55},
        )
        east = regional_material_inventory(
            self.candidates, self.provinces,
            {"min_u": 0.70, "max_u": 0.80, "min_v": 0.45, "max_v": 0.55},
        )
        straddling = regional_material_inventory(
            self.candidates, self.provinces,
            {"min_u": 0.20, "max_u": 0.80, "min_v": 0.45, "max_v": 0.55},
        )
        self.assertEqual(["province_west"], west["source_geochemical_province_ids"])
        self.assertEqual(["province_east"], east["source_geochemical_province_ids"])
        self.assertIn("mat_copper", [c["material_id"] for c in west["likely_materials"]])
        self.assertNotIn("mat_copper", [c["material_id"] for c in east["likely_materials"]])
        # A region spanning both provinces keeps the chemistry of each.
        self.assertEqual(
            {"province_west", "province_east"},
            set(straddling["source_geochemical_province_ids"]),
        )
        self.assertIn("mat_copper", [c["material_id"] for c in straddling["likely_materials"]])
        self.assertAlmostEqual(35.0, straddling["element_profile"]["Si"])

    def test_generated_unit_is_a_pickable_map_card(self):
        from tests.test_building_sim import FakeWorldModel
        from simulations.map.map_simulation import MapSimulation
        from world.simulation_context import SimulationContext

        candidate = self.candidates["likely_materials"][1]
        cards = [
            _body_card("planet_map_test", province, candidate)
            for province in self.provinces["provinces"]
        ]
        planet = {
            "id": "planet_map_test", "name": "Map test", "type": "location",
            "_dataset": "locations", "location_class": "planet",
            "bounds": {"type": "bbox", "min_x": -180, "max_x": 180,
                       "min_y": -90, "max_y": 90},
            "geochemical_material_model": self.provinces,
            "material_heatmap_model": {
                "status": "generated",
                "composite_layer": {"name": "Materials", "image_path": "map.png"},
                "layers": [],
            },
        }
        world = FakeWorldModel([planet, *cards])
        sim = MapSimulation(SimulationContext(
            year=2400, root_entity_id=planet["id"], world_model=world,
        ))
        self.assertTrue(sim.set_active_layer_kind(sim.MATERIAL_HEATMAP_LAYER_KIND))
        markers = [layer for layer in sim.get_layers() if layer.get("shape") == "marker"]
        self.assertEqual(len(cards), len(markers))
        for marker in markers:
            self.assertTrue(marker["pickable"])
            self.assertTrue(sim._can_open_location_inspector(marker["entity_id"]))
        sim._select_picked_layer(markers[0], (100, 100), record_click=True)
        sim._select_picked_layer(markers[0], (100, 100), record_click=True)
        self.assertEqual(
            {"kind": "location", "id": markers[0]["entity_id"]},
            sim._pending_inspector_target,
        )

    def test_soil_samples_coarser_water_and_province_chemistry(self):
        from simulations.world_gen.regolith_soils import derive_regolith_soil_model

        provinces = [
            {"id": "calcareous", "elements": {"Ca": 5.0, "S": 0.0}},
            {"id": "sulfidic", "elements": {"Ca": 0.0, "S": 1.5}},
        ]
        planet = {"geochemical_material_model": {
            "provinces": provinces,
            # Global UV index raster: west half calcareous, east half sulfidic.
            "province_index_rows": [[0, 0, 1, 1, 1]] * 3,
        }}
        heightmap = {"sample_grid": {"rows": [[100] * 4 for _ in range(4)]}}
        water = {
            "climate_grid": {
                "temperature_rows_k": [[290, 290], [290, 290]],
                "annual_precipitation_rows_mm": [[500, 500], [500, 500]],
            },
            # The coarser water grid floods only the north-west cells.
            "surface_water_grid": {"water_presence_rows": [[True, False], [False, False]]},
        }
        soil = derive_regolith_soil_model(planet, heightmap, water, {}, {
            "element_profile": {"Ca": 0, "S": 0},
        })
        self.assertEqual("abiotic_soils_resolved", soil["status"])
        self.assertEqual(0.0, soil["grid"]["soil_depth_m_rows"][0][0])
        self.assertGreater(soil["grid"]["soil_depth_m_rows"][0][-1], 0.0)
        # On land, the calcareous parent buffers pH upward and the sulfidic
        # parent acidifies it.
        # (The last column sits on the u = 1 seam, which wraps to u = 0.)
        depth_rows = soil["grid"]["soil_depth_m_rows"]
        self.assertGreater(depth_rows[2][1], 0.0)
        self.assertGreater(depth_rows[2][2], 0.0)
        ph_rows = soil["grid"]["ph_rows"]
        self.assertGreater(ph_rows[2][1], ph_rows[2][2])

    def test_generated_cards_share_one_ontology_commit(self):
        from world.entity_loader import EntityLoader

        loader = EntityLoader.__new__(EntityLoader)
        loader.use_ontology = True
        loader.datasets = {"locations": []}
        loader.entities = {}
        loader._persistent_store = Mock()
        loader._persistent_store.persist_entities.return_value = True
        loader._load_deletion_overrides = Mock(return_value=set())
        loader._write_deletion_overrides = Mock(return_value=True)
        cards = [
            {"id": "body_a", "type": "location", "_dataset": "locations"},
            {"id": "body_b", "type": "location", "_dataset": "locations"},
        ]
        self.assertTrue(loader.persist_entities(cards))
        loader._persistent_store.persist_entities.assert_called_once_with(cards)
        self.assertEqual({"body_a", "body_b"}, set(loader.entities))

    def test_regenerated_bodies_are_not_retired_while_vanished_ones_are(self):
        from simulations.world_gen.world_gen_sim import WorldGenSimulation

        sim = WorldGenSimulation()
        kept = {"id": "geounit_a", "type": "location"}
        vanished = {"id": "geocover_b", "type": "location"}
        planet = {
            "constituents": ["geounit_a", "geocover_b"],
            "_pending_generated_material_cards": [kept, vanished],
        }
        # The pre-heightfield prior retires every body...
        sim._retire_obsolete_material_cards(planet, ["geounit_a", "geocover_b"], [])
        self.assertEqual({"geounit_a", "geocover_b"}, set(planet["_obsolete_generated_material_body_ids"]))
        # ...and the LOD0 product regenerates the one that still forms.
        sim._queue_material_cards(planet, [kept])
        self.assertEqual(["geocover_b"], planet["_obsolete_generated_material_body_ids"])
        self.assertEqual(["geounit_a"], planet["constituents"])
        self.assertEqual([kept], planet["_pending_generated_material_cards"])


class GeneratedPlanetPlacementTests(unittest.TestCase):
    def test_worldgen_persists_bodies_and_renders_from_them(self):
        from world.world_model import WorldModel
        from tests.test_world_gen_orbit_clicks import FakeWorldModel
        from simulations.world_gen.material_lod import MATERIAL_LOD_MODEL_VERSION
        from simulations.world_gen.world_gen_sim import WorldGenSimulation

        # Initialize the real ontology-backed material catalog, then keep the
        # generated world isolated in a fake loader and one known output path.
        WorldModel()
        output_root = Path(__file__).parent / "generated_material_output"
        output_root.mkdir(exist_ok=True)
        world = FakeWorldModel(entries_directory=output_root)
        sim = WorldGenSimulation(world, parent_system_id="system_alpha", year=2400)
        sim.worldgen_feedback_iterations = 2
        planet = {
            "id": "planet_geo_test", "name": "Geochemistry Test",
            "type": "location", "_dataset": "locations",
            "location_class": "planet", "star_system": "system_alpha",
            "semi_major_axis_m": sim.AU_M, "tags": ["world_gen_candidate"],
        }
        world.loader.entities[planet["id"]] = planet
        world.loader.datasets["locations"].append(planet)
        sim.selected_world_gen_planet_id = planet["id"]
        bundle = output_root / "assets/maps/material_heatmaps/planet_geo_test.i0r"
        try:
            self.assertTrue(sim._save_selected_planet_seed())
            self.assertTrue(sim._save_atmosphere_model())
            self.assertTrue(sim._save_interior_regime_model())
            terrain_start = time.perf_counter()
            self.assertTrue(sim._save_terrain_seed_model())
            terrain_elapsed = time.perf_counter() - terrain_start
            placement = planet["geochemical_material_model"]
            self.assertEqual("generated", placement["status"])
            self.assertGreaterEqual(len(placement["provinces"]), 2)
            self.assertGreaterEqual(len(placement["body_ids"]), 1)
            self.assertTrue(placement["relief_retention_rows"])
            self.assertTrue(placement["province_index_rows"])
            self.assertTrue(all(body_id in world.loader.entities for body_id in placement["body_ids"]))
            self.assertEqual(
                MATERIAL_LOD_MODEL_VERSION,
                planet["material_heatmap_model"]["model_version"],
            )
            self.assertTrue(bundle.exists())
            self.assertTrue(sim._save_water_cycle_model())
            for body_id in planet["geochemical_material_model"].get("cover_body_ids") or []:
                self.assertIn(body_id, world.loader.entities)
            print(f"terrain and material publishing: {terrain_elapsed:.2f}s")
        finally:
            bundle.unlink(missing_ok=True)
            _remove_empty_output_tree(output_root)


if __name__ == "__main__":
    unittest.main()
