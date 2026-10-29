"""Rock cliffs: the scarp profile of a layered rock sequence.

Where the land cuts across beds of unequal strength it does not form a
ramp.  A strong bed stands as a rock face (the free face of Wood 1942 and
King 1953) at the angle its rock mass can hold; the debris it sheds rests
against its foot as talus; the weak bed beneath is kept steep by the cap
above it (the rampart of the Colorado Plateau scarps: Koons 1955, Schumm &
Chorley 1966, Howard & Selby 1994); and beyond the foot of the rampart the
weak bed is stripped back to a bench on top of the next strong bed (the
Tonto Platform on the Tapeats Sandstone, the Esplanade on the Supai Group).

Going up through one scarp the profile has five parts, each with the
gradient its material allows:

* the bench below (half of it: the other half belongs to the scarp below);
* rampart: the weak unit under the cap, a debris-mantled slope;
* talus: the buried lower part of the strong unit, at the angle of repose;
* face: the exposed upper part of the strong unit, at its strength angle;
* the bench above (again half of it).

The gradients are limits, not shares of a ratio, so the profile depends on
the slope the beds are cut at: on a gentle slope nearly all of the run is
bench, on a steep one the benches shrink to ledges (a canyon wall of cliffs
and slopes), and where the ground is steeper than even that the whole
profile steepens together.  It is tabulated for a ladder of slopes
(``SLOPE_LEVELS``) and applied as a remap of the dip-corrected elevation,
scarp by scarp.  The remap is the identity in the middle of every bench and
puts the scarp in the middle of its run, so the ground above the brink rises
by as much as the ground below the foot sinks: a level keeps the mean height
its parent gave it.

Rock sequences are layered at every scale (bed sets, beds, bedding).  The
beds are the planet's stack (``strata``): one partition of nested beds in
depth below the stack's reference horizon, which rock uplift, basins and
folds hold up, so a cliff stands where the ground cuts a strong bed of the
same sequence on every map and folded beds make hogbacks.  Each level
builds the order of beds its cells resolve (``BED_ORDER``) and
only where a scarp's whole run fits inside the parent's cells
(``RUN_GATE_PARENT_CELLS``): a wider staircase is the parent's to draw, and
where nobody drew it the beds are bevelled, as on any plain that cuts
across strata.  Cliffs therefore stand on valley sides, escarpments and
mountain flanks.  The two finer levels step an order again (``restep``)
until its faces are resolved.  Streams cut back into the scarps one level
below the one that built them (``scarp_canyons``), and whatever then stands
steeper than its rock holds fails (``rockfall``).

Abiotic by contract: a vegetated debris slope stands steeper and a root mat
holds soil on ledges; the Biosphere may add that on top of these fields.
"""

from __future__ import annotations

import math

import numpy as np

from simulations.world_gen.strata import BED_THICKNESS_LADDER_M

MODEL = "scarp_profile_v1"
LANDFORM_ID = "caprock_mesas_and_benches"

# Strength-equilibrium rock slopes (Selby 1980, "A rock mass strength
# classification for geomorphic purposes"; Selby 1982; Moon 1984): the
# inclination a rock face holds rises with its mass-strength rating, in a
# band from about 35 degrees at a rating of 50 to about 85 degrees at 90.
# The ontology's 0..1 ``slope_resistance_index`` is read as that rating / 100.
FACE_ANGLE_AT_RATING_50_DEG = 35.0
FACE_ANGLE_PER_RATING_DEG = 1.25
FACE_ANGLE_MAX_DEG = 85.0
# Below this a "face" is no steeper than the debris lying on it: the rock is
# a slope former (shale, marl, weak sandstone, evaporites).
FACE_MIN_ANGLE_DEG = 40.0
# Talus stands at the angle of repose of coarse angular debris, 33-37 degrees
# (Carson 1977; Statham 1976); the lower figure, because the apron's lower
# part is a little gentler than its top (fall sorting, Kirkby & Statham 1975).
TALUS_GRADIENT = 0.65
# Debris-mantled slopes in weak rock under a cap: 28-38 degrees in dry lands
# (Schumm & Chorley 1966); under a wet climate the weak rock weathers to a
# clayey mantle that creeps and slides at far lower angles (threshold slopes,
# Carson & Kirkby 1972).  Humid .. arid.
RAMPART_GRADIENT = (0.36, 0.65)
# Share of a strong unit that stands as a bare face; the rest is banked with
# its own debris.  Weathering-limited (arid) scarps shed their talus as fast
# as it falls, transport-limited (humid) ones bury most of the face.
EXPOSED_FACE_SHARE = (0.35, 1.0)
# The bench at the foot of a rampart is cut in the lowest part of the weak
# unit (a thin remnant on the stripped surface), and never has less than this
# share of a scarp's height to rise through (so it keeps a drainage slope).
BENCH_RISE_SHARE = 0.15
MIN_BENCH_RISE_SHARE = 0.03
# Slopes the profile is tabulated for.
SLOPE_LEVELS = np.geomspace(0.003, 3.0, 25)

