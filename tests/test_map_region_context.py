import unittest
from types import SimpleNamespace
from unittest.mock import patch

from simulations.map.map_simulation import MapSimulation
from simulations.world_gen.coastal_geomorphology import COASTAL_MODEL_VERSION
from simulations.world_gen.heightmap import refresh_heightmap_derivatives
from world.simulation_context import SimulationContext


class _World:
    def __init__(self, entities):
        self.entities = {entity["id"]: entity for entity in entities}
        self.repository_revision = 0
        self.loader = SimpleNamespace(
            entities=self.entities,
            datasets={"locations": list(self.entities.values())},
            persist_entity=self.persist_entity,
            set_relation=self.set_relation,
            remove_relation=self.remove_relation,
            set_literal=self.set_literal,
            save_changed_dataset_files=lambda _changed: None,
        )

    def get_entity(self, entity_id):
        return self.entities.get(entity_id)

    def get_dataset(self, dataset_name):
        return list(self.entities.values()) if dataset_name == "locations" else []

    def get_active_locations(self, _year):
        return list(self.entities.values())

    def persist_entity(self, entity, previous_entity_id=None):
        self.entities[entity["id"]] = entity
        return True

    @staticmethod
    def _ids(value):
        if isinstance(value, str):
            return [value] if value else []
        if isinstance(value, list):
            return [item for item in value if isinstance(item, str)]
        return []

    def set_relation(self, source_id, field_name, target_id, reciprocal_field=None, persist=True):
        source = self.entities.get(source_id)
        target = self.entities.get(target_id)
        if not isinstance(source, dict) or not isinstance(target, dict):
            return set()
        ids = self._ids(source.get(field_name))
        if target_id not in ids:
            source[field_name] = ids + [target_id]
        return {source_id}

    def remove_relation(self, source_id, field_name, target_id, reciprocal_field=None, persist=True):
        source = self.entities.get(source_id)
        if not isinstance(source, dict):
            return set()
        source[field_name] = [item for item in self._ids(source.get(field_name)) if item != target_id]
        return {source_id}

    def set_literal(self, entity_id, field_name, value, persist=True):
        entity = self.entities.get(entity_id)
        if not isinstance(entity, dict):
            return set()
        entity[field_name] = value
        return {entity_id}


def _planet():
    return {
        "id": "earth",
        "type": "location",
        "_dataset": "locations",
        "location_class": "planet",
        "bounds": {"type": "bbox", "min_x": -180, "max_x": 180, "min_y": -90, "max_y": 90},
        "heightmap_model": {
            "sea_level_m": 0,
            "sample_grid": {"width": 3, "height": 3, "rows": [[-10, 0, 10], [-5, 5, 15], [0, 10, 20]]},
        },
        "water_cycle_model": {
            "climate_zones": [{"id": "temperate_wet", "color": [82, 142, 104]}],
            "climate_grid": {
                "rows": [["ocean", "temperate_wet", "temperate_wet"]] * 3,
                "elevation_rows": [[-10, 0, 10], [-5, 5, 15], [0, 10, 20]],
            },
        },
    }


def _add_coast(planet):
    planet["heightmap_model"]["wrap_x"] = False
    planet["heightmap_model"]["coverage"] = "regional_patch"
    planet["heightmap_model"]["sample_grid"]["wrap_x"] = False
    planet["heightmap_model"] = refresh_heightmap_derivatives(
        planet["heightmap_model"], inherited_sea_level_m=0.0,
    )
    planet["coastal_geomorphology_model"] = {
        "status": "coastal_geomorphology_resolved",
        "model_version": COASTAL_MODEL_VERSION,
        "source_heightfield_fingerprint": planet["heightmap_model"]["source_heightfield_fingerprint"],
        "summary": {"dominant_assemblages": [{"id": "clastic_beach", "length_km": 42.0}]},
        "segments": [{
            "id": "coast_fixture",
            "primary_assemblage": "clastic_beach",
            "display_color": [230, 204, 126],
            "confidence": 0.8,
            "measurements": {"centroid_uv": [0.5, 0.5]},
            "geometry": {"points": [[0.46, 0.48], [0.50, 0.50], [0.54, 0.52]]},
        }],
    }
    return planet


