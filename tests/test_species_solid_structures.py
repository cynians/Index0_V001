import math

from simulations.species.plant_assets import PlantGrowthSnapshot
from simulations.species.species_renderer import SurfaceElevationCamera
from simulations.species.solid_structures import SolidStructureField, normalise_solid_structures
from simulations.species.species_simulation import (
    SpeciesSimulation,
    climbing_support_axis_at_z,
    climbing_support_from_tree_snapshot,
)
from tools.render_solid_structure_growth import (
    COVERED_WALL,
    PILLAR,
    SEED,
    TREE_ENVIRONMENT,
    TREE_FIXTURE,
    VINE_PILLAR_ENVIRONMENT,
    VINE_WALL_ENVIRONMENT,
    WALL,
)
from tools.render_vine_climbing import VINE_FIXTURE


def _mature(entity, environment, lod=2):
    simulation = SpeciesSimulation(species_entity=entity, seed=SEED, environment=environment)
    simulation.lod = lod
    simulation.set_age(simulation.mature_age_days)
    return simulation


def _structural_hits(simulation, field):
    hits = []
    snapshot = simulation.render_snapshot
    for index, placement in enumerate(snapshot.placements):
        if placement[0] not in {"stem_section", "branch_section"} or placement[1] < 0:
            continue
        parent = snapshot.placements[placement[1]]
        points = [parent[2:5], *snapshot.placement_paths.get(str(index), [])]
        if tuple(points[-1]) != tuple(placement[2:5]):
            points.append(placement[2:5])
        hit = field.path_hit(points)
        if hit is not None:
            hits.append((index, hit["structure"]["id"]))
    return hits


def test_pixel_mask_is_extruded_into_a_rotatable_3d_solid():
    structure = {
        "id": "rotated_wall",
        "kind": "wall",
        "position_m": [1.0, 2.0, 0.0],
        "rotation_deg": 90.0,
        "pixel_size_m": 0.5,
        "extrusion_depth_m": 0.2,
        "mask_rows": ["##", "#."],
    }
    field = SolidStructureField.from_environment({"solid_structures": [structure]})
    assert len(field.structures) == 1
    solid = field.structures[0]
    occupied_world = SolidStructureField._local_to_world(solid, (-0.25, 0.0, 0.25))
    empty_world = SolidStructureField._local_to_world(solid, (0.25, 0.0, 0.25))
    behind_world = SolidStructureField._local_to_world(solid, (-0.25, 0.2, 0.25))
    assert field.contains(occupied_world)["cell"] == (1, 0)
    assert field.contains(empty_world) is None
    assert field.contains(behind_world) is None
    assert field.segment_hit(
        SolidStructureField._local_to_world(solid, (-0.75, 0.0, 0.25)),
        SolidStructureField._local_to_world(solid, (0.0, 0.0, 0.25)),
    )["structure"]["id"] == "rotated_wall"


def test_solid_input_validation_rejects_empty_nonfinite_and_zero_sized_masks():
    structures = normalise_solid_structures({"solid_structures": [
        None,
        {},
        {"position_m": [0, 0, 0], "pixel_size_m": 1, "extrusion_depth_m": 1, "mask_rows": ["..."]},
        {"position_m": [math.nan, 0, 0], "pixel_size_m": 1, "extrusion_depth_m": 1, "mask_rows": ["#"]},
        {"position_m": [0, 0, 0], "pixel_size_m": 0, "extrusion_depth_m": 1, "mask_rows": ["#"]},
        WALL,
    ]})
    assert [item["id"] for item in structures] == ["wall_fixture"]
    assert structures[0]["mask_width_px"] == 10
    assert structures[0]["mask_height_px"] == 14