# The order of the planet's bed ladder (``strata.BED_THICKNESS_LADDER_M``)
# each level builds: bed sets and flow packages (Grand Canyon units: ~50-300
# m), thick beds, and beds (Campbell 1967: strata are layered at every scale
# from the formation to the lamina).  Sized so that on the slopes a level
# typically has, a scarp's run is a few of its parent's cells.
BED_ORDER = {2: 1, 3: 4, 4: 5}
# Nominal thickness of those beds (lognormal about it, ``strata``), for the audit.
BED_THICKNESS_M = {
    level: (0.4 * BED_THICKNESS_LADDER_M[order], 2.5 * BED_THICKNESS_LADDER_M[order]) for level, order in BED_ORDER.items()
}
# The stack's structure (reference horizon height) a record keeps, on about
# this many nodes a side: the surface every reader of the record steps
# against.
STRUCTURE_RECORD_CELLS = 128
# A scarp is built where its run (height / slope) is at most this many parent
# cells: full below the first, none above the second (a form four cells
# across is one the parent would show itself: procedure, visibility rule).
RUN_GATE_PARENT_CELLS = (2.0, 4.0)
# A rock step breaks the surface only where it stands higher than the soil
# is deep: face height in regolith depths, buried below the first, bare from
# the second (abiotic: the mantle's depth is the soil model's).
FACE_ABOVE_REGOLITH_DEPTHS = (1.0, 2.0)
# A part of the profile counts as a scarp only where the ground falls across
# it: by this share of the slope the profile was laid out for it is none, by
# the second it is whole.
REALISED_SLOPE_SHARE = (0.3, 0.7)
# Rockfall relaxation (``relax_to_strength``): passes at most, and the height
# change per pass (in cells) under which it has come to rest.
RELAX_ITERATIONS = 400
RELAX_TOLERANCE_CELLS = 0.0005
# Rockfall (``rockfall``) reads the rock again from the ground it is laying
# back, every few passes (a wall cut through a cap comes to stand in the bed
# below), and is given the passes a wall many cells high needs to come to
# rest: the passes grow with the square of that height in cells.
RELAX_REREAD_PASSES = 8
ROCKFALL_PASSES = 8 * RELAX_ITERATIONS
# Debris spreads sideways as it comes to rest: what rockfall moved is spread
# over about this many cells.  Cell-to-cell relaxation alone leaves every
# column of a slope at its own level (any corrugation under the limit is
# stable), which shows as streaks down a laid-back wall.
ROCKFALL_SPREAD_CELLS = 1.0
# Rock fails this far beyond the gradient its profile is laid out at.
FAILURE_MARGIN = 1.15
# Levels below the one that built an order that step it again.
RESTEP_LEVELS = 2
# Below this share of layered rock the sequence does not control the relief.
MIN_LAYERED_SHARE = 0.3
# Cells the surface is smoothed over before it is stepped (the remap is added
# to the ground as it is: applied to the ground itself it multiplied every
# bit of cell-scale relief inside a strong bed by the cliff gain), and over
# which its slope is read.
SMOOTHING_CELLS = 2.0
SLOPE_SMOOTHING_CELLS = 1.5
# Coarse grids (cells per side) an order's record keeps of where it applies
# and of the slope its profile was laid out for.
WEIGHT_RECORD_CELLS = 64
SLOPE_RECORD_CELLS = 128

BENCH, RAMPART, TALUS, FACE = 0, 1, 2, 3
SEGMENT_NAMES = ("bench", "rampart", "talus", "face")


def _smooth01(values):
    values = np.clip(values, 0.0, 1.0)
    return values * values * (3.0 - 2.0 * values)


def face_gradient(resistance):
    """Gradient of the rock face a rock of this slope resistance holds (0: none)."""
    rating = 100.0 * float(resistance)
    angle = FACE_ANGLE_AT_RATING_50_DEG + FACE_ANGLE_PER_RATING_DEG * (rating - 50.0)
    if angle < FACE_MIN_ANGLE_DEG:
        return 0.0
    return math.tan(math.radians(min(angle, FACE_ANGLE_MAX_DEG)))


def climate_parameters(aridity):
    """``(exposed face share, rampart gradient)`` for an aridity of 0 (humid) .. 1 (arid)."""
    dry = min(1.0, max(0.0, float(aridity)))
    return (
        EXPOSED_FACE_SHARE[0] + (EXPOSED_FACE_SHARE[1] - EXPOSED_FACE_SHARE[0]) * dry,
        RAMPART_GRADIENT[0] + (RAMPART_GRADIENT[1] - RAMPART_GRADIENT[0]) * dry,
    )


def _bed_resistance(bed):
    """A bed's slope resistance (rows without the strength column: from its erodibility)."""
    return float(bed[3]) if len(bed) > 3 else 1.0 - float(bed[2])


def scarp_units(strata):
    """Beds merged into slope-forming and cliff-forming units.

    Returns ``[[base, top, face gradient, rock]]`` from the bottom up; the
    gradient is 0 for a slope former.  Weak beds lying on each other make
    one slope; strong beds make one cliff only while the rock stays the same:
    where one strong rock lies on another the contact is a ledge, so a stack
    of flows and sandstones is a wall of steps, not one face.
    """
    units = []
    rocks = strata.get("bed_materials") or []
    for index, bed in enumerate(strata.get("beds") or []):
        base, thickness = float(bed[0]), float(bed[1])
        if thickness <= 0.0:
            continue
        face = face_gradient(_bed_resistance(bed))
        rock = rocks[index] if index < len(rocks) else None
        previous = units[-1] if units else None
        if previous is not None and (previous[2] > 0.0) == (face > 0.0) and (face <= 0.0 or previous[3] == rock):
            previous[1] = base + thickness
        else:
            units.append([base, base + thickness, face, rock])
    return units


def _profile_pieces(units, exposure, rampart, talus):
    """``[(rise, limit gradient or None, part)]`` of the whole sequence, bottom up."""
    pieces = []
    index = 0
    while index < len(units):
        soft = units[index] if units[index][2] <= 0.0 else None
        if soft is not None:
            index += 1
        hard = units[index] if index < len(units) and units[index][2] > 0.0 else None
        if hard is not None:
            index += 1
        soft_rise = soft[1] - soft[0] if soft is not None else 0.0
        hard_rise = hard[1] - hard[0] if hard is not None else 0.0
        cycle = soft_rise + hard_rise
        if hard is None:
            # No cap above: the weak unit keeps the slope it is given.
            parts = [(cycle, None, BENCH)]
        else:
            bench = min(cycle, max(BENCH_RISE_SHARE * soft_rise, MIN_BENCH_RISE_SHARE * cycle))
            face = min(exposure * hard_rise, cycle - bench)
            buried = max(0.0, min(hard_rise - face, cycle - bench - face))
            under_cap = max(0.0, cycle - bench - face - buried)
            parts = [(bench, None, BENCH), (under_cap, rampart, RAMPART), (buried, talus, TALUS), (face, hard[2], FACE)]
        pieces.extend(part for part in parts if part[0] > 1e-9)
    return pieces


