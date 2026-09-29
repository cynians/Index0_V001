import gzip
import io
import json
import math
import unittest
from dataclasses import replace
from pathlib import Path

from simulations.species.plant_assets import (
    PlantAssetStore,
    PlantBlueprint,
    is_plant_species_entity,
    pixel_asset_depicted_size_m,
)
from simulations.species.species_renderer import (
    SpeciesRenderer,
    TopDownDiagnosticCamera,
    top_down_diagnostic_bounds,
)
from simulations.species.species_simulation import SpeciesSimulation


class SpeciesSimulationTests(unittest.TestCase):
    def test_shrub_organs_attach_to_shoot_tips_and_respect_leaf_arrangement(self):
        for arrangement, count in (("alternate", 1), ("distichous", 1),
                                   ("opposite", 2), ("whorled", 3)):
            with self.subTest(arrangement=arrangement):
                sim = SpeciesSimulation(species_entity={
                    "id": "spec_attachment_shrub", "plant_growth_form": "shrub",
                    "plant_growth_behaviour": "branched_woody",
                    "leaf_arrangement": arrangement,
                }, seed=303)
                sim.set_age(sim.mature_age_days)
                placements = sim.render_snapshot.placements
                shoots = [i for i, p in enumerate(placements)
                          if p[0] in {"stem_section", "branch_section"}]
                for i in shoots:
                    leaves = [p for p in placements if p[0] == "leaf" and p[1] == i]
                    self.assertEqual(count, len(leaves))
                for organ in (p for p in placements if p[0] in {"leaf", "flower"}):
                    self.assertEqual(placements[organ[1]][2:5], organ[2:5])

    def test_shrub_crown_spreads_in_three_dimensions_and_keeps_lod_zero_bare(self):
        sim = SpeciesSimulation(species_entity={
            "id": "spec_cane_shrub", "plant_growth_form": "shrub",
        }, seed=303)
        sim.set_age(sim.mature_age_days)
        snapshot = sim.render_snapshot
        canes = [p for p in snapshot.placements if p[0] == "stem_section" and p[1] == 0]
        self.assertGreater(len(canes), 1)
        self.assertGreater(max(p[2] for p in canes) - min(p[2] for p in canes), 0.1)
        self.assertGreater(max(p[3] for p in canes) - min(p[3] for p in canes), 0.1)
        self.assertEqual(snapshot.to_dict(), sim.generate_snapshot().to_dict())
        self.assertFalse(any(p[0] in {"leaf", "flower"}
                             for p in sim.generate_snapshot(lod=0).placements))
        seedling = sim.generate_snapshot(age_days=0)
        first_cane = next(p for p in seedling.placements if p[0] == "stem_section")
        self.assertGreater(first_cane[4], abs(first_cane[2]) + abs(first_cane[3]))

    def test_sparse_plant_rows_are_detected_but_animals_are_not(self):
        from world.plant_catalogue import PlantCatalogue, PLANTAE_ID
        plant = {"id":"p", "type":"species", "parents":[PLANTAE_ID]}
        catalogue = PlantCatalogue.build({PLANTAE_ID:{"type":"cladistics"}, "p":plant})
        self.assertTrue(is_plant_species_entity(plant, catalogue))
        for row in ({"type":"species", "common_name":"Eastern White Pine"},
                    {"type":"species", "plant_lifespan":"perennial"},
                    {"type":"species", "common_name":"Tree Sparrow"}):
            self.assertFalse(is_plant_species_entity(row, catalogue))

    def test_species_sim_is_independent_from_bioregion_state(self):
        sim = SpeciesSimulation(
            species_entity={
                "id": "spec_test_shrub",
                "common_name": "Test Shrub",
                "species_class": "natural_plant",
                "plant_growth_form": "shrub",
                "plant_growth_behaviour": "branched_woody",
            },
            seed=7,
        )

        self.assertEqual("species", sim.render_mode)
        self.assertNotIn("grid", sim.__dict__)
        self.assertNotIn("vegetation", sim.__dict__)
        self.assertGreater(sim.get_growth_summary()["stem_count"], 0)

    def test_growth_is_deterministic_and_age_changes_structure(self):
        entity = {
            "id": "spec_test_tree",
            "common_name": "Test Tree",
            "plant_growth_form": "tree",
        }
        first = SpeciesSimulation(species_entity=entity, seed=19)
        second = SpeciesSimulation(species_entity=entity, seed=19)
        self.assertEqual(first.render_snapshot.to_dict(), second.render_snapshot.to_dict())

        first.set_age(0)
        young_count = first.get_growth_summary()["placement_count"]
        first.set_age(first.mature_age_days)
        mature_count = first.get_growth_summary()["placement_count"]
        self.assertGreater(mature_count, young_count)

    def test_species_model_is_three_dimensional_and_keeps_projected_rendering(self):
        sim = SpeciesSimulation(
            species_entity={
                "id": "spec_3d_contract",
                "common_name": "3D Contract Plant",
                "plant_growth_form": "tree",
                "plant_growth_behaviour": "branched_woody",
            },
            seed=23,
        )
        snapshot = sim.render_snapshot
        self.assertEqual(3, snapshot.model_space["dimensions"])
        self.assertEqual("z", snapshot.model_space["up_axis"])
        self.assertEqual("orthographic", snapshot.model_space["projection"])
        self.assertEqual(len(snapshot.placements), len(snapshot.placement_orientations))
        for orientation in snapshot.placement_orientations.values():
            self.assertEqual(3, len(orientation["forward"]))
            self.assertEqual(3, len(orientation["right"]))
            self.assertEqual(3, len(orientation["up"]))
        scene = sim.get_scene_reference().to_dict()
        self.assertEqual("3d_orthographic", scene["model_space"])
        restored = type(snapshot).from_dict(snapshot.to_dict())
        self.assertEqual(snapshot.model_space, restored.model_space)
        self.assertEqual(snapshot.placement_orientations, restored.placement_orientations)

    def test_growth_forms_select_distinct_architectural_shapes(self):
        expected = {
            "tree": "tree",
            "shrub": "shrub",
            "subshrub": "subshrub",
            "forb": "forb",
            "graminoid": "graminoid",
            "fern": "fern",
            "moss": "moss",
            "succulent": "succulent",
            "aquatic": "aquatic",
            "vine": "climber",
        }
        for growth_form, shape in expected.items():
            with self.subTest(growth_form=growth_form):
                sim = SpeciesSimulation(
                    species_entity={"id": f"spec_form_{growth_form}", "plant_growth_form": growth_form},
                    seed=41,
                )
                sim.set_age(sim.mature_age_days)
                self.assertEqual(shape, sim.blueprint.growth["shape"])
                self.assertEqual(3, sim.render_snapshot.stats["model_dimensions"])
                self.assertGreater(sim.render_snapshot.stats["placement_count"], 0)

    def test_vine_searches_on_ground_then_climbs_a_reachable_tree_support(self):
        entity = {
            "id": "spec_vine_fixture",
            "plant_growth_form": "vine",
            "plant_growth_behaviour": "climbing_support_dependent",
            "mature_height": {"max_m": 5.0},
            "leaf_arrangement": "alternate",
        }
        ground = SpeciesSimulation(species_entity=entity, seed=417)
        ground.set_age(ground.mature_age_days)
        ground_stats = ground.render_snapshot.stats
        ground_stems = [p for p in ground.render_snapshot.placements if p[0] == "stem_section"]
        self.assertEqual("ground_search", ground_stats["vine_phase"])
        self.assertEqual(0, ground_stats["vine_support_contact_count"])
        self.assertLess(max(p[4] for p in ground_stems), 0.08)
        self.assertGreater(max(math.hypot(p[2], p[3]) for p in ground_stems), 4.5)
        self.assertLessEqual(ground_stats["vine_axis_length_m"], ground_stats["vine_axis_budget_m"] + 0.0001)

        environment = {"climbing_supports": [{
            "id": "tree_fixture",
            "kind": "tree",
            "center_m": [1.35, 0.15],
            "radius_m": 0.16,
            "height_m": 4.0,
            "crown_radius_m": 1.0,
        }]}
        climber = SpeciesSimulation(species_entity=entity, seed=417, environment=environment)
        climber.set_age(climber.mature_age_days)
        stats = climber.render_snapshot.stats
        self.assertEqual("climbing", stats["vine_phase"])
        self.assertEqual("tree_fixture", stats["vine_selected_support_id"])
        self.assertEqual("tree", stats["vine_selected_support_kind"])
        self.assertEqual(1, stats["vine_support_contact_count"])
        self.assertGreater(stats["vine_climbing_height_m"], 1.5)
        self.assertGreater(stats["vine_turn_count"], 1.0)
        self.assertAlmostEqual(
            stats["vine_axis_length_m"],
            stats["vine_ground_axis_length_m"] + stats["vine_climbing_axis_length_m"],
            places=4,
        )
        self.assertLessEqual(stats["vine_axis_length_m"], stats["vine_axis_budget_m"] + 0.02)
        contacts = [
            item for item in climber.render_snapshot.attachment_points
            if item.get("socket") == "support_contact"
        ]
        self.assertGreater(len(contacts), 1)
        self.assertTrue(all(item["support_id"] == "tree_fixture" for item in contacts))
        self.assertTrue(all(-1 <= p[1] < index for index, p in enumerate(climber.render_snapshot.placements)))
        repeat = SpeciesSimulation(species_entity=entity, seed=417, environment=environment)
        repeat.set_age(repeat.mature_age_days)
        self.assertEqual(climber.render_snapshot.to_dict(), repeat.render_snapshot.to_dict())

        juvenile = SpeciesSimulation(species_entity=entity, seed=417, environment=environment)
        juvenile.set_age(juvenile.mature_age_days * 0.1)
        self.assertEqual("ground_search", juvenile.render_snapshot.stats["vine_phase"])
        self.assertEqual(0, juvenile.render_snapshot.stats["vine_support_contact_count"])

    def test_vine_support_inputs_are_bounded_and_canonical_metrics_are_lod_stable(self):
        entity = {
            "id": "spec_vine_bounds",
            "plant_growth_form": "vine",
            "plant_growth_behaviour": "climbing_support_dependent",
            "mature_height": {"max_m": 3.0},
        }
        environment = {"climbing_supports": [
            None,
            {},
            {"center_m": [float("nan"), 0.0], "radius_m": 0.2, "height_m": 2.0},
            {"center_m": [50.0, 0.0], "radius_m": 0.2, "height_m": 2.0},
        ]}
        sim = SpeciesSimulation(species_entity=entity, seed=19, environment=environment)
        sim.set_age(sim.mature_age_days)
        stats = sim.render_snapshot.stats
        self.assertEqual(1, stats["vine_support_count"])
        self.assertIsNone(stats["vine_selected_support_id"])
        self.assertEqual("ground_search", stats["vine_phase"])
        canonical = {
            key: stats[key]
            for key in (
                "vine_phase", "vine_axis_budget_m", "vine_axis_length_m",
                "vine_ground_axis_length_m", "vine_climbing_axis_length_m",
                "vine_climbing_height_m", "vine_support_contact_count",
            )
        }
        for lod in (0, 1, 2):
            snapshot = sim.generate_snapshot(age_days=sim.mature_age_days, lod=lod)
            self.assertEqual(canonical, {key: snapshot.stats[key] for key in canonical})
            restored = type(snapshot).from_dict(snapshot.to_dict())
            self.assertEqual(snapshot.to_dict(), restored.to_dict())
        self.assertFalse(any(p[0] == "leaf" for p in sim.generate_snapshot(lod=0).placements))

    def test_dwarf_authored_height_keeps_the_shapes_branch_generation_density(self):
        # A shrub's internode length is a fixed constant sized for the
        # shape's reference stature (2.2 m). Authoring a much smaller
        # mature height (a genuine dwarf/low shrub) must scale that
        # internode down too, or branch generations collapse toward 1-2
        # and the plant renders as a bare skeletal stick rather than a
        # miniature of the same architecture.
        reference = SpeciesSimulation(species_entity={
            "id": "spec_reference_shrub", "plant_growth_form": "shrub",
            "plant_growth_behaviour": "branched_woody",
        }, seed=303)
        dwarf = SpeciesSimulation(species_entity={
            "id": "spec_dwarf_shrub", "plant_growth_form": "shrub",
            "plant_growth_behaviour": "branched_woody",
            "mature_height": {"max_m": 1.0},
        }, seed=303)
        reference.set_age(reference.mature_age_days)
        dwarf.set_age(dwarf.mature_age_days)

        reference_ratio = (reference.blueprint.growth["max_height_m"]
                            / reference.blueprint.growth["internode_length_m"])
        dwarf_ratio = (dwarf.blueprint.growth["max_height_m"]
                       / dwarf.blueprint.growth["internode_length_m"])
        self.assertAlmostEqual(reference_ratio, dwarf_ratio, places=3)
        self.assertGreater(dwarf.get_growth_summary()["branch_count"], 20)

        # An authored height at or above the shape's reference stature is
        # left untouched.
        tall = SpeciesSimulation(species_entity={
            "id": "spec_tall_shrub", "plant_growth_form": "shrub",
            "plant_growth_behaviour": "branched_woody",
            "mature_height": {"max_m": 3.0},
        }, seed=303)
        tall.set_age(tall.mature_age_days)
        self.assertEqual(reference.blueprint.growth["internode_length_m"],
                          tall.blueprint.growth["internode_length_m"])

    def test_unauthored_canopy_shape_varies_deterministically_by_species(self):
        # Without any authored visual-fit field, every species of a given
        # growth form used to render with bit-identical branch_droop /
        # crown_openness / fine_twig_density / leaf_cluster_density --
        # a landscape of unauthored species looked like visual clones. A
        # small deterministic per-species jitter on the *default* fixes
        # that while leaving authored values completely untouched.
        first = PlantBlueprint.from_species_entity(
            {"id": "spec_forb_variety_a", "plant_growth_form": "forb"}, "spec_forb_variety_a")
        second = PlantBlueprint.from_species_entity(
            {"id": "spec_forb_variety_b", "plant_growth_form": "forb"}, "spec_forb_variety_b")
        self.assertNotEqual(first.growth["crown_openness"], second.growth["crown_openness"])
        self.assertNotEqual(first.growth["branch_droop"], second.growth["branch_droop"])
        for growth in (first.growth, second.growth):
            for field in ("branch_droop", "crown_openness", "fine_twig_density", "leaf_cluster_density"):
                self.assertGreaterEqual(growth[field], 0.0)
                self.assertLessEqual(growth[field], 1.0)

        # Same species id is fully deterministic (reproducible across runs).
        repeat = PlantBlueprint.from_species_entity(
            {"id": "spec_forb_variety_a", "plant_growth_form": "forb"}, "spec_forb_variety_a")
        self.assertEqual(first.growth["crown_openness"], repeat.growth["crown_openness"])

        # An authored value is never touched by the jitter.
        authored = PlantBlueprint.from_species_entity({
            "id": "spec_forb_variety_a", "plant_growth_form": "forb",
            "plant_crown_openness": 0.5,
        }, "spec_forb_variety_a")
        self.assertEqual(0.5, authored.growth["crown_openness"])

    def test_species_sim_exposes_human_height_reference(self):
        sim = SpeciesSimulation(
            species_entity={"id": "spec_height_reference", "plant_growth_form": "forb"},
            seed=9,
        )
        reference = sim.get_height_reference()
        self.assertEqual("human_silhouette", reference["kind"])
        self.assertEqual(1.75, reference["height_m"])
        self.assertEqual(3, len(reference["position_m"]))
        self.assertLessEqual(sim.bounds["min_y"], -1.75)

    def test_species_diagnostic_tabs_and_camera_fit_use_same_simulation(self):
        sim = SpeciesSimulation(
            species_entity={
                "id": "spec_diagnostic_tabs",
                "plant_growth_form": "tree",
                "plant_growth_behaviour": "branched_woody",
            },
            seed=303,
        )
        self.assertEqual(
            {"individual", "top_down", "roots", "branches", "architecture", "editor", "gallery", "forest", "compare"},
            {tab["id"] for tab in sim.get_simulation_panel_tabs()},
        )
        self.assertTrue(sim.set_active_simulation_panel_tab("top_down"))
        self.assertTrue(sim.suppress_global_overlays)
        self.assertTrue(sim.set_active_simulation_panel_tab("forest"))
        self.assertTrue(sim.suppress_global_overlays)
        self.assertFalse(sim.set_active_simulation_panel_tab("unknown"))
        sim.set_active_simulation_panel_tab("individual")
        self.assertFalse(sim.suppress_global_overlays)
        self.assertGreater(sim.get_initial_camera_zoom(1200, 800), sim.min_zoom)

    def test_top_down_view_projects_model_xy_and_fits_the_live_crown(self):
        sim = SpeciesSimulation(
            species_entity={
                "id": "spec_top_down",
                "plant_growth_form": "tree",
                "plant_growth_behaviour": "branched_woody",
            },
            seed=303,
        )
        sim.set_age(sim.mature_age_days)
        bounds = top_down_diagnostic_bounds(sim)
        camera = TopDownDiagnosticCamera(800, 500, bounds)

        self.assertNotEqual(camera.world_to_screen_3d((0.0, 0.0, 0.0)),
                            camera.world_to_screen_3d((1.0, 1.0, 0.0)))
        self.assertEqual(camera.world_to_screen_3d((0.25, -0.4, 0.0)),
                         camera.world_to_screen_3d((0.25, -0.4, 12.0)))
        self.assertLess(bounds[0], bounds[1])
        self.assertLess(bounds[2], bounds[3])

    def test_functional_traits_shape_species_growth_recipe(self):
        sim = SpeciesSimulation(
            species_entity={
                "id": "spec_trait_tree",
                "plant_growth_form": "tree",
                "mature_height": {"max_m": 12},
                "growth_rate": "slow",
                "leaf_arrangement": "opposite",
                "plant_lifespan": "perennial",
            },
            seed=5,
        )
        self.assertEqual("tree", sim.blueprint.growth["shape"])
        self.assertEqual(12.0, sim.blueprint.growth["max_height_m"])
        self.assertEqual(0.28, sim.blueprint.growth["growth_rate_bias"])
        self.assertEqual(180.0, sim.blueprint.growth["phyllotaxis_deg"])

    def test_stoloniferous_clones_build_connected_rooting_nodes_and_ramets(self):
        entity = {
            "id": "spec_stoloniferous_clubmoss",
            "plant_growth_form": "other_unknown",
            "plant_growth_behaviour": "stoloniferous_clonal",
            "plant_lifespan": "perennial",
            "mature_height": {"max_m": 1.0},
            "leaf_size_class": "very_small",
            "leaf_arrangement": "spiral",
            "plant_lateral_axis_orientation": "mixed",
            "root_architecture": "adventitious",
            "root_depth_class": "shallow",
            "clonal_spread": "high",
        }
        first = SpeciesSimulation(species_entity=entity, seed=303)
        second = SpeciesSimulation(species_entity=entity, seed=303)
        first.set_age(first.mature_age_days)
        second.set_age(second.mature_age_days)

        snapshot = first.render_snapshot
        stats = snapshot.stats
        self.assertEqual(snapshot.to_dict(), second.render_snapshot.to_dict())
        self.assertEqual("stoloniferous_clonal", stats["clonal_behaviour"])
        self.assertEqual("high", stats["clonal_spread_class"])
        self.assertEqual(8, stats["clonal_ramet_count"])
        self.assertEqual(8, stats["clonal_rooting_node_count"])
        self.assertGreater(stats["clonal_axis_length_m"], stats["clonal_spread_radius_m"])
        self.assertGreater(stats["leaf_count"], stats["clonal_ramet_count"])
        self.assertGreater(stats["branch_count"], stats["clonal_ramet_count"])
        self.assertEqual("contact_nodes", stats["root_distribution"])
        self.assertEqual("distributed_adventitious_proxy", stats["root_model_status"])
        self.assertEqual(stats["clonal_rooting_node_count"], stats["root_cluster_count"])
        self.assertEqual(
            stats["clonal_rooting_node_count"],
            sum(placement[0] == "root_support" for placement in snapshot.placements),
        )
        support_indices = {
            index for index, placement in enumerate(snapshot.placements)
            if placement[0] == "root_support"
        }
        directly_rooted_supports = {
            placement[1] for placement in snapshot.placements
            if placement[0] == "root_section" and placement[1] in support_indices
        }
        self.assertEqual(support_indices, directly_rooted_supports)
        self.assertLess(stats["root_cluster_spread_m"], stats["root_system_span_m"])
        lod_zero = first.generate_snapshot(first.mature_age_days, lod=0)
        for key in ("root_depth_m", "root_length_m", "root_segment_count", "root_cluster_count"):
            self.assertEqual(stats[key], lod_zero.stats[key])
        self.assertLess(lod_zero.stats["root_visible_segment_count"], stats["root_visible_segment_count"])
        summary = first.get_growth_summary()
        self.assertEqual("contact_nodes", summary["root_distribution"])
        self.assertEqual(8, summary["root_cluster_count"])
        for index, placement in enumerate(snapshot.placements):
            parent = placement[1]
            self.assertTrue(parent < index)
            self.assertGreaterEqual(parent, -1)

    def test_distributed_contact_roots_are_trait_driven_and_reusable(self):
        base = {
            "plant_growth_form": "forb",
            "mature_height": {"max_m": 0.5},
            "root_architecture": "adventitious",
            "root_depth_class": "shallow",
            "clonal_spread": "low",
        }
        for behaviour in ("stoloniferous_clonal", "rhizomatous_clonal"):
            sim = SpeciesSimulation(
                species_entity={
                    **base,
                    "id": f"spec_reusable_{behaviour}",
                    "plant_growth_behaviour": behaviour,
                },
                seed=41,
            )
            sim.set_age(sim.mature_age_days)
            self.assertEqual("contact_nodes", sim.render_snapshot.stats["root_distribution"])
            self.assertEqual(
                sim.render_snapshot.stats["clonal_rooting_node_count"],
                sim.render_snapshot.stats["root_cluster_count"],
            )

        fibrous = SpeciesSimulation(
            species_entity={
                **base,
                "id": "spec_non_adventitious_stolon",
                "plant_growth_behaviour": "stoloniferous_clonal",
                "root_architecture": "fibrous",
            },
            seed=41,
        )
        fibrous.set_age(fibrous.mature_age_days)
        self.assertNotEqual("contact_nodes", fibrous.render_snapshot.stats.get("root_distribution"))

    def test_clonal_spread_changes_footprint_without_changing_authored_height(self):
        base = {
            "plant_growth_form": "other_unknown",
            "plant_growth_behaviour": "stoloniferous_clonal",
            "mature_height": {"max_m": 1.0},
            "leaf_size_class": "very_small",
        }
        cases = {}
        for spread in ("none", "low", "moderate", "high", "other_unknown"):
            sim = SpeciesSimulation(
                species_entity={**base, "id": f"spec_clone_{spread}", "clonal_spread": spread},
                seed=17,
            )
            sim.set_age(sim.mature_age_days)
            cases[spread] = sim

        self.assertLess(
            cases["low"].render_snapshot.stats["clonal_spread_radius_m"],
            cases["high"].render_snapshot.stats["clonal_spread_radius_m"],
        )
        self.assertLess(
            cases["low"].render_snapshot.stats["clonal_ramet_count"],
            cases["high"].render_snapshot.stats["clonal_ramet_count"],
        )
        self.assertEqual(1, cases["none"].render_snapshot.stats["clonal_ramet_count"])
        self.assertEqual(4, cases["other_unknown"].render_snapshot.stats["clonal_ramet_count"])
        for sim in cases.values():
            self.assertEqual(1.0, sim.blueprint.growth["max_height_m"])
            lod_zero = sim.generate_snapshot(sim.mature_age_days, lod=0)
            self.assertEqual(
                sim.render_snapshot.stats["clonal_ramet_count"],
                lod_zero.stats["clonal_ramet_count"],
            )
            self.assertFalse(any(row[0] == "leaf" for row in lod_zero.placements))

    def test_clonal_axis_topology_varies_by_seed_but_remains_deterministic(self):
        entity = {
            "id": "spec_seeded_rhizome",
            "plant_growth_form": "forb",
            "plant_growth_behaviour": "rhizomatous_clonal",
            "mature_height": {"max_m": 0.8},
            "root_architecture": "adventitious",
            "clonal_spread": "high",
        }
        cases = []
        for seed in range(1, 13):
            first = SpeciesSimulation(species_entity=entity, seed=seed)
            second = SpeciesSimulation(species_entity=entity, seed=seed)
            first.set_age(first.mature_age_days)
            second.set_age(second.mature_age_days)
            self.assertEqual(first.render_snapshot.to_dict(), second.render_snapshot.to_dict())
            cases.append(first.render_snapshot)
        self.assertGreater(len({case.stats["clonal_axis_count"] for case in cases}), 1)
        self.assertTrue(all(2 <= case.stats["clonal_axis_count"] <= 4 for case in cases))
        self.assertGreater(len({tuple(tuple(row) for row in case.placements) for case in cases}), 1)

    def test_clonal_axes_avoid_bounded_neighbour_root_influence_zones(self):
        entity = {
            "id": "spec_root_aware_rhizome",
            "plant_growth_form": "graminoid",
            "plant_growth_behaviour": "rhizomatous_clonal",
            "mature_height": {"max_m": 12.0},
            "root_architecture": "adventitious",
            "clonal_spread": "high",
        }
        zones = [
            {"id": "west", "center_m": [-1.35, 1.45], "radius_m": 0.42, "influence": 1.0},
            {"id": "east", "center_m": [1.15, -0.85], "radius_m": 0.42, "influence": 1.0},
        ]
        control = SpeciesSimulation(species_entity=entity, seed=149)
        treated = SpeciesSimulation(
            species_entity=entity, seed=149,
            environment={"neighbour_root_zones": zones},
        )
        duplicate = SpeciesSimulation(
            species_entity=entity, seed=149,
            environment={"neighbor_root_zones": zones},
        )
        for simulation in (control, treated, duplicate):
            simulation.set_age(simulation.mature_age_days)

        a, b = control.render_snapshot, treated.render_snapshot
        self.assertNotEqual(a.placements, b.placements)
        self.assertEqual(b.placements, duplicate.render_snapshot.placements)
        self.assertEqual(2, b.stats["neighbour_root_zone_count"])
        self.assertEqual("planar_influence_proxy", b.stats["neighbour_root_model_status"])
        self.assertGreater(b.stats["neighbour_root_avoidance_count"], 0)
        self.assertGreaterEqual(b.stats["neighbour_root_min_clearance_m"], 0.0)
        for key in (
            "clonal_axis_count", "clonal_ramet_count", "clonal_rooting_node_count",
            "clonal_spread_radius_m", "graminoid_culm_count",
        ):
            self.assertEqual(a.stats[key], b.stats[key])

        snapshots = [treated.generate_snapshot(treated.mature_age_days, lod=lod) for lod in range(3)]
        for key in (
            "clonal_axis_count", "clonal_ramet_count", "clonal_spread_radius_m",
            "neighbour_root_avoidance_count", "neighbour_root_min_clearance_m",
        ):
            self.assertEqual(1, len({snapshot.stats[key] for snapshot in snapshots}))

        malformed = SpeciesSimulation(
            species_entity=entity, seed=149,
            environment={"neighbour_root_zones": [None, {}, {"center_m": [0, 0], "radius_m": 0}]},
        )
        malformed.set_age(malformed.mature_age_days)
        self.assertEqual(0, malformed.render_snapshot.stats["neighbour_root_zone_count"])
        self.assertEqual(a.placements, malformed.render_snapshot.placements)

    def test_graminoid_form_composes_with_rhizomatous_clonal_behaviour(self):
        shared = {
            "id": "spec_generic_woody_clonal_grass",
            "plant_lifespan": "perennial",
            "plant_woodiness": "woody",
            "mature_height": {"max_m": 12.0},
            "leaf_length": {"typical_m": 0.12},
            "leaf_structure": "simple",
            "leaf_arrangement": "alternate",
            "leaf_attachment_pattern": "along_stem",
            "plant_leaf_distribution": "along_shoot",
            "plant_lateral_axis_orientation": "plagiotropic",
            "root_architecture": "adventitious",
            "belowground_storage": ["rhizome"],
            "clonal_spread": "high",
        }
        form_only = SpeciesSimulation(
            species_entity={**shared, "plant_growth_form": "graminoid"}, seed=149,
        )
        behaviour_only = SpeciesSimulation(
            species_entity={
                **shared,
                "plant_growth_form": "other_unknown",
                "plant_growth_behaviour": "rhizomatous_clonal",
            },
            seed=149,
        )
        combined = SpeciesSimulation(
            species_entity={
                **shared,
                "plant_growth_form": "graminoid",
                "plant_growth_behaviour": "rhizomatous_clonal",
            },
            seed=149,
        )
        for simulation in (form_only, behaviour_only, combined):
            simulation.set_age(simulation.mature_age_days)

        a = form_only.render_snapshot
        b = behaviour_only.render_snapshot
        ab = combined.render_snapshot
        self.assertTrue(a.stats["graminoid_culm_grammar"])
        self.assertFalse(b.stats["graminoid_culm_grammar"])
        self.assertTrue(ab.stats["graminoid_culm_grammar"])
        self.assertEqual(
            ["graminoid_culms", "rhizomatous_clonal"],
            ab.stats["composed_growth_grammars"],
        )
        self.assertEqual(ab.stats["clonal_ramet_count"], ab.stats["graminoid_culm_count"])
        self.assertGreater(ab.stats["graminoid_culm_node_count"], ab.stats["graminoid_culm_count"])
        self.assertGreater(ab.stats["graminoid_branch_complement_count"], 0)
        self.assertNotEqual(b.placements, ab.placements)

        # The clonal half of the contract is unchanged by the graminoid form.
        for key in (
            "clonal_ramet_count",
            "clonal_rooting_node_count",
            "clonal_axis_length_m",
            "clonal_spread_radius_m",
            "clonal_connector_depth_m",
            "root_cluster_count",
        ):
            self.assertEqual(b.stats[key], ab.stats[key])
        self.assertEqual("contact_nodes", ab.stats["root_distribution"])
        self.assertTrue(any(
            placement[0] == "leaf"
            and ab.placements[placement[1]][0] == "branch_section"
            for placement in ab.placements
        ))

        # Canonical composition quantities survive visual LOD changes.
        snapshots = [combined.generate_snapshot(combined.mature_age_days, lod=lod) for lod in range(3)]
        for key in (
            "clonal_ramet_count",
            "clonal_rooting_node_count",
            "clonal_axis_length_m",
            "graminoid_culm_count",
            "graminoid_culm_node_count",
            "graminoid_branch_complement_count",
        ):
            self.assertEqual(1, len({snapshot.stats[key] for snapshot in snapshots}))
        self.assertFalse(any(row[0] == "leaf" for row in snapshots[0].placements))
        for index, placement in enumerate(ab.placements):
            self.assertLess(placement[1], index)
            self.assertGreaterEqual(placement[1], -1)

    def test_tree_form_composes_with_suckering_clonal_behaviour(self):
        shared = {
            "id": "spec_generic_suckering_conifer",
            "plant_lifespan": "perennial",
            "plant_woodiness": "woody",
            "mature_height": {"max_m": 12.0},
            "leaf_structure": "needle_like",
            "leaf_arrangement": "spiral",
            "leaf_attachment_pattern": "along_stem",
            "plant_leaf_distribution": "along_shoot",
            "plant_lateral_axis_orientation": "mixed",
            "root_architecture": "mixed",
            "clonal_spread": "moderate",
        }
        behaviour_only = SpeciesSimulation(
            species_entity={
                **shared,
                "plant_growth_form": "other_unknown",
                "plant_growth_behaviour": "suckering_clonal",
            }, seed=211,
        )
        combined = SpeciesSimulation(
            species_entity={
                **shared,
                "plant_growth_form": "tree",
                "plant_growth_behaviour": "suckering_clonal",
            }, seed=211,
        )
        duplicate = SpeciesSimulation(species_entity=dict(combined.species_entity), seed=211)
        for simulation in (behaviour_only, combined, duplicate):
            simulation.set_age(simulation.mature_age_days)

        b = behaviour_only.render_snapshot
        ab = combined.render_snapshot
        self.assertEqual(ab.to_dict(), duplicate.render_snapshot.to_dict())
        self.assertTrue(ab.stats["tree_clonal_grammar"])
        self.assertEqual(["tree", "suckering_clonal"], ab.stats["composed_growth_grammars"])
        self.assertEqual(1, ab.stats["mature_tree_count"])
        self.assertEqual(ab.stats["clonal_ramet_count"], ab.stats["tree_sucker_count"])
        self.assertEqual(1 + ab.stats["tree_sucker_count"], ab.stats["tree_individual_count"])
        self.assertEqual(1, sum(placement[0] == "root" for placement in ab.placements))
        self.assertNotEqual(b.placements, ab.placements)
        for key in (
            "clonal_axis_count", "clonal_ramet_count", "clonal_axis_length_m",
            "clonal_spread_radius_m", "clonal_connector_depth_m",
        ):
            self.assertEqual(b.stats[key], ab.stats[key])
        clone_attachments = [
            item for item in ab.attachment_points
            if item.get("side") in {"clonal_ramet", "lateral"}
        ]
        self.assertTrue(clone_attachments)
        self.assertTrue(all("cluster_id" in item for item in clone_attachments))

        snapshots = [combined.generate_snapshot(combined.mature_age_days, lod=lod) for lod in range(3)]
        for key in (
            "clonal_axis_count", "clonal_ramet_count", "clonal_axis_length_m",
            "tree_sucker_count", "tree_individual_count",
        ):
            self.assertEqual(1, len({snapshot.stats[key] for snapshot in snapshots}))
        self.assertFalse(any(row[0] == "leaf" for row in snapshots[0].placements))

    def test_terminal_compound_frond_crowns_are_trait_driven_and_lod_stable(self):
        entity = {
            "id": "spec_generic_rhizomatous_frond_plant",
            "plant_growth_form": "other_unknown",
            "plant_growth_behaviour": "rhizomatous_clonal",
            "plant_lifespan": "perennial",
            "mature_height": {"min_m": 4.0, "typical_m": 7.0, "max_m": 10.0},
            "leaf_size_class": "very_large",
            "leaf_length": {"min_m": 5.0, "typical_m": 8.0, "max_m": 11.0},
            "leaf_structure": "pinnately_compound",
            "leaflet_count": {"min": 120, "typical": 135, "max": 150},
            "leaflet_length": {"min_m": 0.71, "typical_m": 1.10, "max_m": 1.79},
            "leaflet_width": {"min_m": 0.033, "typical_m": 0.060, "max_m": 0.095},
            "leaf_cluster_size": {"min": 6, "typical": 9, "max": 12},
            "plant_leaf_distribution": "terminal_cluster",
            "root_architecture": "adventitious",
            "clonal_spread": "high",
        }
        first = SpeciesSimulation(species_entity=entity, seed=719)
        second = SpeciesSimulation(species_entity=entity, seed=719)
        self.assertEqual(8.0, first.blueprint.growth["leaf_length_m"])
        self.assertEqual(135, first.blueprint.growth["leaflet_count"])
        self.assertEqual(9, first.blueprint.growth["leaf_cluster_size"])

        detailed = first.generate_snapshot(first.mature_age_days, lod=2)
        self.assertEqual(detailed.to_dict(), second.generate_snapshot(second.mature_age_days, lod=2).to_dict())
        self.assertTrue(detailed.stats["terminal_frond_crown_grammar"])
        self.assertEqual(8, detailed.stats["frond_crown_count"])
        self.assertEqual(detailed.stats["clonal_ramet_count"], detailed.stats["frond_crown_count"])
        self.assertEqual(9, detailed.stats["fronds_per_crown"])
        self.assertEqual(72, detailed.stats["estimated_frond_count"])
        self.assertEqual(72, detailed.stats["visible_frond_count"])
        self.assertEqual(135, detailed.stats["leaflets_per_frond"])
        self.assertEqual(9_720, detailed.stats["estimated_leaflet_count"])
        self.assertEqual(8, len(detailed.leaf_clusters))

        for cluster in detailed.leaf_clusters:
            self.assertEqual("terminal_cluster", cluster["leaf_distribution"])
            self.assertEqual("pinnately_compound", cluster["organ_structure"])
            self.assertEqual(9, cluster["estimated_leaf_count"])
            self.assertEqual(135, cluster["leaflet_count_per_leaf"])
            host = cluster["host_placement_index"]
            self.assertEqual("stem_section", detailed.placements[host][0])
            self.assertEqual(9, len(cluster["sample_placement_indices"]))
            for leaf_index in cluster["sample_placement_indices"]:
                self.assertEqual("leaf", detailed.placements[leaf_index][0])
                self.assertEqual(host, detailed.placements[leaf_index][1])
                self.assertEqual(detailed.placements[host][2:5], detailed.placements[leaf_index][2:5])

        self.assertEqual(72, len(detailed.attachment_points))
        self.assertTrue(all(item["socket"] == "terminal_crown" for item in detailed.attachment_points))
        invariants = (
            "clonal_ramet_count", "clonal_rooting_node_count", "frond_crown_count",
            "fronds_per_crown", "estimated_frond_count", "leaflets_per_frond",
            "estimated_leaflet_count", "leaf_area_m2", "root_segment_count",
        )
        lod_zero = first.generate_snapshot(first.mature_age_days, lod=0)
        lod_one = first.generate_snapshot(first.mature_age_days, lod=1)
        for key in invariants:
            self.assertEqual(detailed.stats[key], lod_zero.stats[key], key)
            self.assertEqual(detailed.stats[key], lod_one.stats[key], key)
        self.assertEqual(0, lod_zero.stats["visible_frond_count"])
        self.assertEqual(0, lod_zero.stats["leaf_count"])
        self.assertEqual(40, lod_one.stats["visible_frond_count"])
        self.assertEqual(40, lod_one.stats["leaf_count"])

        control = SpeciesSimulation(
            species_entity={**entity, "plant_leaf_distribution": "along_shoot"},
            seed=719,
        ).generate_snapshot(first.mature_age_days, lod=2)
        self.assertFalse(control.stats["terminal_frond_crown_grammar"])
        self.assertEqual(0, control.stats["frond_crown_count"])
        self.assertGreater(control.stats["stem_count"], detailed.stats["stem_count"])

        # The same grammar remains reusable by other frond-like plants and
        # depends on no species identifier.
        frond_like = SpeciesSimulation(
            species_entity={**entity, "id": "spec_other_frond_plant", "leaf_structure": "frond_like"},
            seed=719,
        ).generate_snapshot(first.mature_age_days, lod=2)
        self.assertTrue(frond_like.stats["terminal_frond_crown_grammar"])
        self.assertEqual(72, frond_like.stats["estimated_frond_count"])
        frond_like_module = next(module for module in frond_like.modules.values() if module["id"] == "leaf")
        self.assertEqual(0.16, frond_like_module["visual"]["frond_arch"])

    def test_hierarchical_fern_fronds_are_botanical_leaves_on_rhizome_sockets(self):
        entity = {
            "id": "spec_generic_divided_fern",
            "plant_growth_form": "fern",
            "plant_growth_behaviour": "fern_fronding",
            "plant_lifespan": "perennial",
            "plant_life_form": "geophyte",
            "mature_height": {"min_m": 0.6, "typical_m": 1.2, "max_m": 2.0},
            "leaf_length": {"min_m": 0.6, "typical_m": 1.2, "max_m": 2.0},
            "leaf_structure": "frond_like",
            "leaf_arrangement": "alternate",
            "leaf_division_order": 3,
            "leaflet_count": {"min": 20, "typical": 24, "max": 30},
            "leaflet_length": {"min_m": 0.07, "typical_m": 0.25, "max_m": 0.50},
            "leaflet_width": {"min_m": 0.03, "typical_m": 0.09, "max_m": 0.15},
            "frond_stipe_fraction": {"min": 0.32, "typical": 0.42, "max": 0.50},
            "belowground_storage": ["rhizome"],
            "root_architecture": "adventitious",
            "max_root_depth": {"max_m": 1.0},
            "clonal_spread": "high",
        }
        first = SpeciesSimulation(species_entity=entity, seed=863)
        second = SpeciesSimulation(species_entity=entity, seed=863)
        self.assertEqual(3, first.blueprint.growth["leaf_division_order"])
        self.assertEqual(0.42, first.blueprint.growth["frond_stipe_fraction"])
        self.assertEqual(24, first.blueprint.growth["leaflet_count"])

        detailed = first.generate_snapshot(first.mature_age_days, lod=2)
        self.assertEqual(detailed.to_dict(), second.generate_snapshot(second.mature_age_days, lod=2).to_dict())
        self.assertTrue(detailed.stats["hierarchical_frond_grammar"])
        self.assertEqual("spaced_sockets", detailed.stats["rhizome_frond_distribution"])
        self.assertEqual(8, detailed.stats["canonical_frond_count"])
        self.assertEqual(8, detailed.stats["visible_frond_count"])
        self.assertEqual(3, detailed.stats["frond_division_order"])
        self.assertEqual(24, detailed.stats["primary_pinnae_per_frond"])
        self.assertEqual("alternate", detailed.stats["primary_pinna_arrangement"])
        self.assertEqual(192, detailed.stats["estimated_primary_pinna_count"])
        self.assertEqual(8, detailed.stats["leaf_count"])
        self.assertEqual(8, detailed.stats["leaf_cluster_count"])
        self.assertEqual(8, detailed.stats["estimated_leaf_count"])
        self.assertEqual(8, detailed.stats["rhizome_rooting_node_count"])
        self.assertEqual(8, detailed.stats["root_cluster_count"])
        self.assertEqual("contact_nodes", detailed.stats["root_distribution"])
        self.assertFalse(any(row[0] == "stem_section" for row in detailed.placements))

        for cluster in detailed.leaf_clusters:
            self.assertEqual(1, cluster["estimated_leaf_count"])
            self.assertEqual("frond_like", cluster["organ_structure"])
            self.assertEqual(3, cluster["leaf_division_order"])
            self.assertEqual(24, cluster["primary_pinna_count"])
            self.assertEqual("alternate", cluster["primary_pinna_arrangement"])
            self.assertEqual(1, len(cluster["sample_placement_indices"]))
            leaf_index = cluster["sample_placement_indices"][0]
            self.assertEqual("leaf", detailed.placements[leaf_index][0])
        self.assertEqual(8, len(detailed.attachment_points))
        self.assertTrue(all(item["socket"] == "frond" for item in detailed.attachment_points))
        self.assertTrue(all(
            detailed.placements[item["stem_placement_index"]][0] == "branch_section"
            for item in detailed.attachment_points
        ))
        for index, placement in enumerate(detailed.placements):
            self.assertLess(int(placement[1]), index)
            self.assertGreaterEqual(int(placement[1]), -1)

        invariants = (
            "canonical_frond_count", "frond_division_order", "primary_pinnae_per_frond",
            "primary_pinna_arrangement",
            "estimated_primary_pinna_count", "leaf_area_m2", "rhizome_axis_length_m",
            "rhizome_rooting_node_count", "root_segment_count", "root_cluster_count",
        )
        lod_zero = first.generate_snapshot(first.mature_age_days, lod=0)
        lod_one = first.generate_snapshot(first.mature_age_days, lod=1)
        for key in invariants:
            self.assertEqual(detailed.stats[key], lod_zero.stats[key], key)
            self.assertEqual(detailed.stats[key], lod_one.stats[key], key)
        self.assertEqual(0, lod_zero.stats["visible_frond_count"])
        self.assertEqual(0, lod_zero.stats["leaf_count"])
        self.assertEqual(4, lod_one.stats["visible_frond_count"])
        self.assertEqual(4, lod_one.stats["leaf_count"])

        once_divided = SpeciesSimulation(
            species_entity={**entity, "leaf_division_order": 1},
            seed=863,
        ).generate_snapshot(first.mature_age_days, lod=2)
        self.assertEqual(1, once_divided.stats["frond_division_order"])
        for key in ("canonical_frond_count", "estimated_primary_pinna_count", "leaf_area_m2", "root_segment_count"):
            self.assertEqual(detailed.stats[key], once_divided.stats[key])

        compact = SpeciesSimulation(
            species_entity={**entity, "id": "spec_crown_fern", "belowground_storage": [], "clonal_spread": "none"},
            seed=863,
        ).generate_snapshot(first.mature_age_days, lod=2)
        self.assertEqual("compact_crown", compact.stats["rhizome_frond_distribution"])
        self.assertNotEqual("contact_nodes", compact.stats.get("root_distribution"))

    def test_fern_clonal_spread_and_bad_division_values_are_bounded(self):
        base = {
            "plant_growth_form": "fern",
            "plant_growth_behaviour": "fern_fronding",
            "plant_life_form": "geophyte",
            "belowground_storage": ["rhizome"],
            "root_architecture": "adventitious",
            "leaf_structure": "frond_like",
            "leaf_division_order": 0,
            "frond_stipe_fraction": {"typical": -3},
        }
        counts = {}
        lengths = {}
        for spread in ("low", "moderate", "high", "other_unknown"):
            sim = SpeciesSimulation(
                species_entity={**base, "id": f"spec_fern_{spread}", "clonal_spread": spread},
                seed=41,
            )
            snapshot = sim.generate_snapshot(sim.mature_age_days, lod=2)
            counts[spread] = snapshot.stats["canonical_frond_count"]
            lengths[spread] = snapshot.stats["rhizome_axis_length_m"]
            self.assertEqual(1, sim.blueprint.growth["leaf_division_order"])
            self.assertEqual(0.0, sim.blueprint.growth["frond_stipe_fraction"])
        self.assertEqual((3, 5, 8, 5), tuple(counts[key] for key in ("low", "moderate", "high", "other_unknown")))
        self.assertLess(lengths["low"], lengths["high"])

    def test_tree_architecture_fields_reach_blueprint_snapshot_and_topology(self):
        base = {
            "plant_growth_form": "tree",
            "plant_growth_behaviour": "branched_woody",
            "plant_lifespan": "perennial",
            "mature_height": {"max_m": 24},
            "plant_leaf_distribution": "terminal_cluster",
            "plant_shoot_dimorphism": "single_shoot_system",
            "plant_fine_twig_density": 0.4,
            "plant_leaf_cluster_density": 0.6,
        }
        cases = {
            "birch": SpeciesSimulation(species_entity={
                **base, "id": "spec_arch_birch",
                "plant_axis_continuity": "sympodial",
                "plant_branching_rhythm": "diffuse",
                "plant_branching_timing": "mixed",
                "plant_lateral_axis_orientation": "plagiotropic",
                "plant_flowering_position": "mixed",
                "plant_apical_control": 0.82,
            }, seed=303),
            "oak": SpeciesSimulation(species_entity={
                **base, "id": "spec_arch_oak",
                "plant_axis_continuity": "monopodial",
                "plant_branching_rhythm": "continuous",
                "plant_branching_timing": "delayed",
                "plant_lateral_axis_orientation": "plagiotropic",
                "plant_flowering_position": "lateral",
                "plant_apical_control": 0.42,
            }, seed=303),
            "chestnut": SpeciesSimulation(species_entity={
                **base, "id": "spec_arch_chestnut", "leaf_arrangement": "opposite",
                "plant_axis_continuity": "monopodial_to_sympodial",
                "plant_branching_rhythm": "rhythmic",
                "plant_branching_timing": "delayed",
                "plant_lateral_axis_orientation": "mixed",
                "plant_flowering_position": "terminal",
                "plant_apical_control": 0.60,
            }, seed=303),
        }
        for simulation in cases.values():
            simulation.set_age(simulation.mature_age_days)

        self.assertEqual("sympodial", cases["birch"].get_growth_summary()["axis_continuity"])
        self.assertEqual("continuous", cases["oak"].blueprint.growth["branching_rhythm"])
        self.assertEqual("terminal", cases["chestnut"].get_growth_summary()["flowering_position"])
        self.assertEqual(0.6, cases["chestnut"].get_growth_summary()["apical_control"])

        chestnut_placements = cases["chestnut"].render_snapshot.placements
        trunk_indices = {index for index, placement in enumerate(chestnut_placements)
                         if placement[0] == "stem_section"}
        branch_hosts = {}
        for placement in chestnut_placements:
            if placement[0] == "branch_section" and placement[1] in trunk_indices:
                branch_hosts[placement[1]] = branch_hosts.get(placement[1], 0) + 1
        self.assertGreaterEqual(len(branch_hosts), 2)
        # Opposite-arrangement branches always come in pairs (branches_per_tier=2);
        # a host can now carry more than one tier's worth (an even multiple of
        # 2) since higher tier density means adjacent tiers can round to the
        # same discrete trunk node -- the *pairing* is the real invariant,
        # not "exactly one tier per host".
        self.assertTrue(all(count % 2 == 0 for count in branch_hosts.values()))
        self.assertNotEqual(
            cases["oak"].render_snapshot.placements,
            cases["chestnut"].render_snapshot.placements,
        )

    def test_authored_plant_module_references_reach_blueprint(self):
        sim = SpeciesSimulation(
            species_entity={
                "id": "spec_asset_refs",
                "plant_growth_form": "graminoid",
                "plant_growth_behaviour": "tussock_tillering",
                "leaf_structure": "pinnately_compound",
                "plant_leaf_module_ref": "assets/illustrations/leaf.png",
                "plant_flower_module_ref": "assets/illustrations/flower.png",
                "plant_stem_module_ref": "assets/illustrations/stem.png",
                "plant_branch_module_ref": "assets/illustrations/branch.png",
                "plant_fruit_module_ref": "assets/illustrations/fruit.png",
            },
            seed=12,
        )
        self.assertEqual("assets/illustrations/leaf.png", sim.blueprint.module("leaf").asset_ref)
        self.assertEqual("assets/illustrations/flower.png", sim.blueprint.module("flower").asset_ref)
        self.assertEqual("pinnately_compound", sim.blueprint.growth["leaf_structure"])
        self.assertEqual("assets/illustrations/stem.png", sim.blueprint.module("stem_section").asset_ref)
        self.assertEqual("assets/illustrations/branch.png", sim.blueprint.module("branch_section").asset_ref)
        self.assertEqual("assets/illustrations/fruit.png", sim.blueprint.module("fruit").asset_ref)

    def test_authored_module_anchors_reach_blueprint(self):
        sim = SpeciesSimulation(
            species_entity={
                "id": "spec_anchor_refs",
                "plant_growth_form": "graminoid",
                "plant_module_anchors": {
                    "leaf": {"attachment_point": [0.5, 0.92], "growth_vector": [0.0, -1.0]},
                },
            },
            seed=12,
        )
        self.assertEqual((0.5, 0.92), sim.blueprint.module("leaf").attachment_point)
        self.assertEqual((0.0, -1.0), sim.blueprint.module("leaf").growth_axis)

    def test_one_leaf_asset_can_be_mirrored_for_the_alternate_side(self):
        self.assertFalse(SpeciesRenderer._mirror_leaf_for_rotation("leaf", 0.0))
        self.assertTrue(SpeciesRenderer._mirror_leaf_for_rotation("leaf", 300.0))
        self.assertFalse(SpeciesRenderer._mirror_leaf_for_rotation("flower", 180.0))

    def test_single_axis_has_one_culm_alternating_leaves_and_one_terminal_flower(self):
        sim = SpeciesSimulation(
            species_entity={
                "id": "spec_single_culm",
                "plant_growth_form": "graminoid",
                "plant_growth_behaviour": "unbranched_single_axis",
                "plant_lifespan": "short_lived_perennial",
                "plant_flower_module_ref": "assets/illustrations/spike.png",
            },
            seed=12,
        )
        sim.set_age(200)
        self.assertEqual(0, sum(1 for item in sim.render_snapshot.placements if item[0] == "branch_section"))
        self.assertEqual(1, sum(1 for item in sim.render_snapshot.placements if item[0] == "flower"))
        self.assertLess(sim.render_snapshot.stats["leaf_count"], sim.render_snapshot.stats["stem_count"])
        self.assertEqual(sim.render_snapshot.stats["leaf_count"], len(sim.render_snapshot.attachment_points))
        self.assertEqual(
            [sim.render_snapshot.placements[item["stem_placement_index"]][2:5] for item in sim.render_snapshot.attachment_points],
            [placement[2:5] for placement in sim.render_snapshot.placements if placement[0] == "leaf"],
        )

    def test_tussock_grass_adds_authored_inflorescence_after_reproductive_onset(self):
        sim = SpeciesSimulation(
            species_entity={
                "id": "spec_asset_grass",
                "plant_growth_form": "graminoid",
                "plant_growth_behaviour": "tussock_tillering",
                "plant_lifespan": "short_lived_perennial",
                "plant_flower_module_ref": "assets/illustrations/spike.png",
            },
            seed=12,
        )
        sim.set_age(200)
        self.assertEqual("reproductive", sim.get_growth_summary()["life_phase"])
        self.assertGreater(
            sum(1 for item in sim.render_snapshot.placements if item[0] == "flower"),
            0,
        )
        self.assertEqual(
            "assets/illustrations/spike.png",
            sim.render_snapshot.modules["flower"]["asset_ref"],
        )

    def test_aquatic_rosette_has_submerged_rhizome_surface_leaves_and_one_flower(self):
        sim = SpeciesSimulation(
            species_entity={
                "id": "spec_water_lily",
                "plant_growth_form": "aquatic",
                "plant_growth_behaviour": "rhizomatous_clonal",
                "plant_lifespan": "perennial",
                "plant_flower_module_ref": "assets/illustrations/water_lily.png",
            },
            seed=21,
        )
        sim.set_age(180)
        placements = sim.render_snapshot.placements
        self.assertEqual("aquatic", sim.blueprint.growth["shape"])
        self.assertLess(next(item[4] for item in placements if item[0] == "root"), 0.0)
        self.assertTrue(all(item[4] == 0.0 for item in placements if item[0] == "leaf"))
        self.assertGreater(sum(1 for item in placements if item[0] == "stem_section"), 0)
        self.assertEqual(2, sum(1 for item in placements if item[0] == "flower"))
        self.assertGreater(len(sim.render_snapshot.placement_paths), 0)
        self.assertEqual(
            sim.render_snapshot.stats["leaf_count"],
            len(sim.render_snapshot.attachment_points),
        )

    def test_woody_branching_can_bake_curved_stem_paths(self):
        sim = SpeciesSimulation(
            species_entity={
                "id": "spec_curved_tree",
                "plant_growth_form": "tree",
                "plant_growth_behaviour": "branched_woody",
                "plant_lifespan": "perennial",
                "mature_height": {"max_m": 20},
                "plant_flower_module_ref": "assets/illustrations/catkin.png",
            },
            seed=31,
        )
        sim.set_age(365)
        self.assertGreater(sum(1 for item in sim.render_snapshot.placements if item[0] == "branch_section"), 0)
        self.assertGreater(len(sim.render_snapshot.placement_paths), 0)
        self.assertLess(len(sim.render_snapshot.placement_paths), 200)
        self.assertGreater(len(sim.render_snapshot.attachment_points), 0)
        self.assertGreater(sum(1 for item in sim.render_snapshot.placements if item[0] == "flower"), 0)
        self.assertGreater(sim.get_growth_summary()["branch_count"], 0)

    def test_mixed_long_short_shoots_distribute_birch_leaves(self):
        sim = SpeciesSimulation(
            species_entity={
                "id": "spec_birch_architecture",
                "plant_growth_form": "tree",
                "plant_growth_behaviour": "branched_woody",
                "plant_lifespan": "perennial",
                "mature_height": {"max_m": 30},
                "plant_shoot_dimorphism": "long_and_short_shoots",
                "plant_leaf_distribution": "mixed_long_short_shoots",
                "plant_leaf_spacing_bias": 0.72,
                "plant_branch_droop": 0.78,
                "plant_branch_angle_gradient": 0.66,
                "plant_crown_openness": 0.80,
                "plant_leaf_depth_gradient": 0.56,
            },
            seed=303,
        )
        sim.set_age(sim.mature_age_days)

        # Default snapshot represents foliage as calculative cohorts rather
        # than one placement per leaf, so a mature crown stays cheap to
        # simulate/render (see docs/species_sim... perf notes).
        snapshot = sim.render_snapshot
        self.assertEqual(0, sum(1 for item in snapshot.placements if item[0] == "leaf"))
        self.assertGreater(snapshot.stats["leaf_cluster_count"], 20)
        self.assertGreater(snapshot.stats["estimated_leaf_count"], 100)
        self.assertEqual(
            snapshot.stats["estimated_leaf_count"],
            sum(cluster["estimated_leaf_count"] for cluster in snapshot.leaf_clusters),
        )
        shoot_types = {cluster["shoot_type"] for cluster in snapshot.leaf_clusters}
        self.assertIn("short", shoot_types)
        self.assertIn("long", shoot_types)
        self.assertEqual("mixed_long_short_shoots", sim.blueprint.growth["leaf_distribution"])

        # On-demand full detail (close-up diagnostics) reruns the exact same
        # deterministic per-leaf geometry the coarse pass now skips.
        detailed = sim.get_detailed_snapshot()
        leaves = [item for item in detailed.placements if item[0] == "leaf"]
        self.assertGreaterEqual(len(leaves), 20)
        self.assertGreater(len({round(item[2], 2) for item in leaves}), 6)
        self.assertEqual(detailed.stats["leaf_count"], len(detailed.attachment_points))
        self.assertGreater(detailed.stats["estimated_leaf_count"], detailed.stats["leaf_count"])
        self.assertEqual(
            detailed.stats["estimated_leaf_count"],
            sum(cluster["estimated_leaf_count"] for cluster in detailed.leaf_clusters),
        )

    def test_shoot_distribution_grammar_flowers_without_a_flower_asset(self):
        # tree_shoots.py used to gate flower *placement itself* behind an
        # authored plant_flower_module_ref, even though SpeciesRenderer
        # already has a plain-colour fallback for an unasseted flower
        # placement (see species_renderer.py's generic placement-kind
        # fallback). That meant flowers never appeared at all -- not even
        # as a fallback dot -- for any shoot_distribution_grammar tree
        # without a flower pixel asset, regardless of reproductive_factor.
        dimorphic = SpeciesSimulation(species_entity={
            "id": "spec_flower_fallback_dimorphic", "plant_growth_form": "tree",
            "plant_growth_behaviour": "branched_woody", "plant_lifespan": "perennial",
            "mature_height": {"max_m": 20}, "plant_shoot_dimorphism": "long_and_short_shoots",
            "plant_leaf_distribution": "mixed_long_short_shoots",
        }, seed=303)
        terminal = SpeciesSimulation(species_entity={
            "id": "spec_flower_fallback_terminal", "plant_growth_form": "tree",
            "plant_growth_behaviour": "branched_woody", "plant_lifespan": "perennial",
            "mature_height": {"max_m": 20}, "plant_leaf_distribution": "along_shoot",
            "plant_flowering_position": "terminal",
        }, seed=303)
        for sim in (dimorphic, terminal):
            self.assertIsNone(sim.blueprint.module("flower").asset_ref)
            reproductive_start = sim.blueprint.growth["life_history"]["reproductive_start_days"]
            sim.set_age(reproductive_start + 5)
            self.assertGreater(sim.render_snapshot.stats.get("reproductive_factor", 0.0), 0.0)
            flower_count = sum(1 for item in sim.render_snapshot.placements if item[0] == "flower")
            self.assertGreater(flower_count, 0)

        # Lateral/axillary flowering on a single shoot system uses a real
        # base socket instead of being silently dropped.
        lateral_single_shoot = SpeciesSimulation(species_entity={
            "id": "spec_flower_fallback_lateral", "plant_growth_form": "tree",
            "plant_growth_behaviour": "branched_woody", "plant_lifespan": "perennial",
            "mature_height": {"max_m": 20}, "plant_shoot_dimorphism": "single_shoot_system",
            "plant_leaf_distribution": "along_shoot", "plant_flowering_position": "lateral",
        }, seed=303)
        reproductive_start = lateral_single_shoot.blueprint.growth["life_history"]["reproductive_start_days"]
        lateral_single_shoot.set_age(reproductive_start + 5)
        self.assertGreater(lateral_single_shoot.render_snapshot.stats.get("reproductive_factor", 0.0), 0.0)
        lateral_flowers = [item for item in lateral_single_shoot.render_snapshot.placements if item[0] == "flower"]
        self.assertGreater(len(lateral_flowers), 0)
        for flower in lateral_flowers:
            self.assertEqual(lateral_single_shoot.render_snapshot.placements[flower[1]][2:5], flower[2:5])

        mixed_single_shoot = SpeciesSimulation(species_entity={
            "id": "spec_cone_fallback_mixed", "plant_growth_form": "tree",
            "plant_growth_behaviour": "branched_woody", "plant_lifespan": "perennial",
            "mature_height": {"max_m": 20}, "plant_shoot_dimorphism": "single_shoot_system",
            "plant_leaf_distribution": "along_shoot", "plant_flowering_position": "mixed",
            "plant_reproductive_structure": "cone",
        }, seed=303)
        mixed_single_shoot.set_age(
            mixed_single_shoot.blueprint.growth["life_history"]["reproductive_start_days"] + 5
        )
        self.assertGreater(
            sum(1 for item in mixed_single_shoot.render_snapshot.placements if item[0] == "flower"),
            0,
        )

    def test_pixel_document_depicted_size_is_visual_metadata_not_structural_length(self):
        document_path = Path("artifacts/reproductive_organs_v001/_metric_size_test.layers.json.gz")
        asset_path = document_path.with_name("_metric_size_test.png")
        document_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with gzip.open(document_path, "wt", encoding="utf-8") as handle:
                json.dump({"dimensions_m": {"size": 0.008}}, handle)
            self.assertEqual(0.008, pixel_asset_depicted_size_m(str(asset_path)))
            blueprint = PlantBlueprint.from_species_entity({
                "id": "spec_metric_flower",
                "plant_growth_form": "shrub",
                "plant_flower_module_ref": str(asset_path),
            })
            flower = blueprint.module("flower")
            self.assertEqual(0.008, flower.visual["depicted_size_m"])
            self.assertEqual(0.16, flower.length_m)
            round_trip = PlantBlueprint.from_dict(blueprint.to_dict())
            self.assertEqual(0.008, round_trip.module("flower").visual["depicted_size_m"])
            self.assertEqual(0.16, round_trip.module("flower").length_m)

            legacy_blueprint = replace(
                blueprint,
                modules=[
                    replace(module, visual={}) if module.id == "flower" else module
                    for module in blueprint.modules
                ],
            )
            current = SpeciesSimulation(species_entity={"id": "spec_metric_flower"}, blueprint=blueprint, seed=303)
            legacy = SpeciesSimulation(species_entity={"id": "spec_metric_flower"}, blueprint=legacy_blueprint, seed=303)
            current.set_age(current.mature_age_days)
            legacy.set_age(legacy.mature_age_days)
            self.assertEqual(legacy.render_snapshot.placements, current.render_snapshot.placements)
            self.assertEqual(legacy.render_snapshot.bounds_m, current.render_snapshot.bounds_m)
            self.assertEqual(legacy.render_snapshot.stats, current.render_snapshot.stats)
            self.assertEqual(legacy.get_ecological_outcome(), current.get_ecological_outcome())
        finally:
            document_path.unlink(missing_ok=True)

    def test_low_apical_control_produces_co_dominant_multi_trunk_individuals(self):
        # Every shoot_distribution_grammar tree used to build exactly one
        # perfectly-centred trunk regardless of species. Weak apical
        # dominance (real multi-stemmed trees: lindens, river birches) must
        # now sometimes fork into 2-3 co-dominant trunks from the base,
        # rolled per individual so the same species shows a mix across
        # seeds the way a real stand does.
        base = {
            "id": "spec_multitrunk_test", "plant_growth_form": "tree",
            "plant_growth_behaviour": "branched_woody", "plant_lifespan": "perennial",
            "mature_height": {"max_m": 12}, "plant_leaf_distribution": "along_shoot",
        }
        weak = {**base, "plant_apical_control": 0.15}
        strong = {**base, "plant_apical_control": 0.98}

        def trunk_count(entity, seed):
            sim = SpeciesSimulation(species_entity=entity, seed=seed)
            sim.set_age(sim.mature_age_days)
            return sum(1 for p in sim.render_snapshot.placements
                       if p[0] == "stem_section" and p[1] == 0)

        weak_counts = [trunk_count(weak, seed) for seed in range(1, 13)]
        strong_counts = [trunk_count(strong, seed) for seed in range(1, 13)]

        self.assertTrue(any(count > 1 for count in weak_counts),
                         "expected at least one multi-trunk individual across 12 seeds at low apical control")
        self.assertTrue(any(count == 1 for count in weak_counts),
                         "expected at least one single-trunk individual too -- not every individual forks")
        self.assertTrue(all(count == 1 for count in strong_counts),
                         "very strong apical dominance should essentially never fork")

        # Determinism: same seed, same species -> identical trunk count.
        self.assertEqual(trunk_count(weak, 3), trunk_count(weak, 3))

        # A multi-trunk individual's total branch/leaf mass matches a
        # single-trunk individual's -- forking redistributes the same
        # canopy across more stems, it doesn't multiply it, so it can't
        # silently inflate ecological quantities.
        single_seed = next(seed for seed, count in zip(range(1, 13), weak_counts) if count == 1)
        multi_seed = next(seed for seed, count in zip(range(1, 13), weak_counts) if count > 1)
        single_sim = SpeciesSimulation(species_entity=weak, seed=single_seed)
        multi_sim = SpeciesSimulation(species_entity=weak, seed=multi_seed)
        single_sim.set_age(single_sim.mature_age_days)
        multi_sim.set_age(multi_sim.mature_age_days)
        single_branch_count = sum(1 for p in single_sim.render_snapshot.placements if p[0] == "branch_section")
        multi_branch_count = sum(1 for p in multi_sim.render_snapshot.placements if p[0] == "branch_section")
        self.assertLess(abs(single_branch_count - multi_branch_count), max(single_branch_count, multi_branch_count) * 0.35)

    def test_longevity_class_and_maturity_drive_trunk_gnarliness(self):
        # Every tree trunk used to be a smooth, monotonically-tapering tube
        # regardless of species or age. A long-lived (or resprouting) tree's
        # trunk should now visibly twist/thicken irregularly as it matures,
        # driven by longevity_class/resprouting/maturity -- no new field.
        base = {
            "id": "spec_gnarl_test", "plant_growth_form": "tree",
            "plant_growth_behaviour": "branched_woody", "plant_lifespan": "perennial",
            "mature_height": {"max_m": 20}, "plant_leaf_distribution": "along_shoot",
            "plant_apical_control": 0.95,  # force a single trunk so only gnarl varies
        }

        def tortuosity(entity, seed, age_fraction=1.0):
            # path length walked / straight-line distance start->end -- 1.0
            # is a perfectly straight trunk, higher is more gnarled/winding.
            sim = SpeciesSimulation(species_entity=entity, seed=seed)
            sim.set_age(round(sim.mature_age_days * age_fraction))
            trunk = [p for p in sim.render_snapshot.placements if p[0] == "stem_section" and p[7] == 1]
            points = [(0.0, 0.0, -0.08)] + [(p[2], p[3], p[4]) for p in trunk]
            path_len = sum(math.dist(points[i], points[i + 1]) for i in range(len(points) - 1))
            straight = math.dist(points[0], points[-1])
            return path_len / straight if straight else 1.0

        very_short = {**base, "longevity_class": "very_short"}
        very_long = {**base, "longevity_class": "very_long"}

        short_tort = tortuosity(very_short, seed=5)
        long_tort = tortuosity(very_long, seed=5)
        self.assertGreater(long_tort, short_tort * 1.1,
                            "a very-long-lived mature trunk should wind visibly more than a very-short-lived one")

        # Determinism: same seed/species -> identical path.
        self.assertEqual(tortuosity(very_long, seed=5), tortuosity(very_long, seed=5))

        # Gnarl scales with maturity -- a young individual of the same
        # long-lived species should look much straighter than the mature one.
        young_tort = tortuosity(very_long, seed=5, age_fraction=0.15)
        self.assertGreater(long_tort, young_tort * 1.1,
                            "gnarl should grow with maturity, not be fully expressed on a young trunk")
        self.assertLess(young_tort, 1.15, "a young trunk should still read as close to straight")

        # Unauthored longevity_class must not collapse every species to one
        # identical gnarl strength (the same "unauthored trait -> visually
        # identical" bug already fixed for colour/canopy-shape defaults) --
        # two different unauthored species ids should differ.
        unauthored = [tortuosity({**base, "id": f"spec_gnarl_unauthored_{letter}"}, seed=5)
                      for letter in "abcde"]
        self.assertGreater(len(set(round(value, 4) for value in unauthored)), 1,
                            "unauthored species shouldn't all collapse to one identical gnarl strength")

    def test_axis_continuity_overrides_longevity_for_trunk_gnarliness(self):
        # Longevity alone is the wrong predictor: some very long-lived trees
        # (coast redwood, most single-leader conifers) stay famously straight
        # and columnar, while others (mulberries, many sympodial broadleafs)
        # characteristically gnarl. axis_continuity -- monopodial (one
        # continuous leader, mechanically straight) vs sympodial (successive
        # lateral takeover, the real cause of a zigzag axis) -- must gate the
        # gnarl mechanism, not just longevity_class/maturity.
        base = {
            "id": "spec_axis_gnarl_test", "plant_growth_form": "tree",
            "plant_growth_behaviour": "branched_woody", "plant_lifespan": "perennial",
            "mature_height": {"max_m": 20}, "plant_leaf_distribution": "along_shoot",
            "plant_apical_control": 0.95, "longevity_class": "very_long",
        }

        def tortuosity(entity, seed=5):
            sim = SpeciesSimulation(species_entity=entity, seed=seed)
            sim.set_age(sim.mature_age_days)
            trunk = [p for p in sim.render_snapshot.placements if p[0] == "stem_section" and p[7] == 1]
            points = [(0.0, 0.0, -0.08)] + [(p[2], p[3], p[4]) for p in trunk]
            path_len = sum(math.dist(points[i], points[i + 1]) for i in range(len(points) - 1))
            straight = math.dist(points[0], points[-1])
            return path_len / straight if straight else 1.0

        monopodial_tort = tortuosity({**base, "plant_axis_continuity": "monopodial"})
        sympodial_tort = tortuosity({**base, "plant_axis_continuity": "sympodial"})
        self.assertGreater(sympodial_tort, monopodial_tort * 1.1,
                            "sympodial growth should wind visibly more than monopodial growth, same longevity/maturity/seed")
        self.assertLess(monopodial_tort, 1.02,
                         "a monopodial (single dominant leader) tree should read as essentially straight, "
                         "like a real coast redwood -- not just 'less gnarled than average'")

    def test_apical_control_still_modulates_very_long_sympodial_gnarl(self):
        # The old hard clamp saturated both cases at gnarl_trait=1.0, making
        # an authored apical-control contrast invisible precisely in the
        # long-lived sympodial trees where the mechanism was strongest.
        base = {
            "id": "spec_sympodial_apical_gnarl_test",
            "plant_growth_form": "tree",
            "plant_growth_behaviour": "branched_woody",
            "plant_lifespan": "perennial",
            "mature_height": {"max_m": 20},
            "plant_leaf_distribution": "along_shoot",
            "plant_axis_continuity": "sympodial",
            "longevity_class": "very_long",
        }

        def tortuosity(apical_control):
            sim = SpeciesSimulation(
                species_entity={**base, "plant_apical_control": apical_control},
                seed=303,
            )
            sim.set_age(sim.mature_age_days)
            trunk = [
                p for p in sim.render_snapshot.placements
                if p[0] == "stem_section" and p[7] == 1
            ]
            points = [(0.0, 0.0, -0.08)] + [(p[2], p[3], p[4]) for p in trunk]
            path_len = sum(math.dist(points[i], points[i + 1]) for i in range(len(points) - 1))
            straight = math.dist(points[0], points[-1])
            return path_len / straight

        weak_control = tortuosity(0.2)
        strong_control = tortuosity(0.8)
        self.assertGreater(
            weak_control,
            strong_control * 1.03,
            "stronger apical control should still reduce gnarl before the bounded response saturates",
        )

    def test_tree_shoot_branch_angle_gradient_rotates_lower_and_upper_axes(self):
        base = {
            "id": "spec_tree_branch_angle_gradient_test",
            "plant_growth_form": "tree",
            "plant_growth_behaviour": "branched_woody",
            "plant_lifespan": "perennial",
            "mature_height": {"max_m": 20},
            "plant_leaf_distribution": "along_shoot",
            "plant_axis_continuity": "monopodial",
            "plant_apical_control": 0.9,
        }

        def first_order_rises(value):
            sim = SpeciesSimulation(
                species_entity={**base, "plant_branch_angle_gradient": value},
                seed=303,
            )
            sim.set_age(sim.mature_age_days)
            placements = sim.render_snapshot.placements
            trunk_height = max(
                p[4] for p in placements if p[0] == "stem_section" and p[7] == 1
            )
            rises = []
            for placement in placements:
                if placement[0] != "branch_section" or placement[7] != 2:
                    continue
                parent = placements[placement[1]]
                if parent[0] != "stem_section":
                    continue
                crown_fraction = parent[4] / trunk_height
                rises.append((crown_fraction, placement[4] - parent[4]))
            return rises

        low = first_order_rises(0.1)
        high = first_order_rises(0.9)
        self.assertEqual([round(item[0], 6) for item in low], [round(item[0], 6) for item in high])

        def mean_band(rows, lower):
            values = [rise for fraction, rise in rows if (fraction < 0.55) == lower]
            self.assertTrue(values)
            return sum(values) / len(values)

        self.assertLess(mean_band(high, True), mean_band(low, True))
        self.assertGreater(mean_band(high, False), mean_band(low, False))

    def test_trunk_girth_scales_radius_and_defaults_to_unchanged(self):
        # Nothing represented trunk girth-to-height ratio at all before this
        # -- every tree used the same fixed height-fraction radius
        # regardless of species (flagged as a follow-up during the trunk
        # multiplicity/lean pass). plant_trunk_girth: 0 (unauthored) must
        # reproduce the original radius exactly; a higher authored value
        # should read as a visibly stouter, pachycaul-style trunk.
        base = {
            "id": "spec_girth_test", "plant_growth_form": "tree",
            "plant_growth_behaviour": "branched_woody", "plant_lifespan": "perennial",
            "mature_height": {"max_m": 20}, "plant_leaf_distribution": "along_shoot",
            "plant_apical_control": 0.95,
        }

        def base_radius(entity, seed=5):
            sim = SpeciesSimulation(species_entity=entity, seed=seed)
            sim.set_age(sim.mature_age_days)
            trunk = [p for p in sim.render_snapshot.placements if p[0] == "stem_section" and p[7] == 1]
            return trunk[0][6]

        unauthored_radius = base_radius(base)
        explicit_zero_radius = base_radius({**base, "plant_trunk_girth": 0.0})
        self.assertEqual(unauthored_radius, explicit_zero_radius,
                          "unauthored trunk_girth must render identically to an explicit 0")

        half_radius = base_radius({**base, "plant_trunk_girth": 0.5})
        full_radius = base_radius({**base, "plant_trunk_girth": 1.0})
        self.assertGreater(half_radius, unauthored_radius,
                            "an authored trunk_girth should visibly thicken the trunk")
        self.assertGreater(full_radius, half_radius,
                            "trunk_girth should scale monotonically with the authored value")
        # 0 -> 1x, 1 -> 4x (see tree_shoots.py's girth_multiplier).
        self.assertAlmostEqual(full_radius / unauthored_radius, 4.0, places=2)

    def test_monopodial_trees_including_a_real_coast_redwood_render_near_straight(self):
        # User feedback with a reference photo: real coast redwoods are
        # famously ramrod-straight, not just "less wiggly than other
        # trees" -- lean and the small baseline path wiggle (not only the
        # gnarl mechanism) both needed gating by axis_continuity, since a
        # monopodial single dominant leader mechanically resists lateral
        # lean, not only zigzag/gnarl.
        from world.world_model import WorldModel

        def lateral_ratio(sim):
            sim.set_age(sim.mature_age_days)
            trunk = [p for p in sim.render_snapshot.placements if p[0] == "stem_section" and p[7] == 1]
            height = trunk[-1][4]
            max_lateral = max(math.hypot(p[2], p[3]) for p in trunk)
            return max_lateral / height if height else 0.0

        world = WorldModel()
        resolved = world.resolved_species_entity("spec_sequoia_sempervirens")
        for seed in (1, 2, 3, 303):
            with self.subTest(seed=seed):
                sim = SpeciesSimulation(world_model=world, species_id="spec_sequoia_sempervirens",
                                         species_entity=resolved, seed=seed)
                ratio = lateral_ratio(sim)
                self.assertLess(ratio, 0.05,
                                 f"seed {seed}: coast redwood trunk should stay within 5% of height laterally, got {ratio:.3f}")

    def test_self_pruning_raises_the_lowest_branch_up_the_trunk(self):
        # Every tree used to start its lowest branch at the same fixed
        # trunk-node fraction (~25% of height) regardless of species. Real
        # trees vary hugely: a self-pruning conifer (coast redwood, white
        # pine) holds a long clear trunk with foliage only near the top,
        # while a non-self-pruning species keeps branches low.
        base = {
            "id": "spec_self_pruning_test", "plant_growth_form": "tree",
            "plant_growth_behaviour": "branched_woody", "plant_lifespan": "perennial",
            "mature_height": {"max_m": 30}, "plant_leaf_distribution": "along_shoot",
            "plant_apical_control": 0.9, "plant_axis_continuity": "monopodial",
        }

        def lowest_branch_fraction(self_pruning, seed=303):
            entity = {**base}
            if self_pruning is not None:
                entity["plant_self_pruning"] = self_pruning
            sim = SpeciesSimulation(species_entity=entity, seed=seed)
            sim.set_age(sim.mature_age_days)
            height = max(p[4] for p in sim.render_snapshot.placements if p[0] == "stem_section" and p[7] == 1)
            branch_starts = [p[4] for p in sim.render_snapshot.placements
                              if p[0] == "branch_section" and p[7] == 2]
            return min(branch_starts) / height

        none_fraction = lowest_branch_fraction("none")
        unauthored_fraction = lowest_branch_fraction(None)
        moderate_fraction = lowest_branch_fraction("moderate")
        strong_fraction = lowest_branch_fraction("strong")

        self.assertLess(none_fraction, unauthored_fraction)
        self.assertLess(unauthored_fraction, moderate_fraction)
        self.assertLess(moderate_fraction, strong_fraction)
        self.assertGreater(strong_fraction, 0.6,
                            "a strong self-pruner should hold a long clear trunk, crown only near the top")

        # Determinism and maturity-scaling: a young strong self-pruner
        # hasn't self-pruned yet, so it should branch much lower than a
        # mature one of the same species.
        young_entity = {**base, "plant_self_pruning": "strong"}
        young_sim = SpeciesSimulation(species_entity=young_entity, seed=303)
        young_sim.set_age(round(young_sim.mature_age_days * 0.2))
        young_height = max(p[4] for p in young_sim.render_snapshot.placements
                            if p[0] == "stem_section" and p[7] == 1)
        young_branch_starts = [p[4] for p in young_sim.render_snapshot.placements
                                if p[0] == "branch_section" and p[7] == 2]
        young_fraction = min(young_branch_starts) / young_height
        self.assertLess(young_fraction, strong_fraction,
                         "a young strong self-pruner shouldn't already have a fully cleared trunk")

    def test_a_real_coast_redwood_holds_a_long_clear_trunk(self):
        # User feedback: real coast redwoods don't just grow straight (the
        # earlier fix), the crown also doesn't begin until way up the
        # trunk. Re-checked against real reference photographs
        # (iNaturalist/Wikimedia): a mature individual reads as a long bare
        # trunk with foliage concentrated near the top, not a "round" crown
        # occupying much of the tree's height. Authored
        # plant_self_pruning=strong (previously "moderate" -- the theory
        # that crown_shape=irregular needed the extra vertical room to
        # read as round didn't hold up against the photos; the "irregular"
        # envelope width/floor were narrowed instead, see tree_shoots.py's
        # _crown_shape_targets).
        from world.world_model import WorldModel

        world = WorldModel()
        resolved = world.resolved_species_entity("spec_sequoia_sempervirens")
        self.assertEqual("strong", resolved.get("plant_self_pruning"))
        sim = SpeciesSimulation(world_model=world, species_id="spec_sequoia_sempervirens",
                                 species_entity=resolved, seed=303)
        sim.set_age(sim.mature_age_days)
        height = max(p[4] for p in sim.render_snapshot.placements if p[0] == "stem_section" and p[7] == 1)
        branch_starts = [p[4] for p in sim.render_snapshot.placements
                          if p[0] == "branch_section" and p[7] == 2]
        self.assertGreater(min(branch_starts) / height, 0.5,
                            "a mature coast redwood should hold a long clear trunk before the crown begins")

    def test_crown_shape_biases_the_canopy_envelope(self):
        # Every tree used to fill the exact same fixed branch-reach envelope
        # (peak at 42% of height) regardless of species -- a conical conifer,
        # a small flat-topped "umbrella" crown, and a broad spreading canopy
        # all looked identical apart from height/colour.
        base = {
            "id": "spec_crown_shape_test", "plant_growth_form": "tree",
            "plant_growth_behaviour": "branched_woody", "plant_lifespan": "perennial",
            "mature_height": {"max_m": 30}, "plant_leaf_distribution": "along_shoot",
            "plant_apical_control": 0.9, "plant_axis_continuity": "monopodial",
        }

        def reach_by_band(crown_shape, seed=303):
            entity = {**base}
            if crown_shape is not None:
                entity["plant_crown_shape"] = crown_shape
            sim = SpeciesSimulation(species_entity=entity, seed=seed)
            sim.set_age(sim.mature_age_days)
            height = max(p[4] for p in sim.render_snapshot.placements if p[0] == "stem_section" and p[7] == 1)
            branches = [p for p in sim.render_snapshot.placements if p[0] == "branch_section" and p[7] == 2]
            low = [math.hypot(p[2], p[3]) for p in branches if p[4] / height < 0.4]
            high = [math.hypot(p[2], p[3]) for p in branches if p[4] / height > 0.75]
            return (sum(low) / len(low) if low else 0.0), (sum(high) / len(high) if high else 0.0)

        conical_low, conical_high = reach_by_band("conical")
        umbrella_low, umbrella_high = reach_by_band("umbrella")
        default_low, default_high = reach_by_band(None)

        self.assertGreater(conical_low, conical_high,
                            "a conical crown should reach further near the base than near the top")
        self.assertGreater(umbrella_high, umbrella_low,
                            "an umbrella crown should reach further near the top than near the base")
        # Unauthored/default species reproduce the original fixed envelope.
        self.assertAlmostEqual(default_low, reach_by_band("ovoid")[0], places=3)
        self.assertAlmostEqual(default_high, reach_by_band("ovoid")[1], places=3)

    def test_a_real_scots_pine_shows_a_small_umbrella_crown_on_a_long_trunk(self):
        # User request: a Scots pine ("Kiefer") has "a very characteristic
        # long, long trunk with a small crown on top" -- added as a new
        # species specifically to exercise crown_shape + self_pruning
        # together.
        from world.world_model import WorldModel

        world = WorldModel()
        resolved = world.resolved_species_entity("spec_pinus_sylvestris")
        self.assertEqual("umbrella", resolved.get("plant_crown_shape"))
        self.assertEqual("strong", resolved.get("plant_self_pruning"))
        sim = SpeciesSimulation(world_model=world, species_id="spec_pinus_sylvestris",
                                 species_entity=resolved, seed=303)
        sim.set_age(sim.mature_age_days)
        height = max(p[4] for p in sim.render_snapshot.placements if p[0] == "stem_section" and p[7] == 1)
        branch_starts = [p[4] for p in sim.render_snapshot.placements
                          if p[0] == "branch_section" and p[7] == 2]
        self.assertGreater(min(branch_starts) / height, 0.5,
                            "a mature Scots pine should hold a long clear trunk before the crown begins")

    def test_leaf_cluster_density_is_continuous_between_tree_species_profiles(self):
        base = {
            "id": "spec_cluster_density_tree",
            "plant_growth_form": "tree",
            "plant_growth_behaviour": "branched_woody",
            "plant_lifespan": "perennial",
            "mature_height": {"max_m": 30},
            "plant_shoot_dimorphism": "long_and_short_shoots",
            "plant_leaf_distribution": "mixed_long_short_shoots",
            "plant_fine_twig_density": 0.75,
        }
        sparse = SpeciesSimulation(
            species_entity={**base, "plant_leaf_cluster_density": 0.15},
            seed=71,
        )
        dense = SpeciesSimulation(
            species_entity={**base, "plant_leaf_cluster_density": 0.85},
            seed=71,
        )
        sparse.set_age(sparse.mature_age_days)
        dense.set_age(dense.mature_age_days)
        self.assertEqual(sparse.render_snapshot.stats["leaf_cluster_count"], dense.render_snapshot.stats["leaf_cluster_count"])
        self.assertLess(
            sparse.render_snapshot.stats["estimated_leaf_count"],
            dense.render_snapshot.stats["estimated_leaf_count"],
        )
        # Visual density only changes how many samples a cluster expands to
        # for rendering, never how many real leaf placements the generator
        # materializes at full detail.
        sparse_detailed = sparse.get_detailed_snapshot()
        dense_detailed = dense.get_detailed_snapshot()
        self.assertEqual(sparse_detailed.stats["leaf_sample_count"], dense_detailed.stats["leaf_sample_count"])

    def test_fascicle_size_drives_shared_socket_needle_bundles(self):
        base = {
            "id": "spec_generic_fascicled_tree",
            "plant_growth_form": "tree",
            "plant_growth_behaviour": "branched_woody",
            "plant_lifespan": "perennial",
            "mature_height": {"max_m": 15},
            "leaf_structure": "needle_like",
            "leaf_arrangement": "fascicled",
            "leaf_clustering": "tufted",
            "plant_shoot_dimorphism": "long_and_short_shoots",
            "plant_leaf_distribution": "mixed_long_short_shoots",
            "plant_leaf_cluster_density": 0.75,
        }
        two = SpeciesSimulation(species_entity={**base, "leaf_fascicle_size": 2}, seed=509)
        five = SpeciesSimulation(species_entity={**base, "leaf_fascicle_size": 5}, seed=509)
        for sim, expected_size in ((two, 2), (five, 5)):
            sim.set_age(sim.mature_age_days)
            coarse = sim.render_snapshot
            detailed = sim.get_detailed_snapshot()
            self.assertEqual(expected_size, sim.blueprint.growth["fascicle_size"])
            self.assertEqual(expected_size, coarse.stats["leaf_fascicle_size"])
            self.assertGreater(coarse.stats["leaf_fascicle_count"], 0)
            self.assertEqual(
                coarse.stats["leaf_fascicle_count"] * expected_size,
                coarse.stats["estimated_fascicled_leaf_count"],
            )
            self.assertEqual(
                coarse.stats["estimated_fascicled_leaf_count"],
                detailed.stats["estimated_fascicled_leaf_count"],
            )
            # Every full-detail fascicle materialises all needles at the same
            # short-shoot socket; orientation, not position, separates them.
            per_socket = {}
            for placement in detailed.placements:
                if placement[0] == "leaf":
                    key = (placement[1], tuple(placement[2:5]))
                    per_socket[key] = per_socket.get(key, 0) + 1
            self.assertTrue(per_socket)
            self.assertEqual({expected_size}, set(per_socket.values()))

        self.assertLess(
            two.render_snapshot.stats["estimated_fascicled_leaf_count"],
            five.render_snapshot.stats["estimated_fascicled_leaf_count"],
        )
        alternate = SpeciesSimulation(
            species_entity={**base, "leaf_arrangement": "alternate", "leaf_fascicle_size": 5},
            seed=509,
        )
        alternate.set_age(alternate.mature_age_days)
        self.assertEqual(0, alternate.blueprint.growth["fascicle_size"])
        self.assertEqual(0, alternate.render_snapshot.stats["leaf_fascicle_count"])
        self.assertEqual(0, alternate.render_snapshot.stats["estimated_fascicled_leaf_count"])

    def test_short_telemetry_run_reports_growth_and_ecological_state(self):
        sim = SpeciesSimulation(
            species_entity={
                "id": "spec_telemetry_grass",
                "plant_growth_form": "graminoid",
                "plant_growth_behaviour": "tussock_tillering",
                "plant_lifespan": "short_lived_perennial",
                "growth_rate": "fast",
                "maturity_rate": "fast",
            },
            seed=13,
        )
        sim.set_age(0)
        telemetry = sim.simulate_days(5)
        self.assertEqual(6, len(telemetry))
        self.assertEqual(0.0, telemetry[0]["elapsed_days"])
        self.assertEqual(5.0, telemetry[-1]["elapsed_days"])
        self.assertEqual("juvenile", telemetry[0]["life_phase"])
        self.assertGreaterEqual(telemetry[-1]["maturity"], telemetry[0]["maturity"])
        self.assertGreater(telemetry[-1]["placement_count"], 0)
        self.assertIn("vitality", telemetry[-1])
        self.assertIn("fecundity", telemetry[-1])

    def test_lifespan_dropdown_resolves_to_species_sim_life_phases(self):
        cases = {
            "ephemeral": (40.0, "senescent"),
            "annual": (250.0, "reproductive"),
            "biennial": (500.0, "reproductive"),
            "short_lived_perennial": (200.0, "reproductive"),
            "perennial": (10_000.0, "senescent"),
        }
        for lifespan, (age_days, expected_phase) in cases.items():
            with self.subTest(lifespan=lifespan):
                sim = SpeciesSimulation(
                    species_entity={
                        "id": f"spec_{lifespan}",
                        "plant_growth_form": "forb",
                        "plant_lifespan": lifespan,
                    },
                    seed=6,
                )
                self.assertEqual(lifespan, sim.blueprint.growth["life_history"]["class"])
                sim.set_age(age_days)
                self.assertEqual(expected_phase, sim.get_growth_summary()["life_phase"])
                self.assertEqual(expected_phase, sim.life_state()["phase"])

    def test_slow_perennial_has_a_reproductive_window_after_maturity(self):
        sim = SpeciesSimulation(
            species_entity={
                "id": "spec_slow_perennial_tree",
                "plant_growth_form": "tree",
                "plant_growth_behaviour": "branched_woody",
                "plant_lifespan": "perennial",
                "maturity_rate": "slow",
            },
            seed=10,
        )
        sim.set_age(sim.mature_age_days)
        self.assertEqual("reproductive", sim.life_state()["phase"])

    def test_terminal_lifespans_stop_ecological_contribution_after_death(self):
        sim = SpeciesSimulation(
            species_entity={
                "id": "spec_annual_life",
                "plant_growth_form": "forb",
                "plant_lifespan": "annual",
            },
            seed=8,
        )
        sim.set_age(sim.max_age_days)
        outcome = sim.get_ecological_outcome()
        self.assertEqual("dead", outcome["life_history"]["phase"])
        self.assertEqual(0.0, outcome["vitality"])
        self.assertEqual(0.0, outcome["fecundity"])
        self.assertEqual(1.0, outcome["mortality_risk"])

    def test_missing_lifespan_uses_transient_default_without_authoring_it(self):
        sim = SpeciesSimulation(
            species_entity={"id": "spec_unknown_life", "plant_growth_form": "forb"},
            seed=9,
        )
        self.assertEqual("perennial", sim.blueprint.growth["life_history"]["class"])
        self.assertEqual("runtime_default", sim.blueprint.growth["life_history"]["source"])
        self.assertNotIn("plant_lifespan", sim.species_entity)

    def test_geophyte_life_form_moves_the_renewal_origin_below_soil(self):
        entity = {
            "id": "spec_geophyte_contract",
            "plant_growth_form": "forb",
            "plant_growth_behaviour": "determinate_sympodial",
            "plant_life_form": "geophyte",
            "belowground_storage": ["corm"],
            "mature_height_class": "low",
            "root_architecture": "adventitious",
        }
        sim = SpeciesSimulation(species_entity=entity, seed=303)
        sim.set_age(sim.mature_age_days)
        snapshot = sim.render_snapshot
        kinds = [placement[0] for placement in snapshot.placements]
        organ_index = kinds.index("renewal_organ")
        bud_index = kinds.index("renewal_bud")
        first_stem = next(placement for placement in snapshot.placements if placement[0] == "stem_section")

        self.assertEqual("geophyte", sim.blueprint.growth["plant_life_form"])
        self.assertEqual(["corm"], sim.blueprint.growth["belowground_storage"])
        self.assertEqual(bud_index, first_stem[1])
        self.assertTrue(any(
            placement[1] == organ_index and placement[0] in {"root_support", "root_section"}
            for placement in snapshot.placements
        ))
        self.assertLess(snapshot.placements[organ_index][4], 0.0)
        self.assertLess(snapshot.placements[bud_index][4], 0.0)
        self.assertEqual(1, snapshot.stats["renewal_bud_count"])
        self.assertEqual("corm", snapshot.stats["renewal_organ_kind"])
        self.assertEqual("runtime_default", snapshot.stats["renewal_bud_depth_source"])
        self.assertGreater(snapshot.stats["renewal_bud_depth_m"], 0.0)
        self.assertEqual(0.0, snapshot.stats["root_origin_z_m"])
        self.assertLess(snapshot.stats["root_growth_origin_z_m"], 0.0)
        self.assertIn("renewal_organ", snapshot.modules)
        self.assertIn("renewal_bud", snapshot.modules)
        self.assertTrue(all(parent < index for index, (_, parent, *_rest) in enumerate(snapshot.placements)
                            if parent >= 0))

        low_detail = sim.generate_snapshot(lod=0)
        self.assertEqual(1, low_detail.stats["renewal_bud_count"])
        self.assertEqual(snapshot.stats["renewal_bud_depth_m"], low_detail.stats["renewal_bud_depth_m"])

    def test_non_geophyte_retains_surface_growth_origin(self):
        sim = SpeciesSimulation(species_entity={
            "id": "spec_surface_origin",
            "plant_growth_form": "tree",
            "plant_life_form": "phanerophyte",
        }, seed=303)
        sim.set_age(sim.mature_age_days)
        snapshot = sim.render_snapshot
        self.assertFalse(any(placement[0].startswith("renewal_") for placement in snapshot.placements))
        self.assertEqual(0, snapshot.stats["renewal_bud_count"])
        self.assertEqual("none", snapshot.stats["renewal_organ_kind"])
        self.assertEqual(snapshot.stats["root_origin_z_m"], snapshot.stats["root_growth_origin_z_m"])

    def test_lod_reduces_leaf_detail_without_changing_species_recipe(self):
        sim = SpeciesSimulation(
            species_entity={"id": "spec_test_herb", "plant_growth_form": "herb"},
            seed=3,
        )
        full = sim.generate_snapshot(age_days=sim.mature_age_days, lod=2)
        skeleton = sim.generate_snapshot(age_days=sim.mature_age_days, lod=0)
        self.assertLess(skeleton.stats["placement_count"], full.stats["placement_count"])
        self.assertEqual(full.blueprint_fingerprint, skeleton.blueprint_fingerprint)
        self.assertNotIn("leaf", skeleton.modules)

    def test_rosette_leaf_sockets_stay_clustered_at_the_surface_crown(self):
        sim = SpeciesSimulation(
            species_entity={
                "id": "spec_test_rosette",
                "plant_growth_form": "forb",
                "plant_growth_behaviour": "rosette_short_internode",
                "leaf_attachment_pattern": "basal_rosette",
            },
            seed=303,
        )
        snapshot = sim.generate_snapshot(age_days=sim.mature_age_days, lod=2)
        leaves = [placement for placement in snapshot.placements if placement[0] == "leaf"]

        self.assertEqual(12, len(leaves))
        self.assertLessEqual(max(math.hypot(leaf[2], leaf[3]) for leaf in leaves), 0.03)
        self.assertLessEqual(max(leaf[4] for leaf in leaves), 0.04)

    def test_rosette_builds_terminal_scapes_only_from_authored_reproductive_traits(self):
        entity = {
            "id": "spec_test_flowering_rosette",
            "plant_growth_form": "forb",
            "plant_growth_behaviour": "rosette_short_internode",
            "reproductive_mode": "sexual",
            "plant_flowering_position": "terminal",
            "plant_reproductive_structure": "spike",
        }
        flowering = SpeciesSimulation(species_entity=entity, seed=303)
        age = flowering.life_history_profile["reproductive_start_days"] + 20.0
        snapshot = flowering.generate_snapshot(age_days=age, lod=2)
        flowers = [placement for placement in snapshot.placements if placement[0] == "flower"]
        self.assertGreaterEqual(len(flowers), 1)
        self.assertTrue(all(snapshot.placements[int(flower[1])][0] == "stem_section" for flower in flowers))

        unresolved = SpeciesSimulation(
            species_entity={key: value for key, value in entity.items() if key not in {
                "plant_flowering_position", "plant_reproductive_structure"
            }},
            seed=303,
        )
        unresolved_snapshot = unresolved.generate_snapshot(age_days=age, lod=2)
        self.assertFalse(any(placement[0] == "flower" for placement in unresolved_snapshot.placements))

    def test_asset_store_round_trips_compressed_blueprint_and_snapshot(self):
        store = PlantAssetStore("assets/plants")
        sim = SpeciesSimulation(
            species_entity={
                "id": "spec_test_plant",
                "plant_growth_form": "forb",
                "plant_growth_behaviour": "rosette_short_internode",
            },
            seed=11,
        )
        self.assertTrue(store.blueprint_path(sim.species_id).name.endswith(".json.gz"))
        self.assertTrue(store.snapshot_path(sim.render_snapshot).name.endswith(".json.gz"))

        encoded = io.BytesIO()
        with gzip.GzipFile(fileobj=encoded, mode="wb") as handle:
            handle.write(json.dumps(sim.render_snapshot.to_dict()).encode("utf-8"))
        with gzip.GzipFile(fileobj=io.BytesIO(encoded.getvalue()), mode="rb") as handle:
            restored = json.loads(handle.read().decode("utf-8"))
        self.assertEqual("plant_growth_snapshot", restored["kind"])
        self.assertEqual(sim.render_snapshot.to_dict(), restored)

    def test_all_growth_behaviours_produce_modular_snapshots(self):
        behaviours = (
            "iterative_indeterminate",
            "determinate_sympodial",
            "rosette_short_internode",
            "branched_woody",
            "climbing_support_dependent",
            "creeping_prostrate",
            "tussock_tillering",
            "rhizomatous_clonal",
            "stoloniferous_clonal",
            "suckering_clonal",
        )
        for behaviour in behaviours:
            with self.subTest(behaviour=behaviour):
                sim = SpeciesSimulation(
                    species_entity={
                        "id": f"spec_{behaviour}",
                        "plant_growth_form": "forb",
                        "plant_growth_behaviour": behaviour,
                    },
                    seed=4,
                )
                self.assertGreater(sim.get_growth_summary()["placement_count"], 0)

    def test_iterative_herbaceous_forb_has_bounded_axes_and_lateral_panicles(self):
        entity = {
            "id": "spec_iterative_forb_fixture",
            "plant_growth_form": "forb",
            "plant_growth_behaviour": "iterative_indeterminate",
            "plant_lifespan": "annual",
            "plant_woodiness": "herbaceous",
            "mature_height": {"max_m": 1.3},
            "leaf_attachment_pattern": "terminal_cluster",
            "plant_leaf_distribution": "terminal_cluster",
            "leaf_arrangement": "alternate",
            "reproductive_mode": "sexual",
            "plant_flowering_position": "lateral",
            "plant_reproductive_structure": "panicle",
        }
        first = SpeciesSimulation(species_entity=entity, seed=303)
        second = SpeciesSimulation(species_entity=entity, seed=303)
        age = first.life_history_profile["reproductive_start_days"] + 5.0
        for simulation in (first, second):
            simulation.set_lod(2)
            simulation.set_age(age)

        self.assertEqual(first.render_snapshot.to_dict(), second.render_snapshot.to_dict())
        placements = first.render_snapshot.placements
        stems = [item for item in placements if item[0] == "stem_section"]
        branches = [item for item in placements if item[0] == "branch_section"]
        leaves = [item for item in placements if item[0] == "leaf"]
        flowers = [item for item in placements if item[0] == "flower"]
        self.assertGreaterEqual(len(stems), 5)
        self.assertLessEqual(len(branches), 4)
        self.assertLess(len(branches), len(stems))
        self.assertTrue(all(placements[item[1]][0] == "stem_section" for item in branches))
        self.assertTrue(all(placements[item[1]][0] == "stem_section" for item in flowers))
        self.assertTrue(all(item[4] >= 0.3 for item in leaves))
        self.assertTrue(all(item[4] >= 0.5 for item in flowers))
        self.assertGreater(len(flowers), 0)
        self.assertGreater(len({round(float(item[6]), 3) for item in leaves}), 1)

        skeleton = first.generate_snapshot(age_days=age, lod=0)
        self.assertEqual(len(stems), sum(item[0] == "stem_section" for item in skeleton.placements))
        self.assertEqual(len(branches), sum(item[0] == "branch_section" for item in skeleton.placements))

        unresolved = SpeciesSimulation(
            species_entity={
                key: value
                for key, value in entity.items()
                if key not in {"plant_flowering_position", "plant_reproductive_structure"}
            },
            seed=303,
        )
        unresolved_snapshot = unresolved.generate_snapshot(age_days=age, lod=2)
        self.assertFalse(any(item[0] == "flower" for item in unresolved_snapshot.placements))

    def test_scene_reference_contains_recipe_not_expanded_leaf_state(self):
        sim = SpeciesSimulation(
            species_entity={"id": "spec_test_plant", "plant_growth_form": "tree"},
            seed=2,
        )
        payload = sim.get_scene_reference().to_dict()
        self.assertEqual("species_plant_instance", payload["kind"])
        self.assertEqual(sim.species_id, payload["species_id"])
        self.assertNotIn("placements", payload)

    def test_ecological_outcome_is_compact_and_aggregatable(self):
        sim = SpeciesSimulation(
            species_entity={"id": "spec_test_plant", "plant_growth_form": "tree"},
            seed=2,
        )
        outcome = sim.get_ecological_outcome({"water_stress": 0.4, "competition": 0.2})
        self.assertEqual(sim.species_id, outcome["species_id"])
        self.assertIn("vitality", outcome)
        self.assertIn("fecundity", outcome)
        self.assertIn("mortality_risk", outcome)
        self.assertEqual("representative_organism_to_population", outcome["aggregation_scope"])
        self.assertNotIn("placements", outcome)

    def test_bake_snapshot_persists_recipe_and_returns_instance_reference(self):
        class MemoryStore:
            def __init__(self):
                self.blueprints = []
                self.snapshots = []

            def save_blueprint(self, blueprint):
                self.blueprints.append(blueprint)
                return "blueprint.json.gz"

            def save_snapshot(self, snapshot):
                self.snapshots.append(snapshot)
                return "snapshot.json.gz"

            def make_scene_reference(self, blueprint, snapshot, **kwargs):
                return {"species_id": blueprint.species_id, "snapshot": snapshot.to_dict()}

        store = MemoryStore()
        sim = SpeciesSimulation(species_entity={"id": "spec_test_plant", "plant_growth_form": "tree"})
        reference = sim.bake_snapshot(store)
        self.assertEqual("spec_test_plant", reference["species_id"])
        self.assertEqual(1, len(store.blueprints))
        self.assertEqual(1, len(store.snapshots))


if __name__ == "__main__":
    unittest.main()
