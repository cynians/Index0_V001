import math


EARTH_RADIUS_M = 6_371_000.0
EARTH_MASS_KG = 5.9722e24
GRAVITATIONAL_CONSTANT = 6.67430e-11
DEFAULT_MANTLE_DENSITY_KG_M3 = 4500.0
DEFAULT_CORE_DENSITY_KG_M3 = 11000.0


def sphere_volume(radius_m):
    return (4.0 / 3.0) * math.pi * max(0.0, radius_m) ** 3


def shell_volume(outer_radius_m, inner_radius_m):
    return max(0.0, sphere_volume(outer_radius_m) - sphere_volume(inner_radius_m))


def derive_planet_physics(seed, crust_density_kg_m3):
    radius_earth = max(0.01, float(seed.get("radius_earth", 1.0)))
    radius_m = radius_earth * EARTH_RADIUS_M
    core_radius_fraction = max(0.0, min(0.95, float(seed.get("core_radius_fraction", 0.55))))
    crust_thickness_km = max(0.1, float(seed.get("crust_thickness_km", 35.0)))
    crust_thickness_m = min(crust_thickness_km * 1000.0, radius_m * 0.45)
    kind = str(seed.get("planet_class") or seed.get("planet_template") or "").strip().lower()

    core_radius_m = radius_m * core_radius_fraction
    crust_inner_radius_m = max(core_radius_m, radius_m - crust_thickness_m)
    mantle_thickness_m = max(0.0, crust_inner_radius_m - core_radius_m)
    total_volume_m3 = sphere_volume(radius_m)

    if kind == "icy_satellite":
        bulk_ice_fraction = max(0.05, min(0.9, float(seed.get("bulk_ice_fraction", 0.52) or 0.52)))
        rock_density = 3300.0
        ice_density = 930.0
        rock_mass_fraction = 1.0 - bulk_ice_fraction
        mean_density_kg_m3 = 1.0 / (
            rock_mass_fraction / rock_density + bulk_ice_fraction / ice_density
        )
        mass_kg = total_volume_m3 * mean_density_kg_m3
        rock_volume_m3 = mass_kg * rock_mass_fraction / rock_density
        ice_volume_m3 = max(0.0, total_volume_m3 - rock_volume_m3)
        rock_core_radius_m = (rock_volume_m3 * 3.0 / (4.0 * math.pi)) ** (1.0 / 3.0)
        ice_shell_thickness_m = max(0.0, radius_m - rock_core_radius_m)
        surface_gravity_m_s2 = GRAVITATIONAL_CONSTANT * mass_kg / (radius_m * radius_m)
        angular_velocity_deg_per_hour = max(0.0001, float(seed.get("angular_velocity_deg_per_hour", 5.5)))
        rotation_period_hours = 360.0 / angular_velocity_deg_per_hour
        return {
            "radius_m": radius_m,
            "radius_earth": radius_earth,
            "core_radius_fraction": rock_core_radius_m / radius_m,
            "mantle_radius_fraction": 0.0,
            "crust_radius_fraction": ice_shell_thickness_m / radius_m,
            "crust_thickness_km": ice_shell_thickness_m / 1000.0,
            "core_density_kg_m3": rock_density,
            "mantle_density_kg_m3": 0.0,
            "crust_density_kg_m3": ice_density,
            "core_mass_kg": mass_kg * rock_mass_fraction,
            "mantle_mass_kg": 0.0,
            "crust_mass_kg": mass_kg * bulk_ice_fraction,
            "mass_kg": mass_kg,
            "mass_earth": mass_kg / EARTH_MASS_KG,
            "mean_density_kg_m3": mean_density_kg_m3,
            "surface_gravity_m_s2": surface_gravity_m_s2,
            "surface_gravity_g": surface_gravity_m_s2 / 9.80665,
            "angular_velocity_deg_per_hour": angular_velocity_deg_per_hour,
            "angular_velocity_rad_s": math.radians(angular_velocity_deg_per_hour) / 3600.0,
            "rotation_period_hours": rotation_period_hours,
            "bulk_ice_fraction": bulk_ice_fraction,
            "rock_mass_fraction": rock_mass_fraction,
            "ice_shell_thickness_km": ice_shell_thickness_m / 1000.0,
            "interior_class": "differentiated_rock_core_ice_shell",
        }

    if kind in {"gas_giant", "ice_giant", "hot_gas_giant"}:
        density_anchor = 1320.0 if kind in {"gas_giant", "hot_gas_giant"} else 1650.0
        density_scale = 0.86 + min(0.34, core_radius_fraction)
        mean_density_kg_m3 = density_anchor * density_scale
        mass_kg = total_volume_m3 * mean_density_kg_m3
        core_mass_fraction = min(0.36, max(0.04, core_radius_fraction * 1.35))
        core_mass_kg = mass_kg * core_mass_fraction
        envelope_mass_kg = mass_kg - core_mass_kg
        surface_gravity_m_s2 = GRAVITATIONAL_CONSTANT * mass_kg / (radius_m * radius_m)

        angular_velocity_deg_per_hour = max(0.0001, float(seed.get("angular_velocity_deg_per_hour", 15.0)))
        rotation_period_hours = 360.0 / angular_velocity_deg_per_hour
        angular_velocity_rad_s = math.radians(angular_velocity_deg_per_hour) / 3600.0

        return {
            "radius_m": radius_m,
            "radius_earth": radius_earth,
            "core_radius_fraction": core_radius_fraction,
            "mantle_radius_fraction": 0.0,
            "crust_radius_fraction": 0.0,
            "crust_thickness_km": 0.0,
            "core_density_kg_m3": DEFAULT_CORE_DENSITY_KG_M3,
            "mantle_density_kg_m3": 0.0,
            "crust_density_kg_m3": 0.0,
            "core_mass_kg": core_mass_kg,
            "mantle_mass_kg": envelope_mass_kg,
            "crust_mass_kg": 0.0,
            "mass_kg": mass_kg,
            "mass_earth": mass_kg / EARTH_MASS_KG,
            "mean_density_kg_m3": mean_density_kg_m3,
            "surface_gravity_m_s2": surface_gravity_m_s2,
            "surface_gravity_g": surface_gravity_m_s2 / 9.80665,
            "angular_velocity_deg_per_hour": angular_velocity_deg_per_hour,
            "angular_velocity_rad_s": angular_velocity_rad_s,
            "rotation_period_hours": rotation_period_hours,
        }

    core_volume_m3 = sphere_volume(core_radius_m)
    mantle_volume_m3 = shell_volume(crust_inner_radius_m, core_radius_m)
    crust_volume_m3 = shell_volume(radius_m, crust_inner_radius_m)

    core_density_kg_m3 = max(2500.0, float(seed.get("core_density_kg_m3", DEFAULT_CORE_DENSITY_KG_M3) or DEFAULT_CORE_DENSITY_KG_M3))
    mantle_density_kg_m3 = max(1500.0, float(seed.get("mantle_density_kg_m3", DEFAULT_MANTLE_DENSITY_KG_M3) or DEFAULT_MANTLE_DENSITY_KG_M3))
    core_mass_kg = core_volume_m3 * core_density_kg_m3
    mantle_mass_kg = mantle_volume_m3 * mantle_density_kg_m3
    crust_mass_kg = crust_volume_m3 * crust_density_kg_m3
    mass_kg = core_mass_kg + mantle_mass_kg + crust_mass_kg
    mean_density_kg_m3 = mass_kg / total_volume_m3 if total_volume_m3 > 0 else 0.0
    surface_gravity_m_s2 = GRAVITATIONAL_CONSTANT * mass_kg / (radius_m * radius_m)

    angular_velocity_deg_per_hour = float(seed.get("angular_velocity_deg_per_hour", 15.0) or 15.0)
    if abs(angular_velocity_deg_per_hour) < 0.0001:
        angular_velocity_deg_per_hour = 0.0001
    rotation_period_hours = 360.0 / abs(angular_velocity_deg_per_hour)
    angular_velocity_rad_s = math.radians(angular_velocity_deg_per_hour) / 3600.0

    return {
        "radius_m": radius_m,
        "radius_earth": radius_earth,
        "core_radius_fraction": core_radius_fraction,
        "mantle_radius_fraction": mantle_thickness_m / radius_m if radius_m > 0 else 0.0,
        "crust_radius_fraction": crust_thickness_m / radius_m if radius_m > 0 else 0.0,
        "crust_thickness_km": crust_thickness_m / 1000.0,
        "core_density_kg_m3": core_density_kg_m3,
        "mantle_density_kg_m3": mantle_density_kg_m3,
        "crust_density_kg_m3": crust_density_kg_m3,
        "core_mass_kg": core_mass_kg,
        "mantle_mass_kg": mantle_mass_kg,
        "crust_mass_kg": crust_mass_kg,
        "mass_kg": mass_kg,
        "mass_earth": mass_kg / EARTH_MASS_KG,
        "mean_density_kg_m3": mean_density_kg_m3,
        "surface_gravity_m_s2": surface_gravity_m_s2,
        "surface_gravity_g": surface_gravity_m_s2 / 9.80665,
        "angular_velocity_deg_per_hour": angular_velocity_deg_per_hour,
        "angular_velocity_rad_s": angular_velocity_rad_s,
        "rotation_period_hours": rotation_period_hours,
        "rotation_direction": "retrograde" if angular_velocity_deg_per_hour < 0.0 else "prograde",
    }