def scarp_transfer(strata):
    """The elevation remap of a bed sequence, for every slope of ``SLOPE_LEVELS``.

    Returns ``real`` (the breakpoints of the stepped profile, dip-corrected
    elevation), ``smooth[level]`` (the smooth elevations that map onto them at
    that slope), ``kind`` (the part of the profile between consecutive
    breakpoints, ``BENCH`` .. ``FACE``), ``unit_real`` / ``unit_height_m``
    (the scarps: from the middle of one bench to the middle of the next) and
    ``unit_face_m`` (the scarps: from the middle of one bench to the middle
    of the next, and the height of bare face in each), and
    ``parent_spacing_m`` / ``regolith_depth_m`` for the gate.
    """
    units = scarp_units(strata)
    exposure = float(strata.get("exposure", EXPOSED_FACE_SHARE[1]))
    rampart = float(strata.get("rampart_gradient", RAMPART_GRADIENT[1]))
    talus = float(strata.get("talus_gradient", TALUS_GRADIENT))
    slopes = SLOPE_LEVELS
    start = units[0][0] if units else 0.0
    # Every bench is shared by the scarp below it and the scarp above it.
    groups, current = [], []
    for rise, gradient, kind in _profile_pieces(units, exposure, rampart, talus):
        if gradient is None:
            current.append((0.5 * rise, None, kind))
            groups.append(current)
            current = [(0.5 * rise, None, kind)]
        else:
            current.append((rise, gradient, kind))
    if current:
        groups.append(current)
    real = [start]
    smooth = [np.full(slopes.shape, start)]
    kinds = []
    unit_real = [start]
    unit_height = []
    unit_face = []
    for group in groups:
        height = sum(rise for rise, _gradient, _kind in group)
        steep = [(rise, gradient) for rise, gradient, _kind in group if gradient]
        free = [rise for rise, gradient, _kind in group if not gradient]
        if not steep:
            spans = [np.full(slopes.shape, rise) for rise, _gradient, _kind in group]
        else:
            # The run each steep part needs at its limit gradient, as a span of
            # smooth elevation; the benches share what is left, and where that
            # would make a bench steeper than the rampart the whole scarp
            # steepens together.
            limited = sum(rise * slopes / gradient for rise, gradient in steep)
            floors = sum(free) * slopes / rampart
            squeeze = height / np.maximum(limited + floors, 1e-12)
            if free:
                squeeze = np.minimum(1.0, squeeze)
            room = height - limited * squeeze
            roomy = room > floors * squeeze + 1e-12
            shares = [np.full(slopes.shape, 1.0)] if len(free) == 1 else []
            if len(free) == 2:
                # The bench below the foot lies under the smooth slope, the
                # bench above the brink over it; their runs are set so that
                # the two volumes are equal and the scarp moves no mean height.
                below, above = free
                moment = 0.0  # each steep part's span times its mid-height above the scarp's start
                climbed = below
                for rise, gradient in steep:
                    moment = moment + rise * slopes / gradient * squeeze * (climbed + 0.5 * rise)
                    climbed += rise
                first = (moment + room * (height - 0.5 * above) - 0.5 * height * height) / max(height - 0.5 * (below + above), 1e-12)
                first = np.clip(first, below * slopes / rampart * squeeze, room - above * slopes / rampart * squeeze)
                shares = [first / np.maximum(room, 1e-12), 1.0 - first / np.maximum(room, 1e-12)]
            spans = []
            for rise, gradient, _kind in group:
                if gradient:
                    spans.append(rise * slopes / gradient * squeeze)
                else:
                    spans.append(np.where(roomy, room * shares.pop(0), rise * slopes / rampart * squeeze))
        for (rise, _gradient, kind), span in zip(group, spans):
            real.append(real[-1] + rise)
            smooth.append(smooth[-1] + np.maximum(span, rise * 1e-9))
            kinds.append(kind)
        # Rounding must not let a scarp's spans miss its end.
        smooth[-1] = np.full(slopes.shape, real[-1])
        unit_real.append(real[-1])
        unit_height.append(height if steep else 0.0)
        unit_face.append(sum(rise for rise, _gradient, kind in group if kind == FACE))
    smooth = np.ascontiguousarray(np.asarray(smooth).T, dtype=np.float64)
    kinds = np.asarray(kinds, dtype=np.int8)
    spans = np.diff(smooth, axis=1)
    part_length = {
        kind: np.concatenate([np.zeros((len(slopes), 1)), np.cumsum(spans * (kinds == kind)[None, :], axis=1)], axis=1)
        for kind in (RAMPART, TALUS, FACE)
    }
    return {
        "real": np.asarray(real, dtype=np.float64),
        "smooth": smooth,
        "kind": kinds,
        "part_length": part_length,
        "slopes": slopes,
        "unit_real": np.asarray(unit_real, dtype=np.float64),
        "unit_height_m": np.asarray(unit_height, dtype=np.float64),
        "unit_face_m": np.asarray(unit_face, dtype=np.float64),
        "regolith_depth_m": float(strata.get("regolith_depth_m") or 0.0),
        "max_unit_m": float(max(unit_height, default=0.0)),
        "parent_spacing_m": float(strata.get("parent_spacing_m") or 0.0),
    }


def _levels(slope, transfer):
    """Lower ladder index and blend fraction of each cell's slope."""
    slopes = transfer["slopes"]
    position = np.interp(np.log(np.clip(slope, slopes[0], slopes[-1])), np.log(slopes), np.arange(len(slopes)))
    lower = np.minimum(position.astype(int), len(slopes) - 2)
    return lower, position - lower


def _locate(values, slope, transfer):
    """Where smooth elevations lie in the profile at their slope.

    Returns ``(interval, start, span, lower, fraction)``: the piece each
    value is in, that piece's start and span of smooth elevation, and the
    ladder position.  Between two slopes of the ladder the breakpoints
    themselves are interpolated: blending two stepped values instead would
    split every face into two half-steep ones, one at each ladder slope's
    brink.
    """
    real = transfer["real"]
    lower, fraction = _levels(slope, transfer)
    table = transfer["smooth"]

    def breakpoint(index):
        return table[lower, index] * (1.0 - fraction) + table[lower + 1, index] * fraction

    low = np.zeros(values.shape, dtype=np.int64)
    high = np.full(values.shape, real.size - 1, dtype=np.int64)
    for _iteration in range(int(math.ceil(math.log2(real.size))) + 1):
        middle = (low + high + 1) // 2
        up = breakpoint(middle) <= values
        low = np.where(up, middle, low)
        high = np.where(up, high, middle - 1)
    interval = np.clip(low, 0, real.size - 2)
    start = breakpoint(interval)
    span = np.maximum(breakpoint(interval + 1) - start, 1e-12)
    return interval, start, span, lower, fraction


