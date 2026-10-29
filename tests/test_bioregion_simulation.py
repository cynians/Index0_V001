import inspect
import unittest

from simulations.bioregion.bioregion_simulation import BioregionSimulation
from tools.author_biosphere_model import build_changes


class _World:
    def __init__(self, entities):
        self.entities = {entity["id"]: dict(entity) for entity in entities}

    def get_entity(self, entity_id):
        return self.entities.get(entity_id)

    def get_dataset(self, dataset_name):
        return [entity for entity in self.entities.values() if entity.get("_dataset") == dataset_name]

    def set_literal(self, entity_id, field_name, value, persist=True):
        entity = self.entities.get(entity_id)
        if entity is None:
            return set()
        entity[field_name] = value
        return {entity_id}


def _regolith_soil_model():
    return {
        "status": "abiotic_soils_resolved",
        "biosphere_contribution": "excluded_pending_separate_design",
        "dominant_soil_classes": [{"id": "weathered_mineral_soil", "land_fraction": 0.8}],
        "grid": {
            "width": 2, "height": 2,
            "soil_depth_m_rows": [[1.0, 1.2], [1.1, 1.3]],
            "porosity_rows": [[0.30, 0.32], [0.31, 0.33]],
            "relative_permeability_rows": [[0.50, 0.52], [0.51, 0.53]],
            "ph_rows": [[6.5, 6.6], [6.55, 6.62]],
            "salinity_index_rows": [[0.10, 0.11], [0.12, 0.13]],
        },
    }


def _build_world():
    location = {
        "id": "loc_test_patch", "_dataset": "locations", "type": "location",
        "location_class": "biosphere_patch",
        "name": "Test Patch",
        "material_heatmap_model": {"stub": True},
        "regolith_soil_model": _regolith_soil_model(),
        "surface_evolution_model": {"process_grid": {"erosion_intensity_rows": [[0.20, 0.22], [0.21, 0.23]]}},
        "ocean_circulation_model": {"stub": True},
        "cryosphere_model": {"stub": True},
        "true_color_model": {"stub": True},
        "bounds": {"type": "bbox", "min_x": 0.0, "max_x": 100.0, "min_y": 0.0, "max_y": 100.0},
    }
    biosphere = {
        "id": "biosphere_test", "_dataset": "biospheres", "type": "biosphere",
        "name": "Test Biosphere",
        "overlay_location": "loc_test_patch",
        "microfauna_species": ["spec_test_ant"],
    }
    species = {
        "id": "spec_test_ant", "_dataset": "species", "type": "species",
        "common_name": "Test Ant",
    }
    return _World([location, biosphere, species])


def _launch_context(biosphere_id="biosphere_test"):
    return {
        "patch_location_id": "loc_test_patch",
        "patch_name": "Test Patch",
        "root_location_id": "loc_test_patch",
        "biosphere_id": biosphere_id,
        "map_size_m": 10.0,
        "source_bounds": {"type": "bbox", "min_x": 0.0, "max_x": 100.0, "min_y": 0.0, "max_y": 100.0},
    }


class BioregionWorldgenBridgeTests(unittest.TestCase):
    def test_resolved_context_no_longer_uses_dead_climate_zone_field(self):
        world = _build_world()
        sim = BioregionSimulation(world_model=world, biosphere_context=_launch_context(), biosphere_id="biosphere_test")
        self.assertIsNotNone(sim.worldgen_context)
        bridge_source = inspect.getsource(BioregionSimulation._resolve_worldgen_context)
        bridge_source += inspect.getsource(BioregionSimulation._has_worldgen_context)
        self.assertNotIn("climate_zone_model", bridge_source)

    def test_material_heatmap_extraction_bug_is_fixed(self):
        world = _build_world()
        sim = BioregionSimulation(world_model=world, biosphere_context=_launch_context(), biosphere_id="biosphere_test")
        self.assertEqual(sim.worldgen_context.get("material_heatmap"), {"stub": True})

    def test_newly_surfaced_worldgen_fields_are_extracted(self):
        world = _build_world()
        sim = BioregionSimulation(world_model=world, biosphere_context=_launch_context(), biosphere_id="biosphere_test")
        context = sim.worldgen_context
        self.assertIsNotNone(context.get("regolith_soil"))
        self.assertEqual(context.get("ocean_circulation"), {"stub": True})
        self.assertEqual(context.get("cryosphere"), {"stub": True})
        self.assertIsNotNone(context.get("surface_evolution"))
        self.assertEqual(context.get("true_color"), {"stub": True})


