"""Lithotectonic settings: where which rocks form.

The classifier turns the tectonic and terrain state of a map into fuzzy
per-cell memberships over geological settings (ridge, arc, collisional core,
shield, platform, rift, ...).  Recipes turn each setting into an areal rock
composition using ``lithotectonic_setting_weights`` authored on ontology
material entities (``tools/author_lithotectonic_settings.py``), gated by the
planet's crust chemistry through ``natural_material_model.likely_materials``.

Architecture invariants: the ontology owns which rock forms where; setting
ids are classifier categories owned by this module; every array here is a
disposable projection of generated truth.  All per-cell work is NumPy.

See docs/worldgen_material_lod_plan_v001.md.
"""

from __future__ import annotations

import math

import numpy as np

from simulations.world_gen import natural_materials
from simulations.world_gen.array_noise import domain_warp_uv, seed_int
from simulations.world_gen.heightmap import iter_orogen_segment_geometry


LITHOTECTONIC_MODEL_VERSION = "lithotectonic-settings-v1"

SETTINGS = (
    {"id": "oceanic_ridge", "label": "Oceanic ridge", "crust": "oceanic", "color": [178, 88, 72]},
    {"id": "abyssal_ocean_floor", "label": "Abyssal ocean floor", "crust": "oceanic", "color": [76, 96, 132]},
    {"id": "oceanic_plateau", "label": "Oceanic plateau", "crust": "oceanic", "color": [132, 70, 96]},
    {"id": "island_arc", "label": "Island arc", "crust": "oceanic", "color": [214, 120, 60]},
    {"id": "continental_arc", "label": "Continental arc", "crust": "continental", "color": [226, 92, 64]},
    {"id": "forearc_accretionary", "label": "Forearc / accretionary wedge", "crust": "any", "color": [120, 150, 110]},
    {"id": "collisional_orogen_core", "label": "Collisional orogen core", "crust": "continental", "color": [196, 70, 150]},
    {"id": "fold_thrust_belt", "label": "Fold-thrust belt", "crust": "continental", "color": [120, 170, 214]},
    {"id": "foreland_basin", "label": "Foreland basin", "crust": "continental", "color": [226, 206, 120]},
    {"id": "exposed_shield", "label": "Exposed shield", "crust": "continental", "color": [236, 128, 150]},
    {"id": "continental_platform", "label": "Continental platform", "crust": "continental", "color": [150, 196, 150]},
    {"id": "intracratonic_basin", "label": "Intracratonic basin", "crust": "continental", "color": [240, 226, 160]},
    {"id": "continental_rift", "label": "Continental rift", "crust": "continental", "color": [204, 150, 90]},
    {"id": "passive_margin_shelf", "label": "Passive-margin shelf", "crust": "continental", "color": [140, 204, 214]},
    {"id": "continental_hotspot", "label": "Continental hotspot / LIP", "crust": "continental", "color": [150, 60, 60]},
    {"id": "volcanic_plains", "label": "Volcanic plains", "crust": "any", "color": [110, 64, 60]},
    {"id": "ancient_highland_crust", "label": "Ancient highland crust", "crust": "any", "color": [210, 204, 190]},
    {"id": "impact_basin", "label": "Impact basin", "crust": "any", "color": [170, 150, 176]},
)
SETTING_IDS = tuple(setting["id"] for setting in SETTINGS)
SETTING_INDEX = {setting_id: index for index, setting_id in enumerate(SETTING_IDS)}
SETTING_BY_ID = {setting["id"]: setting for setting in SETTINGS}

# A setting whose recipe resolves to nothing on this planet borrows the
# nearest geological analogue before falling back to the planet's crust.
SETTING_FALLBACKS = {
    "oceanic_ridge": ("volcanic_plains", "oceanic_plateau"),
    "abyssal_ocean_floor": ("oceanic_ridge", "volcanic_plains"),
    "oceanic_plateau": ("oceanic_ridge", "volcanic_plains"),
    "island_arc": ("continental_arc", "oceanic_ridge"),
    "continental_arc": ("island_arc", "collisional_orogen_core"),
    "forearc_accretionary": ("fold_thrust_belt", "island_arc"),
    "collisional_orogen_core": ("exposed_shield", "fold_thrust_belt"),
    "fold_thrust_belt": ("foreland_basin", "collisional_orogen_core"),
    "foreland_basin": ("continental_platform", "fold_thrust_belt"),
    "exposed_shield": ("collisional_orogen_core", "continental_platform"),
    "continental_platform": ("intracratonic_basin", "exposed_shield"),
    "intracratonic_basin": ("continental_platform", "foreland_basin"),
    "continental_rift": ("continental_hotspot", "foreland_basin"),
    "passive_margin_shelf": ("continental_platform", "foreland_basin"),
    "continental_hotspot": ("volcanic_plains", "continental_rift"),
    "volcanic_plains": ("oceanic_ridge", "continental_hotspot"),
    "ancient_highland_crust": ("exposed_shield", "volcanic_plains"),
    "impact_basin": ("ancient_highland_crust", "volcanic_plains"),
}

