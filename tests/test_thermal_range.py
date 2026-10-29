"""Heat and cold as zones a plant grows wild in (``thermal_range_coldest`` / ``thermal_range_warmest``)."""
import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import numpy as np

from simulations.biosphere.ecology import (
    THERMAL_ZONE_C, THERMAL_ZONE_RAMP_C, THERMAL_ZONES, profile_from_entity, thermal_limits, thermal_response,
    thermal_response_array,
)
from world.plant_growth_catalog import controlled_plant_field_rows
from world.plant_traits import (
    PLANT_THERMAL_ZONES, PLANT_TRAIT_BEHAVIOR_PATHS, PLANT_TRAIT_CHOICES, PLANT_TRAIT_SCHEMA_FIELDS,
)


def plant(coldest=None, warmest=None, **traits):
    entity = {"id": f"spec_{coldest}_{warmest}", "plant_growth_form": "tree", **traits}
    if coldest:
        entity["thermal_range_coldest"] = coldest
    if warmest:
        entity["thermal_range_warmest"] = warmest
    return profile_from_entity(entity)


def climate(coldest_c, warmest_c, **more):
    return {"coldest_month_temperature_k": 273.15 + coldest_c, "warmest_month_temperature_k": 273.15 + warmest_c, **more}


def score(profile, coldest_c, warmest_c):
    return thermal_response(profile, climate(coldest_c, warmest_c))


def test_the_schema_offers_both_ends_on_the_kernels_scale():
    for key in ("thermal_range_coldest", "thermal_range_warmest"):
        assert PLANT_TRAIT_SCHEMA_FIELDS[key]["type"] == "string"
        assert PLANT_TRAIT_BEHAVIOR_PATHS[key][0] == "Environmental Response"
        values = [row["value"] for row in PLANT_TRAIT_CHOICES[key]]
        assert values == list(THERMAL_ZONES) + ["other_unknown"]
        # The card's dropdown is built from the same rows.
        assert [row["value"] for row in controlled_plant_field_rows(key) if "value" in row] == values
    assert tuple(value for value, _label in PLANT_THERMAL_ZONES) == THERMAL_ZONES == tuple(THERMAL_ZONE_C)


def test_the_scale_is_ordered():
    figures = [THERMAL_ZONE_C[zone] for zone in THERMAL_ZONES]
    for colder, warmer in zip(figures, figures[1:]):
        assert all(a <= b for a, b in zip(colder, warmer)) and colder != warmer
    # A plant of any one zone has a summer it is unharmed in: what it needs lies under what it bears.
    assert all(need <= bears for _winter, need, bears in figures)
    # Nothing bears more than the limit every plant shares.
    assert figures[-1][2] + THERMAL_ZONE_RAMP_C == 48.0


def test_a_plant_without_a_range_keeps_the_shared_limits():
    unknown = plant()
    assert unknown.thermal_source == "limits shared by all plants"
    assert thermal_limits(unknown) == ((5.0, 10.0), (38.0, 48.0), None)
    assert score(unknown, -40.0, 18.0) == (1.0, None)  # no winter limit it did not author
    assert plant("other_unknown", "other_unknown").thermal_source == "limits shared by all plants"
    assert thermal_limits(plant("nonsense", "tepid")) == thermal_limits(unknown)


def test_the_coldest_zone_sets_winter_and_the_warmth_needed_the_warmest_sets_heat():
    oak = plant("cool", "mild")
    assert oak.thermal_source == "authored thermal range (cool to mild)"
    assert thermal_limits(oak) == ((9.0, 15.0), (26.0, 32.0), (-16.0, -10.0))
    assert score(oak, 2.0, 18.0) == (1.0, None)
    assert score(oak, -10.0, 15.0) == (1.0, None)  # unharmed on the figures themselves
    assert score(oak, 6.0, 26.0) == (1.0, None)
    assert score(oak, -13.0, 18.0) == (0.5, "frost")
    assert score(oak, -16.0, 18.0)[0] == 0.0
    assert score(oak, 2.0, 12.0) == (0.5, "growing-season warmth")
    assert score(oak, 6.0, 29.0) == (0.5, "heat")
    assert score(oak, 12.0, 41.0) == (0.0, "heat")
    wide = plant("cold", "very_hot")
    assert score(wide, -20.0, 41.0) == (1.0, None)
    assert score(wide, -28.0, 16.0) == (0.5, "frost")
    assert score(wide, -31.0, 16.0) == (0.0, "frost")
    # One zone alone: neither a cooler winter nor a hotter summer than its own.
    tropical = plant("hot", "hot")
    assert tropical.thermal_source == "authored thermal range (hot)"
    assert score(tropical, 24.0, 28.0) == (1.0, None)
    assert score(tropical, 6.0, 28.0) == (0.0, "frost")
    assert score(tropical, 20.0, 42.0) == (0.0, "heat")
    arctic = plant("frigid", "frigid")
    assert score(arctic, -30.0, 6.0) == (1.0, None)
    assert score(arctic, -30.0, 18.0) == (0.0, "heat")