def remap(x, slope, transfer):
    """Fully stepped elevation of smooth elevation ``x`` (identity outside the sequence)."""
    x, slope = np.broadcast_arrays(np.asarray(x, dtype=np.float64), np.asarray(slope, dtype=np.float64))
    result = np.array(x, dtype=np.float64)
    real = transfer["real"]
    if real.size < 2:
        return result
    inside = (x >= real[0]) & (x <= real[-1])
    if not inside.any():
        return result
    values = x[inside]
    interval, start, span, _lower, _fraction = _locate(values, slope[inside], transfer)
    result[inside] = real[interval] + np.clip((values - start) / span, 0.0, 1.0) * (real[interval + 1] - real[interval])
    return result


def part_lengths(x, slope, transfer):
    """Smooth-elevation length of rampart, talus and face below ``x``: ``{part: array}``.

    The share of a window of smooth elevation that a part takes is the
    share of the ground it takes in plan (run is proportional to smooth
    elevation), which is how a cell wider than a face still knows how much
    of it is face.
    """
    x, slope = np.broadcast_arrays(np.asarray(x, dtype=np.float64), np.asarray(slope, dtype=np.float64))
    real = transfer["real"]
    if real.size < 2:
        return {kind: np.zeros(x.shape) for kind in (RAMPART, TALUS, FACE)}
    values = np.clip(x, real[0], real[-1])
    interval, start, span, lower, fraction = _locate(values.ravel(), slope.ravel(), transfer)
    along = np.clip(values.ravel() - start, 0.0, span)
    lengths = {}
    for kind in (RAMPART, TALUS, FACE):
        table = transfer["part_length"][kind]
        below = table[lower, interval] * (1.0 - fraction) + table[lower + 1, interval] * fraction
        lengths[kind] = (below + np.where(transfer["kind"][interval] == kind, along, 0.0)).reshape(x.shape)
    return lengths


def run_gate(x, slope, transfer):
    """How far the scarp at smooth (or stepped) elevation ``x`` is built: 0 .. 1.

    A scarp whose run (its height over the slope) is longer than the
    parent's cells is not this level's to draw, and one whose face is lower
    than the soil is deep stays under it.  A scarp begins and ends where the
    remap is the identity, so the stepped elevation names the same scarp as
    the smooth one.
    """
    spacing = transfer["parent_spacing_m"]
    bounds = transfer["unit_real"]
    x, slope = np.broadcast_arrays(np.asarray(x, dtype=np.float64), np.asarray(slope, dtype=np.float64))
    if bounds.size < 2:
        return np.ones(x.shape)
    unit = np.clip(np.searchsorted(bounds, x, side="right") - 1, 0, bounds.size - 2)
    built = np.ones(x.shape)
    if spacing > 0.0:
        run_cells = transfer["unit_height_m"][unit] / np.maximum(slope, 1e-9) / spacing
        full, none = RUN_GATE_PARENT_CELLS
        built = _smooth01((none - run_cells) / (none - full))
    regolith = transfer["regolith_depth_m"]
    if regolith > 0.0:
        buried, bare = FACE_ABOVE_REGOLITH_DEPTHS
        built = built * _smooth01((transfer["unit_face_m"][unit] / regolith - buried) / (bare - buried))
    return built


def step(x, weight, slope, transfer):
    """Smooth elevation ``x`` with the scarp profile applied at ``weight`` (0..1)."""
    x = np.asarray(x, dtype=np.float64)
    return x + (remap(x, slope, transfer) - x) * weight * run_gate(x, slope, transfer)


def unstep(y, weight, slope, transfer, iterations=30):
    """Inverse of ``step``: the smooth elevation behind a stepped one (bisection)."""
    y = np.asarray(y, dtype=np.float64)
    reach = max(1.0, float(transfer["max_unit_m"]))
    low = y - reach
    high = y + reach
    for _iteration in range(iterations):
        middle = 0.5 * (low + high)
        above = step(middle, weight, slope, transfer) > y
        high = np.where(above, middle, high)
        low = np.where(above, low, middle)
    return 0.5 * (low + high)


def profile_part(real_elevation, transfer):
    """Part of the profile (``BENCH`` .. ``FACE``) at a stepped, dip-corrected elevation."""
    real = transfer["real"]
    values = np.asarray(real_elevation, dtype=np.float64)
    if real.size < 2:
        return np.zeros(values.shape, dtype=np.int8)
    interval = np.clip(np.searchsorted(real, values, side="right") - 1, 0, real.size - 2)
    inside = (values >= real[0]) & (values <= real[-1])
    return np.where(inside, transfer["kind"][interval], BENCH).astype(np.int8)


def bed_at(real_elevation, strata):
    """Index of the bed a stepped, dip-corrected elevation lies in (-1 outside)."""
    beds = strata.get("beds") or []
    values = np.asarray(real_elevation, dtype=np.float64)
    if not beds:
        return np.full(values.shape, -1, dtype=np.int64)
    tops = np.asarray([float(bed[0]) + float(bed[1]) for bed in beds])
    index = np.searchsorted(tops, values, side="right")
    inside = (values >= float(beds[0][0])) & (index < len(beds))
    return np.where(inside, index, -1).astype(np.int64)


# --- the beds of an order -------------------------------------------------------


def bed_sequence(seed_text, level, low, high, layered, coarser=None, bed_rocks=None):
    """Beds of the order ``level`` builds, covering ``low .. high`` (m above the stack's reference horizon).

    ``layered`` is ``[(material, share, erodibility, slope resistance)]``.
    The beds are the planet's stack (``strata.beds_between`` with the planet
    seed ``seed_text``), so every map cuts the same sequence.  With
    ``coarser`` (the record of the next coarser order) a bed keeps the rock
    of the coarser bed it lies in ``strata.MEMBER_INHERIT_SHARE`` per order
    of difference; otherwise it is drawn from ``layered`` with the bed's own
    planet-anchored draws.  ``bed_rocks`` ``{bed id: material}`` (the rock
    the rock map draws on a bed this tile exposes) comes first.  Returns
    ``[(base, thickness, material, erodibility, resistance)]``, lowest first.
    """
    from simulations.world_gen import strata as stack

    order = BED_ORDER[int(level)]
    shares = {item[0]: float(item[1]) for item in layered}
    by_material = {item[0]: item for item in layered}
    coarser_tops = coarser_rocks = None
    gap = 1
    if coarser and coarser.get("beds") and coarser.get("bed_materials"):
        coarser_tops = np.asarray([float(bed[0]) + float(bed[1]) for bed in coarser["beds"]])
        coarser_rocks = [
            (material, 0.0, float(bed[2]), _bed_resistance(bed))
            for bed, material in zip(coarser["beds"], coarser["bed_materials"])
        ]
        gap = max(1, order - int(coarser.get("bed_order", BED_ORDER.get(int(coarser.get("built_at_level", 2)), 1))))
    beds = []
    # Height above the horizon is minus the depth below it.
    for bed_id, top, base in reversed(stack.beds_between(-high, -low, order, seed_text)):
        bottom, thickness = -base, base - top
        middle = bottom + 0.5 * thickness
        inherited = None
        if coarser_tops is not None and middle >= float(coarser["beds"][0][0]):
            index = int(np.searchsorted(coarser_tops, middle, side="right"))
            if index < len(coarser_rocks):
                inherited = coarser_rocks[index][0]
        material = (bed_rocks or {}).get(int(bed_id))
        if material not in by_material:
            material = stack.bed_rock(bed_id, order, shares, seed_text, coarser_rock=inherited, order_gap=gap)
        rock = by_material.get(material)
        if rock is None:
            rock = coarser_rocks[index]
        beds.append((bottom, thickness, rock[0], rock[2], rock[3]))
    return beds