# Materials without authored weights still participate through their
# formation profile.  This is a derivation rule over ontology fields, used
# only when ``lithotectonic_setting_weights`` is absent on the card.
_PROFILE_SETTING_WEIGHTS = {
    "felsic_bedrock": {"continental_arc": 0.05, "collisional_orogen_core": 0.05, "exposed_shield": 0.05},
    "mafic_bedrock": {"oceanic_ridge": 0.05, "volcanic_plains": 0.05, "continental_hotspot": 0.05},
    "ultramafic_bedrock": {"oceanic_ridge": 0.02, "forearc_accretionary": 0.02},
    "intermediate_volcanic": {"continental_arc": 0.05, "island_arc": 0.05},
    "felsic_volcanic": {"continental_arc": 0.04, "continental_rift": 0.03},
    "carbonate_basin": {"continental_platform": 0.05, "passive_margin_shelf": 0.05},
    "fine_basin_sediment": {"foreland_basin": 0.05, "continental_platform": 0.04, "intracratonic_basin": 0.04},
    "sand": {"foreland_basin": 0.05, "continental_platform": 0.04},
    "conglomerate": {"foreland_basin": 0.04, "continental_rift": 0.03},
    "metamorphic_uplift": {"collisional_orogen_core": 0.04, "exposed_shield": 0.03},
    "evaporite": {"intracratonic_basin": 0.02},
    "hydrated_alteration": {"forearc_accretionary": 0.02},
    "fresh_pyroclastic": {"continental_arc": 0.03, "island_arc": 0.03},
    "impact": {"impact_basin": 0.30, "ancient_highland_crust": 0.05},
}

_SUBSTRATE_REPRESENTATIONS = {"bedrock_unit"}
# Rock-like surface units that form their own mapped bedrock where their
# setting is active (pyroclastic sheets, impact breccia).
_SUBSTRATE_COVER_CATEGORIES = {"pyroclastic_deposit", "impact_material"}


def _clamp01(values):
    return np.clip(values, 0.0, 1.0)


def _smooth01(values):
    values = np.clip(values, 0.0, 1.0)
    return values * values * (3.0 - 2.0 * values)


def sample_global_rows(rows, u_values, v_values, default=0.0):
    """Bilinear sample of a whole-planet grid (x = u*(w-1), wrapped) at UV."""
    shape = (np.asarray(v_values).size, np.asarray(u_values).size)
    if not rows or not isinstance(rows, list) or not rows or not isinstance(rows[0], list):
        return np.full(shape, float(default), dtype=np.float64)
    width = min(len(row) for row in rows)
    if width < 1:
        return np.full(shape, float(default), dtype=np.float64)
    values = np.asarray([row[:width] for row in rows], dtype=np.float64)
    height = values.shape[0]
    fx = (np.mod(np.asarray(u_values, dtype=np.float64), 1.0) * max(1, width - 1))[None, :]
    fy = (np.clip(np.asarray(v_values, dtype=np.float64), 0.0, 1.0) * max(1, height - 1))[:, None]
    x0 = np.floor(fx).astype(np.int64)
    y0 = np.floor(fy).astype(np.int64)
    tx = fx - x0
    ty = fy - y0
    x0 %= width
    x1 = (x0 + 1) % width
    y0 = np.clip(y0, 0, height - 1)
    y1 = np.clip(y0 + 1, 0, height - 1)
    top = values[y0, x0] * (1.0 - tx) + values[y0, x1] * tx
    bottom = values[y1, x0] * (1.0 - tx) + values[y1, x1] * tx
    return top * (1.0 - ty) + bottom * ty


def box_blur(values, *, passes=1, wrap_x=False):
    """3 x 3 box blur over the last two axes (clamped in y, optional x wrap)."""
    values = np.asarray(values, dtype=np.float64)
    for _pass in range(max(0, int(passes))):
        if wrap_x:
            west = np.roll(values, 1, axis=-1)
            east = np.roll(values, -1, axis=-1)
        else:
            west = np.concatenate([values[..., :1], values[..., :-1]], axis=-1)
            east = np.concatenate([values[..., 1:], values[..., -1:]], axis=-1)
        horizontal = (west + values + east) / 3.0
        north = np.concatenate([horizontal[..., :1, :], horizontal[..., :-1, :]], axis=-2)
        south = np.concatenate([horizontal[..., 1:, :], horizontal[..., -1:, :]], axis=-2)
        values = (north + horizontal + south) / 3.0
    return values


def _wrapped_du(u_grid, center_u):
    delta = u_grid - float(center_u)
    return np.where(delta > 0.5, delta - 1.0, np.where(delta < -0.5, delta + 1.0, delta))


def _band(signed, center, width):
    return np.exp(-(((signed - float(center)) / max(1e-6, float(width))) ** 2))


