"""Planetary-scale mineralization potential hints.

This does not model deposit genesis (tonnage, grade, vein geometry, deposit
body shape) -- that resolves at regional/site scale in regional_materials.py,
which already defines hydrothermal_vein/hydrothermal_sulfide deposit types.
This module exposes a coarse, per-cell HINT of where regional deposit
generation is more likely to be rewarding, derived entirely from tectonic
data that already exists at planetary scale:

- subduction-arc proximity on the overriding plate -> porphyry-style
  potential (e.g. porphyry copper belts form above subducting slabs)
- mid-ocean-ridge / young-oceanic-crust proximity -> volcanogenic massive
  sulfide (VMS) potential
- collision/transform deformation-zone proximity -> orogenic-gold-style
  potential
- large-igneous-province hotspots add a secondary boost, since major mantle
  plume volcanism is also associated with magmatic sulfide concentration
"""

import math


MINERALIZATION_MODEL_VERSION = "mineralization-potential-v1"

FAVORABLE_THRESHOLD = 0.35


def _clamp(value, low=0.0, high=1.0):
    return max(low, min(high, float(value)))


def _wrapped_delta(a, b):
    delta = a - b
    return delta - round(delta)


def _nearest_boundary_distance(nx, ny, segments):
    nearest = 2.0
    for segment in segments:
        try:
            x1 = float(segment["x1"])
            y1 = float(segment["y1"])
            x2 = float(segment["x2"])
            y2 = float(segment["y2"])
        except (KeyError, TypeError, ValueError):
            continue
        for px, py in ((x1, y1), ((x1 + x2) * 0.5, (y1 + y2) * 0.5), (x2, y2)):
            distance = math.hypot(_wrapped_delta(nx, px), ny - py)
            if distance < nearest:
                nearest = distance
    return nearest


def _summary(rows):
    flat = [value for row in rows for value in row]
    if not flat:
        return {"mean": 0.0, "favorable_fraction": 0.0}
    favorable = sum(1 for value in flat if value >= FAVORABLE_THRESHOLD) / len(flat)
    return {"mean": round(sum(flat) / len(flat), 4), "favorable_fraction": round(favorable, 4)}


def derive_mineralization_potential_model(tectonic_model):
    tectonic_model = tectonic_model if isinstance(tectonic_model, dict) else {}
    boundary_segments = tectonic_model.get("boundary_segments") or []
    subduction_segments = [segment for segment in boundary_segments if segment.get("kind") == "subduction"]
    divergent_segments = [segment for segment in boundary_segments if segment.get("kind") == "divergent"]
    deformation_segments = [
        segment for segment in boundary_segments if segment.get("kind") in ("collision", "transform")
    ]
    hotspots = (tectonic_model.get("hotspot_model") or {}).get("hotspots") or []
    lig_hotspots = [item for item in hotspots if item.get("buoyancy_flux_class") == "major"]

    lithosphere_grid = tectonic_model.get("lithosphere_grid") or {}
    width = int(lithosphere_grid.get("width", 0) or 0)
    height = int(lithosphere_grid.get("height", 0) or 0)
    age_rows = lithosphere_grid.get("ocean_floor_age_rows_myr") or []
    if not width or not height:
        return {"status": "unavailable", "model_version": MINERALIZATION_MODEL_VERSION}

    porphyry_rows, vms_rows, orogenic_rows = [], [], []
    for y in range(height):
        porphyry_row, vms_row, orogenic_row = [], [], []
        ny = y / max(1, height - 1)
        for x in range(width):
            nx = x / max(1, width - 1)
            porphyry = math.exp(-((_nearest_boundary_distance(nx, ny, subduction_segments) / 0.05) ** 2))
            young_crust = 0.0
            if age_rows and y < len(age_rows) and x < len(age_rows[y]):
                young_crust = _clamp(1.0 - float(age_rows[y][x]) / 40.0)
            ridge_proximity = math.exp(-((_nearest_boundary_distance(nx, ny, divergent_segments) / 0.05) ** 2))
            vms = max(ridge_proximity, young_crust * 0.6)
            orogenic = math.exp(-((_nearest_boundary_distance(nx, ny, deformation_segments) / 0.06) ** 2))
            lip_boost = 0.0
            for hotspot in lig_hotspots:
                hx = float(hotspot.get("mantle_x", 0.5) or 0.5)
                hy = float(hotspot.get("mantle_y", 0.5) or 0.5)
                distance = math.hypot(_wrapped_delta(nx, hx), ny - hy)
                lip_boost = max(lip_boost, math.exp(-((distance / 0.08) ** 2)))
            porphyry_row.append(round(_clamp(porphyry), 3))
            vms_row.append(round(_clamp(vms + lip_boost * 0.3), 3))
            orogenic_row.append(round(_clamp(orogenic), 3))
        porphyry_rows.append(porphyry_row)
        vms_rows.append(vms_row)
        orogenic_rows.append(orogenic_row)

    return {
        "status": "mineralization_potential_derived",
        "model_version": MINERALIZATION_MODEL_VERSION,
        "width": width,
        "height": height,
        "porphyry_potential_rows": porphyry_rows,
        "vms_potential_rows": vms_rows,
        "orogenic_gold_potential_rows": orogenic_rows,
        "summary": {
            "porphyry_potential": _summary(porphyry_rows),
            "vms_potential": _summary(vms_rows),
            "orogenic_gold_potential": _summary(orogenic_rows),
        },
        "notes": [
            "Coarse planetary-scale hint from subduction-arc, ridge, and "
            "deformation-zone proximity plus large-igneous-province hotspots.",
            "Does not model deposit genesis, tonnage, or grade -- "
            "regional/site generation resolves actual deposits and may "
            "weight toward these favorable zones.",
        ],
    }
