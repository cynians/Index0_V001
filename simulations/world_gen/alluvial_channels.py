"""Alluvial river channels at Site scale (LOD4+): meandering and braided.

Below about 10 m cell spacing a river stops being a flow line and becomes a
channel with two banks.  Alluvial channels take one of two classic planforms
(Leopold & Wolman 1957):

* meandering -- one sinuous thread; in each bend the outer bank is a steep
  cut bank above a scour pool and the inner bank a gently sloping point bar,
  dry at ordinary flow (e.g. the Rio Beni, the lower Mississippi);
* braided -- a wide, shallow belt of threads that divide and rejoin around
  bars (e.g. the Brahmaputra, Canterbury Plains rivers, most rivers on Earth
  before land plants, Davies & Gibling 2010).

Everything is sized at bankfull, the channel-forming flow:

* discharge: annual runoff of the parent level times contributing area
  (rivers entering the tile bring their catchment) gives the mean flow;
  bankfull flow is 3 (humid, perennial) to 10 (arid, flashy) times that.
* bank strength: Schumm (1960, 1963) found the silt-clay percentage M of the
  channel perimeter sets the width/depth ratio, ``F = 255 M^-1.08``, and the
  sinuosity, ``P = 0.94 M^0.25``.  M is taken from the clay-mineral share of
  the parent's surface sediments (ontology modal mineralogy).  No vegetation
  is assumed: abiotic worlds have only mud to hold their banks.
* depth and width: continuity ``Q = W D U`` with Chezy resistance
  ``U = C sqrt(g D S)`` and ``W = F D`` give ``D = (Q / (F C sqrt(g S)))^0.4``,
  so gravity and slope enter.
* regime: braided above the Leopold & Wolman (1957) threshold
  ``S = 0.012 Q^-0.44``; meandering well below it; low-sinuosity
  (wandering) in between.
* meanders: wavelength about 11 channel widths (Leopold & Wolman 1960); the
  centreline is a Kinoshita sine-generated curve (Langbein & Leopold 1966)
  whose deflection amplitude follows from the sinuosity, ``P = 1 / J0(w)``,
  confined to the valley floor.
* cross-section: pool at the cut bank, point bar on the inside, scaled by
  the bend curvature; symmetric at crossings.  At mean flow the water is
  ``(Q_mean / Q_bankfull)^0.4`` of the bankfull depth (at-a-station depth
  exponent, Leopold & Maddock 1953), so bars emerge.
* the carved volume is returned to the floodplain as natural levees that
  decay away from the banks (e-folding 1.5 channel widths), which keeps the
  child's mean at the parent's spacing.

Scale gate: a channel is carved at the first level whose spacing resolves
its width (``W >= RESOLVE_WIDTH_CELLS * dx``) and whose parent's did not.
Deeper levels inherit the carved surface through the heightfield and the
centrelines through ``heightmap_model.regional_landforms`` (global UV), so
materials and water keep reading one geometry at every level.
"""

from __future__ import annotations

import math

import numpy as np

from simulations.world_gen.array_noise import seed_int, value_noise
from simulations.world_gen.material_routing import (
    CHANNEL_HEAD_AREA_M2,
    box_mean,
    d8_receivers,
    filled_routing,
    gaussian_blur,
    inlet_mask,
    upstream_sum,
)

LANDFORM_ID = "alluvial_channels"
CHANNEL_PLANFORM_MIN_LEVEL = 4
# A channel is carved when this many cells span its bankfull width.
RESOLVE_WIDTH_CELLS = 1.5
SECONDS_PER_YEAR = 3.156e7
# Bankfull / mean annual discharge, humid .. arid catchments.
BANKFULL_TO_MEAN_DISCHARGE = (3.0, 10.0)
# Dimensionless Chezy coefficient U / sqrt(g D S) of sand and gravel rivers.
CHEZY_COEFFICIENT = 12.0
# Schumm (1960): width/depth = 255 M^-1.08; Schumm (1963): P = 0.94 M^0.25.
SCHUMM_WIDTH_DEPTH = (255.0, -1.08)
SCHUMM_SINUOSITY = (0.94, 0.25)
WIDTH_DEPTH_RANGE = (4.0, 120.0)
SINUOSITY_RANGE = (1.0, 2.6)
# Leopold & Wolman (1957), SI: braided above S = 0.012 Q^-0.44.
BRAIDING_THRESHOLD = (0.012, -0.44)
# Width/depth of a braided belt (Brahmaputra ~100+, gravel braidplains 50-300).
BRAIDED_WIDTH_DEPTH = 90.0
MEANDER_WAVELENGTH_WIDTHS = 11.0
# Kinoshita skewness and flatness terms (Parker et al. 1983).
KINOSHITA_SKEW = 1.0 / 32.0
KINOSHITA_FLATNESS = 1.0 / 192.0
AT_A_STATION_DEPTH_EXPONENT = 0.4
LEVEE_DECAY_WIDTHS = 1.5
# Distance (in channel widths) over which a levee rises from the bank edge.
LEVEE_RAMP_WIDTHS = 0.15
# Active threads across a braided belt at low flow.
BRAID_THREADS = 3
DEFAULT_RUNOFF_MM = 300.0
DEFAULT_SILT_CLAY_PERCENT = 12.0
MIN_REACH_CELLS = 8
# A child reconstructs its parent's samples with about this Gaussian width
# (cubic B-spline: sigma = 0.58 sample spacings).
PARENT_RECONSTRUCTION_SIGMA = 0.58
# Points either side of the jump-flood answer checked for the true nearest.
NEAREST_POLISH_POINTS = 8


def _smooth01(values):
    values = np.clip(values, 0.0, 1.0)
    return values * values * (3.0 - 2.0 * values)


# --- inputs from the parent level --------------------------------------------

def parent_runoff_mm(parent_entity):
    """Mean annual runoff (mm) of the parent level's water cycle."""
    grid = ((parent_entity or {}).get("water_cycle_model") or {}).get("climate_grid") or {}
    rows = grid.get("annual_runoff_rows_mm")
    if not rows:
        return DEFAULT_RUNOFF_MM, "default"
    values = np.asarray(rows, dtype=np.float64)
    return float(np.mean(values[values > 0.0])) if np.any(values > 0.0) else 0.0, "parent_water_cycle"