def orogen_setting_bands_grid(u_values, v_values, tectonic_model):
    """Mechanism-specific belt evidence from the heightfield's own segments.

    The band centres and widths mirror ``heightmap._np_segment_forcing`` so
    that arc volcanics sit on the arc ridge, foreland sediments in the
    foreland trough and metamorphic cores under the collisional high.
    """
    shape = (np.asarray(v_values).size, np.asarray(u_values).size)
    names = (
        "ridge", "rift_axis", "rift_shoulder", "collision_core", "fold_thrust",
        "foreland", "trench", "accretionary", "forearc", "arc", "backarc",
        "transpression", "transtension", "strike_slip",
    )
    bands = {name: np.zeros(shape, dtype=np.float64) for name in names}
    if not isinstance(tectonic_model, dict) or not tectonic_model.get("boundary_segments"):
        return bands

    envelope = None

    def raise_band(name, item, values):
        rows, columns = item["rows"], item["columns"]
        values = np.where(item["valid"], values * envelope, 0.0)
        np.maximum(bands[name][rows, columns], values, out=bands[name][rows, columns])

    for item in iter_orogen_segment_geometry(u_values, v_values, tectonic_model):
        system = item["system"]
        segment = item["segment"]
        profile = system.get("forcing_profile") if isinstance(system.get("forcing_profile"), dict) else {}
        sides = system.get("sides") if isinstance(system.get("sides"), dict) else {}
        mechanism = str(system.get("mechanism") or "")
        width = min(0.05, max(0.012, float(segment.get("influence_width", profile.get("reference_width", 0.028)) or 0.028)))
        activity = min(1.0, max(0.35, float(segment.get("activity_scale", 1.0) or 1.0)))
        signed = item["signed_distance"]
        # Belts are strips parallel to each segment.  Beyond the segment ends
        # the strip would fan out at every convex bend; chained neighbours
        # cover the interior, so fade anything past the segment's own span.
        along_overshoot = np.sqrt(np.maximum(0.0, item["distance"] ** 2 - signed ** 2))
        envelope = np.exp(-((along_overshoot / (width * 0.9)) ** 2))
        if mechanism == "continental_collision":
            hinterland = 1.0 if int(sides.get("hinterland_normal_side", 1) or 1) >= 0 else -1.0
            raise_band("collision_core", item, _band(signed, hinterland * width * 0.24, width * 0.68) * activity)
            raise_band("fold_thrust", item, _band(signed, -hinterland * width * 0.52, width * 0.72) * activity)
            raise_band("foreland", item, _band(signed, -hinterland * width * 1.48, width * 0.52) * activity)
        elif mechanism in {"ocean_continent_subduction", "island_arc_subduction"}:
            over = 1.0 if int(sides.get("overriding_normal_side", 1) or 1) >= 0 else -1.0
            raise_band("trench", item, _band(signed, -over * width * 0.62, width * 0.34) * activity)
            raise_band("accretionary", item, _band(signed, -over * width * 0.10, width * 0.38) * activity)
            raise_band("forearc", item, _band(signed, over * width * 0.44, width * 0.46) * activity)
            raise_band("arc", item, _band(signed, over * width * 1.24, width * 0.58) * activity)
            raise_band("backarc", item, _band(signed, over * width * 2.08, width * 0.72) * activity)
        elif mechanism == "continental_rift":
            raise_band("rift_axis", item, _band(signed, 0.0, width * 0.42) * activity)
            shoulders = np.maximum(
                _band(signed, width * 0.92, width * 0.48),
                _band(signed, -width * 0.92, width * 0.48),
            )
            raise_band("rift_shoulder", item, shoulders * activity)
        elif mechanism == "oceanic_spreading":
            raise_band("ridge", item, _band(signed, 0.0, width * 0.92) * activity)
        elif mechanism == "transpressional_strike_slip":
            raise_band("transpression", item, _band(signed, 0.0, width * 0.40) * activity)
        elif mechanism == "transtensional_strike_slip":
            raise_band("transtension", item, _band(signed, 0.0, width * 0.40) * activity)
        elif mechanism == "strike_slip":
            raise_band("strike_slip", item, _band(signed, 0.0, width * 0.40) * activity)
    return bands


def _ellipse_evidence(items, u_grid, v_grid, *, radius_key=None, width_key=None, height_key=None, predicate=None):
    evidence = np.zeros(np.broadcast_shapes(u_grid.shape, v_grid.shape), dtype=np.float64)
    for item in items or []:
        if not isinstance(item, dict) or (predicate is not None and not predicate(item)):
            continue
        cx = float(item.get("center_x", 0.5) or 0.5)
        cy = float(item.get("center_y", 0.5) or 0.5)
        if radius_key:
            rx = ry = max(0.005, float(item.get(radius_key, 0.05) or 0.05))
        else:
            rx = max(0.005, float(item.get(width_key, 0.08) or 0.08))
            ry = max(0.005, float(item.get(height_key, 0.06) or 0.06))
        dx = _wrapped_du(u_grid, cx) / rx
        dy = (v_grid - cy) / ry
        np.maximum(evidence, np.exp(-(dx * dx + dy * dy)), out=evidence)
    return evidence


def _line_evidence(items, u_grid, v_grid, width):
    evidence = np.zeros(np.broadcast_shapes(u_grid.shape, v_grid.shape), dtype=np.float64)
    for item in items or []:
        if not isinstance(item, dict):
            continue
        x1 = float(item.get("x1", 0.0) or 0.0)
        y1 = float(item.get("y1", 0.0) or 0.0)
        x2 = float(item.get("x2", 0.0) or 0.0)
        y2 = float(item.get("y2", 0.0) or 0.0)
        if x2 - x1 > 0.5:
            x2 -= 1.0
        elif x2 - x1 < -0.5:
            x2 += 1.0
        dx = x2 - x1
        dy = y2 - y1
        length_sq = max(1e-12, dx * dx + dy * dy)
        best = None
        for shift in (-1.0, 0.0, 1.0):
            px = u_grid + shift
            t = np.clip(((px - x1) * dx + (v_grid - y1) * dy) / length_sq, 0.0, 1.0)
            distance = np.hypot(px - (x1 + t * dx), v_grid - (y1 + t * dy))
            best = distance if best is None else np.minimum(best, distance)
        np.maximum(evidence, np.exp(-((best / width) ** 2)), out=evidence)
    return evidence