def test_wall_contacts_use_nearest_mask_cells_instead_of_converging_on_center():
    wall = {**WALL, "position_m": [0.0, 0.5, 0.0]}
    field = SolidStructureField.from_environment({"solid_structures": [wall]})
    contacts = [
        field.nearest_ground_contact((root_x, -0.8, 0.045), 5.0)
        for root_x in (-0.8, 0.0, 0.8)
    ]
    contact_x = [contact["point_m"][0] for contact in contacts]
    assert contact_x[0] < contact_x[1] < contact_x[2]
    assert all(abs(actual - expected) <= WALL["pixel_size_m"] for actual, expected in zip(contact_x, (-0.8, 0.0, 0.8)))
    assert len({contact["cell"][1] for contact in contacts}) == 3


def test_vines_contact_and_follow_wall_and_pillar_pixel_surfaces_without_penetration():
    cases = (
        (VINE_WALL_ENVIRONMENT, "wall_fixture", "wall"),
        (VINE_PILLAR_ENVIRONMENT, "pillar_fixture", "pillar"),
    )
    for environment, expected_id, expected_kind in cases:
        simulation = _mature(VINE_FIXTURE, environment)
        snapshot = simulation.render_snapshot
        stats = snapshot.stats
        assert stats["vine_phase"] == "climbing"
        assert stats["vine_attachment_mode"] == "pixel_solid_surface"
        assert stats["vine_selected_support_id"] == expected_id
        assert stats["vine_selected_support_kind"] == expected_kind
        assert stats["vine_support_contact_count"] == 1
        assert stats["vine_climbing_height_m"] > 2.0
        assert stats["solid_structure_response"] == "support_surface_climbing"
        contacts = [item for item in snapshot.attachment_points if item.get("socket") == "support_contact"]
        assert len(contacts) > 2
        assert all(item["support_id"] == expected_id for item in contacts)
        assert _structural_hits(simulation, SolidStructureField.from_environment(environment)) == []
        assert all(-1 <= placement[1] < index for index, placement in enumerate(snapshot.placements))
        restored = PlantGrowthSnapshot.from_dict(snapshot.to_dict())
        assert restored.to_dict() == snapshot.to_dict()


def test_wall_vine_uses_bounded_seeded_surface_meander_with_axis_budget():
    environment = {"solid_structures": [COVERED_WALL]}
    first = _mature(VINE_FIXTURE, environment)
    second = SpeciesSimulation(species_entity=VINE_FIXTURE, seed=SEED + 1, environment=environment)
    second.lod = 2
    second.set_age(second.mature_age_days)
    for simulation in (first, second):
        stats = simulation.render_snapshot.stats
        assert stats["vine_surface_pattern"] == "bounded_lateral_meander"
        assert 0.15 <= stats["vine_surface_pattern_amplitude_m"] <= 0.30
        assert stats["vine_surface_lateral_span_m"] > 0.30
        assert stats["vine_axis_length_m"] <= stats["vine_axis_budget_m"] + 1e-4
        assert _structural_hits(simulation, SolidStructureField.from_environment(environment)) == []
    first_x = [
        item["position_m"][0]
        for item in first.render_snapshot.attachment_points
        if item.get("side") == "climbing_axis"
    ]
    second_x = [
        item["position_m"][0]
        for item in second.render_snapshot.attachment_points
        if item.get("side") == "climbing_axis"
    ]
    assert first_x != second_x
    assert first.generate_snapshot(first.mature_age_days, lod=0).stats["vine_surface_lateral_span_m"] == first.render_snapshot.stats["vine_surface_lateral_span_m"]


def test_surface_elevation_camera_flattens_depth_without_changing_surface_x_or_z():
    camera = SurfaceElevationCamera(400, 300, (-2.0, 2.0, -1.0, 1.0, 0.0, 3.0), 0.0)
    assert camera.world_to_screen_3d((0.75, -1.0, 1.25)) == camera.world_to_screen_3d((0.75, 1.0, 1.25))
    assert camera.world_to_screen_3d((-0.75, 0.0, 1.25))[0] < camera.world_to_screen_3d((0.75, 0.0, 1.25))[0]
    assert camera.world_to_screen_3d((0.0, 0.0, 2.0))[1] < camera.world_to_screen_3d((0.0, 0.0, 1.0))[1]