def parent_aridity(parent_entity):
    """Aridity (0 humid .. 1 hyper-arid) from the parent's P/PET."""
    grid = ((parent_entity or {}).get("water_cycle_model") or {}).get("climate_grid") or {}
    precipitation = grid.get("annual_precipitation_rows_mm")
    evaporation = grid.get("annual_potential_evaporation_rows_mm")
    if not precipitation or not evaporation:
        return 0.5
    index = float(np.mean(np.asarray(precipitation, dtype=np.float64))) / max(1.0, float(np.mean(np.asarray(evaporation, dtype=np.float64))))
    return 1.0 / (1.0 + (index / 0.3) ** 2)


def _is_clay_mineral(card):
    text = str((card or {}).get("scientific_classification") or "").lower()
    return "clay" in text or ("phyllosilicate" in text and "mica" not in text)


def bank_silt_clay_percent(parent_entity):
    """Silt-clay share of bank sediment from the planet's floodplain materials.

    Banks are overbank deposits, so they are made of the catalogue materials
    whose ontology card lists the ``floodplain`` depositional environment --
    the same candidates the material layer puts on floodplains -- weighted
    by prevalence.  Each contributes the clay-mineral weight percent of its
    modal mineralogy; clay minerals are clay-sized, so this is a lower bound
    on Schumm's silt-clay percentage.
    """
    natural_material_model = (parent_entity or {}).get("natural_material_model") or {}
    if not natural_material_model:
        return DEFAULT_SILT_CLAY_PERCENT, "default"
    from simulations.world_gen.material_lod import resolve_environment_candidates
    from simulations.world_gen.natural_materials import MATERIAL_BY_ID

    total = 0.0
    clay = 0.0
    for candidate in resolve_environment_candidates(natural_material_model, "floodplain"):
        card = MATERIAL_BY_ID.get(str(candidate.get("material_id") or "")) or {}
        modal = card.get("modal_mineralogy_wt") or {}
        weight = float(candidate.get("prevalence") or 0.0)
        if weight <= 0.0 or not modal:
            continue
        modal_total = sum(float(value or 0.0) for value in modal.values()) or 1.0
        share = sum(
            float(value or 0.0) for mineral, value in modal.items()
            if _is_clay_mineral(MATERIAL_BY_ID.get(str(mineral)))
        ) / modal_total
        total += weight
        clay += weight * share * 100.0
    if total <= 0.0:
        return DEFAULT_SILT_CLAY_PERCENT, "default"
    return float(np.clip(clay / total, 1.0, 80.0)), "floodplain_materials_modal_mineralogy"


def planet_gravity_m_s2(entity):
    physics = ((entity or {}).get("world_gen_seed") or {}).get("derived_planet_physics") or {}
    return float(physics.get("surface_gravity_m_s2") or 9.80665)


# --- hydraulics ----------------------------------------------------------------

def bankfull_geometry(bankfull_discharge, slope, silt_clay_percent, gravity):
    """Bankfull width, depth, regime and sinuosity (arrays broadcast)."""
    q = np.maximum(np.asarray(bankfull_discharge, dtype=np.float64), 1e-4)
    s = np.clip(np.asarray(slope, dtype=np.float64), 1e-5, 0.2)
    m = float(np.clip(silt_clay_percent, 1.0, 80.0))
    aspect = float(np.clip(SCHUMM_WIDTH_DEPTH[0] * m ** SCHUMM_WIDTH_DEPTH[1], *WIDTH_DEPTH_RANGE))
    shear = CHEZY_COEFFICIENT * np.sqrt(gravity * s)
    depth = (q / (aspect * shear)) ** 0.4
    braided_aspect = max(aspect, BRAIDED_WIDTH_DEPTH)
    braided_depth = (q / (braided_aspect * shear)) ** 0.4
    threshold = BRAIDING_THRESHOLD[0] * q ** BRAIDING_THRESHOLD[1]
    ratio = s / threshold
    # 0 below 0.75 of the threshold, 1 above 1.25: braided belt.
    braid = _smooth01((ratio - 0.75) / 0.5)
    # Full meandering well below the threshold, straightening towards it.
    meander = 1.0 - _smooth01((ratio - 0.3) / 0.6)
    sinuosity = float(np.clip(SCHUMM_SINUOSITY[0] * m ** SCHUMM_SINUOSITY[1], *SINUOSITY_RANGE))
    width = (1.0 - braid) * aspect * depth + braid * braided_aspect * braided_depth
    mean_depth = (1.0 - braid) * depth + braid * braided_depth
    return {
        "width_m": width,
        "depth_m": mean_depth,
        "single_width_m": aspect * depth,
        "braid": braid,
        "meander": meander,
        "sinuosity": 1.0 + (max(1.0, sinuosity) - 1.0) * meander,
        "threshold_ratio": ratio,
        "width_depth_ratio": aspect,
    }


def _sinuosity_to_amplitude():
    """Table of sine-generated curve sinuosity P = 1 / J0(w) against w."""
    omega = np.linspace(0.0, 2.05, 206)
    t = np.linspace(0.0, math.pi, 257)
    j0 = np.trapezoid(np.cos(omega[:, None] * np.sin(t)[None, :]), t, axis=1) / math.pi
    return omega, 1.0 / np.maximum(j0, 1e-3)


_OMEGA_TABLE, _SINUOSITY_TABLE = _sinuosity_to_amplitude()


def deflection_for_sinuosity(sinuosity):
    return np.interp(np.asarray(sinuosity, dtype=np.float64), _SINUOSITY_TABLE, _OMEGA_TABLE)


def _half_amplitude_table():
    """Half lateral range of one sine-generated bend per valley wavelength."""
    phase = np.linspace(0.0, math.tau, 721)
    half = []
    for omega in _OMEGA_TABLE:
        lateral = np.cumsum(np.sin(omega * np.sin(phase))) * (1.0 / 720.0)
        half.append(0.5 * float(lateral.max() - lateral.min()))
    # ``lateral`` is per unit arc wavelength; divide by P for valley wavelength.
    return np.asarray(half) * _SINUOSITY_TABLE


_HALF_AMPLITUDE_TABLE = _half_amplitude_table()


def deflection_for_half_amplitude(half_amplitude_per_wavelength):
    """Largest deflection whose bends stay within the given half-amplitude."""
    return np.interp(np.asarray(half_amplitude_per_wavelength, dtype=np.float64), _HALF_AMPLITUDE_TABLE, _OMEGA_TABLE)


# --- geometry helpers ----------------------------------------------------------

