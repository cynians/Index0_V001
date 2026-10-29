import math

from simulations.species.plant_assets import PlantGrowthSnapshot
from simulations.species.species_simulation import (
    SpeciesSimulation,
    climbing_support_axis_at_z,
    normalise_rod_structures,
)
from tools.render_vine_climbing import VINE_FIXTURE
from tools.render_vine_rod_climbing import ROD, ROD_ENVIRONMENT, SEED


def _mature(environment, seed=SEED, lod=2):
    simulation = SpeciesSimulation(species_entity=VINE_FIXTURE, seed=seed, environment=environment)
    simulation.lod = lod
    simulation.set_age(simulation.mature_age_days)
    return simulation


def test_rod_input_is_bounded_and_invalid_entries_are_rejected():
    rods = normalise_rod_structures({"rod_structures": [
        None,
        {},
        {"position_m": [0, 0, 0], "radius_m": 0, "height_m": 2},
        {"position_m": [math.nan, 0, 0], "radius_m": 0.1, "height_m": 2},
        {"position_m": [0, 0, 0], "radius_m": 0.1, "height_m": 0},
        ROD,
    ]})
    assert len(rods) == 1
    rod = rods[0]
    assert rod["id"] == "steel_rod_fixture"
    assert rod["kind"] == "rod"
    assert rod["axis_points_m"] == [[1.1, 0.35, 0.0], [1.1, 0.35, 3.6]]
    assert rod["support_model"] == "cylindrical_rod_helix"
    assert rod["palette"]["fill"] == [100, 111, 116]


def test_vine_finds_rod_and_circles_it_at_constant_clearance():
    simulation = _mature(ROD_ENVIRONMENT)
    snapshot = simulation.render_snapshot
    stats = snapshot.stats
    assert stats["vine_phase"] == "climbing"
    assert stats["vine_selected_support_id"] == "steel_rod_fixture"
    assert stats["vine_selected_support_kind"] == "rod"
    assert stats["vine_attachment_mode"] == "cylindrical_rod_helix"
    assert stats["vine_turn_count"] > 4.0
    assert stats["vine_ground_axis_length_m"] > 1.0
    assert stats["vine_climbing_height_m"] > 2.5
    assert stats["vine_axis_length_m"] <= stats["vine_axis_budget_m"] + 1e-4
    assert stats["rod_structure_count"] == 1
    assert stats["rod_structure_status"] == "available"

    support = stats["climbing_supports"][0]
    clearances = []
    contacts = [
        item for item in snapshot.attachment_points
        if item.get("side") == "climbing_axis" and item.get("socket") == "support_contact"
    ]
    assert len(contacts) > 8
    for contact in contacts:
        x, y, z = contact["position_m"]
        axis_x, axis_y = climbing_support_axis_at_z(support, z)
        clearances.append(math.hypot(x - axis_x, y - axis_y) - support["radius_m"])
        assert contact["support_id"] == "steel_rod_fixture"
    assert min(clearances) >= 0.0348
    assert max(clearances) <= 0.0352
    assert all(-1 <= placement[1] < index for index, placement in enumerate(snapshot.placements))
    assert PlantGrowthSnapshot.from_dict(snapshot.to_dict()).to_dict() == snapshot.to_dict()


def test_rod_climb_is_deterministic_and_lod_stable():
    reference = _mature(ROD_ENVIRONMENT)
    repeat = _mature(ROD_ENVIRONMENT)
    assert repeat.render_snapshot.to_dict() == reference.render_snapshot.to_dict()
    keys = (
        "vine_phase",
        "vine_axis_length_m",
        "vine_ground_axis_length_m",
        "vine_climbing_axis_length_m",
        "vine_climbing_height_m",
        "vine_turn_count",
        "vine_selected_support_id",
        "vine_attachment_mode",
    )
    expected = {key: reference.render_snapshot.stats[key] for key in keys}
    for lod in (0, 1, 2):
        snapshot = reference.generate_snapshot(reference.mature_age_days, lod=lod)
        assert {key: snapshot.stats[key] for key in keys} == expected
        if lod == 0:
            assert not any(placement[0] == "leaf" for placement in snapshot.placements)


def test_unreachable_or_malformed_rods_do_not_trigger_climbing():
    cases = (
        {"rod_structures": [{**ROD, "position_m": [8.0, 0.0, 0.0]}]},
        {"rod_structures": [{**ROD, "radius_m": 0.0}]},
    )
    for environment in cases:
        snapshot = _mature(environment).render_snapshot
        assert snapshot.stats["vine_phase"] == "ground_search"
        assert snapshot.stats["vine_selected_support_id"] is None
        assert snapshot.stats["vine_support_contact_count"] == 0
