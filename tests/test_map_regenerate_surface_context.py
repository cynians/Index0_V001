import unittest

from simulations.map.map_simulation import MapSimulation


class _Loader:
    def __init__(self, entities):
        self.entities = {entity["id"]: entity for entity in entities}


class _World:
    def __init__(self, entities):
        self.loader = _Loader(entities)

    def get_entity(self, entity_id):
        return self.loader.entities.get(entity_id)


def _heightmap(rows=2, cols=2):
    return {"sample_grid": {"width": cols, "height": rows, "rows": [[0.0] * cols for _ in range(rows)]}}


class _Context:
    def __init__(self, root_entity_id):
        self.root_entity_id = root_entity_id


def _sim(entities, root_entity_id=None):
    sim = MapSimulation.__new__(MapSimulation)
    sim.world_model = _World(entities)
    if root_entity_id is not None:
        sim.context = _Context(root_entity_id)
    return sim


class OwnGeneratedRegionTests(unittest.TestCase):
    """
    Regression coverage for the bug where a location's own "Regenerate This
    Region" output was silently orphaned: rendering fell through to
    _inherited_surface_context, which only walks upward past structural
    ancestors and never looks at the region's own generated children in
    constituents. See the session notes around refined_lod1_19d02aae94 /
    refined_lod1_19c7e4ea11 for the live reproduction.
    """

    def test_returns_none_when_no_constituents(self):
        draft = {"id": "loc_draft_x", "location_class": "region", "constituents": []}
        sim = _sim([draft])
        self.assertIsNone(sim._own_generated_region(draft))

    def test_ignores_non_generated_constituents(self):
        draft = {"id": "loc_draft_x", "location_class": "region", "constituents": ["loc_draft_child"]}
        child_draft = {"id": "loc_draft_child", "location_class": "region"}
        sim = _sim([draft, child_draft])
        self.assertIsNone(sim._own_generated_region(draft))

    def test_ignores_generated_region_without_real_heightmap(self):
        draft = {"id": "loc_draft_x", "location_class": "region", "constituents": ["refined_a"]}
        refined = {"id": "refined_a", "location_class": "generated_region", "heightmap_model": {}}
        sim = _sim([draft, refined])
        self.assertIsNone(sim._own_generated_region(draft))

    def test_picks_own_generated_region(self):
        draft = {"id": "loc_draft_x", "location_class": "region", "constituents": ["refined_a"]}
        refined = {
            "id": "refined_a", "location_class": "generated_region",
            "heightmap_model": _heightmap(), "refinement_revision": 1,
        }
        sim = _sim([draft, refined])
        result = sim._own_generated_region(draft)
        self.assertIsNotNone(result)
        self.assertEqual(result["id"], "refined_a")

    def test_picks_highest_revision_when_multiple_generated_siblings_exist(self):
        # Regenerating a region more than once can leave more than one
        # generated_region constituent behind; the most recent one wins.
        draft = {"id": "loc_draft_x", "location_class": "region", "constituents": ["refined_a", "refined_b"]}
        refined_old = {
            "id": "refined_a", "location_class": "generated_region",
            "heightmap_model": _heightmap(), "refinement_revision": 1,
        }
        refined_new = {
            "id": "refined_b", "location_class": "generated_region",
            "heightmap_model": _heightmap(), "refinement_revision": 2,
        }
        sim = _sim([draft, refined_old, refined_new])
        result = sim._own_generated_region(draft)
        self.assertEqual(result["id"], "refined_b")


