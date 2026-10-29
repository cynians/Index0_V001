import math
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from simulations.species.plant_assets import PlantBlueprint, PlantGrowthSnapshot
from simulations.species.species_simulation import SpeciesSimulation
from simulations.species.species_renderer import DiagnosticCamera, SpeciesRenderer, TopDownDiagnosticCamera


class TreeLeaderFoliageTests(unittest.TestCase):
    def make_sim(self, **fields):
        entity = {"id": "spec_terminal_tree_fixture", "plant_growth_form": "tree",
                  "plant_growth_behaviour": "branched_woody", "plant_lifespan": "perennial",
                  "plant_leaf_distribution": "along_shoot", "plant_axis_continuity": "monopodial",
                  "mature_height": {"max_m": 30}, "plant_apical_control": .95}
        entity.update(fields)
        sim = SpeciesSimulation(species_entity=entity, seed=303)
        sim.set_age(sim.mature_age_days)
        return sim

    def leaders(self, snapshot):
        return [c for c in snapshot.leaf_clusters if c.get("shoot_role") == "leader"]

    def test_each_live_leader_has_one_connected_cohort_in_both_tree_paths(self):
        for distribution in ("along_shoot", None):
            for control in (.95, .05):
                with self.subTest(distribution=distribution, control=control):
                    sim = self.make_sim(plant_leaf_distribution=distribution, plant_apical_control=control)
                    snapshot = sim.render_snapshot
                    stems = {i for i, p in enumerate(snapshot.placements) if p[0] == "stem_section" and p[7] == 1}
                    tips = stems - {snapshot.placements[i][1] for i in stems}
                    self.assertEqual(tips, {c["leader_tip_index"] for c in self.leaders(snapshot)})
                    for c in self.leaders(snapshot):
                        tip = snapshot.placements[c["leader_tip_index"]]
                        self.assertEqual(c["leader_base_index"], tip[1])
                        self.assertEqual(c["shoot_end_m"], list(tip[2:5]))
                        self.assertGreater(c["leaf_area_m2"], 0)

    def test_fascicles_area_and_sockets_survive_lod_and_detail(self):
        sim = self.make_sim(leaf_structure="needle_like", leaf_arrangement="fascicled",
                            leaf_fascicle_size=2, plant_trunk_straightness=1.)
        canonical = self.leaders(sim.render_snapshot)[0]
        self.assertEqual(canonical["shoot_end_m"], canonical["visual_positions_m"][0])
        for lod in (0, 1, 2):
            snapshot = sim.generate_snapshot(sim.mature_age_days, lod)
            c = self.leaders(snapshot)[0]
            self.assertEqual(canonical, c)
        detailed = sim.get_detailed_snapshot()
        c = self.leaders(detailed)[0]
        self.assertEqual(canonical["estimated_leaf_count"], c["estimated_leaf_count"])
        self.assertEqual(canonical["leaf_area_m2"], c["leaf_area_m2"])
        self.assertEqual(c["estimated_leaf_count"], len(c["sample_placement_indices"]))
        for i in c["sample_placement_indices"]:
            leaf = detailed.placements[i]
            self.assertEqual(leaf[2:5], detailed.placements[leaf[1]][2:5])
            for vector in detailed.placement_orientations[str(i)].values():
                self.assertTrue(all(math.isfinite(v) for v in vector))
                self.assertAlmostEqual(1., math.sqrt(sum(v*v for v in vector)), places=4)
        restored = PlantGrowthSnapshot.from_dict(detailed.to_dict())
        self.assertEqual(detailed.to_dict(), restored.to_dict())

    def test_no_extra_wood_or_reproduction_and_deterministic_recipe(self):
        sim = self.make_sim(plant_flowering_position="terminal", plant_shoot_dimorphism="single_shoot_system")
        actual = sim.render_snapshot
        with patch("simulations.species.tree_leader_foliage.add_tree_leader_foliage"):
            baseline = sim.generate_snapshot(sim.mature_age_days, sim.lod)
        self.assertEqual(actual.placements, baseline.placements)
        self.assertEqual(actual.stats["structural_axis_length_m"], baseline.stats["structural_axis_length_m"])
        self.assertEqual(actual.to_dict(), sim.generate_snapshot(sim.mature_age_days, sim.lod).to_dict())
        restored = PlantBlueprint.from_dict(sim.blueprint.to_dict())
        self.assertEqual(1, restored.growth["tree_leader_foliage_version"])
        self.assertEqual(restored.fingerprint(), sim.blueprint.fingerprint())
        previous = dict(sim.blueprint.to_dict())
        previous["growth"] = dict(previous["growth"])
        previous["growth"].pop("tree_leader_foliage_version")
        self.assertNotEqual(PlantBlueprint.from_dict(previous).fingerprint(), restored.fingerprint())

    def test_basal_foliage_and_unemerged_seedling_do_not_gain_terminal_cohort(self):
        sim = self.make_sim(plant_leaf_distribution="basal_tuft")
        self.assertEqual([], self.leaders(sim.render_snapshot))
        sim = self.make_sim()
        self.assertEqual([], self.leaders(sim.generate_snapshot(0, 2)))

    def test_leaf_off_factor_suppresses_terminal_cohort(self):
        from simulations.species.tree_leader_foliage import add_tree_leader_foliage
        sim = self.make_sim()
        clusters = []
        add_tree_leader_foliage(sim, list(sim.render_snapshot.placements), clusters, [], 1., 2, leaf_factor=0)
        self.assertEqual([], clusters)

    def test_biosim_representatives_and_display_trees_use_live_recipe(self):
        from world.world_model import WorldModel
        from simulations.biosphere.biosphere_simulation import BiosphereSimulation
        from simulations.biosphere.biosphere_renderer import BiosphereBuilderRenderer
        world = WorldModel()
        site = BiosphereSimulation.reference_site(world_model=world)
        site.ecology.introduce("spec_pinus_sylvestris", 5, 5, 4.5, .8)
        site.representatives.sync_from_population(site.ecology)
        representatives = site.representatives.items(alive_only=True)
        self.assertEqual(1, len(representatives))  # a stand is its plants, and 4.5 m has room for one pine
        for representative in representatives:
            body = representative.simulation
            body.set_age(body.mature_age_days * .9)
            self.assertEqual(1, body.blueprint.growth["tree_leader_foliage_version"])
            self.assertTrue(self.leaders(body.render_snapshot))
            self.assertGreater(body.get_ecological_outcome()["leaf_area_proxy"], 0)
        renderer = BiosphereBuilderRenderer(SimpleNamespace(camera=None))
        display = renderer._species_case(site, {"species_id": "spec_pinus_sylvestris", "display_maturity": .9})
        self.assertEqual(representatives[0].simulation.blueprint.fingerprint(), display.blueprint.fingerprint())
        self.assertTrue(self.leaders(display.render_snapshot))

    def test_blocked_leader_is_removed_and_surviving_sockets_are_remapped(self):
        import copy
        sim = self.make_sim(plant_apical_control=.05)
        snapshot = sim.render_snapshot
        leaders = self.leaders(snapshot)
        self.assertGreater(len(leaders), 1)
        target = snapshot.placements[1][2:5]
        class Solid:
            structures = ["test obstacle"]
            def path_hit(self, path):
                return {"structure": {"id": "test obstacle"}} if tuple(path[-1]) == tuple(target) else None
            def contains(self, position):
                return None
        placements = copy.deepcopy(snapshot.placements)
        clusters = copy.deepcopy(snapshot.leaf_clusters)
        sim._prune_tree_solid_intersections(placements, copy.deepcopy(snapshot.placement_paths),
                                           copy.deepcopy(snapshot.attachment_points), clusters, Solid())
        retained = [c for c in clusters if c.get("shoot_role") == "leader"]
        self.assertEqual(len(leaders) - 1, len(retained))
        for c in retained:
            tip = placements[c["leader_tip_index"]]
            self.assertEqual(tip[1], c["leader_base_index"])
            self.assertEqual(c["shoot_end_m"], list(tip[2:5]))

    def test_tree_apex_radius_tapers_without_shortening_axis(self):
        sim = self.make_sim()
        c = self.leaders(sim.render_snapshot)[0]
        tip = sim.render_snapshot.placements[c["leader_tip_index"]]
        base = sim.render_snapshot.placements[c["leader_base_index"]]
        self.assertLess(tip[6], base[6] * .15)
        self.assertAlmostEqual(30 * .92, tip[4])

    def test_renderer_keeps_apex_at_landscape_budget_and_projects_shoot_direction(self):
        import pygame
        pygame.init()
        try:
            for structure in ("needle_like", "simple"):
                sim = self.make_sim(leaf_structure=structure)
                c = self.leaders(sim.render_snapshot)[0]
                # A tilted leader exercises projection rather than treating
                # its horizontal azimuth as a sprite rotation.
                c["shoot_start_m"] = [0., 0., 25.]
                c["shoot_end_m"] = [1., 2., 28.]
                c["visual_positions_m"] = [c["shoot_end_m"]]
                for camera in (DiagnosticCamera(400, 400, (-5, 5, 20, 30)),
                               TopDownDiagnosticCamera(400, 400, (-5, 5, -5, 5))):
                    renderer = SpeciesRenderer(SimpleNamespace(camera=None))
                    draws = []
                    def draw_asset(screen, sim, camera, kind, point, rotation, scale, **kwargs):
                        if kind == "leaf":
                            draws.append((point, rotation))
                        return True
                    with patch.object(renderer, "_draw_module_asset", side_effect=draw_asset):
                        renderer._draw_individual(pygame.Surface((400, 400)), sim, camera=camera,
                                                  cache=False, visible_indices={c["host_placement_index"]},
                                                  foliage_sample_cap=1)
                    self.assertEqual(1, len(draws))
                    endpoint = camera.world_to_screen_3d(c["shoot_end_m"])
                    if structure == "needle_like":
                        self.assertEqual(endpoint, draws[0][0])
                        start = camera.world_to_screen_3d(c["shoot_start_m"])
                        expected = math.degrees(math.atan2(-(endpoint[0]-start[0]), -(endpoint[1]-start[1]))) + 5.
                        self.assertAlmostEqual(expected, draws[0][1])
                    else:
                        # Broad leaves spread around the endpoint at its
                        # height, rather than sampling the old shoot base.
                        spread = sim.blueprint.module("leaf").length_m * (.7 + .7 * c["visual_density"])
                        self.assertLessEqual(math.dist(endpoint, draws[0][0]), camera.scale * spread * 2.1 + 1)
                        if isinstance(camera, DiagnosticCamera):
                            self.assertEqual(endpoint[1], draws[0][0][1])
        finally:
            pygame.quit()


if __name__ == "__main__":
    unittest.main()