def test_one_end_alone_limits_only_its_side_and_swapped_ends_are_put_right():
    hardy = plant("cold", None)
    assert thermal_limits(hardy) == ((5.0, 11.0), (38.0, 48.0), (-31.0, -25.0))
    tender = plant(None, "warm")
    assert thermal_limits(tender) == ((5.0, 10.0), (30.0, 36.0), None)
    assert thermal_limits(plant("mild", "cool")) == thermal_limits(plant("cool", "mild"))
    assert thermal_limits(plant("Very Hot", "very-hot")) == thermal_limits(plant("very_hot", "very_hot"))


def test_exact_figures_stand_before_the_zones():
    litchi = plant("warm", "hot", frost_tolerance={"min_c": -5},
                   temperature_range={"min_c": 15, "max_c": 40, "optimal_min_c": 20, "optimal_max_c": 35})
    assert thermal_limits(litchi) == ((15.0, 20.0), (35.0, 40.0), (-5.0, 1.0))
    assert litchi.thermal_source == "authored frost_tolerance over authored temperature_range over authored thermal range (warm to hot)"
    # An exact frost figure alone leaves the rest to the zones.
    hardy = plant("mild", "warm", frost_tolerance={"min_c": -20.0})
    assert thermal_limits(hardy) == ((12.0, 18.0), (30.0, 36.0), (-20.0, -14.0))
    # Half a temperature range gives the half it has.
    assert thermal_limits(plant("cool", "mild", temperature_range={"optimal_max_c": 30, "max_c": 38})) == (
        (9.0, 15.0), (30.0, 38.0), (-16.0, -10.0))
    assert thermal_limits(plant(temperature_range={"min_c": "warm", "max_c": None})) == thermal_limits(plant())


def test_shade_helps_against_heat_and_the_arrays_agree_with_the_points():
    oak = plant("cool", "mild")
    assert thermal_response(oak, climate(8.0, 33.0))[0] == 0.0
    assert thermal_response(oak, climate(8.0, 33.0, canopy_shade=1.0))[0] == 5.0 / 6.0
    # Shade takes no warmth from what grows under it: a zone's summers are those of the open air.
    fern = plant("hot", "hot")
    assert thermal_response(fern, climate(22.0, 26.0, canopy_shade=1.0)) == thermal_response(fern, climate(22.0, 26.0)) == (1.0, None)
    assert thermal_response(plant(), climate(-5.0, 12.0, canopy_shade=1.0)) == (1.0, None)
    warmest = 273.15 + np.array([4.0, 12.0, 18.0, 26.0, 30.0, 41.0, 18.0, 18.0])
    coldest = 273.15 + np.array([-30.0, -5.0, 2.0, 6.0, 8.0, 12.0, -10.0, -14.0])
    for profile in (oak, plant(), plant("cold", "very_hot"), plant("hot", "hot"), plant(None, "warm")):
        for shade in (0.0, 0.5):
            np.testing.assert_allclose(thermal_response_array(profile, warmest, coldest, shade), [
                thermal_response(profile, {"warmest_month_temperature_k": w, "coldest_month_temperature_k": c,
                                           "canopy_shade": shade})[0]
                for w, c in zip(warmest, coldest)])
    assert thermal_response_array(oak, np.array([np.nan]), np.array([270.0])).tolist() == [1.0]
