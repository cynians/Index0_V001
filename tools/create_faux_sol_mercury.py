"""Idempotently create the Faux Sol system and its first world-gen calibration body."""

from simulations.world_gen.crust import element_name
from simulations.world_gen.world_gen_sim import TRACE_RESERVE_PERCENT, WorldGenSimulation
from world.world_model import WorldModel


SYSTEM_ID = "system_faux_sol"
STAR_ID = "star_faux_sol"


def upsert(loader, entity):
    existing = loader.get(entity["id"])
    if isinstance(existing, dict):
        existing.update(entity)
        entity = existing
    loader.persist_entity(entity)
    return entity


def create():
    world = WorldModel()
    loader = world.loader

    system = upsert(loader, {
        "id": SYSTEM_ID,
        "name": "Faux Sol System",
        "pretty_name": "Faux Sol System",
        "type": "location",
        "_dataset": "locations",
        "location_class": "star_system",
        "location_role": "star_system",
        "system_role": "star_system",
        "system_class": "single_star_reference_system",
        "constituents": [STAR_ID],
        "tags": ["world_gen_calibration", "solar_system_analogue"],
        "wiki_entry": "A world-generation calibration system. Bodies are produced through the normal tools and compared with Solar System measurements.",
    })
    upsert(loader, {
        "id": STAR_ID,
        "name": "Faux Sol",
        "pretty_name": "Faux Sol",
        "type": "location",
        "_dataset": "locations",
        "location_class": "star",
        "location_role": "orbital_body",
        "system_role": "orbital_body",
        "star_system": SYSTEM_ID,
        "parent_location": SYSTEM_ID,
        "star_class": "main_sequence",
        "spectral_class": "G2V",
        "mass_kg": 1.98847e30,
        "radius_m": 696_340_000.0,
        "luminosity_solar": 1.0,
        "display_color": [255, 236, 188],
        "tags": ["world_gen_calibration", "solar_analogue"],
    })

    sim = WorldGenSimulation(world_model=world, parent_system_id=SYSTEM_ID)
    sim.active_planet_template = "metal_core_airless"
    sim.pending_body_class = "planet"
    sim.input_buffers["periapsis_au"] = "0.307499"
    sim.input_buffers["apoapsis_au"] = "0.466697"
    sim.planet_name_buffer = "Faux Mercury"
    if not sim._commit_named_planet():
        raise RuntimeError(sim.commit_status)

    sim.active_planet_template = "metal_core_airless"
    sim.seed_input_buffers.update({
        "radius_earth": "0.3829",
        "core_radius_fraction": "0.85",
        "crust_thickness_km": "40",
        "angular_velocity_deg_per_hour": "0.25577",
        "water_fraction": "0",
        "volatile_inventory": "none",
        "tectonics_mode": "inactive",
        "map_seed": "faux-sol-mercury-v1",
    })
    template = sim.PLANET_TEMPLATES["metal_core_airless"]
    sim.crust_composition = {
        "major_elements": [
            {"symbol": symbol, "name": element_name(symbol), "abundance_percent": abundance}
            for symbol, abundance in template["major_elements"]
        ],
        "trace_reserve_percent": TRACE_RESERVE_PERCENT,
        "trace_elements": [
            {"symbol": "H", "name": element_name("H"), "abundance_percent": 0.03, "rarity": "common"},
            {"symbol": "He", "name": element_name("He"), "abundance_percent": 0.005, "rarity": "rare"},
        ],
    }
    planet = sim._selected_planet_entity()
    planet["world_gen_seed"] = {
        "surface_age_myr": 4000.0,
        "impact_flux_factor": 1.1,
        "resurfacing_fraction": 0.08,
    }

    for stage in (
        sim._save_selected_planet_seed,
        sim._save_atmosphere_model,
        sim._save_interior_regime_model,
        sim._save_terrain_seed_model,
    ):
        if not stage():
            raise RuntimeError(sim.commit_status)

    planet = sim._selected_planet_entity()
    physics = planet["derived_planet_physics"]
    atmosphere = planet["atmosphere_model"]
    heightmap = planet.get("heightmap_model") or {}
    planet["reference_calibration"] = {
        "target": "Mercury",
        "status": "ready_for_visual_review",
        "characteristics": {
            "mean_orbit_au": {"target": 0.3871, "generated": planet.get("semi_major_axis_m", 0.0) / sim.AU_M},
            "eccentricity": {"target": 0.2056, "generated": planet.get("eccentricity")},
            "orbital_period_days": {"target": 87.969, "generated": planet.get("orbital_period_hours", 0.0) / 24.0},
            "radius_km": {"target": 2439.7, "generated": physics.get("radius_m", 0.0) / 1000.0},
            "mass_earth": {"target": 0.0553, "generated": physics.get("mass_earth")},
            "mean_density_kg_m3": {"target": 5427.0, "generated": physics.get("mean_density_kg_m3")},
            "rotation_days": {"target": 58.646, "generated": physics.get("rotation_period_hours", 0.0) / 24.0},
            "core_radius_fraction": {"target": 0.85, "generated": physics.get("core_radius_fraction")},
            "atmosphere_state": {"target": "exosphere", "generated": atmosphere.get("atmosphere_state")},
            "relief_span_km": {"target": 9.86, "generated": (heightmap.get("max_elevation_m", 0.0) - heightmap.get("min_elevation_m", 0.0)) / 1000.0},
        },
        "known_model_gaps": [
            "No explicit axial-tilt input yet (Mercury target: about 2 degrees).",
            "The thermal model reports equilibrium/greenhouse temperature, not Mercury's day-night 430 C to -180 C extremes.",
            "Magnetic-field strength is not yet derived from core state and rotation.",
            "Crater geography is statistically analogous; it does not reproduce named Mercury basins such as Caloris.",
        ],
        "sources": [
            "https://science.nasa.gov/mercury/facts/",
            "https://eros.usgs.gov/doi-remote-sensing-activities/2016/usgs/global-topographic-map-mercury",
        ],
    }
    planet["axial_tilt_deg_reference_target"] = 2.0
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
    comparison = result["reference_calibration"]["characteristics"]
    print(result["id"], result["name"])
    for key, values in comparison.items():
        print(f"{key}: target={values['target']} generated={values['generated']}")