def test_tree_collision_gates_axes_and_descendants_around_both_structures():
    baseline = _mature(TREE_FIXTURE, {})
    avoided = _mature(TREE_FIXTURE, TREE_ENVIRONMENT)
    stats = avoided.render_snapshot.stats
    assert stats["solid_structure_response"] == "collision_gated_growth"
    assert stats["solid_structure_collision_count"] >= 2
    assert stats["solid_structure_pruned_placement_count"] > stats["solid_structure_collision_count"]
    assert stats["solid_structure_avoided_ids"] == ["pillar_fixture", "wall_fixture"]
    assert len(avoided.render_snapshot.placements) < len(baseline.render_snapshot.placements)
    assert _structural_hits(avoided, SolidStructureField.from_environment(TREE_ENVIRONMENT)) == []
    assert all(-1 <= placement[1] < index for index, placement in enumerate(avoided.render_snapshot.placements))
    assert all(
        0 <= int(item["stem_placement_index"]) < len(avoided.render_snapshot.placements)
        for item in avoided.render_snapshot.attachment_points
        if "stem_placement_index" in item
    )
    repeat = _mature(TREE_FIXTURE, TREE_ENVIRONMENT)
    assert repeat.render_snapshot.to_dict() == avoided.render_snapshot.to_dict()


def test_vine_solid_contact_metrics_are_lod_stable_and_juveniles_stay_on_ground():
    reference = _mature(VINE_FIXTURE, VINE_PILLAR_ENVIRONMENT)
    keys = (
        "vine_phase",
        "vine_axis_length_m",
        "vine_ground_axis_length_m",
        "vine_climbing_axis_length_m",
        "vine_climbing_height_m",
        "vine_support_contact_count",
        "vine_selected_support_id",
        "vine_attachment_mode",
    )
    expected = {key: reference.render_snapshot.stats[key] for key in keys}
    for lod in (0, 1, 2):
        snapshot = reference.generate_snapshot(age_days=reference.mature_age_days, lod=lod)
        assert {key: snapshot.stats[key] for key in keys} == expected
        if lod == 0:
            assert not any(placement[0] == "leaf" for placement in snapshot.placements)

    juvenile = SpeciesSimulation(
        species_entity=VINE_FIXTURE,
        seed=SEED,
        environment=VINE_PILLAR_ENVIRONMENT,
    )
    juvenile.set_age(juvenile.mature_age_days * 0.05)
    assert juvenile.render_snapshot.stats["vine_phase"] == "ground_search"
    assert juvenile.render_snapshot.stats["vine_support_contact_count"] == 0


def test_vine_can_follow_axis_extracted_from_generated_tree_trunk():
    tree = _mature(TREE_FIXTURE, {})
    support = climbing_support_from_tree_snapshot(
        tree.render_snapshot,
        position_m=(0.72, 0.48, 0.0),
    )
    assert support is not None
    assert support["source_species_id"] == TREE_FIXTURE["id"]
    assert len(support["axis_points_m"]) > 10

    vine = _mature(VINE_FIXTURE, {"climbing_supports": [support]})
    snapshot = vine.render_snapshot
    stats = snapshot.stats
    assert stats["vine_phase"] == "climbing"
    assert stats["vine_attachment_mode"] == "sampled_trunk_axis"
    normalised_support = snapshot.stats["climbing_supports"][0]
    clearances = []
    for attachment in snapshot.attachment_points:
        if attachment.get("side") != "climbing_axis":
            continue
        x, y, z = attachment["position_m"]
        axis_x, axis_y = climbing_support_axis_at_z(normalised_support, z)
        clearances.append(math.hypot(x - axis_x, y - axis_y) - normalised_support["radius_m"])
    assert len(clearances) > 5
    assert min(clearances) >= 0.03
    assert max(clearances) <= 0.04