def _gaussian_smooth(values, sigma_samples):
    """Endpoint-pinned Gaussian smoothing of a 1-D array (point reflection)."""
    values = np.asarray(values, dtype=np.float64)
    n = values.size
    radius = int(min(3.0 * sigma_samples, n - 2))
    if radius < 1 or sigma_samples <= 0.0:
        return values.copy()
    offsets = np.arange(-radius, radius + 1)
    kernel = np.exp(-0.5 * (offsets / sigma_samples) ** 2)
    kernel /= kernel.sum()
    head = 2.0 * values[0] - values[1:radius + 1][::-1]
    tail = 2.0 * values[-1] - values[-radius - 1:-1][::-1]
    return np.convolve(np.concatenate([head, values, tail]), kernel, mode="valid")


def _resample_polyline(x, y, step, *extra):
    """Resample a polyline (and per-vertex attributes) at a fixed arc step."""
    segment = np.hypot(np.diff(x), np.diff(y))
    arc = np.concatenate([[0.0], np.cumsum(segment)])
    total = float(arc[-1])
    count = max(2, int(math.ceil(total / max(step, 1e-6))) + 1)
    stations = np.linspace(0.0, total, count)
    out = [np.interp(stations, arc, x), np.interp(stations, arc, y)]
    out.extend(np.interp(stations, arc, np.asarray(values, dtype=np.float64)) for values in extra)
    return stations, out


def _resample_smooth(x, y, step, *extra):
    """Resample stored centreline points as a Catmull-Rom curve.

    Stored reaches are samples of a smooth curve; rebuilding them as a
    polyline put a tangent kink at every stored point, which the bank line
    (half a channel width out) showed as scallops at the parent's spacing.
    Attributes are interpolated linearly.
    """
    x = np.asarray(x, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)
    if x.size < 3:
        return _resample_polyline(x, y, step, *extra)
    chord = np.concatenate([[0.0], np.cumsum(np.hypot(np.diff(x), np.diff(y)))])
    total = float(chord[-1])
    count = max(2, int(math.ceil(total / max(step, 1e-6))) + 1)
    stations = np.linspace(0.0, total, count)
    segment = np.clip(np.searchsorted(chord, stations, side="right") - 1, 0, x.size - 2)
    length = np.maximum(chord[segment + 1] - chord[segment], 1e-9)
    t = np.clip((stations - chord[segment]) / length, 0.0, 1.0)[:, None]
    points = np.stack([x, y], axis=1)
    padded = np.vstack([2.0 * points[0] - points[1], points, 2.0 * points[-1] - points[-2]])
    p0, p1, p2, p3 = padded[segment], padded[segment + 1], padded[segment + 2], padded[segment + 3]
    curve = 0.5 * (
        2.0 * p1 + (p2 - p0) * t + (2.0 * p0 - 5.0 * p1 + 4.0 * p2 - p3) * t * t
        + (3.0 * p1 - p0 - 3.0 * p2 + p3) * t * t * t
    )
    out = [curve[:, 0], curve[:, 1]]
    out.extend(np.interp(stations, chord, np.asarray(values, dtype=np.float64)) for values in extra)
    return stations, out


def _tangent_and_curvature(x, y, step, smooth_samples):
    tx = np.gradient(x)
    ty = np.gradient(y)
    norm = np.maximum(np.hypot(tx, ty), 1e-12)
    tx, ty = tx / norm, ty / norm
    angle = np.unwrap(np.arctan2(ty, tx))
    curvature = np.gradient(angle) / max(step, 1e-9)
    if smooth_samples > 0.5:
        curvature = _gaussian_smooth(curvature, smooth_samples)
    return tx, ty, curvature


def _shift(values, row_shift, column_shift, fill):
    out = np.full(values.shape, fill, dtype=values.dtype)
    height, width = values.shape
    if abs(row_shift) >= height or abs(column_shift) >= width:
        return out
    rs = slice(max(0, row_shift), height + min(0, row_shift))
    rd = slice(max(0, -row_shift), height + min(0, -row_shift))
    cs = slice(max(0, column_shift), width + min(0, column_shift))
    cd = slice(max(0, -column_shift), width + min(0, -column_shift))
    out[rs, cs] = values[rd, cd]
    return out


def nearest_point_field(px, py, shape, dx, dy, max_radius_m):
    """Nearest centreline point per cell (jump flooding); ``(-1, inf)`` beyond reach."""
    height, width = shape
    index = np.full(shape, -1, dtype=np.int64)
    if px.size == 0:
        return index, np.full(shape, np.inf)
    columns = np.clip(np.rint(px / dx).astype(np.int64), 0, width - 1)
    rows = np.clip(np.rint(py / dy).astype(np.int64), 0, height - 1)
    offset = (px - columns * dx) ** 2 + (py - rows * dy) ** 2
    order = np.argsort(-offset, kind="stable")
    index[rows[order], columns[order]] = order
    x_cells = (np.arange(width) * dx)[None, :]
    y_cells = (np.arange(height) * dy)[:, None]

    def distance2(candidate):
        valid = candidate >= 0
        safe = np.where(valid, candidate, 0)
        d2 = (x_cells - px[safe]) ** 2 + (y_cells - py[safe]) ** 2
        return np.where(valid, d2, np.inf)

    best = distance2(index)
    radius_cells = min(float(max(height, width)), max(1.0, max_radius_m / max(min(dx, dy), 1e-9)))
    step = 1 << int(math.ceil(math.log2(radius_cells + 1.0)))
    while step >= 1:
        for row_shift in (-step, 0, step):
            for column_shift in (-step, 0, step):
                if row_shift == 0 and column_shift == 0:
                    continue
                candidate = _shift(index, row_shift, column_shift, -1)
                d2 = distance2(candidate)
                closer = d2 < best
                if closer.any():
                    index = np.where(closer, candidate, index)
                    best = np.where(closer, d2, best)
        step //= 2
    # Jump flooding settles on a nearly equidistant point about half the
    # time along a dense polyline, which jitters the along-channel position
    # and bank side cell to cell.  The points are ordered, so the true
    # nearest lies a few indices away: check them.
    found = index >= 0
    for offset in range(-NEAREST_POLISH_POINTS, NEAREST_POLISH_POINTS + 1):
        if offset == 0:
            continue
        candidate = np.where(found, np.clip(index + offset, 0, px.size - 1), -1)
        d2 = distance2(candidate)
        closer = d2 < best
        index = np.where(closer, candidate, index)
        best = np.where(closer, d2, best)
    distance = np.sqrt(best)
    far = distance > max_radius_m
    return np.where(far, -1, index), np.where(far, np.inf, distance)


# --- reach extraction and planform --------------------------------------------