# --- the record a level keeps ---------------------------------------------------


def coarse_grid(values, cells, digits=3):
    """``values`` sampled on about ``cells`` x ``cells`` nodes (a record's compact raster)."""
    height, width = values.shape
    rows = np.unique(np.linspace(0, height - 1, min(cells + 1, height)).round().astype(int))
    columns = np.unique(np.linspace(0, width - 1, min(cells + 1, width)).round().astype(int))
    return np.round(values[np.ix_(rows, columns)], digits).tolist()


def sample_coarse(grid, fraction_u, fraction_v):
    """Bilinear sample of a coarse record grid at tile fractions (clamped)."""
    values = np.asarray(grid, dtype=np.float64)
    x = np.clip(fraction_u, 0.0, 1.0) * (values.shape[1] - 1)
    y = np.clip(fraction_v, 0.0, 1.0) * (values.shape[0] - 1)
    x0 = np.clip(np.floor(x).astype(int), 0, max(0, values.shape[1] - 2))
    y0 = np.clip(np.floor(y).astype(int), 0, max(0, values.shape[0] - 2))
    x1 = np.minimum(x0 + 1, values.shape[1] - 1)
    y1 = np.minimum(y0 + 1, values.shape[0] - 1)
    fx, fy = x - x0, y - y0
    return (values[y0, x0] * (1 - fx) + values[y0, x1] * fx) * (1 - fy) + (values[y1, x0] * (1 - fx) + values[y1, x1] * fx) * fy


def dip_offset(strata, u, v):
    """Height of the stack's reference horizon at ``u, v`` (the record's structure grid, clamped to its bounds)."""
    b = strata["uv_bounds"]
    fraction_u = (np.asarray(u, dtype=np.float64) - b["min_u"]) / max(1e-12, b["max_u"] - b["min_u"])
    fraction_v = (np.asarray(v, dtype=np.float64) - b["min_v"]) / max(1e-12, b["max_v"] - b["min_v"])
    return sample_coarse(strata["structure"], fraction_u, fraction_v)


def record_fields(strata, u, v):
    """Dip offset, remap weight and profile slope of an order's record at ``u, v``."""
    b = strata["uv_bounds"]
    fraction_u = (u - b["min_u"]) / max(1e-12, b["max_u"] - b["min_u"])
    fraction_v = (v - b["min_v"]) / max(1e-12, b["max_v"] - b["min_v"])
    inside = (fraction_u >= 0.0) & (fraction_u <= 1.0) & (fraction_v >= 0.0) & (fraction_v <= 1.0)
    weight = np.where(inside, sample_coarse(strata["weight"], fraction_u, fraction_v), 0.0)
    slope = sample_coarse(strata["slope"], fraction_u, fraction_v)
    return dip_offset(strata, u, v), np.clip(weight, 0.0, 1.0), slope


def heightmap_orders(heightmap):
    """The bed orders a level built or stepped again, coarsest first (``[]`` without any)."""
    orders = []
    for landform in (((heightmap or {}).get("regional_landforms") or {}).get("landforms") or []):
        if not isinstance(landform, dict) or landform.get("landform") != LANDFORM_ID:
            continue
        strata = landform.get("strata") or {}
        if strata.get("model") == MODEL and strata.get("uv_bounds"):
            orders.append(strata)
    return sorted(orders, key=lambda strata: int(strata.get("built_at_level", 0)))


def _uv_grids(bounds, shape):
    height, width = shape
    u = (bounds["min_u"] + (bounds["max_u"] - bounds["min_u"]) * np.arange(width)[None, :] / max(1, width - 1)) * np.ones((height, 1))
    v = (bounds["min_v"] + (bounds["max_v"] - bounds["min_v"]) * np.arange(height)[:, None] / max(1, height - 1)) * np.ones((1, width))
    return u, v