class BioregionDurableEntityTests(unittest.TestCase):
    def test_loading_with_biosphere_id_pulls_species_roster_from_entity(self):
        world = _build_world()
        sim = BioregionSimulation(world_model=world, biosphere_context=_launch_context(), biosphere_id="biosphere_test")
        species_ids = {entry["id"] for entry in sim.available_species}
        self.assertIn("spec_test_ant", species_ids)

    def test_soil_profile_generated_on_first_load(self):
        world = _build_world()
        sim = BioregionSimulation(world_model=world, biosphere_context=_launch_context(), biosphere_id="biosphere_test")

        area_profile = sim.biosphere_entity.get("area_soil_profile")
        self.assertIsInstance(area_profile, dict)
        self.assertEqual(area_profile.get("generated_from"), "regolith_soil_model")
        for field_name in (
            "organic_layer", "topsoil", "subsoil", "parent_material", "moisture_capacity",
            "ph", "salinity", "nutrients", "microbial_activity", "drainage", "compaction",
            "erosion_risk", "root_depth_constraints",
        ):
            self.assertIn(field_name, area_profile)
        # Biology fields stay visibly unresolved -- the abiotic source model
        # deliberately excludes them (see regolith_soils.py).
        self.assertIsNone(area_profile.get("organic_layer"))
        self.assertIsNone(area_profile.get("microbial_activity"))
        self.assertIsNotNone(area_profile.get("moisture_capacity"))

        biosphere_profile = sim.biosphere_entity.get("biosphere_soil_profile")
        self.assertEqual(biosphere_profile.get("generated_from"), "area_soil_profile_baseline")

        # Staged, not just held in memory.
        self.assertEqual(world.entities["biosphere_test"]["area_soil_profile"], area_profile)

    def test_soil_profile_is_not_regenerated_on_second_load(self):
        world = _build_world()
        BioregionSimulation(world_model=world, biosphere_context=_launch_context(), biosphere_id="biosphere_test")

        original_method = BioregionSimulation._generate_area_soil_profile
        call_count = []

        def counting_generate(self):
            call_count.append(1)
            return original_method(self)

        BioregionSimulation._generate_area_soil_profile = counting_generate
        try:
            BioregionSimulation(world_model=world, biosphere_context=_launch_context(), biosphere_id="biosphere_test")
        finally:
            BioregionSimulation._generate_area_soil_profile = original_method

        self.assertEqual(len(call_count), 0)

    def test_hierarchy_breadcrumb_walks_parent_biosphere(self):
        world = _build_world()
        world.entities["biosphere_parent"] = {
            "id": "biosphere_parent", "_dataset": "biospheres", "type": "biosphere",
            "name": "Parent Bioregion",
        }
        world.entities["biosphere_test"]["parent_biosphere"] = "biosphere_parent"

        sim = BioregionSimulation(world_model=world, biosphere_context=_launch_context(), biosphere_id="biosphere_test")
        breadcrumb = sim.get_bioregion_hierarchy_breadcrumb()
        self.assertEqual(breadcrumb, "Parent Bioregion > Test Biosphere")

    def test_generic_test_tab_path_is_unaffected(self):
        # No biosphere_context/biosphere_id at all -- the original prototype
        # test-tab path must keep working unmodified.
        sim = BioregionSimulation()
        self.assertIsNone(sim.biosphere_entity)
        self.assertIsNone(sim.worldgen_context)
        self.assertTrue(len(sim.available_species) > 0)


class AuthorBiosphereModelTests(unittest.TestCase):
    def test_build_changes_carries_existing_fields_forward(self):
        datasets = {
            "schemas": [],
            "biospheres": [
                {
                    "id": "biosphere_cerrado_ecoregion", "_dataset": "biospheres", "type": "biosphere",
                    "name": "Old Name",
                    "custom_field_not_in_schema": "must survive the rewrite",
                }
            ],
        }
        changes = build_changes(datasets)
        biosphere_change = next(change for change in changes if change.get("id") == "biosphere_cerrado_ecoregion")

        self.assertEqual(biosphere_change.get("custom_field_not_in_schema"), "must survive the rewrite")
        self.assertEqual(biosphere_change.get("overlay_location"), "loc_cerrado_ecoregion")
        self.assertEqual(biosphere_change.get("bioregion_subclass"), "terrestrial")

    def test_build_changes_syncs_reverse_pointer_on_overlay_location(self):
        datasets = {
            "schemas": [],
            "biospheres": [],
            "locations": [
                {
                    "id": "loc_cerrado_ecoregion", "_dataset": "locations", "type": "location",
                    "location_class": "biosphere_patch",
                    "custom_location_field": "must survive the rewrite",
                }
            ],
        }
        changes = build_changes(datasets)
        location_change = next(change for change in changes if change.get("id") == "loc_cerrado_ecoregion")

        self.assertEqual(location_change.get("biosphere_entity_id"), "biosphere_cerrado_ecoregion")
        self.assertEqual(location_change.get("custom_location_field"), "must survive the rewrite")

    def test_build_changes_declares_schema_fields(self):
        changes = build_changes({"schemas": [], "biospheres": []})
        schema_change = next(change for change in changes if change.get("id") == "schema_biosphere")

        fields = schema_change["fields"]
        for field_name in ("overlay_location", "parent_biosphere", "area_soil_profile", "biosphere_soil_profile"):
            self.assertIn(field_name, fields)


if __name__ == "__main__":
    unittest.main()