def _trace_reaches(receivers, gated, shape):
    """Downstream cell paths through gated cells, longest first.

    Returns ``[(cells, junction)]`` where ``junction`` is the already-traced
    cell the reach flows into (or ``None``).
    """
    size = receivers.size
    flat_gated = gated.ravel()
    valid = (receivers < size)
    target = np.where(valid, receivers, 0)
    has_donor = np.zeros(size, dtype=bool)
    donors = np.flatnonzero(flat_gated & valid)
    has_donor[target[donors][flat_gated[target[donors]]]] = True
    heads = np.flatnonzero(flat_gated & ~has_donor)
    from simulations.world_gen.fluvial_relief import outlet_distance

    length = outlet_distance(np.where(flat_gated, receivers, size))
    heads = heads[np.argsort(-length[heads], kind="stable")]
    visited = np.zeros(size, dtype=bool)
    reaches = []
    for head in heads.tolist():
        cells = []
        cell = head
        junction = None
        while True:
            if visited[cell]:
                junction = cell
                break
            if not flat_gated[cell]:
                break
            visited[cell] = True
            cells.append(cell)
            nxt = int(receivers[cell])
            if nxt >= size:
                break
            cell = nxt
        if len(cells) >= MIN_REACH_CELLS:
            reaches.append((np.asarray(cells, dtype=np.int64), junction))
    return reaches


