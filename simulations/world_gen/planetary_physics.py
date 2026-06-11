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

    core_radius_m = radius_m * core_radius_fraction
    crust_inner_radius_m = max(core_radius_m, radius_m - crust_thickness_m)
    mantle_thickness_m = max(0.0, crust_inner_radius_m - core_radius_m)

    core_volume_m3 = sphere_volume(core_radius_m)
    mantle_volume_m3 = shell_volume(crust_inner_radius_m, core_radius_m)
    crust_volume_m3 = shell_volume(radius_m, crust_inner_radius_m)
    total_volume_m3 = sphere_volume(radius_m)

    core_mass_kg = core_volume_m3 * DEFAULT_CORE_DENSITY_KG_M3
    mantle_mass_kg = mantle_volume_m3 * DEFAULT_MANTLE_DENSITY_KG_M3
    crust_mass_kg = crust_volume_m3 * crust_density_kg_m3
    mass_kg = core_mass_kg + mantle_mass_kg + crust_mass_kg
    mean_density_kg_m3 = mass_kg / total_volume_m3 if total_volume_m3 > 0 else 0.0
    surface_gravity_m_s2 = GRAVITATIONAL_CONSTANT * mass_kg / (radius_m * radius_m)

    angular_velocity_deg_per_hour = max(0.0001, float(seed.get("angular_velocity_deg_per_hour", 15.0)))
    rotation_period_hours = 360.0 / angular_velocity_deg_per_hour
    angular_velocity_rad_s = math.radians(angular_velocity_deg_per_hour) / 3600.0

    return {
        "radius_m": radius_m,
        "radius_earth": radius_earth,
        "core_radius_fraction": core_radius_fraction,
        "mantle_radius_fraction": mantle_thickness_m / radius_m if radius_m > 0 else 0.0,
        "crust_radius_fraction": crust_thickness_m / radius_m if radius_m > 0 else 0.0,
        "crust_thickness_km": crust_thickness_m / 1000.0,
        "core_density_kg_m3": DEFAULT_CORE_DENSITY_KG_M3,
        "mantle_density_kg_m3": DEFAULT_MANTLE_DENSITY_KG_M3,
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
    }
