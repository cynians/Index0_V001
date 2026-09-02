"""Persistent, scale-aware geomorphology derived from terrain process truth.

The heightfield remains the elevation authority.  This module classifies how
that relief is expressed at the surface: ridges and scarps, incised valleys,
colluvial slopes, alluvial/depositional lows, and mantled plains.  The compact
model is persisted; dense fields are deterministically reconstructed from the
saved height, drainage, and surface-evolution grids at render resolution.

LOD contract: this is a derived interpretation of the current parent-derived
height and process state. It may classify finer ridges, valleys, scarps, talus,
alluvium, and exposure, but it is not an independent terrain source.
"""

from __future__ import annotations

import hashlib
import math

try:
    import numpy as np
except ImportError:  # pragma: no cover
    np = None


SURFACE_GEOMORPHOLOGY_MODEL_VERSION = "surface-geomorphology-v2"


def _clamp(value, low=0.0, high=1.0):
    try:
        value = float(value)
    except (TypeError, ValueError):
        value = low
    return max(low, min(high, value))


def _stable_unit(value):
    digest = hashlib.sha256(str(value).encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "little") / float((1 << 64) - 1)


def dominant_structural_strike_degrees(tectonic_model, heightmap=None, seed="surface"):
    """Resolve structural strike from the nearest persisted plate boundary."""
    tectonic_model = tectonic_model if isinstance(tectonic_model, dict) else {}
    heightmap = heightmap if isinstance(heightmap, dict) else {}
    source = heightmap.get("source_uv_bounds") if isinstance(heightmap.get("source_uv_bounds"), dict) else {}
    center_u = (float(source.get("min_u", 0.0)) + float(source.get("max_u", 1.0))) * 0.5
    center_v = (float(source.get("min_v", 0.0)) + float(source.get("max_v", 1.0))) * 0.5
    best = None
    for segment in tectonic_model.get("boundary_segments") or []:
        kind = str(segment.get("kind") or "passive")
        if kind not in {"collision", "subduction", "transform", "divergent"}:
            continue
        x1 = float(segment.get("x1", 0.0) or 0.0)
        y1 = float(segment.get("y1", 0.5) or 0.5)
        x2 = float(segment.get("x2", 0.0) or 0.0)
        y2 = float(segment.get("y2", 0.5) or 0.5)
        dx = x2 - x1
        if dx > 0.5:
            dx -= 1.0
        elif dx < -0.5:
            dx += 1.0
        dy = y2 - y1
        length_sq = dx * dx + dy * dy
        if length_sq <= 1e-12:
            continue
        for shift in (-1.0, 0.0, 1.0):
            relative_x = center_u - (x1 + shift)
            relative_y = center_v - y1
            along = _clamp((relative_x * dx + relative_y * dy) / length_sq)
            distance = math.hypot(relative_x - along * dx, relative_y - along * dy)
            kind_bonus = 0.0 if kind in {"collision", "subduction"} else 0.035
            score = distance + kind_bonus
            if best is None or score < best[0]:
                best = (score, math.degrees(math.atan2(dy, dx)) % 180.0)
    if best is not None:
        return round(best[1], 3)
    return round(_stable_unit(str(seed) + ":structural-strike") * 180.0, 3)


def _resample(values, target_h, target_w):
    values = np.asarray(values, dtype=np.float32)
    if values.ndim != 2 or values.shape[0] < 1 or values.shape[1] < 1:
        return np.zeros((target_h, target_w), dtype=np.float32)
    source_h, source_w = values.shape
    if (source_h, source_w) == (target_h, target_w):
        return values.copy()
    ys = np.linspace(0.0, source_h - 1, target_h, dtype=np.float32)
    xs = np.linspace(0.0, source_w - 1, target_w, dtype=np.float32)
    y0 = np.floor(ys).astype(np.int32)
    x0 = np.floor(xs).astype(np.int32)
    y1 = np.minimum(source_h - 1, y0 + 1)
    x1 = np.minimum(source_w - 1, x0 + 1)
    fy = (ys - y0)[:, None]
    fx = (xs - x0)[None, :]
    top = values[y0[:, None], x0[None, :]] * (1.0 - fx) + values[y0[:, None], x1[None, :]] * fx
    bottom = values[y1[:, None], x0[None, :]] * (1.0 - fx) + values[y1[:, None], x1[None, :]] * fx
    return top * (1.0 - fy) + bottom * fy


