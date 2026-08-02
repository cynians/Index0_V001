"""Classify a generated world from authored boundary conditions.

Template ids are deliberately absent from this module.  A template is only a
convenient way to populate the editable world-gen inputs; changing the preset
label without changing those inputs must never change the generated world.
"""


def _clamp(value, low, high):
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        numeric = low
    return max(low, min(high, numeric))


def _element_abundance(seed, symbol):
    composition = seed.get("crust_composition") if isinstance(seed, dict) else {}
    composition = composition if isinstance(composition, dict) else {}
    total = 0.0
    for group_name in ("major_elements", "trace_elements"):
        for row in composition.get(group_name) or []:
            if not isinstance(row, dict) or str(row.get("symbol") or "").strip() != symbol:
                continue
            try:
                total += max(0.0, float(row.get("abundance_percent", 0.0) or 0.0))
            except (TypeError, ValueError):
                pass
    return total


def _has_explicit_bulk_composition(seed):
    """Return whether the seed contains any authored major-element inventory."""
    composition = seed.get("crust_composition") if isinstance(seed, dict) else {}
    composition = composition if isinstance(composition, dict) else {}
    for row in composition.get("major_elements") or []:
        if not isinstance(row, dict):
            continue
        try:
            if float(row.get("abundance_percent", 0.0) or 0.0) > 0.0:
                return True
        except (TypeError, ValueError):
            pass
    return False


def is_airless_surface(seed):
    """Return whether the visible volatile/water inputs describe an airless body."""
    seed = seed if isinstance(seed, dict) else {}
    inventory = str(seed.get("volatile_inventory") or "").strip().lower()
    water_fraction = _clamp(seed.get("water_fraction", 0.0), 0.0, 1.0)
    return inventory == "none" and water_fraction <= 0.03


def is_envelope_world(seed, physics=None):
    """Infer the no-solid-surface route without consulting a template id."""
    seed = seed if isinstance(seed, dict) else {}
    physics = physics if isinstance(physics, dict) else {}
    if is_airless_surface(seed):
        return False

    radius_earth = max(
        0.0,
        float(physics.get("radius_earth", seed.get("radius_earth", 0.0)) or 0.0),
    )
    mass_earth = max(0.0, float(physics.get("mass_earth", 0.0) or 0.0))
    inventory = str(seed.get("volatile_inventory") or "").strip().lower()
    hydrogen_helium = _element_abundance(seed, "H") + _element_abundance(seed, "He")
    has_explicit_bulk_composition = _has_explicit_bulk_composition(seed)

    # An authored elemental inventory wins over a size proxy. "Dense" describes
    # the atmosphere control; it does not silently add a bulk H/He envelope.
    if has_explicit_bulk_composition:
        return hydrogen_helium >= 35.0

    # Old/incomplete seeds may have no usable composition. Preserve a cautious
    # size/volatile fallback for those records until they are edited and saved.
    return bool(
        (inventory == "dense" and radius_earth >= 2.2)
        or (inventory in {"wet", "earthlike"} and radius_earth >= 3.0)
        or (mass_earth >= 12.0 and inventory not in {"none", "thin", "dry"})
    )


def infer_world_class(seed, physics=None):
    """Return a derived display/solver class from first-screen and orbit inputs."""
    seed = seed if isinstance(seed, dict) else {}
    physics = physics if isinstance(physics, dict) else {}
    radius_earth = max(
        0.0,
        float(physics.get("radius_earth", seed.get("radius_earth", 0.0)) or 0.0),
    )
    water_fraction = _clamp(seed.get("water_fraction", 0.0), 0.0, 1.0)
    inventory = str(seed.get("volatile_inventory") or "").strip().lower()
    body_class = str(seed.get("orbital_body_class") or "").strip().lower()
    hydrogen = _element_abundance(seed, "H")

    if is_envelope_world(seed, physics):
        return "gas_giant" if radius_earth >= 5.0 else "ice_giant"
    if body_class == "moon" and hydrogen >= 1.0:
        return "icy_satellite"
    if is_airless_surface(seed):
        return "airless_rocky"
    if water_fraction >= 0.72:
        return "ocean_world"
    if water_fraction <= 0.08 and inventory in {"dry", "thin", "dense"}:
        return "desert_terrestrial"
    return "terrestrial"
