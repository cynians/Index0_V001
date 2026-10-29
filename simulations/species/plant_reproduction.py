"""Shared trait interpretation for plant reproductive assurance."""

from __future__ import annotations

import math


def reproductive_profile(value):
    """Validate an optional portable seasonal recipe; malformed is neutral.

    Windows use fractions of a model year, whose origin is explicitly
    chosen by the author. Retention may cross into the following year.
    Existing plants without a recipe retain their original life history.
    """
    if not isinstance(value, dict):
        return None
    keys = ("cycle_days", "flowering_start", "flowering_end", "fruit_start",
            "fruit_ripe", "fruit_retention_end", "flower_size_m", "fruit_size_m")
    if any(isinstance(value.get(key), bool) or not isinstance(value.get(key), (int, float))
           or not math.isfinite(value[key]) for key in keys):
        return None
    if not (1 <= value["cycle_days"] <= 10000
            and 0 <= value["flowering_start"] < value["fruit_start"]
            <= value["flowering_end"] < value["fruit_ripe"] < 1
            and value["fruit_ripe"] < value["fruit_retention_end"] <= 2
            and 0 < value["flower_size_m"] <= 1
            and 0 < value["fruit_size_m"] <= 1):
        return None
    result = {key: float(value[key]) for key in keys}
    for key in ("unripe_color", "ripe_color"):
        color = value.get(key)
        if not (isinstance(color, (list, tuple)) and len(color) == 3
                and all(isinstance(c, int) and not isinstance(c, bool) and 0 <= c <= 255 for c in color)):
            return None
        result[key] = list(color)
    result["status"] = str(value.get("status") or "authored_qualitative_seasonal_recipe")
    result["version"] = 1
    leaf_keys = ("leaf_out_start", "leaf_out_full", "leaf_fall_start", "leaf_fall_end")
    if any(key in value for key in leaf_keys):
        if (any(isinstance(value.get(key), bool) or not isinstance(value.get(key), (int, float))
                or not math.isfinite(value[key]) for key in leaf_keys)
                or not 0 <= value[leaf_keys[0]] < value[leaf_keys[1]]
                < value[leaf_keys[2]] < value[leaf_keys[3]] <= 1):
            return None
        result.update({key: float(value[key]) for key in leaf_keys})
        result["version"] = 2
    from simulations.species.pendant_reproduction import pendant_display_profile
    pendant = pendant_display_profile(value.get("pendant_display"))
    if pendant is not None and (pendant["flower_drop_m"] or pendant["fruit_drop_m"]):
        result["pendant_display"] = pendant
        result["version"] = 3
    from simulations.species.pendant_reproduction import fruit_cluster_profile
    cluster=fruit_cluster_profile(value.get('fruit_cluster_display'))
    if cluster is not None and cluster['max_count']>1 and pendant and pendant['fruit_drop_m']:
        result['fruit_cluster_display']=cluster
        result['version']=4
    from simulations.species.persistent_calyces import persistent_calyx_profile
    calyx = persistent_calyx_profile(value.get("persistent_calyx_display"))
    if calyx:
        result["persistent_calyx_display"] = calyx
        result["version"] = 5
    return result


