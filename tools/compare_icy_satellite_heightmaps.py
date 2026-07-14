"""Compare procedural icy-satellite relief with the Cassini-derived Dione reference."""

import json
import math
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from simulations.world_gen.atmosphere import derive_atmosphere_model
from simulations.world_gen.heightmap import derive_heightmap_model
from simulations.world_gen.interior_regime import derive_interior_regime_model
from simulations.world_gen.planetary_physics import derive_planet_physics
from simulations.world_gen.tectonics import derive_crater_model
from simulations.world_gen.terrain_seed import derive_terrain_seed_model


def _relief_metrics(payload):
    rows = payload.get("rows") or payload["sample_grid"]["rows"]
    values = [float(value) for row in rows for value in row[:-1]]
    ordered = sorted(values)
    neighbor_differences = []
    for row_index, row in enumerate(rows):
        for col_index in range(len(row) - 1):
            neighbor_differences.append(float(row[col_index]) - float(row[(col_index + 1) % (len(row) - 1)]))
            if row_index + 1 < len(rows):
                neighbor_differences.append(float(row[col_index]) - float(rows[row_index + 1][col_index]))
    return {
        "min_elevation_m": round(min(values), 1),
        "max_elevation_m": round(max(values), 1),
        "relief_range_m": round(max(values) - min(values), 1),
        "mean_elevation_m": round(statistics.fmean(values), 1),
        "standard_deviation_m": round(statistics.pstdev(values), 1),
        "p05_m": round(ordered[int(0.05 * (len(ordered) - 1))], 1),
        "p95_m": round(ordered[int(0.95 * (len(ordered) - 1))], 1),
        "neighbor_rms_m": round(math.sqrt(statistics.fmean(value * value for value in neighbor_differences)), 1),
    }


def _generate_case(case_id, surface_age_myr, resurfacing_fraction, impact_flux_factor, tidal_heating_w_m2):
    seed = {
        "planet_id": f"moon_{case_id}",
        "planet_template": "icy_satellite",
        "planet_class": "icy_satellite",
        "orbital_body_class": "moon",
        "radius_earth": 561_400.0 / 6_371_000.0,
        "core_radius_fraction": 0.61,
        "crust_thickness_km": 180.0,
        "angular_velocity_deg_per_hour": 360.0 / (2.736915 * 24.0),
        "water_fraction": 0.0,
        "bulk_ice_fraction": 0.52,
        "surface_ice_fraction": 1.0,
        "volatile_inventory": "none",
        "tectonics_mode": "unknown",
        "map_seed": f"icy-comparison-{case_id}",
        "surface_age_myr": surface_age_myr,
        "tidal_heating_w_m2": tidal_heating_w_m2,
        "resurfacing_fraction": resurfacing_fraction,
        "impact_flux_factor": impact_flux_factor,
        "crater_population_slope": 1.9,
    }
    physics = derive_planet_physics(seed, 930.0)
    atmosphere = derive_atmosphere_model(seed, physics, 1.0, 9.58)
    regime = derive_interior_regime_model(seed, physics, atmosphere, "water_ice_shell")
    terrain = derive_terrain_seed_model(seed, physics, atmosphere, regime, planet_id=seed["planet_id"], system_id="comparison")
    craters = derive_crater_model(terrain, seed, physics, seed["planet_id"])
    heightmap = derive_heightmap_model(terrain, seed, physics, seed["planet_id"], crater_model=craters)
    return {
        "inputs": {
            "surface_age_myr": surface_age_myr,
            "resurfacing_fraction": resurfacing_fraction,
            "impact_flux_factor": impact_flux_factor,
            "tidal_heating_w_m2": tidal_heating_w_m2,
        },
        "physics": {
            "mean_density_kg_m3": round(physics["mean_density_kg_m3"], 1),
            "surface_gravity_g": round(physics["surface_gravity_g"], 4),
            "ice_shell_thickness_km": round(physics["ice_shell_thickness_km"], 1),
        },
        "craters": {
            "catalog_count": len(craters["craters"]),
            "minimum_catalog_diameter_km": craters["minimum_catalog_diameter_km"],
            "counts_at_or_above_km": {
                str(diameter): sum(crater["diameter_km"] >= diameter for crater in craters["craters"])
                for diameter in (10, 20, 50, 100, 200)
            },
        },
        "relief": _relief_metrics(heightmap),
    }


def main():
    reference = json.loads((ROOT / "world" / "reference_data" / "dione_heightmap_reference.json").read_text(encoding="utf-8"))
    result = {
        "reference_dione": _relief_metrics(reference),
        "procedural_cases": {
            "dione_range": _generate_case("dione_range", 3800.0, 0.22, 1.0, 0.012),
            "young_resurfaced": _generate_case("young_resurfaced", 450.0, 0.68, 0.75, 0.055),
            "ancient_quiet": _generate_case("ancient_quiet", 4500.0, 0.05, 1.2, 0.003),
        },
    }
    output = ROOT / ".cache" / "icy_satellite_heightmap_comparison.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