def _hotspot_evidence(hotspot_model, u_grid, v_grid):
    evidence = np.zeros(np.broadcast_shapes(u_grid.shape, v_grid.shape), dtype=np.float64)
    for hotspot in (hotspot_model or {}).get("hotspots") or []:
        if not isinstance(hotspot, dict):
            continue
        major = hotspot.get("buoyancy_flux_class") == "major"
        for point in hotspot.get("track") or []:
            if not isinstance(point, dict):
                continue
            volume = float(point.get("relative_volume", 0.0) or 0.0)
            radius = (0.016 + 0.018 * float(point.get("erosion_softening", 0.0) or 0.0)) * (1.6 if major else 1.0)
            dx = _wrapped_du(u_grid, float(point.get("x", 0.0) or 0.0)) / radius
            dy = (v_grid - float(point.get("y", 0.5) or 0.5)) / radius
            np.maximum(evidence, volume * np.exp(-(dx * dx + dy * dy)), out=evidence)
    return evidence


def _crater_evidence(crater_model, u_grid, v_grid, radius_m):
    """Rims and ejecta of retained planetary craters in global UV."""
    shape = np.broadcast_shapes(u_grid.shape, v_grid.shape)
    evidence = np.zeros(shape, dtype=np.float64)
    craters = (crater_model or {}).get("craters") or []
    if not craters or not radius_m:
        return evidence
    u_row = u_grid[0] if u_grid.ndim == 2 else u_grid
    v_col = v_grid[:, 0] if v_grid.ndim == 2 else v_grid
    for crater in craters:
        if not isinstance(crater, dict):
            continue
        try:
            cx = float(crater.get("x", 0.0) or 0.0) % 1.0
            cy = min(1.0, max(0.0, float(crater.get("y", 0.5) or 0.5)))
            angular_radius = max(1e-5, float(crater.get("diameter_km", 1.0) or 1.0) * 500.0 / float(radius_m))
        except (TypeError, ValueError):
            continue
        latitude = (0.5 - cy) * math.pi
        reach_v = angular_radius * 2.15 / math.pi
        reach_u = angular_radius * 2.15 / math.tau / max(0.12, abs(math.cos(latitude)))
        rows = np.nonzero(np.abs(v_col - cy) <= reach_v)[0]
        columns = np.nonzero(np.abs(_wrapped_du(u_row, cx)) <= reach_u)[0]
        if rows.size == 0 or columns.size == 0:
            continue
        sub_v = v_col[rows][:, None]
        sub_u = u_row[columns][None, :]
        cell_latitude = (0.5 - sub_v) * math.pi
        distance = np.hypot(
            cell_latitude - latitude,
            np.cos((cell_latitude + latitude) * 0.5) * _wrapped_du(sub_u, cx) * math.tau,
        ) / angular_radius
        rim = np.exp(-(((distance - 1.0) / 0.13) ** 2))
        ejecta = np.where(distance >= 1.0, np.exp(-np.maximum(0.0, distance - 1.0) / 0.36), 0.0)
        floor = np.maximum(0.0, 1.0 - distance) * 0.18
        value = np.where(distance <= 2.15, np.clip(rim * 0.92 + ejecta * 0.72 + floor, 0.0, 1.0), 0.0)
        block = evidence[np.ix_(rows, columns)]
        evidence[np.ix_(rows, columns)] = np.maximum(block, value)
    return evidence