class MapRegionContextTests(unittest.TestCase):
    def test_authored_region_map_can_generate_its_inherited_full_footprint(self):
        earth = _planet()
        region = {
            "id": "authored_region",
            "type": "location",
            "_dataset": "locations",
            "location_class": "region",
            "parent_location": "earth",
            "parents": ["earth"],
            "bounds": {
                "type": "polygon",
                "points": [(-20, -10), (20, -10), (20, 10), (-20, 10)],
            },
        }
        world = _World([earth, region])
        sim = MapSimulation(SimulationContext(2400, region["id"], world))
        generated = {
            "id": "refined_authored_region_lod1_test",
            "refinement_parent_map_id": region["id"],
        }

        with patch(
            "simulations.world_gen.regional_refinement.generate_refined_region",
            return_value=generated,
        ) as generate:
            self.assertTrue(sim.can_regenerate_current_region())
            result = sim.regenerate_current_region()

        self.assertIs(generated, result)
        generation_parent = generate.call_args.args[1]
        self.assertEqual(region["id"], generation_parent["id"])
        self.assertEqual(
            "parent_surface_inherited",
            generation_parent["heightmap_model"]["status"],
        )
        self.assertEqual(
            {"min_x": -20.0, "max_x": 20.0, "min_y": -10.0, "max_y": 10.0},
            generate.call_args.args[2],
        )

    def test_authored_region_refinement_is_composited_into_region_and_planet_maps(self):
        earth = _planet()
        region = {
            "id": "authored_region",
            "type": "location",
            "_dataset": "locations",
            "location_class": "region",
            "parent_location": "earth",
            "parents": ["earth"],
            "bounds": {
                "type": "bbox",
                "min_x": -20,
                "max_x": 20,
                "min_y": -10,
                "max_y": 10,
            },
        }
        refinement = {
            "id": "refined_authored_region_lod1_test",
            "type": "location",
            "_dataset": "locations",
            "location_class": "generated_region",
            "location_role": "map_refinement_region",
            "refinement_parent_map_id": region["id"],
            "refinement_root_planet_id": "earth",
            "map_detail_level": 1,
            "refinement_revision": 3,
            "bounds": {
                "type": "bbox",
                "min_x": -20,
                "max_x": 20,
                "min_y": -10,
                "max_y": 10,
            },
            "heightmap_model": {
                "sample_grid": {
                    "width": 2,
                    "height": 2,
                    "rows": [[0, 1], [1, 0]],
                },
            },
            "water_cycle_model": {},
        }
        world = _World([earth, region, refinement])

        region_models = MapSimulation(
            SimulationContext(2400, region["id"], world)
        )._refined_region_models()
        planet_models = MapSimulation(
            SimulationContext(2400, earth["id"], world)
        )._refined_region_models()

        self.assertEqual([refinement["id"]], [row["entity_id"] for row in region_models])
        self.assertEqual([refinement["id"]], [row["entity_id"] for row in planet_models])

    def test_generated_region_can_regenerate_itself_from_its_parent_footprint(self):
        earth = _planet()
        region = {
            "id": "refined_earth_lod1_test",
            "type": "location",
            "_dataset": "locations",
            "location_class": "generated_region",
            "location_role": "map_refinement_region",
            "refinement_parent_map_id": "earth",
            "parent_location": "earth",
            "refinement_seed_suffix": "original-region-seed",
            "map_detail_level": 1,
            "map_detail_profile": {"label": "Macroregion"},
            "bounds": {
                "type": "bbox",
                "min_x": -20,
                "max_x": 20,
                "min_y": -10,
                "max_y": 10,
            },
            "heightmap_model": {
                "sample_grid": {
                    "width": 2,
                    "height": 2,
                    "rows": [[0, 1], [1, 0]],
                },
            },
        }
        world = _World([earth, region])
        sim = MapSimulation(SimulationContext(2400, region["id"], world))
        regenerated = {**region, "refinement_revision": 2}

        with patch(
            "simulations.world_gen.regional_refinement.generate_refined_region",
            return_value=regenerated,
        ) as generate:
            self.assertTrue(sim.can_regenerate_current_region())
            result = sim.regenerate_current_region()

        self.assertIs(regenerated, result)
        parent_arg = generate.call_args.args[1]
        self.assertEqual("earth", parent_arg["id"])
        self.assertEqual(region["bounds"], {"type": "bbox", **generate.call_args.args[2]})
        self.assertEqual(
            "original-region-seed",
            generate.call_args.kwargs["seed_suffix"],
        )

    def test_selected_material_occurrence_anchors_the_next_refinement(self):
        earth = _planet()
        occurrence = {
            "id": "occurrence_fayalite_focus",
            "material_id": "mat_fayalite",
            "name": "Fayalite",
            "center": {"x": 0.75, "y": 0.25},
            "estimated_radius_m": 1200.0,
            "deposit_body": {
                "geometry": {
                    "bounding_radius_m": 1200.0,
                    "footprint_vertices": [[1, 0], [0, 1], [-1, 0], [0, -1]],
                },
            },
        }
        earth["regional_material_model"] = {
            "occurrences": [occurrence],
        }
        world = _World([earth])
        sim = MapSimulation(SimulationContext(2400, earth["id"], world))
        sim.selected_material_occurrence_id = occurrence["id"]
        generated = {"id": "focused_child"}

        with (
            patch.object(
                sim,
                "_visible_refinement_bounds",
                return_value={
                    "min_x": -50.0,
                    "max_x": 50.0,
                    "min_y": -25.0,
                    "max_y": 25.0,
                },
            ),
            patch(
                "simulations.world_gen.regional_refinement.generate_refined_region",
                return_value=generated,
            ) as generate,
        ):
            result = sim.regenerate_visible_region(
                SimpleNamespace(), 1920, 1080,
            )

        self.assertIs(generated, result)
        self.assertEqual(
            {
                "min_x": 40.0,
                "max_x": 140.0,
                "min_y": -70.0,
                "max_y": -20.0,
            },
            generate.call_args.args[2],
        )
        self.assertEqual(
            occurrence["id"],
            generate.call_args.kwargs["focus_occurrence_id"],
        )

    def test_surface_derivative_validation_is_reused_between_frames(self):
        earth = _add_coast(_planet())
        world = _World([earth])

        with patch(
            "simulations.map.map_simulation.ensure_coastal_model_current",
            return_value=False,
        ) as ensure_current:
            sim = MapSimulation(SimulationContext(2400, "earth", world))
            sim.get_heightmap_base_layer()
            sim.get_heightmap_base_layer()

        self.assertEqual(1, ensure_current.call_count)

    def test_coastal_layer_uses_persisted_segments_and_crops_for_child_regions(self):
        earth = _add_coast(_planet())
        region = {
            "id": "region", "type": "location", "_dataset": "locations",
            "location_class": "region", "parent_location": "earth", "parents": ["earth"],
            "map_context_parent": "earth",
            "bounds": {"type": "polygon", "points": [(-20, -10), (20, -10), (20, 10), (-20, 10)]},
        }
        world = _World([earth, region])
        root_sim = MapSimulation(SimulationContext(2400, "earth", world))
        child_sim = MapSimulation(SimulationContext(2400, "region", world))

        self.assertIn(root_sim.COASTAL_LAYER_KIND, root_sim.get_available_layer_kinds())
        root_sim.set_active_layer_kind(root_sim.COASTAL_LAYER_KIND)
        self.assertTrue(root_sim._build_coastal_layers()[0]["entity_id"].startswith("coast_"))
        self.assertIn(child_sim.COASTAL_LAYER_KIND, child_sim.get_available_layer_kinds())
        child_layer = child_sim._build_coastal_layers()[0]
        self.assertTrue(all(0.0 <= point[0] <= 40.0 for point in child_layer["points"]))

    def test_heightmap_base_carries_material_probabilities_into_normal_map_rendering(self):
        earth = _planet()
        earth["material_heatmap_model"] = {
            "composite_layer": {
                "bundle_path": "assets/maps/material_heatmaps/earth.i0r",
                "bundle_layer_id": "composite",
            },
        }
        world = _World([earth])
        sim = MapSimulation(SimulationContext(2400, "earth", world))

        base_layer = sim.get_heightmap_base_layer()

        self.assertEqual("composite", base_layer["surface_material_layer"]["bundle_layer_id"])
        self.assertEqual(92, base_layer["surface_material_opacity"])

    def test_polygon_region_inherits_a_cropped_parent_surface_and_climate_layer(self):
        earth = _planet()
        region = {
            "id": "region",
            "type": "location",
            "_dataset": "locations",
            "location_class": "region",
            "parent_location": "earth",
            "parents": ["earth"],
            "map_context_parent": "earth",
            "bounds": {"type": "polygon", "points": [(-20, -10), (20, -10), (20, 10), (-20, 10)]},
        }
        world = _World([earth, region])
        sim = MapSimulation(SimulationContext(2400, "region", world))

        self.assertIn(sim.HEIGHTMAP_LAYER_KIND, sim.get_available_layer_kinds())
        self.assertIn(sim.TRUE_COLOR_LAYER_KIND, sim.get_available_layer_kinds())
        self.assertIn(sim.HYDROLOGY_LAYER_KIND, sim.get_available_layer_kinds())
        true_color_layer = sim.get_heightmap_base_layer(render_mode="true_color")
        self.assertEqual("true_color", true_color_layer["render_mode"])
        self.assertEqual(
            "planet-true-color-v4",
            true_color_layer["true_color_model"]["model_version"],
        )
        base_layer = sim.get_heightmap_base_layer()
        hydro_layer = sim._build_hydrology_layers()[0]

        self.assertEqual("parent_surface_inherited", base_layer["heightmap_model"]["status"])
        self.assertEqual((40.0, 20.0), (base_layer["width_world"], base_layer["height_world"]))
        self.assertEqual("parent_climate_inherited", hydro_layer["water_cycle_model"]["status"])
        self.assertEqual("temperate_wet", hydro_layer["water_cycle_model"]["climate_grid"]["rows"][0][0])

    def test_reparenting_a_map_region_updates_the_new_parents_constituents(self):
        earth = _planet()
        parent = {
            "id": "country",
            "type": "location",
            "_dataset": "locations",
            "location_class": "country",
            "parent_location": "earth",
            "parents": ["earth"],
            "bounds": {"type": "polygon", "points": [(-30, -20), (30, -20), (30, 20), (-30, 20)]},
        }
        region = {
            "id": "region",
            "type": "location",
            "_dataset": "locations",
            "location_class": "region",
            "parent_location": "earth",
            "parents": ["earth"],
            "bounds": {"type": "polygon", "points": [(-10, -10), (10, -10), (10, 10), (-10, 10)]},
        }
        earth["constituents"] = ["region", "country"]
        world = _World([earth, parent, region])
        sim = MapSimulation(SimulationContext(2400, "earth", world))

        self.assertTrue(sim._update_location_parent("region", "country"))
        self.assertEqual("country", region["parent_location"])
        self.assertEqual(["country"], region["parents"])
        self.assertEqual("country", region["map_context_parent"])
        self.assertIn("region", parent["constituents"])
        self.assertNotIn("region", earth["constituents"])

    def test_left_drag_pans_without_changing_projection_focus(self):
        sim = MapSimulation.__new__(MapSimulation)
        sim.map_projection_focus_x = 0.25
        sim.map_projection_focus_y = -0.1
        sim.map_projection_dragging = False
        sim.map_projection_drag_start = None
        sim.hover_entity_id = None
        sim.hover_spatial_feature_id = None
        sim.hover_screen_pos = None
        camera = SimpleNamespace(x=10.0, y=20.0, zoom=2.0)

        sim._begin_camera_drag((100, 100), camera)
        self.assertFalse(sim.map_projection_dragging)
        self.assertTrue(sim._update_camera_drag((120, 110), camera))

        self.assertEqual((0.25, -0.1), (sim.map_projection_focus_x, sim.map_projection_focus_y))
        self.assertEqual((0.0, 15.0), (camera.x, camera.y))

    def test_double_click_refocus_centres_the_globe_at_the_chosen_point(self):
        earth = _planet()
        world = _World([earth])
        sim = MapSimulation(SimulationContext(2400, "earth", world))
        camera = SimpleNamespace(x=35.0, y=15.0, width=100.0, height=100.0, zoom=1.0)

        self.assertTrue(sim._refocus_map_at_screen_point(camera, (80.0, 60.0)))

        self.assertNotEqual((0.0, 0.0), (sim.map_projection_focus_x, sim.map_projection_focus_y))
        self.assertEqual((0.0, 0.0), (camera.x, camera.y))


if __name__ == "__main__":
    unittest.main()
