"""Recompute Earth climate from the bundled authored relief grid.

This lightweight refresh intentionally needs no geospatial input libraries: it
keeps the bundled Natural Earth rivers and lakes while evaluating the same
coupled climate model used by generated worlds.
"""

import gzip
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from simulations.world_gen.water_cycle import derive_water_cycle_model


OUTPUT = ROOT / "world" / "reference_data" / "earth_worldgen_reference.json.gz"


def refresh():
    with gzip.open(OUTPUT, "rt", encoding="utf-8") as handle:
        payload = json.load(handle)

    heightmap = payload["heightmap_model"]
    prior_water = payload.get("water_cycle_model") or {}
    simulated = derive_water_cycle_model(
        terrain={
            "map_seed": "earth_reference_2026",
            "hydrology": {
                "target_ocean_fraction": heightmap.get("ocean_fraction", 0.708),
                "liquid_water_possible": True,
                # Natural Earth remains the visual river reference; this pass
                # specifically evaluates the generated climate model.
                "drainage_enabled": False,
            },
        },
        heightmap=heightmap,
        atmosphere={
            "estimated_surface_temperature_k": 288.0,
            "surface_pressure_bar": 1.01325,
        },
        seed={
            "map_seed": "earth_reference_2026",
            "rotation_hours": 23.934,
            "axial_tilt_deg": 23.44,
            "climate_mode": "latitudinal_seasonal",
        },
        planet_id="planet_earth",
    )
    simulated.update({
        "status": "earth_reference_simulated_climate",
        "source": "Index0 coupled climate model driven by NOAA/NCEI ETOPO5 relief; Natural Earth supplies reference hydrography.",
        "rivers": prior_water.get("rivers") or [],
        "river_count": len(prior_water.get("rivers") or []),
        "reference_lakes": prior_water.get("reference_lakes") or [],
        "lake_count": len(prior_water.get("reference_lakes") or []),
    })
    payload["water_cycle_model"] = simulated
    with gzip.open(OUTPUT, "wt", encoding="utf-8", compresslevel=9) as handle:
        json.dump(payload, handle, separators=(",", ":"), ensure_ascii=False)
    return payload


if __name__ == "__main__":
    result = refresh()
    grid = result["water_cycle_model"]["climate_grid"]
    print(f"Wrote simulated Earth climate: {grid['width']}x{grid['height']}")