def classify_lithotectonic_settings(
    u_values,
    v_values,
    *,
    tectonic_model=None,
    elevation=None,
    sea_level=None,
    shelf=None,
    crater_model=None,
    radius_m=None,
    planet_tags=(),
    sharpness=2.0,
    smoothing_passes=0,
    wrap_x=False,
):
    """Return ``(memberships[S, H, W], evidence)`` over ``SETTING_IDS``.

    ``u_values``/``v_values`` are global UV coordinates of the grid columns and
    rows.  ``elevation`` (H x W, metres) and ``shelf`` (H x W, 0..1) are
    optional; without them passive margins and plate-less terrain classes use
    tectonic evidence only (the pre-heightfield prior).
    """
    u_values = np.asarray(u_values, dtype=np.float64)
    v_values = np.asarray(v_values, dtype=np.float64)
    shape = (v_values.size, u_values.size)
    u_grid = u_values[None, :]
    v_grid = v_values[:, None]
    tectonic_model = tectonic_model if isinstance(tectonic_model, dict) else {}
    tags = {str(tag) for tag in planet_tags or ()}
    plate_world = bool(tectonic_model.get("plates")) and bool(tectonic_model.get("boundary_segments"))
    scores = {setting_id: np.zeros(shape, dtype=np.float64) for setting_id in SETTING_IDS}
    craters = _crater_evidence(crater_model, np.broadcast_to(u_grid, shape), np.broadcast_to(v_grid, shape), radius_m)

    if elevation is not None:
        elevation = np.asarray(elevation, dtype=np.float64)
    evidence_summary = {"plate_world": plate_world}

    if plate_world:
        lithosphere = tectonic_model.get("lithosphere_grid") if isinstance(tectonic_model.get("lithosphere_grid"), dict) else {}
        continental_rows = lithosphere.get("continental_fraction_rows")
        continental = _clamp01(sample_global_rows(continental_rows, u_values, v_values, 0.5))
        if elevation is not None and sea_level is not None:
            # The lithosphere summary is a 97 x 49 grid; its margins would
            # show as stair steps.  The heightfield resolves the real
            # continental edge (freeboard vs. abyssal depth), so crust type
            # follows it wherever it is available.
            freeboard = _smooth01((elevation - float(sea_level) + 2600.0) / 2400.0)
            continental = _clamp01(continental * 0.35 + freeboard * 0.65)
        # Ocean-floor age is only meaningful on oceanic crust; interpolating
        # it across cratons (ages in Gyr) or into zero-valued continental
        # cells would fake young/old floor along every margin.
        age_rows = lithosphere.get("ocean_floor_age_rows_myr")
        if age_rows and continental_rows:
            source_oceanic = [[max(0.0, 1.0 - float(value)) for value in row] for row in continental_rows]
            weighted_age = [
                [float(age) * weight for age, weight in zip(age_row, weight_row)]
                for age_row, weight_row in zip(age_rows, source_oceanic)
            ]
            ocean_age = sample_global_rows(weighted_age, u_values, v_values, 0.0) / np.maximum(
                sample_global_rows(source_oceanic, u_values, v_values, 1.0), 0.05
            )
        else:
            ocean_age = sample_global_rows(age_rows, u_values, v_values, 90.0)
        oceanic = 1.0 - continental
        bands = orogen_setting_bands_grid(u_values, v_values, tectonic_model)
        provinces = tectonic_model.get("continental_province_model") if isinstance(tectonic_model.get("continental_province_model"), dict) else {}
        cratons = provinces.get("cratons") or []
        warp_seed = seed_int(tectonic_model.get("map_seed") or "lithotectonic", "province_warp")
        warped_u, warped_v = domain_warp_uv(
            np.broadcast_to(u_grid, shape), np.broadcast_to(v_grid, shape),
            warp_seed, amplitude=0.018, frequency=14.0,
        )
        shield = _ellipse_evidence(cratons, warped_u, warped_v, width_key="width", height_key="height", predicate=lambda item: item.get("state") == "exposed_shield")
        covered_craton = _ellipse_evidence(cratons, warped_u, warped_v, width_key="width", height_key="height", predicate=lambda item: item.get("state") != "exposed_shield")
        basins = _ellipse_evidence(provinces.get("intracratonic_basins"), warped_u, warped_v, radius_key="radius")
        failed_rifts = _line_evidence(provinces.get("failed_rifts"), warped_u, warped_v, 0.016)
        hotspots = _hotspot_evidence(tectonic_model.get("hotspot_model"), warped_u, warped_v)
        # Ridge flanks: the youngest floor, relative to this ocean's own age
        # distribution (some worlds recycle their oceans much faster).
        ocean_cells = oceanic > 0.6
        typical_age = float(np.median(ocean_age[ocean_cells])) if ocean_cells.any() else 60.0
        young = _clamp01(1.0 - ocean_age / max(6.0, typical_age * 0.35))
        active = np.maximum.reduce([
            bands["arc"], bands["trench"], bands["collision_core"], bands["fold_thrust"],
            bands["accretionary"], bands["forearc"],
        ])
        if elevation is not None and sea_level is not None:
            depth = float(sea_level) - elevation
            shallow_water = np.where((depth > 0.0) & (depth < 450.0), 1.0 - depth / 450.0, 0.0)
        else:
            shallow_water = np.zeros(shape, dtype=np.float64)
        shelf_evidence = np.maximum(
            shallow_water,
            np.asarray(shelf, dtype=np.float64) if shelf is not None else 0.0,
        )

        scores["oceanic_ridge"] = oceanic * np.maximum(bands["ridge"], young * 0.7)
        scores["abyssal_ocean_floor"] = oceanic * (0.55 * (1.0 - young * 0.6))
        scores["oceanic_plateau"] = oceanic * hotspots * 1.2
        scores["island_arc"] = oceanic * bands["arc"] * 1.2
        scores["continental_arc"] = continental * bands["arc"] * 1.2
        scores["forearc_accretionary"] = np.maximum.reduce([bands["forearc"], bands["accretionary"], bands["trench"] * 0.6])
        scores["collisional_orogen_core"] = continental * bands["collision_core"] * 1.1
        scores["fold_thrust_belt"] = continental * np.maximum.reduce([bands["fold_thrust"], bands["transpression"] * 0.7, bands["strike_slip"] * 0.45])
        scores["foreland_basin"] = continental * bands["foreland"]
        scores["exposed_shield"] = continental * shield * (1.0 - active * 0.8)
        scores["continental_platform"] = continental * (0.30 + covered_craton * 0.55) * (1.0 - active * 0.7)
        scores["intracratonic_basin"] = continental * basins * (1.0 - active * 0.7)
        scores["continental_rift"] = continental * np.maximum.reduce([
            bands["rift_axis"], bands["rift_shoulder"] * 0.55, failed_rifts * 0.85,
            bands["transtension"] * 0.6, bands["backarc"] * 0.45,
        ])
        scores["passive_margin_shelf"] = shelf_evidence * (1.0 - active) * 1.1
        scores["continental_hotspot"] = continental * hotspots
        scores["impact_basin"] = craters
        evidence_summary.update({
            "mean_continental_fraction": round(float(continental.mean()), 4),
            "band_cover": {name: round(float((values > 0.25).mean()), 4) for name, values in bands.items()},
        })
    elif elevation is not None and "plate_tectonic_surface" in tags:
        # A mobile-lid world whose plate model is unavailable (fixtures,
        # imported terrain): crust type follows freeboard, basement is
        # exposed on the high, eroded continental interior, platform cover
        # fills the lowlands and shelves become passive margins.
        finite = elevation[np.isfinite(elevation)]
        reference = float(sea_level) if sea_level is not None else (float(np.percentile(finite, 35.0)) if finite.size else 0.0)
        continental = _smooth01((elevation - reference + 2600.0) / 2400.0)
        oceanic = 1.0 - continental
        land_values = elevation[elevation >= reference]
        if land_values.size >= 4:
            low, high = np.percentile(land_values, 15.0), np.percentile(land_values, 90.0)
        else:
            low, high = reference, reference + 1.0
        rank = np.clip((elevation - low) / max(1.0, high - low), 0.0, 1.0)
        volcanic_tendency = 0.55 if tags.intersection({"volcanic_surface", "basaltic_surface", "active_volcanism"}) else 0.1
        depth = reference - elevation
        shelf_evidence = np.where((depth > 0.0) & (depth < 450.0), 1.0 - depth / 450.0, 0.0)
        if shelf is not None:
            shelf_evidence = np.maximum(shelf_evidence, np.asarray(shelf, dtype=np.float64))
        scores["exposed_shield"] = continental * _smooth01((rank - 0.45) / 0.4) * (1.0 - volcanic_tendency * 0.4)
        scores["continental_platform"] = continental * (0.30 + (1.0 - rank) * 0.35) * (1.0 - volcanic_tendency * 0.3)
        scores["continental_hotspot"] = continental * volcanic_tendency * 0.45
        scores["abyssal_ocean_floor"] = oceanic * 0.55
        scores["passive_margin_shelf"] = shelf_evidence * 1.1
        scores["impact_basin"] = craters
        evidence_summary["classification_mode"] = "freeboard_without_plate_model"
    else:
        volcanic_tendency = 0.35
        if tags.intersection({"volcanic_surface", "basaltic_surface", "active_volcanism"}):
            volcanic_tendency = 0.75
        if elevation is not None:
            finite = elevation[np.isfinite(elevation)]
            low, high = (np.percentile(finite, 20.0), np.percentile(finite, 80.0)) if finite.size else (0.0, 1.0)
            height_rank = _clamp01((elevation - low) / max(1.0, high - low))
        else:
            height_rank = np.full(shape, 0.5, dtype=np.float64)
        scores["volcanic_plains"] = (1.0 - height_rank) * volcanic_tendency + 0.05
        scores["ancient_highland_crust"] = height_rank * (1.0 - volcanic_tendency * 0.4) + 0.05
        scores["impact_basin"] = craters * 1.2

    stack = np.stack([scores[setting_id] for setting_id in SETTING_IDS]).astype(np.float64)
    if smoothing_passes:
        stack = box_blur(stack, passes=int(smoothing_passes), wrap_x=wrap_x)
    stack = np.power(np.clip(stack, 0.0, None) + 1e-6, float(sharpness))
    total = stack.sum(axis=0)
    memberships = (stack / np.maximum(total, 1e-12)).astype(np.float32)
    evidence_summary["mean_memberships"] = {
        setting_id: round(float(memberships[index].mean()), 4)
        for index, setting_id in enumerate(SETTING_IDS)
    }
    return memberships, evidence_summary


