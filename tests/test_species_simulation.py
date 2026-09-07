import gzip
import io
import json
import unittest
from pathlib import Path

from simulations.species.plant_assets import PlantAssetStore, is_plant_species_entity
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
        self.assertTrue(all(count == 2 for count in branch_hosts.values()))
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
