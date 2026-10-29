"""Choose a representative mature display age without changing species traits."""
import math


def mature_preview_age(sim):
    """Prefer a leafy flowering phase, or mature fungal bodies, on the model clock.

    Selection is deterministic. It does not claim a measured calendar date and
    never changes the simulation's life history or persisted biological fields.
    """
    growth = sim.blueprint.growth
    mature = sim.mature_age_days
    if growth.get("fungal_grammar_version"):
        recipe = growth["fungal_growth_profile"]["resolved"]
        cycle = recipe["flush_cycle_model_days"]
        age = recipe["first_flush_model_days"] + cycle * .45
        return age + max(0, math.ceil((mature-age)/cycle)) * cycle

    life = sim.life_history_profile
    start = max(mature, life["reproductive_start_days"])
    end = max(start, life["senescence_start_days"])
    candidates = [mature, start + (end-start)*.2]
    profile = growth.get("reproductive_profile")
    if profile:
        cycle = profile["cycle_days"]
        phases = [(profile["flowering_start"] + min(profile["flowering_end"],
                   profile["fruit_start"])) / 2]
        if "leaf_out_full" in profile:
            phases.append((profile["leaf_out_full"] + profile["leaf_fall_start"])/2)
        phases.extend(i/64 for i in range(64))
        for phase in phases:
            age = cycle*phase
            candidates.append(age + max(0, math.ceil((mature-age)/cycle))*cycle)

    def score(age):
        state = sim.life_state(age)
        healthy = state["phase"] not in {"juvenile", "dead", "dormant", "senescent"}
        return (healthy, state.get("leaf_factor", 1.),
                state.get("reproductive_factor", 0.), -state.get("senescence_factor", 0.))

    return float(max(candidates, key=score))