def build_order(
    elevation, land, *, level, layered, layered_share, aridity, seed_text, bounds, dx, dy, parent_spacing_m,
    weight=None, coarser=None, regolith_depth_m=0.0, structure=None, bed_rocks=None,
):
    """The scarps of the bed order ``level`` resolves, as a height change.

    ``elevation`` is the ground they are cut into (with every coarser order
    already stepped), ``layered`` its rocks (``bed_sequence``), ``weight``
    where the sequence may show (0..1: shore, tile rim, lava cones),
    ``coarser`` the record of the next coarser order (its rocks are kept),
    ``structure`` the height of the planet stack's reference horizon on this
    grid (``strata.reference_horizon``; flat without it) and ``seed_text``
    the planet's stack seed.  Returns ``(residual, strata)``, or
    ``(None, None)`` where this level builds none.
    """
    if int(level) not in BED_ORDER or not layered or not land.any():
        return None, None
    from simulations.world_gen.material_routing import gaussian_blur

    u, v = _uv_grids(bounds, elevation.shape)
    frame = {
        "uv_bounds": {key: float(bounds[key]) for key in ("min_u", "max_u", "min_v", "max_v")},
        "structure": coarse_grid(
            np.zeros(elevation.shape) if structure is None else np.asarray(structure, dtype=np.float64),
            STRUCTURE_RECORD_CELLS, digits=2,
        ),
    }
    dip = dip_offset(frame, u, v)
    relative = gaussian_blur(elevation - dip, SMOOTHING_CELLS)
    low = float(relative[land].min())
    high = float(relative[land].max())
    beds = bed_sequence(seed_text, level, low, high, layered, coarser=coarser, bed_rocks=bed_rocks)
    exposure, rampart = climate_parameters(aridity)
    slope_y, slope_x = np.gradient(relative, dy, dx)
    slope_grid = coarse_grid(gaussian_blur(np.hypot(slope_x, slope_y), SLOPE_SMOOTHING_CELLS), SLOPE_RECORD_CELLS, digits=5)
    blend = min(1.0, (layered_share - MIN_LAYERED_SHARE) / 0.3)
    applies = np.full(elevation.shape, blend) if weight is None else np.asarray(weight, dtype=np.float64) * blend
    strata = {
        "model": MODEL,
        "built_at_level": int(level),
        "bed_order": int(BED_ORDER[int(level)]),
        "parent_spacing_m": round(float(parent_spacing_m or 0.0), 4),
        "regolith_depth_m": round(float(regolith_depth_m or 0.0), 3),
        "exposure": round(exposure, 4), "rampart_gradient": round(rampart, 4), "talus_gradient": TALUS_GRADIENT,
        # [base, thickness, erodibility, slope resistance] and the rock of each bed.
        "beds": [[round(bed[0], 4), round(bed[1], 4), round(bed[3], 4), round(bed[4], 4)] for bed in beds],
        "bed_materials": [bed[2] for bed in beds],
        **frame,
        "weight": coarse_grid(applies, WEIGHT_RECORD_CELLS),
        "slope": slope_grid,
    }
    transfer = scarp_transfer(strata)
    # Stepped with the record's own grids, so a finer level that reads the
    # record undoes exactly this.
    _dip, recorded_weight, slope = record_fields(strata, u, v)
    residual = np.where(land, step(relative, recorded_weight, slope, transfer) - relative, 0.0)
    return residual, strata


def restep(parent_heightmap, u, v, inherited, level, with_steps=False):
    """Height change that keeps the parent's scarps sharp at this level.

    A child that only interpolates a stepped surface smears every cliff over
    a parent cell: a 100 m cliff became a 12-degree ramp one level down.
    Here the smooth surface behind the parent's steps is recovered at the
    parent's cells (``unstep``, finest order first), interpolated to this
    grid and stepped again, so a face stands at its own angle as soon as the
    cells resolve it while every parent cell keeps its height.  Returns
    ``(change, orders)``; ``(None, [])`` when the parent has no order young
    enough to need it.  ``with_steps`` adds a third value: per order, the
    height its scarps add to the ground they are cut into at this grid
    (what ``build_order`` returned at the level that built it), which is
    what ``scarp_canyons`` cuts back from.
    """
    orders = [
        strata for strata in heightmap_orders(parent_heightmap)
        if int(level) - int(strata.get("built_at_level", 0)) <= RESTEP_LEVELS
    ]
    rows = (((parent_heightmap or {}).get("sample_grid") or {}).get("rows")) or []
    bounds = (parent_heightmap or {}).get("source_uv_bounds") or {}
    if not orders or not rows or not bounds:
        return (None, [], []) if with_steps else (None, [])
    from simulations.world_gen.regional_refinement import _sample_bicubic_grid

    smooth_parent = np.asarray(rows, dtype=np.float64)
    parent_u, parent_v = _uv_grids(bounds, smooth_parent.shape)
    transfers = [scarp_transfer(strata) for strata in orders]
    for strata, transfer in zip(reversed(orders), reversed(transfers)):
        dip, weight, slope = record_fields(strata, parent_u, parent_v)
        smooth_parent = unstep(smooth_parent - dip, weight, slope, transfer) + dip
    local_u = (u - bounds["min_u"]) / max(1e-12, bounds["max_u"] - bounds["min_u"])
    local_v = (v - bounds["min_v"]) / max(1e-12, bounds["max_v"] - bounds["min_v"])
    surface = _sample_bicubic_grid(smooth_parent, local_u, local_v, wrap_x=False)
    # Child cells per parent cell.
    cells = max(1.0, (surface.shape[1] - 1) / max(1e-12, (float(local_u[0, -1]) - float(local_u[0, 0])) * (smooth_parent.shape[1] - 1)))
    near_face = np.zeros(surface.shape)
    steps = []
    for strata, transfer in zip(orders, transfers):
        dip, weight, slope = record_fields(strata, u, v)
        smooth = surface - dip
        fall_y, fall_x = np.gradient(smooth)
        reach = 0.5 * cells * np.hypot(fall_x, fall_y)
        face_in_reach = part_lengths(smooth + reach, slope, transfer)[FACE] - part_lengths(smooth - reach, slope, transfer)[FACE]
        near_face = np.maximum(near_face, (face_in_reach > 0.0) & (weight * run_gate(smooth, slope, transfer) > 0.0))
        stepped = step(smooth, weight, slope, transfer)
        steps.append(stepped - smooth)
        surface = stepped + dip
    # Only a face is sharpened.  Between two parent cells the remap has the
    # gains of the slope the order was laid out for; relief the parent added
    # since (a valley side through a rampart) would be multiplied by them,
    # and weak rock stood up as a wall.  Away from faces the child keeps the
    # parent's own slopes.
    from simulations.world_gen.material_routing import gaussian_blur

    sharpened = np.clip(2.0 * gaussian_blur(near_face.astype(np.float64), 0.5 * cells), 0.0, 1.0)
    change = (surface - inherited) * sharpened
    return (change, orders, steps) if with_steps else (change, orders)


def _strength_parts(surface, orders, u, v):
    """Per order, finest first: where it shows, what its beds hold, and how its bed heights sit to the ground's."""
    from simulations.world_gen.material_routing import REPOSE_GRADIENT

    parts = []
    ground = surface
    for strata in reversed(orders):
        transfer = scarp_transfer(strata)
        dip, weight, slope = record_fields(strata, u, v)
        smooth = unstep(surface - dip, weight, slope, transfer)
        real = remap(smooth, slope, transfer)
        faces = np.asarray([face_gradient(_bed_resistance(bed)) for bed in strata.get("beds") or []] + [0.0]) * FAILURE_MARGIN
        parts.append({
            "strata": strata, "shows": weight * run_gate(smooth, slope, transfer) > 0.5, "faces": faces,
            "weak": max(REPOSE_GRADIENT, float(strata.get("rampart_gradient", RAMPART_GRADIENT[1])) * FAILURE_MARGIN),
            # Height in the order's beds = ground + this (the dip, and what finer orders and a partial weight add).
            "offset": real - ground,
        })
        surface = smooth + dip
    return parts


