"""Routing-driven material processes: provenance, talus, catena, bed sorting, faults.

See docs/worldgen_material_lod_plan_v001.md section 4.
"""

import random
import unittest
from pathlib import Path

import numpy as np

from simulations.world_gen import material_routing as routing
from simulations.world_gen.material_lod import (
    COVER_CLASS_IDS,
    assemble_visible_composition,
    derive_cover_fractions,
    resolve_environment_candidates,
)
from simulations.world_gen.natural_materials import configure_material_catalog
from world.persistent_ontology_store import PersistentOntologyStore


def setUpModule():
    rows = PersistentOntologyStore(
        Path(__file__).resolve().parents[1] / "ontology" / "index0.owl"
    ).load_datasets().get("materials") or []
    configure_material_catalog(rows)


def _reference_upstream(receivers, values):
    """Walk every cell's path to its sink and add its value along the way."""
    size = receivers.size
    totals = np.zeros_like(values, dtype=np.float64)
    for cell in range(size):
        current = cell
        while current < size:
            totals[current] += values[cell]
            current = receivers[current]
    return totals


class UpstreamRoutingTests(unittest.TestCase):
    def test_pointer_doubling_matches_path_walk(self):
        rng = np.random.default_rng(2)
        elevation = rng.uniform(0.0, 50.0, (13, 17)) + np.arange(17)[None, :] * 3.0
        receivers, _gradient = routing.d8_receivers(elevation, dx=30.0, dy=30.0)
        values = rng.uniform(0.0, 1.0, (receivers.size, 3))
        np.testing.assert_allclose(routing.upstream_sum(receivers, values), _reference_upstream(receivers, values))

    def test_d8_follows_the_steepest_descent_and_stops_at_sinks(self):
        elevation = np.add.outer(np.zeros(5), np.arange(6, 0, -1) * 10.0)
        receivers, gradient = routing.d8_receivers(elevation, dx=10.0, dy=10.0, sinks=np.zeros((5, 6), dtype=bool))
        grid = receivers.reshape(5, 6)
        self.assertEqual(2 * 6 + 1, grid[2, 0])  # east, down the ramp
        self.assertEqual(30, grid[2, 5])  # lowest column is a sink
        self.assertAlmostEqual(1.0, gradient[2, 0])