def _smooth(values, passes, *, wrap_x=False):
    result = np.asarray(values, dtype=np.float32)
    for _ in range(max(1, int(passes))):
        left = np.roll(result, 1, axis=1) if wrap_x else np.concatenate((result[:, :1], result[:, :-1]), axis=1)
        right = np.roll(result, -1, axis=1) if wrap_x else np.concatenate((result[:, 1:], result[:, -1:]), axis=1)
        up = np.concatenate((result[:1], result[:-1]), axis=0)
        down = np.concatenate((result[1:], result[-1:]), axis=0)
        result = (result * 4.0 + left + right + up + down) / 8.0
    return result


def _positive(values, percentile=96.0):
    values = np.maximum(0.0, np.asarray(values, dtype=np.float32))
    scale = float(np.percentile(values, percentile))
    return np.clip(values / max(1e-6, scale), 0.0, 1.0)


def _process_rows(model, key):
    grid = model.get("process_grid") if isinstance(model, dict) else {}
    rows = grid.get(key) if isinstance(grid, dict) else None
    return rows if isinstance(rows, list) and rows and isinstance(rows[0], list) else None


def derive_surface_geomorphology_fields(
    heightmap,
    *,
    water_cycle=None,
    surface_evolution=None,
    target_size,
):
    """Reconstruct geomorphic fields from persisted physical inputs."""
    if np is None:
        return {}
    heightmap = heightmap if isinstance(heightmap, dict) else {}
    water_cycle = water_cycle if isinstance(water_cycle, dict) else {}
    surface_evolution = surface_evolution if isinstance(surface_evolution, dict) else {}
    target_w, target_h = max(2, int(target_size[0])), max(2, int(target_size[1]))
    detail_level = max(0, int(heightmap.get("map_detail_level", 0) or 0))
    rows = ((heightmap.get("sample_grid") or {}).get("rows") or [])
    if not rows or not isinstance(rows[0], list):
        return {}
    source_h = len(rows)
    source_w = min(len(row) for row in rows if isinstance(row, list))
    source_elevation = np.asarray(
        [row[:source_w] for row in rows],
        dtype=np.float32,
    )
    elevation = _resample(source_elevation, target_h, target_w)
    spacing_x = max(1.0, float(heightmap.get("sample_spacing_x_m") or heightmap.get("equator_resolution_m_per_px") or 1.0))
    spacing_y = max(1.0, float(heightmap.get("sample_spacing_y_m") or spacing_x))
    wrap_x = bool(heightmap.get("wrap_x", False))
    source_form_elevation = source_elevation
    if detail_level >= 1:
        # Regional samples can contain one-cell generator noise that is below
        # the intended visual scale of this LOD. Smooth only the derived
        # interpretation; the persisted heightmap and all inherited values
        # remain unchanged.
        source_form_elevation = _smooth(
            source_elevation,
            1,
            wrap_x=wrap_x,
        )
    # Derive slope from the persisted sample lattice before upsampling it.
    # Differentiating the bilinear render lattice creates a slope discontinuity
    # at every source-cell edge; true color and hillshade then turn those
    # harmless interpolation boundaries into dark rectangular scratches.
    source_dzdy, source_dzdx = np.gradient(
        source_form_elevation,
        spacing_y,
        spacing_x,
    )
    dzdx = _resample(source_dzdx, target_h, target_w)
    dzdy = _resample(source_dzdy, target_h, target_w)
    gradient = np.sqrt(dzdx * dzdx + dzdy * dzdy)
    slope_degrees = np.degrees(np.arctan(gradient))
    slope = np.clip(slope_degrees / 38.0, 0.0, 1.0)

    # Classify landforms on the persisted height lattice before resampling.
    # Computing these fields on an enlarged render lattice makes each
    # bilinear cell edge look like a real ridge/scarp boundary in downstream
    # products, even though the underlying elevation is continuous.
    source_local_mean = _smooth(source_form_elevation, 2, wrap_x=wrap_x)
    source_broad_mean = _smooth(source_form_elevation, 8, wrap_x=wrap_x)
    source_local_tpi = source_form_elevation - source_local_mean
    source_broad_tpi = source_local_mean - source_broad_mean
    source_ridge = _positive(source_local_tpi * 0.72 + source_broad_tpi * 0.28)
    source_valley = _positive(-source_local_tpi * 0.78 - source_broad_tpi * 0.22)
    source_ruggedness = _positive(np.abs(source_form_elevation - source_local_mean))
    source_laplacian = source_form_elevation - _smooth(source_form_elevation, 1, wrap_x=wrap_x)
    source_convexity = _positive(source_laplacian)
    source_concavity = _positive(-source_laplacian)
    ridge = _resample(source_ridge, target_h, target_w)
    valley = _resample(source_valley, target_h, target_w)
    ruggedness = _resample(source_ruggedness, target_h, target_w)
    convexity = _resample(source_convexity, target_h, target_w)
    concavity = _resample(source_concavity, target_h, target_w)
    scarp = np.clip(slope * (0.38 + convexity * 0.62) * (0.42 + ruggedness * 0.58), 0.0, 1.0)

    evolution = {}
    for name, key in (
        ("erosion", "erosion_potential_rows"),
        ("deposition", "sediment_deposition_rows"),
        ("aeolian", "aeolian_transport_rows"),
        ("weathering", "chemical_weathering_rows"),
        ("incision", "channel_incision_rows_m"),
    ):
        process_rows = _process_rows(surface_evolution, key)
        if process_rows:
            values = np.maximum(0.0, _resample(process_rows, target_h, target_w))
            evolution[name] = _positive(values, 98.0) if name == "incision" else np.clip(values, 0.0, 1.0)
        else:
            evolution[name] = np.zeros_like(elevation)

    drainage = water_cycle.get("drainage_network_model") if isinstance(water_cycle.get("drainage_network_model"), dict) else {}
    accumulation_rows = drainage.get("flow_accumulation_rows") if isinstance(drainage, dict) else None
    if isinstance(accumulation_rows, list) and accumulation_rows and isinstance(accumulation_rows[0], list):
        accumulation = np.maximum(0.0, _resample(accumulation_rows, target_h, target_w))
        accumulation = np.log1p(accumulation)
        accumulation /= max(1e-6, float(np.percentile(accumulation, 98.0)))
        accumulation = np.clip(accumulation, 0.0, 1.0)
    else:
        accumulation = np.zeros_like(elevation)

    channel = np.maximum(accumulation, evolution["incision"])
    incised_valley = np.clip(valley * (0.28 + channel * 0.72) * (0.35 + evolution["erosion"] * 0.65), 0.0, 1.0)
    talus = np.clip(slope * (1.0 - scarp * 0.42) * (0.32 + ruggedness * 0.68) * (1.0 - evolution["deposition"] * 0.55), 0.0, 1.0)
    basin_low = np.clip((1.0 - slope) * (0.38 + valley * 0.62), 0.0, 1.0)
    alluvial = np.clip(basin_low * (evolution["deposition"] * 0.65 + channel * 0.35) * (1.0 - incised_valley * 0.5), 0.0, 1.0)
    mantled_plain = np.clip((1.0 - slope) * (0.34 + evolution["aeolian"] * 0.36 + evolution["weathering"] * 0.30) * (1.0 - alluvial * 0.55), 0.0, 1.0)
    bedrock = np.clip(0.08 + ridge * 0.32 + scarp * 0.42 + ruggedness * 0.18 + evolution["erosion"] * 0.22 - alluvial * 0.46 - mantled_plain * 0.34, 0.02, 0.99)

    return {
        "elevation": elevation,
        "dzdx": dzdx,
        "dzdy": dzdy,
        "slope": slope,
        "slope_degrees": slope_degrees,
        "ridge": ridge,
        "valley": valley,
        "ruggedness": ruggedness,
        "convexity": convexity,
        "concavity": concavity,
        "scarp": scarp,
        "drainage_accumulation": accumulation,
        "incised_valley": incised_valley,
        "talus": talus,
        "alluvial": alluvial,
        "mantled_plain": mantled_plain,
        "bedrock_exposure": bedrock,
        **evolution,
    }