class MaterialHeatmapContextTests(unittest.TestCase):
    def test_prefers_own_generated_region_material_heatmap_over_root_planet_fallback(self):
        planet = {
            "id": "planet_x", "location_class": "planet",
            "material_heatmap_model": {"status": "wrong_source"},
        }
        draft = {
            "id": "loc_draft_x", "location_class": "region",
            "constituents": ["refined_a"],
        }
        refined = {
            "id": "refined_a", "location_class": "generated_region",
            "heightmap_model": _heightmap(),
            "material_heatmap_model": {"status": "correct_regional_source"},
            "generated_truth_lineage": {"root_planet_id": "planet_x"},
        }
        sim = _sim([planet, draft, refined])
        heatmap_model, _source_uv_bounds = sim._material_heatmap_context(draft)
        self.assertEqual(heatmap_model.get("status"), "correct_regional_source")

    def test_own_generated_region_material_heatmap_is_not_cropped_by_placement_uv(self):
        # The region's own material_heatmap_model raster is dedicated to its
        # full extent (generate_material_heatmap_model in
        # regional_refinement.py generates it directly for this region) --
        # unlike the root_planet fallback, it must not be cropped by the
        # heightmap's placement-in-parent source_uv_bounds. Regressing this
        # made True Color render blank after a region regeneration: a small,
        # wrong corner of an already-correct raster got cropped out.
        draft = {
            "id": "loc_draft_x", "location_class": "region",
            "constituents": ["refined_a"],
        }
        refined = {
            "id": "refined_a", "location_class": "generated_region",
            "heightmap_model": {
                **_heightmap(),
                "source_uv_bounds": {"min_u": 0.52, "max_u": 0.68, "min_v": 0.53, "max_v": 0.78},
            },
            "material_heatmap_model": {"status": "own_dedicated_raster"},
        }
        sim = _sim([draft, refined])
        heatmap_model, source_uv_bounds = sim._material_heatmap_context(draft)
        self.assertEqual(heatmap_model.get("status"), "own_dedicated_raster")
        self.assertIsNone(source_uv_bounds)

    def test_falls_back_to_root_planet_when_no_own_generated_region_exists(self):
        planet = {
            "id": "planet_x", "location_class": "planet",
            "material_heatmap_model": {"status": "planet_fallback"},
        }
        generated_region_without_material = {
            "id": "refined_a", "location_class": "generated_region",
            "generated_truth_lineage": {"root_planet_id": "planet_x"},
        }
        sim = _sim([planet, generated_region_without_material])
        heatmap_model, _source_uv_bounds = sim._material_heatmap_context(generated_region_without_material)
        self.assertEqual(heatmap_model.get("status"), "planet_fallback")


class RefinedRegionModelsSelfCompositeTests(unittest.TestCase):
    """
    Regression coverage for the bug where a location's own generated_region
    descendant (the source the base heightmap/true-color layer is already
    built from) was also matched as if it were a nested child to overlay on
    top of that same base -- descends_from() only checks
    refinement_parent_map_id == root_id, which is trivially true for a
    region's own output. This redoubled the (expensive) true-color render
    and, for at least one real reproduction this session
    (refined_lod1_cf6b61c505 under Test World 11 / Test Continent / Draft
    Region 001), left the final blit painting nothing over the screen --
    the map canvas stayed on the pre-content splash frame.
    """

    def _bbox(self, min_x, max_x, min_y, max_y):
        return {"type": "bbox", "min_x": min_x, "max_x": max_x, "min_y": min_y, "max_y": max_y}

    def test_own_generated_region_is_excluded_from_composite_children(self):
        draft = {
            "id": "loc_draft_x", "location_class": "region",
            "bounds": self._bbox(0.0, 10.0, 0.0, 10.0),
            "constituents": ["refined_a"],
        }
        own_generated = {
            "id": "refined_a", "location_class": "generated_region",
            "heightmap_model": _heightmap(), "map_detail_level": 1,
            "refinement_parent_map_id": "loc_draft_x",
            "bounds": self._bbox(0.0, 10.0, 0.0, 10.0),
        }
        sim = _sim([draft, own_generated], root_entity_id="loc_draft_x")
        models = sim._refined_region_models()
        self.assertNotIn("refined_a", [model.get("entity_id") for model in models])

    def test_a_genuine_sibling_generated_region_is_still_included(self):
        # Two independent regenerations of the same draft (e.g. after a
        # revision bump) can leave more than one generated_region entity
        # pointing at the same parent -- only the *currently resolved* own
        # generated region should be excluded, not every candidate that
        # happens to share refinement_parent_map_id.
        draft = {
            "id": "loc_draft_x", "location_class": "region",
            "bounds": self._bbox(0.0, 10.0, 0.0, 10.0),
            "constituents": ["refined_current"],
        }
        current = {
            "id": "refined_current", "location_class": "generated_region",
            "heightmap_model": _heightmap(), "map_detail_level": 1,
            "refinement_revision": 2,
            "refinement_parent_map_id": "loc_draft_x",
            "bounds": self._bbox(0.0, 10.0, 0.0, 10.0),
        }
        stale_sibling = {
            "id": "refined_stale", "location_class": "generated_region",
            "heightmap_model": _heightmap(), "map_detail_level": 1,
            "refinement_revision": 1,
            "refinement_parent_map_id": "loc_draft_x",
            "bounds": self._bbox(0.0, 5.0, 0.0, 5.0),
        }
        sim = _sim([draft, current, stale_sibling], root_entity_id="loc_draft_x")
        models = sim._refined_region_models()
        entity_ids = [model.get("entity_id") for model in models]
        self.assertNotIn("refined_current", entity_ids)
        self.assertIn("refined_stale", entity_ids)


if __name__ == "__main__":
    unittest.main()