def seasonal_reproductive_state(growth, age_days, maturity_days):
    """Apply authored reproduction, optionally with deciduous leaf turnover.

    This optional recipe represents a fruit-bearing reproductive individual;
    it does not assign sex, guarantee pollination, or predict actual dates.
    Perennials repeat; opted-in annual herbs have one season and retain
    terminal death. Senescence of a long-lived clone remains unresolved.
    """
    profile = growth.get("reproductive_profile")
    life = growth.get("life_history", {})
    annual = life.get("class") == "annual" and bool(growth.get("creeping_herb_profile_version")
                                                  or growth.get("dimorphic_herb_profile_version")
                                                  or growth.get('sympodial_herb_version')
                                                  or growth.get('tufted_sedge_version'))
    perennial = life.get('class') == 'perennial' or (life.get('class') == 'short_lived_perennial'
                                                   and bool(growth.get('tufted_sedge_version') or growth.get('basal_subshrub_version') or growth.get('basal_herb_version') or growth.get('rosette_raceme_version')))
    if not profile or (not perennial and not annual):
        return None
    age = max(0.0, float(age_days))
    if growth.get('columnar_version'):
        maturity_days *= growth['columnar_profile']['reproductive_onset_fraction']
    year = age / profile["cycle_days"]
    # An explicitly composed annual has one season, not a repeating clone.
    season = year if annual else year % 1.0
    if annual and age >= float(life.get("age_limit_days") or profile["cycle_days"]):
        return {"phase":"dead", "reproductive_factor":0., "fruiting_factor":0.,
                "fruit_ripeness":0., "seasonal_stage":"dead", "season_fraction":round(season,4),
                "senescence_factor":1., "active_factor":0., "phenology_source":profile["status"]}
    flower = fruit = ripeness = 0.0
    stage = "vegetative"
    if age >= maturity_days and growth.get("reproductive_mode") in {"sexual", "both", "apomictic"}:
        a, b = profile["flowering_start"], profile["flowering_end"]
        if a <= season < b:
            flower = min(1.0, (season - a) / max(0.01, (b-a)*0.2), (b-season) / max(0.01, (b-a)*0.3))
        # A retained cohort can span New Year, but cannot predate maturity
        # or be invented in the first year before the first fruit set.
        for cohort_year in ((0,) if annual else (math.floor(year), math.floor(year)-1)):
            set_age = (cohort_year + profile["fruit_start"]) * profile["cycle_days"]
            t = year - cohort_year
            if set_age >= maturity_days and profile["fruit_start"] < t < profile["fruit_retention_end"]:
                ripeness = min(1.0, (t-profile["fruit_start"]) / (profile["fruit_ripe"]-profile["fruit_start"]))
                fruit = min(1.0, (t-profile["fruit_start"]) / 0.06)
                if t >= 1:
                    fruit *= max(0.0, (profile["fruit_retention_end"]-t) / max(0.01, profile["fruit_retention_end"]-1))
                stage = "retained_fruit" if t >= 1 or season >= 0.85 else "ripe_fruit" if ripeness >= 1 else "developing_fruit"
                break
        if flower > 0:
            stage = "flowering" if fruit == 0 else "flowering_and_fruit_set"
    state = {
        "phase": "juvenile" if age < maturity_days else "reproductive" if flower or fruit else "mature_vegetative",
        "reproductive_factor": round(flower, 4), "fruiting_factor": round(fruit, 4),
        "fruit_ripeness": round(ripeness, 4), "seasonal_stage": stage,
        "season_fraction": round(season, 4), "senescence_factor": 0.0,
        "active_factor": 1.0, "phenology_source": profile["status"],
    }
    if annual:
        start = float(life.get("senescence_start_days") or profile["cycle_days"]*.75)
        end = float(life.get("age_limit_days") or profile["cycle_days"])
        decline = max(0., min(1., (age-start)/max(1.,end-start)))
        state["senescence_factor"] = round(decline,4)
        state["active_factor"] = round(1.-decline*.55,4)
        if decline:
            state["phase"] = "senescent"
    # An explicit adverse-season schedule also describes drought-deciduous
    # turnover. Without dates this remains neutral; it is not a drought sensor.
    if growth.get("leaf_phenology") in {"deciduous", "drought_deciduous"} and "leaf_out_start" in profile:
        a, b, c, d = (profile[k] for k in ("leaf_out_start", "leaf_out_full", "leaf_fall_start", "leaf_fall_end"))
        leaf = max(0.0, min(1.0, (season-a)/(b-a), (d-season)/(d-c)))
        state["leaf_factor"] = round(leaf, 4)
        state["active_factor"] = round(0.25 + 0.75 * leaf, 4)
        if leaf == 0 and age >= maturity_days:
            state["phase"] = "dormant"
    return state


def _unit_interval(value, default=1.0):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return float(default)
    if not math.isfinite(number):
        return float(default)
    return max(0.0, min(1.0, number))


def resolve_reproductive_assurance(growth, environment=None):
    """Resolve pollination dependence without inventing missing conditions.

    Missing pollination context is neutral. An explicit availability value
    limits sexual reproduction, while apomictic and vegetative modes retain
    reproductive assurance. ``both`` receives a bounded vegetative floor;
    unknown modes remain neutral rather than being treated as an extreme.
    """

    growth = growth if isinstance(growth, dict) else {}
    environment = environment if isinstance(environment, dict) else {}
    mode = str(growth.get("reproductive_mode") or "other_unknown").strip().lower()
    supplied = environment.get("pollination_availability") is not None
    availability = _unit_interval(environment.get("pollination_availability"), 1.0)

    if not supplied:
        assurance = 1.0
        status = "neutral_missing_environment"
    elif mode == "sexual":
        assurance = availability
        status = "pollination_limited_sexual"
    elif mode == "both":
        assurance = max(0.55, availability)
        status = "mixed_mode_vegetative_floor"
    elif mode == "apomictic":
        assurance = 1.0
        status = "apomictic_assurance"
    elif mode == "vegetative":
        assurance = 1.0
        status = "vegetative_pollination_independent"
    else:
        assurance = 1.0
        status = "neutral_unknown_mode"

    return {
        "reproductive_mode": mode,
        "pollination_availability": round(availability, 4),
        "pollination_environment_supplied": supplied,
        "reproductive_assurance": round(assurance, 4),
        "reproductive_assurance_status": status,
    }