def _limit_of(ground, parts):
    limit = np.full(ground.shape, np.inf)
    for part in parts:
        held = part["faces"][bed_at(ground + part["offset"], part["strata"])]
        limit = np.where(np.isinf(limit) & part["shows"], np.where(held > 0.0, held, part["weak"]), limit)
    return limit


def strength_limit(surface, orders, u, v):
    """Steepest gradient the rock at the surface holds before it fails (``inf`` where no order shows).

    A strong bed fails a little beyond its face gradient; a weak one beyond
    the repose of its own debris.  Both stand above what the profile is
    laid out at, so ground the profile shaped is left as it is and only
    what later relief over-steepened comes down.
    """
    surface = np.asarray(surface, dtype=np.float64)
    return _limit_of(surface, _strength_parts(surface, orders, u, v))


def relax_to_strength(surface, limit, dx, dy, iterations=None, held=None, reread=None):
    """Rockfall: ground steeper than its rock holds fails until it stands at that angle.

    Each pass moves an eighth of the excess drop between a cell and each of
    its eight neighbours from the upper to the lower one (the upper cell's
    rock decides), so volume is kept: what breaks off a brink lies at the
    foot.  Threshold slopes in the sense of Carson & Kirkby (1972).
    ``held`` (bool) are cells a stream keeps clear: what falls into them is
    carried off, so a canyon floor stays where it was cut.  ``reread``
    (ground -> limit) gives the limits again every ``RELAX_REREAD_PASSES``
    passes, for rock that changes with the height of the ground.
    """
    if not np.isfinite(limit).any():
        return surface
    ground = np.array(surface, dtype=np.float64)
    kept = None if held is None else ground[held]
    diagonal = math.hypot(dx, dy)
    whole, head, tail = slice(None), slice(None, -1), slice(1, None)
    pairs = (
        ((head, whole), (tail, whole), dy),
        ((whole, head), (whole, tail), dx),
        ((head, head), (tail, tail), diagonal),
        ((head, tail), (tail, head), diagonal),
    )

    def held_drops(limits):
        # Per pair: the drop each of its two cells holds towards the other.
        return [(limits[first] * distance, limits[second] * distance) for first, second, distance in pairs]

    drops = held_drops(limit)
    change = np.empty(ground.shape)
    # One pass allocates nothing: a relaxation of a tall wall takes thousands.
    work = [(np.empty(ground[first].shape), np.empty(ground[first].shape)) for first, _second, _distance in pairs]
    tolerance = RELAX_TOLERANCE_CELLS * min(dx, dy)
    for iteration in range(RELAX_ITERATIONS if iterations is None else iterations):
        if reread is not None and iteration and iteration % RELAX_REREAD_PASSES == 0:
            limit = reread(ground)
            drops = held_drops(limit)
        change.fill(0.0)
        for (first, second, _distance), (down, up), (flow, back) in zip(pairs, drops, work):
            np.subtract(ground[first], ground[second], out=flow)
            np.add(flow, up, out=back)
            np.negative(back, out=back)
            np.maximum(back, 0.0, out=back)
            np.subtract(flow, down, out=flow)
            np.maximum(flow, 0.0, out=flow)
            np.subtract(flow, back, out=flow)
            flow *= 0.125
            change[first] -= flow
            change[second] += flow
        ground += change
        if held is not None:
            change[held] = 0.0
            ground[held] = kept
        if max(float(change.max()), -float(change.min())) < tolerance:
            if reread is None:
                break
            fresh = reread(ground)
            if np.array_equal(fresh, limit):
                break
            limit = fresh
            drops = held_drops(limit)
    return ground


def rockfall(surface, orders, u, v, dx, dy, held=None, also=None):
    """``surface`` after everything steeper than its rock holds has failed.

    ``relax_to_strength`` with the limits of ``strength_limit``, read again
    as the ground moves: the rock a slope stands in changes as it lies
    back.  A canyon wall is cut through the cap at first; as it retreats it
    comes to stand in the weak bed under the cap, which holds far less.
    What has moved is then spread sideways by about a cell, as debris
    spreads when it settles, and relaxed once more.  ``held`` as in
    ``relax_to_strength``.  ``also`` (ground -> limit, ``inf`` where it has
    nothing to say) gives limits where no order shows: a sea cliff stands
    in rock whose scarps are not drawn that close to the sea.
    """
    ground = np.asarray(surface, dtype=np.float64)
    # Where each order shows is read once; which of its beds a cell stands
    # in follows the cell's height.
    parts = _strength_parts(ground, orders, u, v)

    def limit_at(current):
        limit = _limit_of(current, parts)
        return limit if also is None else np.where(np.isinf(limit), also(current), limit)

    rested = relax_to_strength(ground, limit_at(ground), dx, dy, iterations=ROCKFALL_PASSES, held=held, reread=limit_at)
    from simulations.world_gen.material_routing import gaussian_blur

    moved = rested - ground
    if held is None:
        spread = ground + gaussian_blur(moved, ROCKFALL_SPREAD_CELLS)
    else:
        # A floor a stream keeps clear takes no part: it neither moves nor
        # holds back the wall beside it.
        free = (~np.asarray(held, dtype=bool)).astype(np.float64)
        share = gaussian_blur(free, ROCKFALL_SPREAD_CELLS)
        spread = ground + gaussian_blur(moved * free, ROCKFALL_SPREAD_CELLS) / np.maximum(share, 1e-6)
        spread = np.where(free > 0.0, spread, ground)
    # The spread rounds off what the fall had trimmed to the cell; what that
    # leaves steeper than its rock holds fails once more.
    return relax_to_strength(spread, limit_at(spread), dx, dy, held=held, reread=limit_at)