def normalized_candidate(candidate):
    """Fill a candidate's formation category and spatial representation.

    ``natural_material_model`` candidates normally carry both; sparse records
    (fixtures, imports) resolve them from the ontology card or the formation
    contract so a deposit can never be mistaken for substrate.
    """
    candidate = dict(candidate or {})
    if candidate.get("spatial_representation") and candidate.get("formation_category"):
        return candidate
    from simulations.world_gen.material_affinities import material_affinity_profile
    from simulations.world_gen.material_formation import formation_contract

    material_id = str(candidate.get("material_id") or "")
    material = natural_materials.MATERIAL_BY_ID.get(material_id) or {}
    profile = material_affinity_profile(material_id) or {}
    contract = formation_contract(
        material_id,
        candidate.get("material_subclass") or material.get("material_subclass"),
        profile.get("profile_id"),
        explicit_category=candidate.get("formation_category") or material.get("formation_category"),
        explicit_representation=candidate.get("spatial_representation") or material.get("spatial_representation"),
    )
    candidate.setdefault("formation_category", contract.get("category_id"))
    if not candidate.get("spatial_representation"):
        candidate["spatial_representation"] = contract.get("spatial_representation")
    if not candidate.get("surface_affinity_profile") and profile:
        candidate["surface_affinity_profile"] = profile
    return candidate


