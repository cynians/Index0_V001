import math
import unittest
from types import SimpleNamespace

from simulations.species.plant_assets import PlantBlueprint
from simulations.species.rosette_shoots import build_rosette_shoots, rosette_bolting_factor, rosette_shoot_profile
from simulations.species.species_simulation import SpeciesSimulation
from simulations.species.species_renderer import DiagnosticCamera, SpeciesRenderer


def mixed_rosette(**changes):
    return {"id": "spec_synthetic_mixed_rosette", "plant_growth_form": "forb",
            "plant_growth_behaviour": "rosette_short_internode",
            "plant_woodiness": "herbaceous", "plant_lifespan": "perennial",
            "leaf_attachment_pattern": "mixed", "leaf_arrangement": "alternate",
            "leaf_size_class": "large", "plant_flowering_position": "mixed",
            "plant_lateral_axis_orientation": "mixed",
            "plant_reproductive_structure": "capitulum", "reproductive_mode": "sexual",
            "mature_height": {"min_m": 0.3, "max_m": 1.2}, **changes}


def branched_profile(**changes):
    return {"form": "branched_rosette", "internode_variation": .5,
            "axis_deflection": .18, "lateral_length_ratio": .26,
            "secondary_branch_probability": 1., **changes}


class RosetteShootTests(unittest.TestCase):
    def test_authored_profile_makes_uneven_ascending_branched_axes(self):
        entity = mixed_rosette(plant_shoot_profile=branched_profile())
        sim = self.make_sim(entity)
        growth = sim.blueprint.growth
        nodes, stats = build_rosette_shoots(growth, 1, 1, 1, 303)
        self.assertGreater(stats["rosette_secondary_axis_count"], 0)
        main = [n for n in nodes if n["role"] == "main_axis"]
        heights = [0.] + [n["position"][2] for n in main]
        gaps = [b-a for a,b in zip(heights, heights[1:])]
        self.assertGreater(max(gaps)-min(gaps), .04)
        self.assertAlmostEqual(growth["max_height_m"], heights[-1])
        lateral = [n for n in nodes if n["role"] == "lateral_axis"]
        self.assertTrue(all(n["position"][2] > nodes[n["parent"]]["position"][2] for n in lateral))
        for i, node in enumerate(nodes):
            self.assertTrue(node["parent"] == -1 or 0 <= node["parent"] < i)
            if node["kind"] in {"leaf", "flower"} and node["parent"] >= 0:
                self.assertIn(nodes[node["parent"]]["kind"], {"stem_section", "branch_section"})
        zero = {**growth, "rosette_shoot_profile": branched_profile(secondary_branch_probability=0.)}
        _, control = build_rosette_shoots(zero, 1, 1, 1, 303)
        self.assertEqual(0, control["rosette_secondary_axis_count"])
        self.assertGreater(stats["structural_axis_length_m"], control["structural_axis_length_m"])
        unrelated = self.make_sim({**entity, "id": "spec_different_family"})
        self.assertEqual(sim.render_snapshot.placements, unrelated.render_snapshot.placements)
        self.assertNotEqual(sim.blueprint.fingerprint(), self.make_sim().blueprint.fingerprint())

    def test_profile_validation_unknown_orientation_and_resource_bounds(self):
        for changes in ({"axis_deflection": float("nan")}, {"internode_variation": True},
                        {"secondary_branch_probability": 2.}, {"lateral_length_ratio": 0.}):
            self.assertIsNone(rosette_shoot_profile(branched_profile(**changes)))
        sim = self.make_sim(mixed_rosette(plant_shoot_profile=branched_profile()))
        growth = sim.blueprint.growth
        for seed in range(20):
            nodes, _ = build_rosette_shoots({**growth, "max_height_m": 1e9, "internode_length_m": .001}, 1, 1, 1, seed)
            self.assertLess(len(nodes), 150)
            self.assertLessEqual(max(n["position"][2] for n in nodes), 20.01)
            self.assertTrue(all(math.isfinite(v) for n in nodes for v in n["position"]))
        nodes, stats = build_rosette_shoots({**growth, "lateral_axis_orientation": "other_unknown"}, 1, 1, 1, 303)
        self.assertEqual(0, stats["rosette_secondary_axis_count"])
        self.assertFalse(any(n["kind"] == "branch_section" for n in nodes))

    def test_profile_canonical_leaf_area_and_axis_length_across_lods(self):
        sim = self.make_sim(mixed_rosette(plant_shoot_profile=branched_profile()))
        snapshots = [sim.generate_snapshot(lod=lod) for lod in (0, 1, 2)]
        for key in ("estimated_leaf_count", "leaf_area_m2", "structural_axis_length_m",
                    "root_depth_m", "root_length_m", "rosette_secondary_axis_count"):
            self.assertEqual(len({s.stats[key] for s in snapshots}), 1, key)

    def make_sim(self, entity=None, seed=303):
        sim = SpeciesSimulation(species_entity=entity or mixed_rosette(), seed=seed)
        sim.set_age(sim.life_history_profile["reproductive_start_days"] + 60)
        return sim

    def test_juvenile_rosette_precedes_bolting_and_flowering(self):
        sim = self.make_sim()
        start = sim.life_history_profile["reproductive_start_days"]
        juvenile = sim.generate_snapshot(age_days=start * 0.5, lod=2)
        early = sim.generate_snapshot(age_days=start * 0.85, lod=2)
        mature = sim.generate_snapshot(age_days=start + 60, lod=2)
        self.assertEqual(0, juvenile.stats["cauline_leaf_count"])
        self.assertFalse(any(p[0] in {"stem_section", "branch_section", "flower"} for p in juvenile.placements))
        self.assertGreater(early.stats["cauline_leaf_count"], 0)
        self.assertFalse(any(p[0] == "flower" for p in early.placements))
        self.assertGreater(mature.stats["cauline_leaf_count"], early.stats["cauline_leaf_count"])
        self.assertGreater(mature.stats["rosette_flower_count"], 0)

    def test_mature_plant_has_basal_and_smaller_attached_stem_leaves(self):
        snapshot = self.make_sim().render_snapshot
        basal = [a for a in snapshot.attachment_points if a.get("cohort") == "basal_leaf"]
        cauline = [a for a in snapshot.attachment_points if a.get("cohort") == "stem_leaf"]
        self.assertEqual(12, len(basal))
        self.assertGreater(len(cauline), 8)
        smallest_basal = min(snapshot.placements[a["leaf_placement_index"]][6] for a in basal)
        self.assertLess(max(snapshot.placements[a["leaf_placement_index"]][6] for a in cauline), smallest_basal)
        for attachment in cauline:
            leaf = snapshot.placements[attachment["leaf_placement_index"]]
            host = snapshot.placements[attachment["stem_placement_index"]]
            self.assertEqual(leaf[2:5], host[2:5])
            self.assertIn(host[0], {"stem_section", "branch_section"})
        self.assertGreater(snapshot.stats["rosette_lateral_axis_count"], 0)
        self.assertTrue(any(p[0] == "flower" and snapshot.placements[p[1]][0] == "branch_section"
                            for p in snapshot.placements))

    def test_lateral_and_terminal_flowering_are_distinct_trait_responses(self):
        growth = self.make_sim().blueprint.growth
        for position in ("terminal", "lateral", "mixed", "other_unknown"):
            with self.subTest(position=position):
                nodes, _ = build_rosette_shoots({**growth, "flowering_position": position}, 1, 1, 1, 303)
                roles = {n["role"] for n in nodes if n["kind"] == "flower"}
                expected = {"terminal": {"terminal_flower"}, "lateral": {"lateral_flower"},
                            "mixed": {"terminal_flower", "lateral_flower"}, "other_unknown": set()}
                self.assertEqual(expected[position], roles)

    def test_unresolved_reproduction_does_not_invent_flowers(self):
        for changes in ({"plant_reproductive_structure": "other_unknown"},
                        {"plant_flowering_position": "other_unknown"},
                        {"reproductive_mode": "vegetative"}):
            sim = self.make_sim(mixed_rosette(**changes))
            self.assertFalse(any(p[0] == "flower" for p in sim.render_snapshot.placements))
            self.assertGreater(sim.render_snapshot.stats["cauline_leaf_count"], 0)

    def test_basal_and_unknown_attachment_keep_existing_scapes(self):
        for attachment in ("basal_rosette", "", "other_unknown"):
            sim = self.make_sim(mixed_rosette(leaf_attachment_pattern=attachment))
            self.assertNotIn("rosette_shoot_grammar_version", sim.blueprint.growth)
            self.assertFalse(any(p[0] == "branch_section" for p in sim.render_snapshot.placements))
            leaves = [p for p in sim.render_snapshot.placements if p[0] == "leaf"]
            self.assertTrue(all(p[4] <= 0.04 for p in leaves))

    def test_finite_bounded_graph_valid_parents_and_round_trips(self):
        first = self.make_sim()
        second = self.make_sim()
        self.assertEqual(first.render_snapshot.to_dict(), second.render_snapshot.to_dict())
        self.assertEqual(first.blueprint.to_dict(), PlantBlueprint.from_dict(first.blueprint.to_dict()).to_dict())
        snapshot = first.render_snapshot
        self.assertEqual(snapshot.to_dict(), type(snapshot).from_dict(snapshot.to_dict()).to_dict())
        for index, p in enumerate(snapshot.placements):
            self.assertTrue(p[1] == -1 or 0 <= p[1] < index)
            self.assertTrue(all(math.isfinite(float(v)) for v in p[2:7]))
        malformed = {**first.blueprint.growth, "max_height_m": float("inf"),
                     "internode_length_m": 0, "phyllotaxis_deg": float("nan")}
        nodes, stats = build_rosette_shoots(malformed, float("nan"), float("inf"), 1, 303)
        self.assertLess(len(nodes), 150)
        self.assertEqual(0, stats["cauline_leaf_count"])
        nodes, _ = build_rosette_shoots({**malformed, "max_height_m": 1e9}, 1, 1, 1, 303)
        self.assertLess(len(nodes), 150)
        self.assertTrue(all(all(math.isfinite(v) for v in n["position"]) for n in nodes))
        self.assertLessEqual(max(n["position"][2] for n in nodes), 20.01)
        self.assertEqual(0, rosette_bolting_factor(first.blueprint.growth, -10))

    def test_ecological_quantities_do_not_depend_on_render_lod(self):
        sim = self.make_sim()
        snapshots = [sim.generate_snapshot(lod=lod) for lod in (0, 1, 2)]
        for key in ("estimated_leaf_count", "leaf_area_m2", "structural_axis_length_m",
                    "root_depth_m", "root_length_m"):
            self.assertEqual(snapshots[0].stats[key], snapshots[1].stats[key], key)
            self.assertEqual(snapshots[1].stats[key], snapshots[2].stats[key], key)
        outcomes = []
        for snapshot in snapshots:
            sim.render_snapshot = snapshot
            outcomes.append(sim.get_ecological_outcome())
        for key in ("resource_demand", "leaf_area_proxy", "estimated_leaf_count", "structural_biomass_proxy"):
            self.assertEqual(outcomes[0][key], outcomes[1][key], key)
            self.assertEqual(outcomes[1][key], outcomes[2][key], key)

    def test_unrelated_species_reuses_grammar_and_attachment_changes_fingerprint(self):
        first = self.make_sim()
        unrelated = self.make_sim(mixed_rosette(id="spec_unrelated_rosette"))
        self.assertEqual(first.render_snapshot.placements, unrelated.render_snapshot.placements)
        control = self.make_sim(mixed_rosette(leaf_attachment_pattern="basal_rosette"))
        self.assertNotEqual(first.blueprint.fingerprint(), control.blueprint.fingerprint())
        fingerprint = first.blueprint.fingerprint()
        first.blueprint.growth["rosette_shoot_grammar_version"] += 1
        self.assertNotEqual(fingerprint, first.blueprint.fingerprint())

    def test_renderer_preserves_progressively_smaller_cauline_leaves(self):
        sim = self.make_sim()
        snapshot = sim.render_snapshot
        camera = DiagnosticCamera(800, 800, (-1, 1, 0, 1.5))
        renderer = SpeciesRenderer(SimpleNamespace(camera=None))
        attachments = [a for a in snapshot.attachment_points if a.get("cohort") == "stem_leaf"]
        # Use equal direction to isolate scale from projection foreshortening.
        index = attachments[0]["leaf_placement_index"]
        p = snapshot.placements[index]
        point = camera.world_to_screen_3d(p[2:5])
        large = renderer._fallback_leaf_endpoint(camera, sim, snapshot, index, point, p[5], 0.45)
        small = renderer._fallback_leaf_endpoint(camera, sim, snapshot, index, point, p[5], 0.15)
        self.assertGreater(math.dist(point, large), math.dist(point, small) * 2.5)


if __name__ == "__main__":
    unittest.main()