def derive_surface_material_partition_fields(
    heightmap,
    *,
    water_cycle=None,
    surface_evolution=None,
    target_size,
):
    """Partition the visible solid surface into geomorphic material domains.

    The returned fractions are not colours and do not create new lithologies.
    They describe where the existing substrate is exposed and where transported
    or weathered cover can physically occupy the surface.  Material generation
    then assigns actual catalogued materials to these domains.
    """
    fields = derive_surface_geomorphology_fields(
        heightmap,
        water_cycle=water_cycle,
        surface_evolution=surface_evolution,
        target_size=target_size,
    )
    if not fields:
        return {}

    alluvial = np.clip(
        fields["alluvial"] * 0.82
        + fields["valley"] * fields["deposition"] * 0.38,
        0.0,
        0.94,
    )
    colluvial = np.clip(
        fields["talus"]
        * (0.48 + fields["slope"] * 0.34)
        * (1.0 - alluvial * 0.72),
        0.0,
        0.86,
    )
    weathered_mantle = np.clip(
        fields["mantled_plain"]
        * (0.42 + fields["weathering"] * 0.46 + fields["aeolian"] * 0.22)
        * (1.0 - alluvial * 0.70)
        * (1.0 - colluvial * 0.55),
        0.0,
        0.88,
    )
    transported_cover = np.clip(alluvial + colluvial + weathered_mantle, 0.0, 0.96)
    bedrock = np.clip(
        fields["bedrock_exposure"] * (1.0 - transported_cover * 0.88),
        0.02,
        1.0 - transported_cover,
    )
    residual_regolith = np.clip(
        1.0 - transported_cover - bedrock,
        0.0,
        0.96,
    )
    return {
        **fields,
        "exposed_bedrock_fraction": bedrock,
        "colluvial_cover_fraction": colluvial,
        "alluvial_cover_fraction": alluvial,
        "weathered_mantle_fraction": weathered_mantle,
        "residual_regolith_fraction": residual_regolith,
        "transported_cover_fraction": transported_cover,
    }