def _meander_offsets(length_m, step, wavelength, sinuosity, strength, seed, confinement=None):
    """Kinoshita centreline in the valley frame: ``(xi, eta)`` per arc step.

    ``wavelength``, ``sinuosity``, ``strength`` and ``confinement`` (the
    half-amplitude the valley floor allows, in wavelengths) are callables of
    the valley station.  A confined river makes lower, rounder bends rather
    than flattening them against the walls.  Deflection amplitude and
    wavelength wander a little along the river (value noise over a few
    bends), and the skew direction is seeded.
    """
    if length_m <= 0.0:
        return np.zeros(1), np.zeros(1)
    rng_phase = (seed % 10_007) / 10_007.0 * math.tau
    skew_sign = 1.0 if (seed // 10_007) % 2 else -1.0
    max_steps = int(length_m / step * 3.5) + 16
    arc = np.arange(max_steps) * step
    reference = max(float(wavelength(0.0)), step * 8.0)
    amplitude_noise = value_noise(arc / (2.0 * reference), np.full(arc.shape, 0.37), seed)
    rate_noise = value_noise(arc / (1.5 * reference), np.full(arc.shape, 0.71), seed + 17)
    xi = np.zeros(max_steps)
    eta = np.zeros(max_steps)
    phase = rng_phase
    position = 0.0
    lateral = 0.0
    count = 0
    for index in range(max_steps):
        xi[index] = position
        eta[index] = lateral
        count = index + 1
        if position >= length_m:
            break
        local_wavelength = float(wavelength(position))
        local_sinuosity = float(sinuosity(position))
        omega = float(deflection_for_sinuosity(local_sinuosity)) * float(strength(position))
        # Natural bend trains vary: some bends near cutoff, some nearly straight.
        omega *= 0.55 + 0.7 * amplitude_noise[index]
        if confinement is not None:
            omega = min(omega, float(deflection_for_half_amplitude(confinement(position))))
        theta = omega * math.sin(phase) + omega ** 3 * skew_sign * (
            KINOSHITA_SKEW * math.cos(3.0 * phase) - KINOSHITA_FLATNESS * math.sin(3.0 * phase)
        )
        position += math.cos(theta) * step
        lateral += math.sin(theta) * step
        arc_wavelength = max(local_wavelength * local_sinuosity, step * 6.0)
        phase += math.tau * step / arc_wavelength * (0.75 + 0.5 * rate_noise[index])
    return xi[:count], eta[:count]


def _reach_geometry(cells, junction_xy, elevation, path_mask, area, *, dx, dy, runoff_m_s, bankfull_ratio,
                    silt_clay, gravity, seed):
    """Valley axis, hydraulics and meandering centreline of one reach."""
    height, width = elevation.shape
    rows, columns = np.divmod(cells, width)
    x = columns * dx
    y = rows * dy
    if junction_xy is not None:
        x = np.append(x, junction_xy[0])
        y = np.append(y, junction_xy[1])
        rows = np.append(rows, rows[-1])
        columns = np.append(columns, columns[-1])
    reach_area = area.ravel()[np.concatenate([cells, cells[-1:]])[:x.size]]
    q_mean = runoff_m_s * reach_area
    q_bankfull = q_mean * bankfull_ratio
    # Bank level: floodplain cells beside the path (not the path groove).
    step = 0.5 * min(dx, dy)
    stations, (sx, sy, s_area, s_rows, s_columns) = _resample_polyline(
        x.astype(np.float64), y.astype(np.float64), step, reach_area, rows, columns,
    )
    first = bankfull_geometry(float(np.median(q_bankfull)), 1e-3, silt_clay, gravity)
    wavelength_guess = MEANDER_WAVELENGTH_WIDTHS * float(np.max(first["single_width_m"]))
    sigma = float(np.clip(0.3 * wavelength_guess, 2.0 * max(dx, dy), 10.0 * max(dx, dy))) / step
    sx = _gaussian_smooth(sx, sigma)
    sy = _gaussian_smooth(sy, sigma)
    # Valley stations along the smoothed axis (the D8 path's staircase is
    # longer than the valley it follows).
    stations = np.concatenate([[0.0], np.cumsum(np.hypot(np.diff(sx), np.diff(sy)))])
    ri = np.clip(np.rint(s_rows).astype(np.int64), 0, height - 1)
    ci = np.clip(np.rint(s_columns).astype(np.int64), 0, width - 1)
    radius = 2
    floor = ~path_mask
    bank_sum = box_mean(np.where(floor, elevation, 0.0), radius)
    bank_count = box_mean(floor.astype(np.float64), radius)
    bank_field = np.where(bank_count > 1e-6, bank_sum / np.maximum(bank_count, 1e-9), elevation)
    bank = _gaussian_smooth(bank_field[ri, ci], max(1.0, 2.0 * sigma))
    bank = np.minimum.accumulate(bank)
    # Valley slope over about one meander wavelength.
    slope_window = max(3.0, wavelength_guess / step)
    slope = np.clip(_gaussian_smooth(-np.gradient(bank) / step, slope_window), 1e-5, 0.2)
    s_q_mean = runoff_m_s * s_area
    geometry = bankfull_geometry(s_q_mean * bankfull_ratio, slope, silt_clay, gravity)
    valley_length = float(stations[-1])
    width_m = geometry["width_m"]

    def along(values):
        return lambda xi: float(np.interp(xi, stations, values))

    # Valley frame and the floor width the bends may use.
    tx_v = np.gradient(sx)
    ty_v = np.gradient(sy)
    norm = np.maximum(np.hypot(tx_v, ty_v), 1e-12)
    nx_v, ny_v = -ty_v / norm, tx_v / norm
    station_wavelength = MEANDER_WAVELENGTH_WIDTHS * geometry["single_width_m"]
    allowed_station = np.maximum(_valley_half_width(sx, sy, nx_v, ny_v, bank, elevation, dx, dy) - 0.5 * width_m, 0.5 * step)
    wavelength = along(station_wavelength)
    sinuosity = along(geometry["sinuosity"])
    strength = along(geometry["meander"])
    confinement = along(allowed_station / np.maximum(station_wavelength, 1e-6))
    xi, eta = _meander_offsets(valley_length, step, wavelength, sinuosity, strength, seed, confinement=confinement)
    local_wavelength = np.interp(xi, stations, station_wavelength)
    # Remove slow lateral drift, keep the bends.
    drift = _gaussian_smooth(eta, max(2.0, float(np.mean(local_wavelength)) / step))
    eta = eta - drift
    # Drift and noise can still push a bend past the floor: soft limit.
    allowed = 1.25 * np.interp(xi, stations, allowed_station)
    eta = allowed * np.tanh(eta / allowed)
    taper = _smooth01(xi / np.maximum(local_wavelength, 1e-6)) * _smooth01((valley_length - xi) / np.maximum(local_wavelength, 1e-6))
    eta = eta * taper
    xi = np.clip(xi, 0.0, valley_length)
    cx = np.interp(xi, stations, sx) + eta * np.interp(xi, stations, nx_v)
    cy = np.interp(xi, stations, sy) + eta * np.interp(xi, stations, ny_v)
    attributes = {
        "bank": np.interp(xi, stations, bank),
        "width": np.interp(xi, stations, width_m),
        "depth": np.interp(xi, stations, geometry["depth_m"]),
        "braid": np.interp(xi, stations, geometry["braid"]),
        "q_ratio": np.full(xi.shape, 1.0 / bankfull_ratio),
    }
    arc, resampled = _resample_polyline(cx, cy, step, *attributes.values())
    points = dict(zip(("x", "y"), resampled[:2]))
    points.update(dict(zip(attributes.keys(), resampled[2:])))
    points["s"] = arc
    tx, ty, curvature = _tangent_and_curvature(points["x"], points["y"], step, max(1.0, 0.25 * float(np.median(points["width"])) / step))
    points["kappa"] = curvature
    summary = {
        "valley_length_m": round(valley_length, 1),
        "channel_length_m": round(float(arc[-1]), 1),
        "sinuosity": round(float(arc[-1]) / max(valley_length, 1e-6), 3),
        "bankfull_discharge_m3_s": round(float(np.max(s_q_mean * bankfull_ratio)), 2),
        "mean_discharge_m3_s": round(float(np.max(s_q_mean)), 3),
        "width_m": round(float(np.median(width_m)), 2),
        "depth_m": round(float(np.median(geometry["depth_m"])), 2),
        "valley_slope": round(float(np.median(slope)), 6),
        "threshold_ratio": round(float(np.median(geometry["threshold_ratio"])), 3),
        "braided_share": round(float(np.mean(geometry["braid"] > 0.5)), 3),
        "wavelength_m": round(float(np.median(MEANDER_WAVELENGTH_WIDTHS * geometry["single_width_m"])), 1),
        "width_depth_ratio": round(float(geometry["width_depth_ratio"]), 2),
    }
    return points, summary


def _valley_half_width(sx, sy, nx, ny, bank, elevation, dx, dy, *, rise_m=1.5, max_cells=60):
    """Distance from the valley axis to ground ``rise_m`` above the bank (min of both sides)."""
    height, width = elevation.shape
    spacing = min(dx, dy)
    half = np.full(sx.shape, max_cells * spacing)
    for side in (-1.0, 1.0):
        found = np.full(sx.shape, max_cells * spacing)
        open_ = np.ones(sx.shape, dtype=bool)
        for step in range(1, max_cells + 1):
            distance = step * spacing
            px = sx + side * nx * distance
            py = sy + side * ny * distance
            columns = np.clip(np.rint(px / dx).astype(np.int64), 0, width - 1)
            rows = np.clip(np.rint(py / dy).astype(np.int64), 0, height - 1)
            outside = (px < 0) | (py < 0) | (px > (width - 1) * dx) | (py > (height - 1) * dy)
            wall = (elevation[rows, columns] > bank + rise_m) & ~outside
            hit = open_ & wall
            found = np.where(hit, distance, found)
            open_ &= ~hit
            if not open_.any():
                break
        half = np.minimum(half, found)
    return _gaussian_smooth(half, 4.0)


# --- rasterization shared by terrain, materials and True Color ------------------

def channel_fields(reaches, shape, *, dx, dy, to_local):
    """Rasterize reach centrelines into per-cell channel fields.

    ``reaches`` is the stored list (see ``_compact_reach``); ``to_local``
    maps global ``(u, v)`` arrays to local metres ``(x, y)``.  Returns a dict
    of ``[H, W]`` arrays: ``depth`` (below bank, m), ``bank`` (bank
    elevation), ``water_depth`` at mean flow, ``levee`` (m), ``in_channel``,
    ``outer`` (-1 inner .. +1 outer bank), ``braid``, ``depth_fraction``,
    ``distance_m`` and ``width_m`` of the nearest channel point and its
    mean-flow water surface ``stage_m``; and of that point's bankfull section
    the mean depth ``mean_depth_m``, the deepest point ``section_depth_m`` and
    the mean flow as a share of bankfull ``mean_to_bankfull`` (what
    ``river_floods`` reads the stage of a flood from).
    """
    step = 0.5 * min(dx, dy)
    columns = {key: [] for key in ("x", "y", "bank", "width", "depth", "braid", "q_ratio", "s", "kappa", "phase", "seed")}
    for reach in reaches or []:
        data = np.asarray(reach.get("points") or [], dtype=np.float64)
        if data.ndim != 2 or data.shape[0] < 2:
            continue
        x, y = to_local(data[:, 0], data[:, 1])
        arc, values = _resample_smooth(x, y, step, *[data[:, index] for index in range(2, data.shape[1])])
        names = ("bank", "width", "depth", "braid", "q_ratio", "s", "kappa", "phase")
        columns["x"].append(values[0])
        columns["y"].append(values[1])
        for name, value in zip(names, values[2:]):
            columns[name].append(value)
        columns["seed"].append(np.full(arc.shape, float(reach.get("seed") or 0)))
    height, width = shape
    zero = np.zeros(shape)
    empty = {
        "depth": zero, "bank": zero.copy(), "water_depth": zero.copy(), "levee": zero.copy(),
        "in_channel": np.zeros(shape, dtype=bool), "outer": zero.copy(), "braid": zero.copy(),
        "depth_fraction": zero.copy(), "distance_m": np.full(shape, np.inf), "width_m": zero.copy(),
        "stage_m": np.full(shape, np.nan),
        "mean_depth_m": zero.copy(), "section_depth_m": zero.copy(), "mean_to_bankfull": np.ones(shape),
    }
    if not columns["x"]:
        return empty
    point = {key: np.concatenate(values) for key, values in columns.items()}
    # A centreline counts as far beyond the grid as its channel and levees reach.  (Kept to a tenth of the
    # grid's size beyond it, a river wider than a Plot lying in its bed was no river there: no channel, no
    # bars, no floods, its water a lake's box.)
    reach_radius = float(np.max(point["width"])) * (0.5 + 6.0 * LEVEE_DECAY_WIDTHS)
    margin_x, margin_y = max(0.1 * width * dx, reach_radius), max(0.1 * height * dy, reach_radius)
    keep = (
        (point["x"] > -margin_x) & (point["x"] < width * dx + margin_x)
        & (point["y"] > -margin_y) & (point["y"] < height * dy + margin_y)
    )
    point = {key: values[keep] for key, values in point.items()}
    if point["x"].size == 0:
        return empty
    tx = np.gradient(point["x"])
    ty = np.gradient(point["y"])
    norm = np.maximum(np.hypot(tx, ty), 1e-12)
    tx, ty = tx / norm, ty / norm
    reach_radius = float(np.max(point["width"])) * (0.5 + 6.0 * LEVEE_DECAY_WIDTHS)
    index, distance = nearest_point_field(point["x"], point["y"], shape, dx, dy, reach_radius)
    found = index >= 0
    safe = np.where(found, index, 0)
    x_cells = (np.arange(width) * dx)[None, :]
    y_cells = (np.arange(height) * dy)[:, None]
    cross = tx[safe] * (y_cells - point["y"][safe]) - ty[safe] * (x_cells - point["x"][safe])
    width_cells = point["width"][safe]
    half = 0.5 * width_cells
    inside = found & (distance <= half)
    n = np.clip(cross / np.maximum(half, 1e-6), -1.0, 1.0)
    kappa = point["kappa"][safe]
    outer = -np.sign(kappa) * n
    asymmetry = np.clip(np.abs(kappa) * width_cells * 1.1, 0.0, 0.75)
    mean_depth = point["depth"][safe]
    braid = point["braid"][safe]
    # Single thread: pool against the cut bank, point bar ramp on the inside.
    pool = 0.5 * asymmetry
    t_out = np.clip((outer - pool) / np.maximum(1.0 - pool, 1e-6), 0.0, 1.0)
    t_in = np.clip((pool - outer) / np.maximum(1.0 + pool, 1e-6), 0.0, 1.0)
    outer_shape = 1.0 - t_out ** (2.0 + 4.0 * asymmetry)
    # Point bars: a near-linear ramp at sharp bends (exponent 1 at the apex).
    inner_shape = 1.0 - t_in ** np.maximum(0.6, 2.0 - 2.0 * asymmetry)
    single_max = 1.5 * mean_depth * (1.0 + 0.3 * asymmetry)
    single = single_max * np.where(outer >= pool, outer_shape, inner_shape)
    # Braided: threads around bars, elongated along the flow.
    phase = point["phase"][safe]
    across = cross
    # Braids: a few threads wander across the belt over one to two belt
    # widths, cross, and leave diamond-shaped bars between them.
    braid_seed = seed_int("braid", int(point["seed"][0])) % (1 << 31)
    threads = np.zeros(shape)
    thread_half = 0.5 * width_cells / BRAID_THREADS * 1.3
    for thread in range(BRAID_THREADS):
        wander = value_noise(phase / (1.0 + 0.3 * thread), np.full(shape, 0.5 + thread), braid_seed + thread)
        centre = 0.42 * width_cells * (2.0 * wander - 1.0)
        section = 1.0 - ((across - centre) / np.maximum(thread_half, 1e-6)) ** 2
        threads = np.maximum(threads, np.clip(section, 0.0, 1.0))
    braided_max = 2.2 * mean_depth
    braided = braided_max * (0.1 + 0.9 * threads) * (1.0 - np.abs(n) ** 8)
    depth = np.where(inside, (1.0 - braid) * single + braid * braided, 0.0)
    local_max = (1.0 - braid) * single_max + braid * braided_max
    water_max = local_max * point["q_ratio"][safe] ** AT_A_STATION_DEPTH_EXPONENT
    water_depth = np.where(inside, np.maximum(0.0, depth - (local_max - water_max)), 0.0)
    # Natural levees: the carved section's area spread over both flanks.
    decay = LEVEE_DECAY_WIDTHS * width_cells
    # The levee rises from the bank edge to its crest over a short distance
    # (the channel section ends at bank level) and decays into the floodplain.
    ramp = LEVEE_RAMP_WIDTHS * width_cells
    levee_height = mean_depth * width_cells / (2.0 * np.maximum(decay - 0.5 * ramp, 1e-6))
    beyond = np.maximum(distance - half, 0.0)
    rise = _smooth01(beyond / np.maximum(ramp, 1e-6))
    levee = np.where(found & ~inside, levee_height * rise * np.exp(-beyond / np.maximum(decay, 1e-6)), 0.0)
    return {
        "depth": depth,
        "bank": np.where(found, point["bank"][safe], 0.0),
        "water_depth": water_depth,
        "levee": levee,
        "in_channel": inside,
        "outer": np.where(inside, outer, 0.0),
        "braid": np.where(inside, braid, 0.0),
        "depth_fraction": np.where(inside, depth / np.maximum(local_max, 1e-6), 0.0),
        "distance_m": np.where(found, distance, np.inf),
        "width_m": np.where(found, width_cells, 0.0),
        # Mean-flow water surface of the nearest channel point (NaN beyond reach).
        "stage_m": np.where(found, point["bank"][safe] - (local_max - water_max), np.nan),
        "mean_depth_m": np.where(found, mean_depth, 0.0),
        "section_depth_m": np.where(found, local_max, 0.0),
        "mean_to_bankfull": np.where(found, point["q_ratio"][safe], 1.0),
    }


def _compact_reach(points, to_uv, seed, summary, spacing):
    """Store a reach as global-UV points (decimated to about ``spacing``)."""
    arc = points["s"]
    stride = max(1, int(round(spacing / max(float(arc[1] - arc[0]) if arc.size > 1 else 1.0, 1e-6))))
    keep = np.unique(np.concatenate([np.arange(0, arc.size, stride), [arc.size - 1]]))
    u, v = to_uv(points["x"][keep], points["y"][keep])
    # Braid threads wander on the channel's own length scale: their phase
    # is distance integrated in widths (s / W jumps wherever W varies).
    phase = np.concatenate([[0.0], np.cumsum(np.diff(arc) / np.maximum(points["width"][1:], 1e-6))])
    columns = [u, v] + [points[key][keep] for key in ("bank", "width", "depth", "braid", "q_ratio", "s", "kappa")] + [phase[keep]]
    rounding = (10, 10, 3, 3, 3, 3, 4, 2, 5, 4)
    rows = np.stack(columns, axis=1)
    return {
        "seed": int(seed),
        "point_fields": ["u", "v", "bank_m", "width_m", "depth_m", "braid", "mean_to_bankfull", "arc_m", "curvature_per_m", "braid_phase"],
        "points": [[round(float(value), digits) for value, digits in zip(row, rounding)] for row in rows],
        **summary,
    }


# --- entry point used by regional_landforms --------------------------------------

def alluvial_channel_residual(
    elevation,
    land,
    *,
    level,
    dx,
    dy,
    parent_spacing_m,
    parent_entity,
    to_local,
    to_uv,
    seed_text,
    inflow_cells=None,
    sea_level=None,
):
    """Carve the channels this level resolves; return ``(residual, record)``.

    ``record`` holds the carved reaches plus those inherited from the parent
    (global UV centrelines) for the material and True Color layers.
    """
    elevation = np.asarray(elevation, dtype=np.float64)
    land = np.asarray(land, dtype=bool)
    shape = elevation.shape
    residual = np.zeros(shape)
    inherited = _clip_reaches(inherited_reaches(parent_entity), shape, dx, dy, to_local)
    record = {"landform": LANDFORM_ID, "level": int(level), "reaches": [], "inherited_reaches": inherited}
    if int(level) < CHANNEL_PLANFORM_MIN_LEVEL or land.sum() < 64:
        return residual, record
    runoff_mm, runoff_source = parent_runoff_mm(parent_entity)
    aridity = parent_aridity(parent_entity)
    silt_clay, silt_clay_source = bank_silt_clay_percent(parent_entity)
    gravity = planet_gravity_m_s2(parent_entity)
    bankfull_ratio = BANKFULL_TO_MEAN_DISCHARGE[0] + (BANKFULL_TO_MEAN_DISCHARGE[1] - BANKFULL_TO_MEAN_DISCHARGE[0]) * aridity
    runoff_m_s = runoff_mm / 1000.0 / SECONDS_PER_YEAR
    record.update({
        "runoff_mm": round(runoff_mm, 2), "runoff_source": runoff_source, "aridity": round(aridity, 3),
        "bankfull_to_mean": round(bankfull_ratio, 2), "silt_clay_percent": round(silt_clay, 2),
        "silt_clay_source": silt_clay_source, "gravity_m_s2": round(gravity, 3),
    })
    receivers = filled_routing(elevation, land, dx=dx, dy=dy, inlets=inlet_mask(inflow_cells, shape, dx=dx, dy=dy))
    sources = np.ones(receivers.size)
    if inflow_cells is not None:
        sources = sources + np.asarray(inflow_cells, dtype=np.float64).ravel()
    area = upstream_sum(receivers, sources)[:, 0].reshape(shape) * dx * dy
    _unused, gradient = d8_receivers(elevation, dx=dx, dy=dy, sinks=~land)
    slope = np.clip(box_mean(gradient, 2), 1e-5, 0.2)
    gate_geometry = bankfull_geometry(runoff_m_s * area * bankfull_ratio, slope, silt_clay, gravity)
    resolved = gate_geometry["width_m"] >= RESOLVE_WIDTH_CELLS * max(dx, dy)
    first_level = int(level) == CHANNEL_PLANFORM_MIN_LEVEL
    if not first_level and parent_spacing_m > 0.0:
        resolved &= gate_geometry["width_m"] < RESOLVE_WIDTH_CELLS * parent_spacing_m
    gated = land & (area >= CHANNEL_HEAD_AREA_M2) & resolved
    if inherited:
        # Channels the parent carved are already in the inherited surface,
        # smoothed by the parent's sampling; add back only the part of their
        # section finer than the parent's spacing (steep cut banks, bar
        # edges), then keep new channels out of them.
        fields = channel_fields(inherited, shape, dx=dx, dy=dy, to_local=to_local)
        gated &= ~(fields["distance_m"] <= 0.5 * fields["width_m"] + 3.0 * max(dx, dy))
        if parent_spacing_m > 1.5 * max(dx, dy):
            section = np.where(fields["in_channel"], -fields["depth"], fields["levee"])
            sigma_cells = PARENT_RECONSTRUCTION_SIGMA * parent_spacing_m / max(dx, dy)
            sharpening = section - gaussian_blur(section, sigma_cells)
            if sea_level is not None:
                sharpening = np.where(land, sharpening, 0.0)
            residual = residual + sharpening
            record["inherited_sharpening_max_m"] = round(float(np.abs(sharpening).max()), 3)
    record["gated_cell_fraction"] = round(float(gated[land].mean()), 5)
    if not gated.any():
        return residual, record
    reaches = _trace_reaches(receivers, gated, shape)
    path_mask = np.zeros(receivers.size, dtype=bool)
    for cells, _junction in reaches:
        path_mask[cells] = True
    path_mask = path_mask.reshape(shape)
    base_seed = seed_int(seed_text, "alluvial_channels") % (1 << 31)
    generated = []
    stored = []
    height, width = shape
    for number, (cells, junction) in enumerate(reaches):
        junction_xy = None
        if junction is not None and generated:
            jr, jc = divmod(int(junction), width)
            jx, jy = jc * dx, jr * dy
            best = None
            for points in generated:
                d2 = (points["x"] - jx) ** 2 + (points["y"] - jy) ** 2
                i = int(np.argmin(d2))
                if best is None or d2[i] < best[0]:
                    best = (float(d2[i]), float(points["x"][i]), float(points["y"][i]))
            junction_xy = (best[1], best[2]) if best else (jx, jy)
        head_row, head_column = divmod(int(cells[0]), width)
        hx, hy = to_uv(np.asarray([head_column * dx]), np.asarray([head_row * dy]))
        reach_seed = seed_int(seed_text, f"reach:{round(float(hx[0]), 6)}:{round(float(hy[0]), 6)}") % (1 << 31)
        points, summary = _reach_geometry(
            cells, junction_xy, elevation, path_mask, area, dx=dx, dy=dy, runoff_m_s=runoff_m_s,
            bankfull_ratio=bankfull_ratio, silt_clay=silt_clay, gravity=gravity, seed=reach_seed + base_seed,
        )
        if summary["width_m"] < RESOLVE_WIDTH_CELLS * max(dx, dy):
            # Narrower than this level resolves once its own valley slope is
            # known: the next level carves it.
            record.setdefault("deferred_reaches", 0)
            record["deferred_reaches"] += 1
            continue
        generated.append(points)
        stored.append(_compact_reach(points, to_uv, reach_seed, {"reach": number, **summary}, spacing=max(dx, dy)))
    fields = channel_fields(stored, shape, dx=dx, dy=dy, to_local=to_local)
    target = elevation + residual
    groove = path_mask & ~fields["in_channel"] & np.isfinite(fields["distance_m"])
    target = np.where(groove, np.maximum(target, fields["bank"]), target)
    target = np.where(fields["in_channel"], fields["bank"] - fields["depth"], target + fields["levee"])
    if sea_level is not None:
        target = np.where(land, np.maximum(target, float(sea_level) + 0.3), elevation)
    residual = target - elevation
    record["reaches"] = stored
    record["carved_cell_fraction"] = round(float(fields["in_channel"][land].mean()), 5)
    record["max_depth_m"] = round(float(fields["depth"].max()), 2)
    record["resolve_width_m"] = round(RESOLVE_WIDTH_CELLS * max(dx, dy), 2)
    return residual, record


def _clip_reaches(reaches, shape, dx, dy, to_local):
    """Pieces of reaches that can touch this grid (levee reach included)."""
    height, width = shape
    clipped = []
    for reach in reaches or []:
        data = np.asarray(reach.get("points") or [], dtype=np.float64)
        if data.ndim != 2 or data.shape[0] < 2:
            continue
        x, y = to_local(data[:, 0], data[:, 1])
        margin = float(np.max(data[:, 3])) * (0.5 + 6.0 * LEVEE_DECAY_WIDTHS) + 2.0 * max(dx, dy)
        near = (x > -margin) & (x < (width - 1) * dx + margin) & (y > -margin) & (y < (height - 1) * dy + margin)
        # Keep one point either side of each run so the piece reaches the edge.
        keep = near | np.r_[near[1:], False] | np.r_[False, near[:-1]]
        starts = np.flatnonzero(keep & ~np.r_[False, keep[:-1]])
        ends = np.flatnonzero(keep & ~np.r_[keep[1:], False])
        for start, end in zip(starts, ends):
            if end - start < 1:
                continue
            piece = dict(reach)
            piece["points"] = [list(row) for row in reach["points"][start:end + 1]]
            clipped.append(piece)
    return clipped


def inherited_reaches(parent_entity):
    """All channel reaches the parent level carried (its own and inherited)."""
    heightmap = (parent_entity or {}).get("heightmap_model") or {}
    for landform in ((heightmap.get("regional_landforms") or {}).get("landforms") or []):
        if isinstance(landform, dict) and landform.get("landform") == LANDFORM_ID:
            return list(landform.get("inherited_reaches") or []) + list(landform.get("reaches") or [])
    return []


def heightmap_channel_reaches(heightmap):
    """Every reach a level knows (own + inherited), for consumers."""
    for landform in (((heightmap or {}).get("regional_landforms") or {}).get("landforms") or []):
        if isinstance(landform, dict) and landform.get("landform") == LANDFORM_ID:
            return list(landform.get("inherited_reaches") or []) + list(landform.get("reaches") or [])
    return []


def local_frame(heightmap, shape):
    """``(dx, dy, to_local, to_uv)`` for a regional heightmap's grid."""
    height, width = shape
    bounds = (heightmap or {}).get("source_uv_bounds") or {}
    u0, u1 = float(bounds.get("min_u", 0.0)), float(bounds.get("max_u", 1.0))
    v0, v1 = float(bounds.get("min_v", 0.0)), float(bounds.get("max_v", 1.0))
    dx = float((heightmap or {}).get("sample_spacing_x_m") or 1.0)
    dy = float((heightmap or {}).get("sample_spacing_y_m") or 1.0)
    centre = 0.5 * (u0 + u1)

    def to_local(u, v):
        u = centre + np.mod(np.asarray(u, dtype=np.float64) - centre + 0.5, 1.0) - 0.5
        return (u - u0) / max(u1 - u0, 1e-15) * (width - 1) * dx, (np.asarray(v, dtype=np.float64) - v0) / max(v1 - v0, 1e-15) * (height - 1) * dy

    def to_uv(x, y):
        return u0 + (u1 - u0) * np.asarray(x) / max((width - 1) * dx, 1e-9), v0 + (v1 - v0) * np.asarray(y) / max((height - 1) * dy, 1e-9)

    return dx, dy, to_local, to_uv


def heightmap_channel_fields(heightmap, shape=None, raster=None):
    """Channel fields for a heightmap, or ``None`` without channels.

    By default on the heightmap's own sample points; ``raster=(width,
    height)`` gives a pixel-centred raster over the same extent (True Color
    renders cells, not points).
    """
    reaches = heightmap_channel_reaches(heightmap)
    if not reaches:
        return None
    rows = ((heightmap or {}).get("sample_grid") or {}).get("rows") or []
    grid_shape = shape or (len(rows), len(rows[0]) if rows else 0)
    dx, dy, to_local, _to_uv = local_frame(heightmap, grid_shape)
    if raster is None:
        return channel_fields(reaches, grid_shape, dx=dx, dy=dy, to_local=to_local)
    target_w, target_h = int(raster[0]), int(raster[1])
    pixel_x = (grid_shape[1] - 1) * dx / max(1, target_w)
    pixel_y = (grid_shape[0] - 1) * dy / max(1, target_h)

    def to_pixels(u, v):
        x, y = to_local(u, v)
        return x - 0.5 * pixel_x, y - 0.5 * pixel_y

    return channel_fields(reaches, (target_h, target_w), dx=pixel_x, dy=pixel_y, to_local=to_pixels)
