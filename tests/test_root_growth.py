import copy
import math
import unittest

from simulations.species.root_growth import root_profile, build_root_graph
from simulations.species.species_simulation import SpeciesSimulation
from simulations.species.plant_assets import PlantGrowthSnapshot


class RootGrowthTests(unittest.TestCase):
    def make_sim(self, architecture="taproot", depth="deep", **extra):
        return SpeciesSimulation(species_entity={"id": "spec_root_test",
            "plant_growth_form": "forb", "root_architecture": architecture,
            "root_depth_class": depth, **extra}, seed=303)

    def test_valid_graph_geometry_bounds_and_determinism(self):
        for architecture in ("taproot", "fibrous", "adventitious", "mixed"):
            for seed in (1, 303, 404):
                profile = root_profile({"root_architecture": architecture, "root_depth_class": "deep"})
                graph, stats = build_root_graph(profile, 1, seed)
                self.assertEqual((graph, stats), build_root_graph(profile, 1, seed))
                self.assertLess(len(graph), 400)
                self.assertAlmostEqual(2.0, stats["root_depth_m"])
                for index, node in enumerate(graph):
                    self.assertLess(node["parent"], index)
                    self.assertGreaterEqual(node["parent"], -1)
                    self.assertTrue(all(math.isfinite(v) for v in node["position"]))
                    self.assertLessEqual(node["position"][2], 0)
                    self.assertGreaterEqual(node["position"][2], -2.0)
                    parent_order = graph[node["parent"]]["order"] if node["parent"] >= 0 else 0
                    self.assertGreaterEqual(node["order"], parent_order)

    def test_depth_and_length_grow_and_primary_axes_do_not_reshuffle(self):
        for architecture in ("taproot", "fibrous", "adventitious", "mixed"):
            profile = root_profile({"root_architecture": architecture, "root_depth_class": "shallow"})
            previous = {"root_depth_m": 0, "root_length_m": 0}
            for maturity in (0, 0.1, 0.2, 0.4, 0.7, 1):
                _, stats = build_root_graph(profile, maturity, 303)
                for key in previous:
                    self.assertGreaterEqual(stats[key], previous[key])
                previous = {k: stats[k] for k in previous}
        profile = root_profile({"root_architecture": "fibrous"})
        before, _ = build_root_graph(profile, 0.14, 303)
        after, _ = build_root_graph(profile, 0.16, 303)
        # Fine-root emergence must not rotate the pre-existing primary axes.
        primary_before = [n for n in before if n["order"] == 0]
        primary_after = [n for n in after if n["order"] == 0]
        for old, new in zip(primary_before, primary_after):
            self.assertAlmostEqual(math.atan2(old["position"][1], old["position"][0]),
                                   math.atan2(new["position"][1], new["position"][0]))

    def test_lod_keeps_complete_parents_and_identical_root_outcomes(self):
        sim = self.make_sim()
        sim.set_age(sim.mature_age_days)
        snapshots = [sim.generate_snapshot(lod=lod) for lod in range(3)]
        for snapshot in snapshots:
            for key in ("root_depth_m", "root_spread_m", "root_length_m", "root_segment_count"):
                self.assertEqual(snapshots[2].stats[key], snapshot.stats[key])
            for index, p in enumerate(snapshot.placements):
                if p[0] == "root_section":
                    self.assertIn(p[0], snapshot.modules)
                    self.assertTrue(0 <= p[1] < index)
            restored = PlantGrowthSnapshot.from_dict(snapshot.to_dict())
            self.assertEqual(snapshot.to_dict(), restored.to_dict())
        self.assertLess(snapshots[0].stats["root_visible_segment_count"], snapshots[2].stats["root_visible_segment_count"])

    def test_unknown_is_unresolved_and_authored_depth_is_used_without_mutating_entity(self):
        sim = self.make_sim(architecture="other_unknown")
        self.assertEqual("unresolved", sim.get_growth_summary()["root_model_status"])
        self.assertFalse(any(p[0] == "root_section" for p in sim.render_snapshot.placements))
        sim = self.make_sim(max_root_depth={"min_m": 0.3, "max_m": 0.8})
        original = copy.deepcopy(sim.species_entity)
        sim.set_age(sim.mature_age_days)
        self.assertEqual(0.8, sim.get_growth_summary()["root_depth_m"])
        self.assertEqual("authored_max_root_depth", sim.get_growth_summary()["root_depth_source"])
        self.assertEqual(original, sim.species_entity)
        for value in (-1, float("nan"), float("inf"), True, "2m"):
            self.assertEqual("depth_class_default", root_profile({"root_depth_class": "deep", "max_root_depth": {"max_m": value}})["depth_source"])

    def test_aquatic_adventitious_roots_attach_to_separate_submerged_stem(self):
        sim = self.make_sim("adventitious", "shallow", plant_growth_form="aquatic")
        sim.set_age(sim.mature_age_days)
        placements = sim.render_snapshot.placements
        roots = [p for p in placements if p[0] == "root_section"]
        origins = {p[1] for p in roots if placements[p[1]][0] == "root_support"}
        self.assertGreater(len(origins), 2)
        crown_z = sim.get_growth_summary()["root_origin_z_m"]
        self.assertLess(crown_z, 0)
        self.assertTrue(all(p[4] < crown_z for p in roots))
        self.assertEqual("stem_section", sim.blueprint.module("root_support").kind)

    def test_root_traits_do_not_change_shoot_geometry(self):
        first = self.make_sim("taproot")
        second = self.make_sim("fibrous")
        def shoots(sim):
            return [p for p in sim.render_snapshot.placements if p[0] not in {"root_section", "root_support"}]
        self.assertEqual(shoots(first), shoots(second))

    def test_frozen_older_blueprint_gets_root_module_definitions(self):
        blueprint = self.make_sim().blueprint
        blueprint.modules = [m for m in blueprint.modules if m.id not in {"root_section", "root_support"}]
        blueprint.growth.pop("root_profile", None)
        sim = SpeciesSimulation(blueprint=blueprint)
        snapshot = sim.render_snapshot
        self.assertTrue(any(p[0] == "root_section" for p in snapshot.placements))
        self.assertIn("root_section", snapshot.modules)


if __name__ == "__main__":
    unittest.main()