def derive_surface_geomorphology_model(
    planet,
    *,
    heightmap=None,
    water_cycle=None,
    surface_evolution=None,
    tectonic_model=None,
):
    """Return the compact persisted contract for the landform layer."""
    planet = planet if isinstance(planet, dict) else {}
    heightmap = heightmap if isinstance(heightmap, dict) else planet.get("heightmap_model") or {}
    water_cycle = water_cycle if isinstance(water_cycle, dict) else planet.get("water_cycle_model") or {}
    surface_evolution = surface_evolution if isinstance(surface_evolution, dict) else planet.get("surface_evolution_model") or {}
    tectonic_model = tectonic_model if isinstance(tectonic_model, dict) else planet.get("tectonic_model") or {}
    seed = str(heightmap.get("map_seed") or planet.get("id") or "surface")
    interior = planet.get("interior_regime_model") if isinstance(planet.get("interior_regime_model"), dict) else {}
    interior_body = interior.get("interior") if isinstance(interior.get("interior"), dict) else interior
    regime = str(
        tectonic_model.get("regime")
        or tectonic_model.get("tectonic_regime")
        or interior_body.get("tectonic_regime")
        or "unknown"
    )
    tags = {str(tag) for tag in (planet.get("natural_material_model") or {}).get("planet_tags") or []}
    active = bool(tectonic_model.get("boundary_segments") or tectonic_model.get("boundaries")) or "plate_tectonic_surface" in tags or any(token in regime.lower() for token in ("plate", "mobile", "episodic", "heat", "plume"))
    if regime == "unknown" and "plate_tectonic_surface" in tags:
        regime = "mobile_lid"
    strike = dominant_structural_strike_degrees(tectonic_model, heightmap, seed)
    fields = derive_surface_geomorphology_fields(
        heightmap,
        water_cycle=water_cycle,
        surface_evolution=surface_evolution,
        target_size=(128, 64),
    )
    summaries = {}
    if fields:
        for key in ("slope_degrees", "ridge", "valley", "scarp", "incised_valley", "talus", "alluvial", "mantled_plain", "bedrock_exposure"):
            values = fields[key]
            summaries[key] = {
                "mean": round(float(np.mean(values)), 5),
                "p90": round(float(np.percentile(values, 90.0)), 5),
            }
    fingerprint = hashlib.sha256(repr([
        heightmap.get("source_heightfield_fingerprint"),
        heightmap.get("map_seed"),
        surface_evolution.get("model_version"),
        water_cycle.get("model_version"),
        regime,
    ]).encode("utf-8")).hexdigest()
    return {
        "status": "derived",
        "model_version": SURFACE_GEOMORPHOLOGY_MODEL_VERSION,
        "truth_state": "derived_landform_state",
        "source_heightfield_fingerprint": heightmap.get("source_heightfield_fingerprint"),
        "input_fingerprint": fingerprint,
        "field_contract": "deterministically_reconstructed_from_height_drainage_and_surface_process_grids",
        "surface_material_contract": "topography_to_exposure_and_transport_domains_to_catalogued_materials",
        "landform_classes": [
            "exposed_ridge", "bedrock_scarp", "incised_valley",
            "colluvial_talus", "alluvial_apron", "mantled_plain",
        ],
        "structural_fabric": {
            "style": "orogenic_fold_fault" if active else "passive_or_relict",
            "dominant_strike_degrees": strike,
            "tectonic_regime": regime,
            "bedrock_banding_enabled": bool(active),
            "banding_source": "tectonic_fabric_crossed_with_topographic_exposure",
        },
        "summary": summaries,
        "source_versions": {
            "heightmap": heightmap.get("model_version"),
            "water_cycle": water_cycle.get("model_version"),
            "surface_evolution": surface_evolution.get("model_version"),
        },
    }