class InletTests(unittest.TestCase):
    def test_river_entering_through_a_notch_crosses_the_tile(self):
        # Ramp falling east; the entry cell on the west edge sits in a 2 m
        # notch, as local detail often leaves it.
        y, x = np.mgrid[0:21, 0:40]
        elevation = 10.0 - 0.05 * x + 0.0 * y
        elevation[10, 0] -= 2.0
        land = np.ones(elevation.shape, dtype=bool)
        inflow = np.zeros(elevation.shape)
        inflow[10, 0] = 5000.0
        size = elevation.size

        def exit_column(receivers):
            cell = 10 * elevation.shape[1]
            while receivers[cell] < size:
                cell = receivers[cell]
            return cell % elevation.shape[1]

        outlet_everywhere = routing.filled_routing(elevation, land, dx=10.0, dy=10.0)
        self.assertEqual(exit_column(outlet_everywhere), 0)
        with_inlets = routing.filled_routing(elevation, land, dx=10.0, dy=10.0, inlets=routing.inlet_mask(inflow, elevation.shape, dx=10.0, dy=10.0))
        self.assertEqual(exit_column(with_inlets), elevation.shape[1] - 1)
        belts = routing.channel_belts(elevation, land, dx=10.0, dy=10.0, inflow_cells=inflow)
        # The river wanders over the smooth ramp (routing micro-relief): somewhere on column 20.
        self.assertGreater(float(belts["area_m2"][:, 20].max()), 5000.0 * 100.0)


    def test_a_river_wider_than_the_tile_still_leaves_through_the_boundary(self):
        # 40 x 40 cells of 7 m: the entering river's floodplain (~5 km) is far
        # wider than the tile; the downstream sides must stay outlets.
        y, x = np.mgrid[0:40, 0:40]
        elevation = 100.0 - 0.02 * x - 0.01 * y + 0.001 * ((x - 20) ** 2)
        land = np.ones(elevation.shape, dtype=bool)
        inflow = np.zeros(elevation.shape)
        inflow[20, 0] = 4.0e11 / 49.0
        mask = routing.inlet_mask(inflow, elevation.shape, dx=7.0, dy=7.0)
        self.assertLessEqual(int(mask.sum()), 40 // 4 + 1)
        receivers = routing.filled_routing(elevation, land, dx=7.0, dy=7.0, inlets=mask)
        cell = 20 * 40
        while receivers[cell] < receivers.size:
            cell = receivers[cell]
        row, column = divmod(cell, 40)
        self.assertTrue(row in (0, 39) or column in (0, 39), (row, column))
        self.assertNotEqual(column, 0)


class BeltTests(unittest.TestCase):
    def test_tributaries_do_not_cut_islands_out_of_a_wide_floodplain(self):
        # A large river enters from the west along row 40; a small tributary
        # descends from the north at column 60.
        y, x = np.mgrid[0:81, 0:121].astype(float)
        elevation = 100.0 - 0.01 * x + 0.002 * np.abs(y - 40.0)
        elevation -= np.where(y < 38.0, 0.4 * np.clip(1.0 - np.abs(x - 60.0) / 3.0, 0.0, 1.0), 0.0)
        land = np.ones(elevation.shape, dtype=bool)
        inflow = np.zeros(elevation.shape)
        inflow[40, 0] = 5.0e10 / 49.0
        inflow[0, 60] = 2.0e6 / 49.0
        belts = routing.channel_belts(elevation, land, dx=7.0, dy=7.0, inflow_cells=inflow)
        self.assertTrue(belts["channel"][20, 60])
        # The river's ~2 km floodplain covers the tributary's surroundings.
        self.assertGreater(float(belts["belt"][20, 56:65].min()), 0.4)
        self.assertGreater(float(belts["half_width_m"][20, 57]), 1000.0)


class RoutingJitterTests(unittest.TestCase):
    def test_flow_lines_on_a_planar_ramp_join_instead_of_running_parallel(self):
        y, x = np.mgrid[0:80, 0:80].astype(float)
        ramp = 500.0 - 0.01 * 50.0 * y  # 1 % down to the south, 50 m cells
        land = np.ones(ramp.shape, dtype=bool)
        receivers, gradient = routing.d8_receivers(ramp, dx=50.0, dy=50.0)
        straight = routing.upstream_area_m2(receivers, ramp.shape, dx=50.0, dy=50.0) / 2500.0
        # Deterministic descent: one line per column, each draining its own column.
        self.assertLessEqual(float(straight.max()), 80.0)
        jitter = routing.routing_jitter(gradient, dx=50.0, dy=50.0, seed=7)
        # Sub-cell relief: well under a cell's drop on average.
        self.assertLess(float(np.abs(jitter).mean()), 0.5)
        wandering, _g = routing.d8_receivers(ramp + jitter, dx=50.0, dy=50.0)
        joined = routing.upstream_area_m2(wandering, ramp.shape, dx=50.0, dy=50.0) / 2500.0
        self.assertGreater(float(joined.max()), 3.0 * float(straight.max()))
        # Deterministic.
        np.testing.assert_array_equal(jitter, routing.routing_jitter(gradient, dx=50.0, dy=50.0, seed=7))


class ProvenanceTests(unittest.TestCase):
    def test_valley_alluvium_carries_the_upstream_rock(self):
        # Granite headwaters (west) drain east down a valley cut in basalt;
        # the valley walls are steeper than the valley floor, so hillslopes
        # feed the axis.
        height, width = 21, 41
        x = np.arange(width)[None, :]
        y = np.arange(height)[:, None]
        elevation = 900.0 - x * 5.0 + np.abs(y - height // 2) * 30.0
        composition = np.zeros((2, height, width))
        composition[0, :, :15] = 1.0
        composition[1, :, 15:] = 1.0
        land = np.ones((height, width), dtype=bool)
        routed = routing.provenance_composition(elevation, land, composition, dx=100.0, dy=100.0)
        self.assertGreater(float(routed[0, height // 2, width - 2]), 0.2)
        # A basalt hillside cell downstream of the contact sees only basalt.
        self.assertLess(float(routed[0, 2, 25]), 1e-6)
        np.testing.assert_allclose(routed.sum(axis=0), 1.0, atol=1e-5)
        # Headwater cells only see their own rock.
        self.assertAlmostEqual(1.0, float(routed[0, height // 2, 1]), places=5)


def _escarpment():
    """A caprock plateau (rock 0) breaking off in a cliff above a slope of rock 1."""
    height, width = 24, 30
    x = np.arange(width, dtype=np.float64)[None, :]
    elevation = np.broadcast_to(np.where(x < 12, 300.0, 300.0 - (x - 12) * 1.5), (height, width)).copy()
    elevation[:, 12:15] = 300.0 - (np.arange(12, 15) - 11) * 18.0
    elevation[:, 15:] = elevation[:, 14:15] - (np.arange(15, width) - 14) * 3.0
    composition = np.zeros((2, height, width))
    composition[0, :, :15] = 1.0
    composition[1, :, 15:] = 1.0
    return elevation, composition


class TalusTests(unittest.TestCase):
    def test_talus_apron_below_a_cliff_is_made_of_the_cliff_rock(self):
        elevation, composition = _escarpment()
        land = np.ones(elevation.shape, dtype=bool)
        receivers, gradient = routing.d8_receivers(elevation, dx=20.0, dy=20.0, sinks=~land)
        fraction, mix = routing.talus_fields(receivers, gradient, land, composition, dx=20.0, dy=20.0)
        apron = fraction[:, 15:20].mean()
        self.assertGreater(apron, 0.1)
        self.assertLess(float(fraction[:, :10].max()), 1e-9)  # nothing on the plateau
        self.assertLess(float(fraction[:, 26:].max()), 1e-9)  # runout is bounded
        deposited = fraction > 1e-6
        self.assertGreater(float(mix[0][deposited].mean()), 0.99)

    def test_only_rock_faces_shed_talus(self):
        # The same escarpment as an alluvial cut bank sheds no rockfall.
        elevation, composition = _escarpment()
        land = np.ones(elevation.shape, dtype=bool)
        receivers, gradient = routing.d8_receivers(elevation, dx=20.0, dy=20.0, sinks=~land)
        fraction, _mix = routing.talus_fields(
            receivers, gradient, land, composition, dx=20.0, dy=20.0, rock=np.zeros(elevation.shape, dtype=bool),
        )
        self.assertLess(float(fraction.max()), 1e-9)

    def test_a_face_narrower_than_a_cell_still_sheds_talus(self):
        # A 20 m rock step on 40 m cells: the grid sees a gradient of 0.5, under
        # the cliff rule, but the scarp record says there is a face.
        height, width = 12, 30
        x = np.arange(width, dtype=np.float64)[None, :]
        elevation = np.broadcast_to(np.where(x < 12, 200.0, 180.0) - x * 0.4, (height, width)).copy()
        land = np.ones(elevation.shape, dtype=bool)
        composition = np.ones((1,) + elevation.shape)
        receivers, gradient = routing.d8_receivers(elevation, dx=40.0, dy=40.0, sinks=~land)
        unseen, _mix = routing.talus_fields(receivers, gradient, land, composition, dx=40.0, dy=40.0)
        self.assertLess(float(unseen.max()), 1e-9)
        faces = np.zeros(elevation.shape, dtype=bool)
        faces[:, 11] = True
        fraction, _mix = routing.talus_fields(receivers, gradient, land, composition, dx=40.0, dy=40.0, faces=faces)
        self.assertGreater(float(fraction[:, 12:15].mean()), 0.05)
        self.assertLess(float(fraction[:, :11].max()), 1e-9)

    def test_apron_length_does_not_depend_on_grid_spacing(self):
        def mean_runout_m(spacing):
            distance = np.arange(0.0, 1_200.0, spacing)
            profile = np.where(distance < 400.0, 500.0, np.where(distance < 460.0, 500.0 - (distance - 400.0) * 2.5, 350.0 - (distance - 460.0) * 0.2))
            elevation = np.broadcast_to(profile, (6, distance.size)).copy()
            land = np.ones(elevation.shape, dtype=bool)
            receivers, gradient = routing.d8_receivers(elevation, dx=spacing, dy=spacing, sinks=~land)
            fraction, _mix = routing.talus_fields(receivers, gradient, land, np.ones((1,) + elevation.shape), dx=spacing, dy=spacing)
            row = fraction[3]
            return float(((distance - 460.0) * row).sum() / max(row.sum(), 1e-9))

        coarse, fine = mean_runout_m(20.0), mean_runout_m(5.0)
        self.assertGreater(coarse, 40.0)
        self.assertLess(abs(coarse - fine) / fine, 0.35)


class CatenaTests(unittest.TestCase):
    def test_crests_are_convex_and_hollows_are_wet(self):
        y, x = np.mgrid[0:41, 0:41]
        hill = 200.0 * np.exp(-(((x - 20) ** 2 + (y - 20) ** 2) / 90.0))
        valley = -60.0 * np.exp(-(((x - 5) ** 2) / 6.0))
        elevation = hill + valley + (40 - y) * 0.5
        land = np.ones(elevation.shape, dtype=bool)
        receivers, gradient = routing.d8_receivers(elevation, dx=25.0, dy=25.0, sinks=~land)
        area = routing.upstream_area_m2(receivers, elevation.shape, dx=25.0, dy=25.0)
        catena = routing.catena_fields(elevation, land, gradient, area, dx=25.0, dy=25.0)
        self.assertGreater(float(catena["crest"][20, 20]), 0.5)
        self.assertLess(float(catena["toeslope"][20, 20]), 0.05)
        self.assertGreater(float(catena["wet"][35:, 3:8].mean()), float(catena["wet"][15:25, 15:25].mean()))

    def test_decimetre_roughness_on_a_plain_is_not_a_catena(self):
        rng = np.random.default_rng(3)
        elevation = 300.0 + rng.normal(0.0, 0.15, (60, 60))
        land = np.ones(elevation.shape, dtype=bool)
        receivers, gradient = routing.d8_receivers(elevation, dx=7.0, dy=7.0, sinks=~land)
        area = routing.upstream_area_m2(receivers, elevation.shape, dx=7.0, dy=7.0)
        catena = routing.catena_fields(elevation, land, gradient, area, dx=7.0, dy=7.0)
        self.assertLess(float(catena["crest"].max()), 0.01)
        self.assertLess(float(catena["toeslope"].max()), 0.01)


class CoverRoutingTests(unittest.TestCase):
    def test_lithic_sources_and_candidate_groups_keep_area_whole(self):
        shape = (2, 3)
        substrate = np.stack([np.full(shape, 0.7), np.full(shape, 0.3)]).astype(np.float32)
        cover = {class_id: np.zeros(shape, dtype=np.float32) for class_id in COVER_CLASS_IDS}
        cover["alluvium"][:] = 0.5
        source = np.stack([np.zeros(shape), np.ones(shape)]).astype(np.float32)
        power = np.asarray([[0.0, 0.5, 1.0], [0.0, 0.5, 1.0]])
        bed = [{"material_id": "mat_gravel", "prevalence": 0.5, "temperature_k": None, "precipitation_mm": None}]
        plain = [{"material_id": "mat_silt", "prevalence": 0.5, "temperature_k": None, "precipitation_mm": None}]
        ids, visible, _cover_total = assemble_visible_composition(
            ["mat_granite", "mat_basalt"], substrate, cover,
            {"alluvium": [{"material_id": "mat_alluvium", "prevalence": 0.8, "temperature_k": None, "precipitation_mm": None}]},
            temperature_k=np.full(shape, 285.0), precipitation_mm=np.full(shape, 900.0),
            lithic_sources={"alluvium": (np.full(shape, 0.4), source)},
            candidate_groups={"alluvium": [(power, bed), (1.0 - power, plain)]},
        )
        np.testing.assert_allclose(visible.sum(axis=0), 1.0, atol=1e-5)
        layer = dict(zip(ids, visible))
        # 0.5 alluvium x 0.4 lithic, all from the basalt source.
        np.testing.assert_allclose(layer["mat_basalt"], 0.3 * 0.5 + 0.2, atol=1e-5)
        self.assertGreater(float(layer["mat_gravel"][0, 2]), float(layer["mat_silt"][0, 2]))
        self.assertGreater(float(layer["mat_silt"][0, 0]), float(layer["mat_gravel"][0, 0]))

    def test_talus_buries_other_cover_and_wet_hollows_need_humid_ground(self):
        shape = (1, 2)
        zeros = np.zeros(shape)
        materials = {class_id: "mat_x" for class_id in COVER_CLASS_IDS}
        common = dict(
            shape=shape,
            land=np.ones(shape, dtype=bool),
            partition={"exposed_bedrock_fraction": zeros + 0.2, "weathered_mantle_fraction": zeros + 0.8},
            processes={},
            ice_mask=np.zeros(shape, dtype=bool),
            airless=False,
            cover_materials=materials,
        )
        catena = {"crest": zeros, "toeslope": zeros, "wet": np.ones(shape)}
        humid = derive_cover_fractions(
            temperature_k=np.full(shape, 285.0), precipitation_mm=np.asarray([[1400.0, 150.0]]),
            catena=catena, talus=np.asarray([[0.0, 0.5]]), **common,
        )
        self.assertGreater(float(humid["wet_hollow"][0, 0]), 0.3)
        self.assertLess(float(humid["wet_hollow"][0, 1]), 0.01)
        self.assertGreater(float(humid["talus"][0, 1]), 0.25)

    def test_depositional_environments_come_from_the_ontology(self):
        model = {"planet_tags": ["active_hydrology", "weathered_surface"], "likely_materials": [
            {"material_id": material_id, "confidence": 0.8, "spatial_representation": "surface_cover"}
            for material_id in ("mat_gravel", "mat_silt", "mat_alluvium", "mat_marine_mud", "mat_talus")
        ]}
        channel_bed = {item["material_id"] for item in resolve_environment_candidates(model, "channel_bed")}
        hollows = {item["material_id"] for item in resolve_environment_candidates(model, "wet_hollow")}
        self.assertTrue({"mat_gravel", "mat_alluvium"} <= channel_bed)
        self.assertIn("mat_silt", hollows)
        self.assertNotIn("mat_marine_mud", hollows)


class FaultOffsetTests(unittest.TestCase):
    def test_faults_offset_units_and_agree_between_overlapping_tiles(self):
        along, across = np.meshgrid(np.linspace(0.0, 30_000.0, 120), np.linspace(0.0, 20_000.0, 80))
        shifted_along, shifted_across, faults, heave = routing.fault_offsets(along, across, unit_scale=1_200.0, seed=5, strain=0.6)
        self.assertTrue(faults)
        displacement = np.hypot(shifted_along - along, shifted_across - across)
        self.assertGreater(float(displacement.max()), 100.0)
        self.assertLess(float(displacement.max()), 1_200.0 * 1.25)
        # One side of a fault is raised relative to the other.
        self.assertGreater(float(heave.max() - heave.min()), 10.0)
        self.assertLessEqual(float(np.abs(heave).max()), max(fault[3] for fault in faults) * 0.5 * len(faults))
        # A second tile sharing the eastern half sees the same displacement.
        sub_along, sub_across = along[:, 60:], across[:, 60:]
        again_along, again_across, _faults, again_heave = routing.fault_offsets(sub_along, sub_across, unit_scale=1_200.0, seed=5, strain=0.6)
        np.testing.assert_allclose(again_along, shifted_along[:, 60:])
        np.testing.assert_allclose(again_across, shifted_across[:, 60:])
        np.testing.assert_allclose(again_heave, heave[:, 60:])


if __name__ == "__main__":
    unittest.main()