def _candidate_setting_weights(candidate):
    material = natural_materials.MATERIAL_BY_ID.get(str(candidate.get("material_id") or "")) or {}
    authored = material.get("lithotectonic_setting_weights") or candidate.get("lithotectonic_setting_weights")
    if isinstance(authored, dict) and authored:
        return {str(key): float(value or 0.0) for key, value in authored.items()}
    profile_id = str(
        (candidate.get("surface_affinity_profile") or {}).get("profile_id")
        or ((material.get("surface_affinity_profile") or {}).get("profile_id"))
        or ""
    )
    return dict(_PROFILE_SETTING_WEIGHTS.get(profile_id) or {})


def _is_substrate_candidate(candidate):
    representation = str(candidate.get("spatial_representation") or "")
    category = str(candidate.get("formation_category") or "")
    if representation in _SUBSTRATE_REPRESENTATIONS:
        return True
    return category in _SUBSTRATE_COVER_CATEGORIES


def _passes_planet_gate(candidate, tags):
    requirements = candidate.get("formation_requirements") if isinstance(candidate.get("formation_requirements"), dict) else {}
    required_all = set(requirements.get("required_all_planet_tags") or [])
    required_any = set(requirements.get("required_any_planet_tags") or [])
    if not required_all.issubset(tags):
        return False
    if required_any and not required_any.intersection(tags):
        return False
    return True


def _profile_id(candidate):
    material = natural_materials.MATERIAL_BY_ID.get(str(candidate.get("material_id") or "")) or {}
    return str(
        (candidate.get("surface_affinity_profile") or {}).get("profile_id")
        or (material.get("surface_affinity_profile") or {}).get("profile_id")
        or ""
    )


def _chemistry_modulation(candidate):
    """Chemistry-driven abundance relative to an Earth-like crust.

    Materials with ontology chemistry carry ``availability_vs_earth`` from
    the planet's element distribution; recipes scale by it directly.  (The
    clipped ``relative_abundance`` could never raise a common rock such as
    basalt, whose Earth abundance is already near 1, while rare rocks could
    triple.)  Materials without chemistry fall back to the relative-abundance
    shift.
    """
    availability = candidate.get("availability_vs_earth")
    if availability is not None:
        return min(3.0, max(0.1, float(availability)))
    from simulations.world_gen.material_affinities import material_affinity_profile

    profile = material_affinity_profile(candidate.get("material_id")) or {}
    base = max(0.05, float(profile.get("abundance", 0.35) or 0.35))
    relative = float(candidate.get("relative_abundance", base) or base)
    return min(3.0, max(0.25, relative / base))


# Bulk-chemistry substitutions: on these worlds the magmas feeding a
# setting's mafic volcanic share are ultramafic (komatiitic/picritic), so
# most of that share moves to ultramafic analogues of the same setting.
# When the planet's element distribution is known the share follows its
# magnesium enrichment over the reference crust (none below 2x, all of it at
# 6x): the tag alone (Mg + Fe >= 13 %) moved 65 % of a basaltic Mars-like
# crust's basalt to komatiite.
ULTRAMAFIC_MAGNESIUM_ENRICHMENT = (2.0, 6.0)
CHEMICAL_SUBSTITUTIONS = (
    ("ultramafic_tendency", "mafic_bedrock", "ultramafic_bedrock", 0.65),
)
# Foundational lithologies (e.g. graphite on carbon-rich crust) form broad
# terranes in every land setting.
FOUNDATIONAL_SHARE = 0.35


def _substitution_share(tag, share, model):
    """Share of a substitution, scaled by the element distribution where known."""
    if tag != "ultramafic_tendency":
        return share
    profile = model.get("element_profile") if isinstance(model.get("element_profile"), dict) else {}
    reference = natural_materials.reference_element_distribution() if natural_materials.reference_crust_percent() else {}
    if not profile.get("Mg") or not reference.get("Mg"):
        return share
    onset, full = ULTRAMAFIC_MAGNESIUM_ENRICHMENT
    enrichment = float(profile["Mg"]) / float(reference["Mg"])
    return share * min(1.0, max(0.0, (enrichment - onset) / (full - onset)))


