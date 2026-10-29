"""
Capability profiles of vehicle designs (docs/logistics_simulation_concept_v001.md
section 3.2).

A design profile is what a vehicle of that design can do with full tanks. It
reads typed fields on the installed components' own entities, so a design
whose components lack them gets no value for that term rather than a guess:

    engines        thrust_n, specific_impulse_s (vacuum); count only when wired
    tanks          propellant_capacity_kg
    any component  shielding_class, life_support_s, docking, atmosphere_entry

Structural features may carry shielding_class and atmosphere_entry too (a hull
that is its own heat shield). Dry mass is the sum of installed component
masses, as in VehicleSimulation.derive_capabilities; hull mass is not
modelled yet.
"""
from simulations.logistics.capabilities import TERMS, stronger_rank
from simulations.space.propulsion import Engine, PropulsionState
from simulations.vehicle.vehicle_design import VehicleDesignController


SPACECRAFT_CLASSES = {"orbital_spacecraft", "planetary_spacecraft", "system_spacecraft", "interstellar_spacecraft"}

# What the designer needs to resolve parts, catalog and wiring. Hull art,
# liveries and the rest stay out: decoding or defaulting them made one design
# cost over a second.
_PROFILE_KEYS = (
    "id", "type", "vehicle_class", "component_catalog", "installed_components", "manual_routes",
    "structural_features", "dimension_length_m", "dimension_width_m", "dimension_height_m",
)


def _design_parts(vehicle_entity, world_model):
    """Installed parts of a design; none, without building a designer, when nothing is installed."""
    if not vehicle_entity.get("installed_components"):
        return []
    design_view = {key: vehicle_entity[key] for key in _PROFILE_KEYS if key in vehicle_entity}
    design = VehicleDesignController(world_model=world_model, vehicle_entity=design_view)
    return list(_installed_parts(design, world_model))


def _positive(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0.0 else None


def _shielding(value):
    return value if value in TERMS["shielding_class"].ranks else None


def _installed_parts(design, world_model):
    """(component entity, mass, wired) per installed component."""
    wiring = design.get_component_wiring_status()
    for component in design.get_placed_components():
        catalog_id = component.get("catalog_id")
        if not catalog_id:
            continue
        entry = design.get_component_catalog_entry(catalog_id) or {}
        entity = world_model.get_entity(catalog_id) if hasattr(world_model, "get_entity") else None
        if not isinstance(entity, dict):
            entity = entry
        if not entity:
            continue
        mass_kg = float(entry.get("mass_kg", entity.get("mass_kg", 0.0)) or 0.0)
        wired = wiring.get(component.get("instance_id"), {"fully_wired": True})["fully_wired"]
        yield entity, mass_kg, wired


def design_propulsion_state(vehicle_entity, world_model):
    """Full-tank propulsion of a design, or None when it has no typed engines and tanks."""
    return _propulsion_from_parts(_design_parts(vehicle_entity, world_model))


def _propulsion_from_parts(parts):
    dry_mass_kg = sum(mass_kg for _entity, mass_kg, _wired in parts)
    propellant_kg = sum(_positive(entity.get("propellant_capacity_kg")) or 0.0 for entity, _mass, _wired in parts)
    engines = tuple(
        Engine(_positive(entity.get("thrust_n")), _positive(entity.get("specific_impulse_s")))
        for entity, _mass, wired in parts
        if wired and _positive(entity.get("thrust_n")) and _positive(entity.get("specific_impulse_s"))
    )
    if not engines or propellant_kg <= 0.0 or dry_mass_kg <= 0.0:
        return None
    return PropulsionState(dry_mass_kg=dry_mass_kg, propellant_kg=propellant_kg, engines=engines)


def space_profile_from_design(vehicle_entity, world_model):
    """The space terms a design can show, as a profile for capabilities.shortfalls."""
    parts = _design_parts(vehicle_entity, world_model)

    shielding = None
    life_support_s = 0.0
    docking = False
    atmosphere_entry = False
    for entity, _mass, _wired in parts:
        shielding = stronger_rank("shielding_class", shielding, _shielding(entity.get("shielding_class")))
        life_support_s += _positive(entity.get("life_support_s")) or 0.0
        docking = docking or bool(entity.get("docking"))
        atmosphere_entry = atmosphere_entry or bool(entity.get("atmosphere_entry"))
    for feature in vehicle_entity.get("structural_features") or []:
        if isinstance(feature, dict):
            shielding = stronger_rank("shielding_class", shielding, _shielding(feature.get("shielding_class")))
            atmosphere_entry = atmosphere_entry or bool(feature.get("atmosphere_entry"))

    profile = {"docking": docking, "atmosphere_entry": atmosphere_entry}
    if shielding is not None:
        profile["shielding_class"] = shielding
    if life_support_s > 0.0:
        profile["life_support_s"] = life_support_s
    propulsion = _propulsion_from_parts(parts)
    if propulsion is not None:
        profile["delta_v_m_s"] = propulsion.delta_v_m_s()
    return profile


def spacecraft_design_profiles(world_model):
    """(design id, name, space profile) for every spacecraft design in the world model."""
    designs = []
    for entity in world_model.get_entities_by_dataset("vehicles"):
        materialize = getattr(entity, "materialize", None)
        entity = materialize() if callable(materialize) else entity
        if not isinstance(entity, dict) or entity.get("type") != "vehicle":
            continue
        if str(entity.get("vehicle_class") or "").strip().lower() not in SPACECRAFT_CLASSES:
            continue
        name = entity.get("pretty_name") or entity.get("name") or entity.get("id")
        designs.append((entity.get("id"), name, space_profile_from_design(entity, world_model)))
    return designs
