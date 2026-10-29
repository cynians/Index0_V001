"""Procedural landforms for hot, volcanically resurfaced stagnant/episodic lids."""

import math

from simulations.world_gen.map_seed import seed_range


def _point(seed, label):
    return {
        "x": seed_range(seed, f"{label}:x", 0.03, 0.97),
        "y": seed_range(seed, f"{label}:y", 0.08, 0.92),
    }


def _path(seed, label, count=5):
    start = _point(seed, label)
    angle = seed_range(seed, f"{label}:angle", 0.0, math.tau)
    length = seed_range(seed, f"{label}:length", 0.08, 0.28)
    points = []
    for index in range(count):
        t = index / max(1, count - 1)
        wobble = math.sin(t * math.pi * 2.0 + seed_range(seed, f"{label}:phase", 0.0, math.tau)) * 0.018
        points.append({
            "x": (start["x"] + math.cos(angle) * length * t - math.sin(angle) * wobble) % 1.0,
            "y": max(0.03, min(0.97, start["y"] + math.sin(angle) * length * t + math.cos(angle) * wobble)),
        })
    return points


def derive_plume_lid_feature_model(seed, physics=None):
    seed = seed if isinstance(seed, dict) else {}
    physics = physics if isinstance(physics, dict) else {}
    map_seed = str(seed.get("resolved_map_seed") or seed.get("map_seed") or seed.get("planet_id") or "plume-lid")
    radius_km = max(1.0, float(physics.get("radius_m", 6_000_000.0) or 6_000_000.0) / 1000.0)

    coronae = []
    for index in range(12):
        item = _point(map_seed, f"corona:{index}")
        item.update({
            "id": f"corona_{index + 1:02d}",
            "diameter_km": seed_range(map_seed, f"corona:{index}:diameter", 120.0, 620.0),
            "uplift_m": seed_range(map_seed, f"corona:{index}:uplift", 350.0, 1350.0),
            "state": "actively_deforming" if index < 3 else "mature",
        })
        coronae.append(item)

    tesserae = []
    for index in range(7):
        item = _point(map_seed, f"tessera:{index}")
        item.update({
            "id": f"tessera_{index + 1:02d}",
            "width_km": seed_range(map_seed, f"tessera:{index}:width", 420.0, 1700.0),
            "height_km": seed_range(map_seed, f"tessera:{index}:height", 260.0, 900.0),
            "uplift_m": seed_range(map_seed, f"tessera:{index}:uplift", 900.0, 2600.0),
            "ridge_orientations_deg": [
                seed_range(map_seed, f"tessera:{index}:ridge_a", 0.0, 180.0),
                seed_range(map_seed, f"tessera:{index}:ridge_b", 0.0, 180.0),
            ],
        })
        tesserae.append(item)

    volcanic_rises = []
    for index in range(18):
        item = _point(map_seed, f"shield:{index}")
        item.update({
            "id": f"shield_province_{index + 1:02d}",
            "diameter_km": seed_range(map_seed, f"shield:{index}:diameter", 90.0, 480.0),
            "height_m": seed_range(map_seed, f"shield:{index}:height", 450.0, 4200.0),
            "activity": "active_or_recent" if index < 4 else "dormant",
        })
        volcanic_rises.append(item)

    pancake_domes = []
    for index in range(10):
        item = _point(map_seed, f"dome:{index}")
        item.update({
            "id": f"pancake_dome_{index + 1:02d}",
            "diameter_km": seed_range(map_seed, f"dome:{index}:diameter", 22.0, 62.0),
            "height_m": seed_range(map_seed, f"dome:{index}:height", 300.0, 1100.0),
            "profile": "flat_topped_steep_sided",
        })
        pancake_domes.append(item)

    rifts = [{"id": f"rift_{index + 1:02d}", "points": _path(map_seed, f"rift:{index}", 6)} for index in range(8)]
    channels = [{
        "id": f"lava_channel_{index + 1:02d}",
        "points": _path(map_seed, f"channel:{index}", 7),
        "length_km": seed_range(map_seed, f"channel:{index}:km", 280.0, 1350.0),
    } for index in range(7)]

    return {
        "status": "plume_lid_features_seeded",
        "model_version": "plume-lid-landforms-v1",
        "radius_km": radius_km,
        "coronae": coronae,
        "tesserae": tesserae,
        "volcanic_rises": volcanic_rises,
        "pancake_domes": pancake_domes,
        "rift_belts": rifts,
        "lava_channels": channels,
        "population_estimates": {
            "small_shield_volcanoes": 4200,
            "coronae": 520,
            "surface_fraction_volcanic_plains": 0.78,
        },
        "notes": ["Feature records are representative resolved landforms; population estimates describe unresolved global texture."],
    }


def derive_hot_surface_weathering_model(seed, atmosphere, feature_model=None):
    pressure = max(0.0, float((atmosphere or {}).get("surface_pressure_bar", 0.0) or 0.0))
    temperature = max(0.0, float((atmosphere or {}).get("estimated_surface_temperature_k", 0.0) or 0.0))
    active = pressure >= 20.0 and temperature >= 550.0
    return {
        "status": "active" if active else "inactive",
        "weathering_class": "hot_dense_co2_sulfur_reactions" if active else "ordinary_rock_weathering",
        "surface_fluid": "supercritical_co2" if pressure >= 73.8 and temperature >= 304.1 else "gas",
        "dominant_processes": ["oxidation", "sulfation", "chloride_reactions"] if active else [],
        "radar_bright_highlands": {
            "enabled": active,
            "elevation_threshold_m": 4700.0 if active else None,
            "transition_uncertainty_m": 900.0 if active else None,
            "cause": "candidate_temperature_dependent_mineral_weathering",
        },
        "interpretation": "candidate temperature-dependent mineral weathering; composition remains uncertain" if active else None,
    }
