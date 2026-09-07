"""Person data-completeness assessment.

An authored person entity may carry anywhere from nothing but an id to a
fully fleshed-out dossier. Before PersonSimulation's engine is generalized
away from its current fixed test-scenario shape (see
docs/person_simulation_concept_v001.md), this module gives every person a
readiness signal: which categories of data are present, and whether the
result is credible enough to simulate as-is or should eventually trigger
character creation to fill the gaps.
"""

from __future__ import annotations

from typing import Any

PERSON_BIG_FIVE_AXIS_IDS = (
    "openness",
    "conscientiousness",
    "extraversion",
    "agreeableness",
    "neuroticism",
)

READINESS_CATEGORIES = (
    {"id": "identity", "label": "Identity"},
    {"id": "personality", "label": "Personality (Big Five)"},
    {"id": "motivation", "label": "Motivation (wishes, goals, dreams)"},
    {"id": "knowledge", "label": "Knowledge"},
    {"id": "social", "label": "Social grounding"},
    {"id": "site", "label": "Physical / site grounding"},
)

READINESS_TIER_AUTHORED = "authored"
READINESS_TIER_SPARSE = "sparse"
READINESS_TIER_EMPTY = "empty"


def _has_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, set, dict)):
        return len(value) > 0
    return True


def _identity_present(person: dict) -> bool:
    return _has_value(person.get("pretty_name")) or _has_value(person.get("name"))


def _personality_present(person: dict) -> bool:
    nested = person.get("big_five") or person.get("personality_big_five") or {}
    if isinstance(nested, dict) and any(_has_value(nested.get(axis)) for axis in PERSON_BIG_FIVE_AXIS_IDS):
        return True
    return any(_has_value(person.get(f"big_five_{axis}")) for axis in PERSON_BIG_FIVE_AXIS_IDS)


def _motivation_present(person: dict) -> bool:
    return any(_has_value(person.get(field)) for field in ("wishes", "goals", "dreams"))


def _knowledge_present(person: dict) -> bool:
    return _has_value(person.get("knowledge_records")) or _has_value(person.get("known_entities"))


def _social_present(person: dict) -> bool:
    return any(
        _has_value(person.get(field))
        for field in (
            "affiliated_factions",
            "affiliated_institutions",
            "associated_locations",
            "residence",
            "participated_events",
            "employment_assignments",
        )
    )


def _site_present(person: dict, world_model=None) -> bool:
    if _has_value(person.get("simulation_site")) or _has_value(person.get("site_position")):
        return True
    if world_model is None:
        return False
    locations = person.get("associated_locations")
    if isinstance(locations, str):
        locations = [locations]
    for location_id in locations if isinstance(locations, (list, tuple, set)) else []:
        location = world_model.get_entity(location_id) if hasattr(world_model, "get_entity") else None
        if isinstance(location, dict) and _has_value(location.get("simulation_points")):
            return True
    return False


_CATEGORY_CHECKS = {
    "identity": _identity_present,
    "personality": _personality_present,
    "motivation": _motivation_present,
    "knowledge": _knowledge_present,
    "social": _social_present,
}


def assess_person_readiness(person: dict | None, world_model=None) -> dict:
    """Score how much authored data a person entity carries.

    Six categories are checked (identity, personality, motivation, knowledge,
    social grounding, site grounding). The tier is a coarse readout of the
    fraction present: ``authored`` (5-6 of 6) is credible as-is, ``empty``
    (0-1 of 6) is a candidate for full character creation, and ``sparse``
    (2-4 of 6) sits between the two -- enough to exist, not enough to feel
    like a written character.
    """

    person = person if isinstance(person, dict) else {}
    present = []
    missing = []
    for category in READINESS_CATEGORIES:
        category_id = category["id"]
        if category_id == "site":
            is_present = _site_present(person, world_model)
        else:
            is_present = _CATEGORY_CHECKS[category_id](person)
        (present if is_present else missing).append(category_id)

    score = len(present) / len(READINESS_CATEGORIES)
    if len(present) >= 5:
        tier = READINESS_TIER_AUTHORED
    elif len(present) <= 1:
        tier = READINESS_TIER_EMPTY
    else:
        tier = READINESS_TIER_SPARSE

    return {
        "tier": tier,
        "score": score,
        "present": present,
        "missing": missing,
    }


def placeable_asset_catalog(point_definitions) -> list[dict]:
    """Point-kind templates a player can place freely in the void test area.

    Duty-only points (no ``tags``, e.g. the lumber dropoff/pickup duties --
    see person_simulation.py's TEST_POINT_DEFINITIONS comment) are excluded:
    they only make sense assigned externally within their one authored
    scenario, not hand-placed into an empty test area. Position is dropped
    since placement supplies it.
    """

    catalog = []
    for definition in point_definitions:
        if not definition.get("tags"):
            continue
        catalog.append({key: value for key, value in definition.items() if key != "position"})
    return catalog


def character_creation_prompt_lines(readiness: dict, person_name: str | None = None) -> list[str]:
    """Human-readable lines describing what character creation would need to fill."""

    labels_by_id = {category["id"]: category["label"] for category in READINESS_CATEGORIES}
    missing_labels = [labels_by_id[category_id] for category_id in readiness.get("missing", []) if category_id in labels_by_id]
    name = person_name or "This person"
    if readiness.get("tier") == READINESS_TIER_AUTHORED:
        return [f"{name} has enough authored data to simulate credibly."]

    lines = [f"{name} lacks enough authored data to simulate credibly."]
    if missing_labels:
        lines.append("Missing: " + ", ".join(missing_labels))
    return lines
