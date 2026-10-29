"""Shared point-in-time helpers for simulations and temporal card data.

Card history and simulation availability are related, but not identical:
history snapshots describe what a card says about a period, while an entity's
start/end years describe when it can participate in a simulation.  Keeping
the normalization here lets both systems agree on year syntax without
coupling their storage formats.
"""

from world.year_utils import parse_year


DEFAULT_SIMULATION_YEAR = 2400


def entity_year_range(entity):
    """Return an inclusive ``(start, end)`` range, or ``None`` if undated."""
    if not isinstance(entity, dict):
        return None

    start = parse_year(entity.get("start_year"))
    end = parse_year(entity.get("end_year"))
    point = parse_year(entity.get("year"))
    if point is None:
        point = parse_year(entity.get("year_number"))
    if point is None:
        point = parse_year(entity.get("effective_year"))

    if start is not None and end is not None:
        return min(start, end), max(start, end)
    if start is not None:
        return start, None
    if end is not None:
        return None, end
    if point is not None:
        return point, point
    return None


def entity_available_at(entity, year, undated=True):
    """Return whether an entity is available in an inclusive view year.

    Undated records remain visible by default.  This is important for draft
    cards and avoids silently removing existing content until a faction or
    designer has supplied dates.
    """
    year = parse_year(year)
    if year is None:
        return True
    year_range = entity_year_range(entity)
    if year_range is None:
        return bool(undated)
    start, end = year_range
    if start is not None and year < start:
        return False
    if end is not None and year > end:
        return False
    return True


def normalized_timeline_snapshots(entity):
    """Normalize the card snapshot shapes into inclusive year entries."""
    raw_entries = entity.get("timeline_snapshots") if isinstance(entity, dict) else None
    if isinstance(raw_entries, dict):
        raw_entries = [
            {"year_range": key, "wiki_entry": value}
            for key, value in raw_entries.items()
        ]
    if not isinstance(raw_entries, (list, tuple)):
        return []

    entries = []
    for raw in raw_entries:
        if not isinstance(raw, dict):
            continue
        start = parse_year(raw.get("start_year"))
        end = parse_year(raw.get("end_year"))
        if start is None or end is None:
            year_range = str(raw.get("year_range") or "").strip()
            parts = year_range.split("-", 1)
            if parts:
                start = parse_year(parts[0])
                end = parse_year(parts[1]) if len(parts) > 1 else start
        if start is None:
            continue
        end = end if end is not None else start
        entries.append(
            {
                "start_year": min(start, end),
                "end_year": max(start, end),
                "wiki_entry": str(raw.get("wiki_entry") or raw.get("text") or ""),
            }
        )
    return entries


def latest_formation_snapshot(entity, year):
    """Return the latest structured formation state at or before ``year``."""
    year = parse_year(year)
    if year is None or not isinstance(entity, dict):
        return None

    candidates = []
    raw_entries = entity.get("formation_snapshots")
    if not isinstance(raw_entries, (list, tuple)):
        return None
    for raw in raw_entries:
        if not isinstance(raw, dict):
            continue
        snapshot_year = parse_year(raw.get("year"))
        if snapshot_year is None:
            snapshot_year = parse_year(raw.get("start_year"))
        if snapshot_year is None or snapshot_year > year:
            continue
        state = raw.get("state")
        if isinstance(state, dict):
            candidates.append((snapshot_year, state))
    if not candidates:
        return None
    return max(candidates, key=lambda candidate: candidate[0])[1]
