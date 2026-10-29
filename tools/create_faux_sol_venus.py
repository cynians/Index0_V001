"""Idempotently create Faux Venus through the normal world-generation stages."""

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


def _composition_fraction(atmosphere, molecule):
    for item in atmosphere.get("composition", []):
        if item.get("molecule") == molecule:
            return float(item.get("fraction", 0.0) or 0.0)
    return 0.0


def _fraction_near_datum(heightmap, tolerance_m=1000.0):
    rows = ((heightmap.get("sample_grid") or {}).get("rows") or [])
    values = [float(value) for row in rows for value in row]
    if not values:
        return 0.0
    return sum(abs(value) <= tolerance_m for value in values) / len(values)


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
        "system_age_gyr": 4.567,
        "constituents": [STAR_ID],
        "tags": ["world_gen_calibration", "solar_system_analogue"],
        "wiki_entry": "A world-generation calibration system whose present-day bodies retain the outcomes of age-dependent processes.",
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
        "age_gyr": 4.567,
        "mass_kg": 1.98847e30,
        "radius_m": 696_340_000.0,
        "luminosity_solar": 1.0,
        "display_color": [255, 236, 188],
        "tags": ["world_gen_calibration", "solar_analogue"],
    })

    sim = WorldGenSimulation(world_model=world, parent_system_id=SYSTEM_ID)
    sim.active_planet_template = "runaway_greenhouse_terrestrial"
    sim.pending_body_class = "planet"
    sim.input_buffers["periapsis_au"] = "0.71844"
    sim.input_buffers["apoapsis_au"] = "0.72821"
    sim.planet_name_buffer = "Faux Venus"
    if not sim._commit_named_planet():
        raise RuntimeError(sim.commit_status)

    sim.active_planet_template = "runaway_greenhouse_terrestrial"
    sim.seed_input_buffers.update({
        "radius_earth": "0.94988",
        "core_radius_fraction": "0.52",
        "crust_thickness_km": "25",
        "angular_velocity_deg_per_hour": "-0.061722",
        "water_fraction": "0",
        "volatile_inventory": "dense",
        "tectonics_mode": "episodic_lid",
        "map_seed": "faux-sol-venus-v1",
    })
    template = sim.PLANET_TEMPLATES["runaway_greenhouse_terrestrial"]
    sim.crust_composition = {
        "major_elements": [
            {"symbol": symbol, "name": element_name(symbol), "abundance_percent": abundance}
            for symbol, abundance in template["major_elements"]
        ],
        "trace_reserve_percent": TRACE_RESERVE_PERCENT,
        "trace_elements": [
            {"symbol": "N", "name": element_name("N"), "abundance_percent": 0.12, "rarity": "common"},
            {"symbol": "Ar", "name": element_name("Ar"), "abundance_percent": 0.01, "rarity": "rare"},
            {"symbol": "Cl", "name": element_name("Cl"), "abundance_percent": 0.02, "rarity": "common"},
        ],
    }
    planet = sim._selected_planet_entity()
    planet["world_gen_seed"] = {
        "surface_age_myr": 350.0,
        "impact_flux_factor": 1.0,
        "resurfacing_fraction": 0.82,
        "water_loss_fraction": 0.995,
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
    atmosphere = planet["atmosphere_model"]
    heightmap = planet.get("heightmap_model") or {}
    features = planet.get("plume_lid_feature_model") or {}
    crater_model = planet.get("crater_model") or {}
    circulation = atmosphere.get("circulation_model") or {}
    clouds = atmosphere.get("cloud_model") or {}
    weathering = planet.get("surface_weathering_model") or {}
    planet["reference_calibration"] = {
        "target": "Venus",
        "status": "ready_for_visual_review",
        "distinctive_characteristics": {
            "runaway_co2_greenhouse": {
                "target": ">96% CO2, about 92 bar and 737 K",
                "generated": {
                    "co2_percent": round(_composition_fraction(atmosphere, "CO2") * 100.0, 3),
                    "pressure_bar": atmosphere.get("surface_pressure_bar"),
                    "temperature_k": atmosphere.get("estimated_surface_temperature_k"),
                },
            },
            "sulfuric_acid_cloud_deck": {
                "target": "near-global sulfuric-acid clouds with acid virga",
                "generated": clouds,
            },
            "atmospheric_superrotation": {
                "target": "cloud atmosphere circles the planet in about four Earth days",
                "generated": circulation,
            },
            "collapsed_hydrologic_cycle": {
                "target": "no present liquid water, rain, or runoff after ancient water loss",
                "generated": planet.get("hydrologic_history_model"),
            },
            "plain_dominated_hypsometry": {
                "target": "over 80% of surface within about 1 km of mean radius",
                "generated": {"fraction_within_1km_of_datum": round(_fraction_near_datum(heightmap), 4)},
            },
            "plume_lid_coronae_and_rifts": {
                "target": "coronae, rift belts and plume-driven deformation without an Earth-like plate network",
                "generated": {"coronae": len(features.get("coronae", [])), "rift_belts": len(features.get("rift_belts", []))},
            },
            "tessera_highlands": {
                "target": "elevated, cross-cut ridged tessera terrain",
                "generated": {"tessera_regions": len(features.get("tesserae", []))},
            },
            "venusian_volcanic_landforms": {
                "target": "shield provinces, pancake domes and very long lava channels",
                "generated": {
                    "shield_provinces": len(features.get("volcanic_rises", [])),
                    "pancake_domes": len(features.get("pancake_domes", [])),
                    "lava_channels": len(features.get("lava_channels", [])),
                },
            },
            "young_resurfaced_crater_record": {
                "target": "geologically young plains, sparse craters and atmospheric filtering of small impactors",
                "generated": {
                    "surface_record_age_myr": (planet.get("planetary_evolution_model") or {}).get("surface_record_age_myr"),
                    "resurfacing_fraction": 0.82,
                    "resolved_craters": len(crater_model.get("craters", [])),
                    "atmospheric_entry_cutoff_km": crater_model.get("atmospheric_entry_cutoff_km"),
                },
            },
            "hot_surface_weathering_and_bright_highlands": {
                "target": "hot CO2/sulfur rock reactions and elevation-dependent radar-bright terrain",
                "generated": weathering,
            },
        },
        "sources": [
            "https://science.nasa.gov/venus/venus-facts/",
            "https://science.nasa.gov/asset/hubble/venus-cloud-tops/",
            "https://www.usgs.gov/publications/venus-volcanism-initial-analysis-magellan-data",
            "https://www.jpl.nasa.gov/news/nasas-magellan-mission-reveals-possible-tectonic-activity-on-venus/",
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
    for key, values in result["reference_calibration"]["distinctive_characteristics"].items():
        print(f"{key}: {values['generated']}")