def shares_the_fall_allows(shares, gradient):
    """Face, talus and rampart shares no larger than a cell's own fall allows.

    A part that fills a share of a cell makes the cell fall at least that
    share of the part's own gradient (a face is 40 degrees or steeper).  The
    profile names parts by height; where rockfall has laid the ground back,
    or a canyon has cut a floor at a face's level, and at fine levels where
    undoing the finer orders exaggerates the ground's ripples, the height
    alone says face.
    """
    least = {"face": math.tan(math.radians(FACE_MIN_ANGLE_DEG)), "talus": TALUS_GRADIENT, "rampart": RAMPART_GRADIENT[0]}
    return {name: np.minimum(shares[name], np.asarray(gradient, dtype=np.float64) / steepness) for name, steepness in least.items()}


def heightmap_scarp_fields(heightmap, shape=None):
    """Where a level's ground is rock face, talus or rampart, and which rock its beds are.

    ``None`` without a bed sequence.  Otherwise ``[H, W]`` arrays on the
    heightfield's lattice (or resampled to ``shape``): ``face`` / ``talus`` /
    ``rampart`` (the share of each cell a scarp of any order puts under that
    part, 0..1), ``height_above_foot_m`` on faces, and ``rock`` (index into
    ``rock_materials`` of the bed at the surface, -1 where no order shows).
    A cell wider than a face holds the face's share of its width; flat
    ground that merely lies at a strong bed's level (a strath, a stripped
    bench) is that bed's rock but no face; a part cannot fill more of a
    cell than the cell's own fall allows (ground that rockfall or a canyon
    has left gentle at a face's level is no face either); and any part of a
    scarp that the finer relief of this level has tipped steeper than debris
    can lie on is face too, whatever the profile called it.  Every layer
    reads the scarps from here, so height, rock, soil and colour agree on
    where a cliff is.
    """
    orders = heightmap_orders(heightmap)
    rows = ((heightmap or {}).get("sample_grid") or {}).get("rows") or []
    bounds = (heightmap or {}).get("source_uv_bounds") or {}
    if not orders or not rows or not bounds:
        return None
    surface = np.asarray(rows, dtype=np.float64)
    spacing_x = float((heightmap or {}).get("sample_spacing_x_m") or 0.0)
    spacing_y = float((heightmap or {}).get("sample_spacing_y_m") or 0.0)
    if shape is not None and tuple(shape) != surface.shape:
        height, width = shape
        spacing_x *= (surface.shape[1] - 1) / max(1, width - 1)
        spacing_y *= (surface.shape[0] - 1) / max(1, height - 1)
        fraction_u = (np.arange(width)[None, :] / max(1, width - 1)) * np.ones((height, 1))
        fraction_v = (np.arange(height)[:, None] / max(1, height - 1)) * np.ones((1, width))
        surface = sample_coarse(surface, fraction_u, fraction_v)
    u, v = _uv_grids(bounds, surface.shape)
    fields = {name: np.zeros(surface.shape) for name in ("face", "talus", "rampart", "height_above_foot_m")}
    materials = sorted({material for strata in orders for material in strata.get("bed_materials") or []})
    position = {material: index for index, material in enumerate(materials)}
    rock = np.full(surface.shape, -1, dtype=np.int64)
    steep = np.zeros(surface.shape)
    gradient = None
    if spacing_x > 0.0 and spacing_y > 0.0:
        from simulations.world_gen.material_routing import CLIFF_GRADIENT, REPOSE_GRADIENT

        ground_y, ground_x = np.gradient(surface, spacing_y, spacing_x)
        gradient = np.hypot(ground_x, ground_y)
        steep = _smooth01((gradient - REPOSE_GRADIENT) / (CLIFF_GRADIENT - REPOSE_GRADIENT))
    in_scarp = np.zeros(surface.shape)
    # Finest order first: each is undone to reach the surface the next coarser stepped.
    for strata in reversed(orders):
        transfer = scarp_transfer(strata)
        dip, weight, slope = record_fields(strata, u, v)
        smooth = unstep(surface - dip, weight, slope, transfer)
        real = remap(smooth, slope, transfer)
        applies = weight * run_gate(smooth, slope, transfer)
        part = profile_part(real, transfer)
        if spacing_x > 0.0 and spacing_y > 0.0:
            # The profile was laid out for the record's slope; it is a scarp
            # only where the ground really falls across it.
            fall_y, fall_x = np.gradient(smooth, spacing_y, spacing_x)
            fall = np.hypot(fall_x, fall_y)
            realised = applies * _smooth01((fall / np.maximum(slope, 1e-9) - REALISED_SLOPE_SHARE[0]) / (REALISED_SLOPE_SHARE[1] - REALISED_SLOPE_SHARE[0]))
            half = 0.5 * fall * max(spacing_x, spacing_y)
            below, above = part_lengths(smooth - half, slope, transfer), part_lengths(smooth + half, slope, transfer)
        else:
            realised, half, below, above = applies, None, None, None
        for kind, name in ((FACE, "face"), (TALUS, "talus"), (RAMPART, "rampart")):
            share = (part == kind).astype(np.float64)
            if half is not None:
                share = np.where(half > 1e-9, np.clip((above[kind] - below[kind]) / np.maximum(2.0 * half, 1e-12), 0.0, 1.0), share)
            fields[name] = np.maximum(fields[name], share * realised)
        in_scarp = np.maximum(in_scarp, np.where(part != BENCH, realised, 0.0))
        breaks = transfer["real"]
        interval = np.clip(np.searchsorted(breaks, real, side="right") - 1, 0, max(0, breaks.size - 2))
        fields["height_above_foot_m"] = np.maximum(
            fields["height_above_foot_m"], np.where((part == FACE) & (realised > 0.5), real - breaks[interval], 0.0))
        of_bed = np.asarray([position[material] for material in strata.get("bed_materials") or []] + [-1], dtype=np.int64)
        rock = np.where((rock < 0) & (applies > 0.5), of_bed[bed_at(real, strata)], rock)
        surface = smooth + dip
    if gradient is not None:
        fields.update(shares_the_fall_allows(fields, gradient))
    # Debris does not lie on ground steeper than its repose: there the scarp
    # is rock face, also in its rampart or its banked foot.
    cliffed = steep * in_scarp
    fields["face"] = np.maximum(fields["face"], cliffed)
    fields["talus"] = fields["talus"] * (1.0 - cliffed)
    fields["rampart"] = fields["rampart"] * (1.0 - cliffed)
    return {
        **fields, "rock": rock, "rock_materials": materials,
        "orders": [int(strata.get("built_at_level", 0)) for strata in orders],
    }
