"""Idempotently generate Faux Earth with coupled oceans, climate, and hydrology."""

from simulations.world_gen.crust import element_name
from simulations.world_gen.world_gen_sim import TRACE_RESERVE_PERCENT, WorldGenSimulation
from world.world_model import WorldModel


SYSTEM_ID = "system_faux_sol"
STAR_ID = "star_faux_sol"


def _upsert(loader, entity):
    existing = loader.get(entity["id"])
    if isinstance(existing, dict):
        existing.update(entity)
        entity = existing
    loader.persist_entity(entity)
    return entity


def _gas_percent(atmosphere, molecule):
    for item in atmosphere.get("composition", []):
        if item.get("molecule") == molecule:
            return round(float(item.get("fraction", 0.0) or 0.0) * 100.0, 3)
    return 0.0


def create():
    world = WorldModel()
    loader = world.loader
    system = _upsert(loader, {
        "id": SYSTEM_ID, "name": "Faux Sol System", "pretty_name": "Faux Sol System",
        "type": "location", "_dataset": "locations", "location_class": "star_system",
        "location_role": "star_system", "system_role": "star_system",
        "system_age_gyr": 4.567, "constituents": [STAR_ID],
        "tags": ["world_gen_calibration", "solar_system_analogue"],
    })
    _upsert(loader, {
        "id": STAR_ID, "name": "Faux Sol", "pretty_name": "Faux Sol", "type": "location",
        "_dataset": "locations", "location_class": "star", "location_role": "orbital_body",
        "system_role": "orbital_body", "star_system": SYSTEM_ID, "parent_location": SYSTEM_ID,
        "star_class": "main_sequence", "spectral_class": "G2V", "age_gyr": 4.567,
        "mass_kg": 1.98847e30, "radius_m": 696_340_000.0, "luminosity_solar": 1.0,
        "display_color": [255, 236, 188], "tags": ["world_gen_calibration", "solar_analogue"],
    })

    sim = WorldGenSimulation(world_model=world, parent_system_id=SYSTEM_ID)
    sim.active_planet_template = "oxygenated_ocean_plate_world"
    sim.pending_body_class = "planet"
    sim.input_buffers.update({"periapsis_au": "0.98329", "apoapsis_au": "1.01671"})
    sim.planet_name_buffer = "Faux Earth"
    if not sim._commit_named_planet():
        raise RuntimeError(sim.commit_status)

    sim.active_planet_template = "oxygenated_ocean_plate_world"
    sim.seed_input_buffers.update({
        "radius_earth": "1.0", "core_radius_fraction": "0.55", "crust_thickness_km": "35",
        "angular_velocity_deg_per_hour": "15.0", "water_fraction": "0.71",
        "volatile_inventory": "earthlike", "tectonics_mode": "mobile_lid", "map_seed": "faux-sol-earth-v1",
    })
    template = sim.PLANET_TEMPLATES["oxygenated_ocean_plate_world"]
    sim.crust_composition = {
        "major_elements": [
            {"symbol": symbol, "name": element_name(symbol), "abundance_percent": abundance}
            for symbol, abundance in template["major_elements"]
        ],
        "trace_reserve_percent": TRACE_RESERVE_PERCENT,
        "trace_elements": [
            {"symbol": "N", "name": element_name("N"), "abundance_percent": 0.12, "rarity": "common"},
            {"symbol": "C", "name": element_name("C"), "abundance_percent": 0.08, "rarity": "common"},
            {"symbol": "Ar", "name": element_name("Ar"), "abundance_percent": 0.01, "rarity": "rare"},
        ],
    }
    planet = sim._selected_planet_entity()
    planet["world_gen_seed"] = {
        "axial_tilt_deg": 23.44, "surface_age_myr": 180.0, "resurfacing_fraction": 0.62,
        "impact_flux_factor": 0.65, "biosphere_state": "oxygenic_mature", "ocean_fraction_target": 0.708,
    }
    for stage in (
        sim._save_selected_planet_seed, sim._save_atmosphere_model,
        sim._save_interior_regime_model, sim._save_terrain_seed_model,
        sim._save_water_cycle_model,
    ):
        if not stage():
            raise RuntimeError(sim.commit_status)

    planet = sim._selected_planet_entity()
    atmosphere = planet.get("atmosphere_model") or {}
    heightmap = planet.get("heightmap_model") or {}
    water = planet.get("water_cycle_model") or {}
    ocean = water.get("ocean_circulation_model") or {}
    hypsometry = heightmap.get("hypsometry_summary") or {}
    planet["reference_calibration"] = {
        "target": "Earth",
        "status": "ready_for_ocean_climate_review",
        "characteristics": {
            "radius_earth": (planet.get("derived_planet_physics") or {}).get("radius_earth"),
            "mass_earth": (planet.get("derived_planet_physics") or {}).get("mass_earth"),
            "rotation_hours": (planet.get("derived_planet_physics") or {}).get("rotation_period_hours"),
            "axial_tilt_deg": (planet.get("world_gen_seed") or {}).get("axial_tilt_deg"),
            "surface_pressure_bar": atmosphere.get("surface_pressure_bar"),
            "surface_temperature_k": atmosphere.get("estimated_surface_temperature_k"),
            "nitrogen_percent": _gas_percent(atmosphere, "N2"),
            "oxygen_percent": _gas_percent(atmosphere, "O2"),
            "ocean_fraction": hypsometry.get("ocean_fraction"),
            "ocean_basins": (ocean.get("summary") or {}).get("ocean_basin_count"),
            "major_gyres": (ocean.get("summary") or {}).get("major_gyre_count"),
            "mean_land_precipitation_mm": (water.get("runoff_summary") or {}).get("mean_land_precipitation_mm"),
            "river_count": water.get("river_count"),
        },
        "sources": [
            "https://oceanservice.noaa.gov/education/tutorial_currents/04currents2.html",
            "https://oceanservice.noaa.gov/education/tutorial_currents/04currents3.html",
            "https://www.usgs.gov/water-science-school/water-cycle",
        ],
    }
    sim._mirror_and_persist_planet(planet)
    constituents = list(system.get("constituents") or [])
    for entity_id in (STAR_ID, planet["id"]):
        if entity_id not in constituents:
            constituents.append(entity_id)
    system["constituents"] = constituents
    loader.persist_entity(system)
    return planet


if __name__ == "__main__":
    result = create()
    print(result["id"], result["name"])
    for key, value in result["reference_calibration"]["characteristics"].items():
        print(f"{key}: {value}")