def resolve_setting_recipes(natural_material_model, *, max_materials=8, minimum_share=0.025):
    """Return ``{setting_id: [(material_id, share), ...]}`` for this planet.

    Shares are normalised within each setting over the materials the planet's
    chemistry supports, scaled by the chemistry-driven abundance shift and
    bulk-chemistry substitutions.  Settings with nothing available borrow an
    analogue setting, then the planet's most prevalent substrate candidates.
    """
    model = natural_material_model if isinstance(natural_material_model, dict) else {}
    tags = {str(tag) for tag in model.get("planet_tags") or []}
    candidates = [
        normalized_candidate(candidate) for candidate in model.get("likely_materials") or []
        if isinstance(candidate, dict) and candidate.get("material_id")
    ]
    substrate = [
        candidate for candidate in candidates
        if (_is_substrate_candidate(candidate) or candidate.get("foundational_lithology"))
        and _passes_planet_gate(candidate, tags)
    ]
    by_profile = {}
    for candidate in substrate:
        by_profile.setdefault(_profile_id(candidate), []).append(candidate)
    active_substitutions = [
        (tag, source, target, _substitution_share(tag, share, model))
        for tag, source, target, share in CHEMICAL_SUBSTITUTIONS
        if tag in tags and by_profile.get(target) and by_profile.get(source)
    ]
    active_substitutions = [item for item in active_substitutions if item[3] > 0.0]
    foundational = [candidate for candidate in substrate if candidate.get("foundational_lithology")]
    direct = {}
    for setting_id in SETTING_IDS:
        weights = {}
        for candidate in substrate:
            weight = _candidate_setting_weights(candidate).get(setting_id, 0.0)
            if weight <= 0.0:
                continue
            confidence = max(0.05, float(candidate.get("confidence", 0.5) or 0.5))
            weights[str(candidate["material_id"])] = weight * math.sqrt(confidence) * _chemistry_modulation(candidate)
        for _tag, source_profile, target_profile, share in active_substitutions:
            moved = 0.0
            for candidate in by_profile.get(source_profile) or []:
                material_id = str(candidate["material_id"])
                if material_id in weights:
                    moved += weights[material_id] * share
                    weights[material_id] *= 1.0 - share
            targets = by_profile.get(target_profile) or []
            confidence_total = sum(max(0.05, float(item.get("confidence", 0.5) or 0.5)) for item in targets)
            for candidate in targets:
                material_id = str(candidate["material_id"])
                weights[material_id] = weights.get(material_id, 0.0) + moved * max(0.05, float(candidate.get("confidence", 0.5) or 0.5)) / confidence_total
        if foundational and SETTING_BY_ID[setting_id]["crust"] != "oceanic" and weights:
            existing = sum(weights.values())
            for candidate in foundational:
                material_id = str(candidate["material_id"])
                weights[material_id] = weights.get(material_id, 0.0) + existing * FOUNDATIONAL_SHARE / (1.0 - FOUNDATIONAL_SHARE) / len(foundational)
        weighted = [(weight, material_id) for material_id, weight in weights.items() if weight > 0.0]
        weighted.sort(key=lambda item: (-item[0], item[1]))
        weighted = weighted[:max_materials]
        total = sum(weight for weight, _material_id in weighted)
        shares = [(material_id, weight / total) for weight, material_id in weighted if total > 0.0]
        shares = [(material_id, share) for material_id, share in shares if share >= minimum_share]
        total = sum(share for _material_id, share in shares)
        direct[setting_id] = [(material_id, share / total) for material_id, share in shares] if total > 0.0 else []

    crust_fallback = sorted(
        substrate,
        key=lambda item: (-float(item.get("prevalence_score", item.get("confidence", 0.0)) or 0.0), str(item["material_id"])),
    )
    if not crust_fallback:
        crust_fallback = sorted(
            (
                candidate for candidate in candidates
                if str(candidate.get("spatial_representation") or "") not in {"bounded_deposit", "constituent_abundance"}
            ),
            key=lambda item: (-float(item.get("prevalence_score", item.get("confidence", 0.0)) or 0.0), str(item["material_id"])),
        )
    fallback_recipe = []
    if crust_fallback:
        top = crust_fallback[:3]
        weights = [max(0.01, float(item.get("prevalence_score", item.get("confidence", 0.1)) or 0.1)) for item in top]
        total = sum(weights)
        fallback_recipe = [(str(item["material_id"]), weight / total) for item, weight in zip(top, weights)]

    recipes = {}
    provenance = {}
    for setting_id in SETTING_IDS:
        recipe = direct[setting_id]
        source = "direct"
        if not recipe:
            for analogue in SETTING_FALLBACKS.get(setting_id, ()):
                if direct.get(analogue):
                    recipe = direct[analogue]
                    source = f"analogue:{analogue}"
                    break
        if not recipe:
            recipe = fallback_recipe
            source = "planet_crust_fallback"
        recipes[setting_id] = recipe
        provenance[setting_id] = source
    return recipes, provenance


def recipe_matrix(recipes, material_ids=None):
    """Return ``(material_ids, R[S, M])`` for composition by tensor product."""
    if material_ids is None:
        seen = []
        for setting_id in SETTING_IDS:
            for material_id, _share in recipes.get(setting_id) or []:
                if material_id not in seen:
                    seen.append(material_id)
        material_ids = seen
    index = {material_id: position for position, material_id in enumerate(material_ids)}
    matrix = np.zeros((len(SETTING_IDS), len(material_ids)), dtype=np.float32)
    for setting_position, setting_id in enumerate(SETTING_IDS):
        for material_id, share in recipes.get(setting_id) or []:
            if material_id in index:
                matrix[setting_position, index[material_id]] += float(share)
    return list(material_ids), matrix


def composition_from_memberships(memberships, matrix):
    """``composition[M, H, W] = sum_s membership[s] * R[s, M]``."""
    return np.tensordot(matrix.T, memberships, axes=([1], [0])).astype(np.float32)
