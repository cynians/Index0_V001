"""How often a river covers the ground beside it, and how often it reworks it (LOD4+).

A carved channel (``alluvial_channels``) is sized at bankfull and drawn at its
mean-flow stage.  Between and above those two stands everything a flood
does, and it follows from the same section:

* how often.  The bankfull flow returns about every year and a half (median
  1.5 years, range 1 to 4 and more: Dunne & Leopold 1978; Williams 1978).
  Flood peaks arrive like a Poisson process, their excess over a threshold
  exponentially spread (Todorovic & Zelenhasic 1970; the annual maxima are
  then Gumbel's), so ``Q_T / Q_bf = 1 + g ln(T / T_bf)`` and the same line
  read below bankfull gives the freshets of a year.  The growth ``g`` is
  steeper the drier the climate (regional growth curves steepen with
  aridity); it is tied here to the flashiness the channel was sized with
  (bankfull 3 to 10 times the mean flow).
* how high.  Within the banks depth goes with discharge to the power 0.4
  (Leopold & Maddock 1953), the exponent the mean-flow stage is drawn with.
  Over the banks the plain carries the excess as a wide, rough second
  channel (Manning's formula on both, the divided-channel method):
  ``rise / D = ((Q / Q_bf - 1) (W_c / W_f) (n_f / n_c)) ^ (3/5)``.
* what it does.  A flood covers a cell when its stage reaches it.  It
  reworks a surface (moves its sediment, and with it whatever stands on it)
  when the water over it is deep enough.  A gravel bed moves at about
  bankfull: bankfull stress is about 1.2 times the stress that starts it
  (Parker 1978).  A bar's surface is built of the finer part of the load and
  a plant is lost with a few centimetres of scour (Wintenberger et al. 2019
  find erosion and burial behind half the deaths of poplar seedlings on Loire
  bars), so less water does it: ``REWORKING_DEPTH_SHARE`` of the bankfull
  depth.  That share is this module's reading, not a measured figure.  With
  it a bar at the water's edge is reworked yearly, the band Mahoney & Rood
  (1998) found cottonwoods to survive in (0.6 to 2 m above the low river)
  every few years, the bank top every few decades, a plain above it never;
  a flashy river in a dry climate reworks ground a bankfull depth above its
  banks.

Abiotic: the plain's roughness is bare ground's, and no plant holds a bar.
Not in it: levees that keep low ground behind them dry (a cell is covered
when the flood's stage at its place along the valley reaches its height),
ice jams, backwater, and the slow turning over of a plain by a migrating
channel.

Returns are in years; ``NEVER_YEARS`` stands for ground no flood reaches.
"""

from __future__ import annotations

import numpy as np

from simulations.world_gen import alluvial_channels

# The flow that fills the channel to its banks returns this often, in years.
BANKFULL_RETURN_YEARS = 1.5
# Growth of flood peaks with the logarithm of their return period, as a share of the bankfull flow: where
# the channel was sized for a humid, steady river (bankfull 3 times the mean flow) and for an arid, flashy
# one (10 times).  The hundred-year flood is then about 2.7 and 7 times the bankfull flow.
FLOOD_GROWTH = (0.4, 1.5)
# Bare floodplain against channel: Manning's n of ground in bars and swales over that of a clean bed.
OVERBANK_ROUGHNESS_RATIO = 2.0
# Width of the plain in channel widths where no relic record tells it.
DEFAULT_FLOODPLAIN_WIDTHS = 10.0
# A bar's surface is reworked when the water over it is this share of the bankfull mean depth.
REWORKING_DEPTH_SHARE = 0.4
# The deepest point of a bankfull section in mean depths, single thread and braided, as
# ``alluvial_channels.channel_fields`` draws them.
SECTION_DEPTH_MEANS = (1.5, 2.2)
# Floods are reckoned out to this many half-widths of the river's plain from its valley axis.
PLAIN_REACH = 1.5
# Returns outside this range are all the same to whoever reads them.
SHORTEST_RETURN_YEARS = 0.1
NEVER_YEARS = 999.0


def flood_growth(bankfull_to_mean):
    """Growth of flood peaks per e-fold of return period, from the channel's bankfull-to-mean flow."""
    low, high = alluvial_channels.BANKFULL_TO_MEAN_DISCHARGE
    share = np.clip((np.asarray(bankfull_to_mean, dtype=np.float64) - low) / (high - low), 0.0, 1.0)
    return FLOOD_GROWTH[0] + (FLOOD_GROWTH[1] - FLOOD_GROWTH[0]) * share


def discharge_for_stage(height_above_bank_m, section_depth_m, mean_depth_m, floodplain_widths):
    """The flow, in bankfull flows, whose stage stands this far above the bank top (below it: negative).

    ``section_depth_m`` is the deepest point of the bankfull section,
    ``mean_depth_m`` its mean depth, ``floodplain_widths`` the plain's width
    in channel widths.
    """
    height = np.asarray(height_above_bank_m, dtype=np.float64)
    section = np.maximum(np.asarray(section_depth_m, dtype=np.float64), 1e-6)
    mean = np.maximum(np.asarray(mean_depth_m, dtype=np.float64), 1e-6)
    within = np.clip((section + np.minimum(height, 0.0)) / section, 0.0, 1.0) ** (
        1.0 / alluvial_channels.AT_A_STATION_DEPTH_EXPONENT)
    over = 1.0 + (np.maximum(height, 0.0) / mean) ** (5.0 / 3.0) * np.maximum(floodplain_widths, 1.0) / OVERBANK_ROUGHNESS_RATIO
    return np.where(height <= 0.0, within, over)


def return_period_years(discharge, growth):
    """How often a flow of that many bankfull flows is exceeded, in years between."""
    exponent = np.clip((np.asarray(discharge, dtype=np.float64) - 1.0) / np.maximum(growth, 1e-6), -50.0, 50.0)
    return np.clip(BANKFULL_RETURN_YEARS * np.exp(exponent), SHORTEST_RETURN_YEARS, NEVER_YEARS)


def stage_above_bank_m(years, section_depth_m, mean_depth_m, floodplain_widths, growth):
    """Where the flood met every ``years`` stands against the bank top, in metres: the inverse of the two above."""
    discharge = np.maximum(0.0, 1.0 + growth * np.log(np.asarray(years, dtype=np.float64) / BANKFULL_RETURN_YEARS))
    section = np.asarray(section_depth_m, dtype=np.float64)
    within = section * (np.minimum(discharge, 1.0) ** alluvial_channels.AT_A_STATION_DEPTH_EXPONENT - 1.0)
    over = np.asarray(mean_depth_m, dtype=np.float64) * (
        np.maximum(discharge - 1.0, 0.0) * OVERBANK_ROUGHNESS_RATIO / np.maximum(floodplain_widths, 1.0)) ** 0.6
    return np.where(discharge <= 1.0, within, over)


def _returns(above_bank, section, mean, growth, plain_widths, reached):
    """``(covered, reworked)`` in years for ground that far above a channel's bank top."""
    def years(extra_depth):
        flow = discharge_for_stage(above_bank + extra_depth, section, mean, plain_widths)
        return np.where(reached, return_period_years(flow, growth), NEVER_YEARS)

    return years(0.0), years(REWORKING_DEPTH_SHARE * mean)


def _along_valleys(heightmap, elevation, growth):
    """Floods read along each river's valley axis (``floodplain_relics``), or ``None`` without one.

    The bank level a cell is measured against is the axis's, which runs
    smoothly down the valley.  Measured against the nearest point of the
    channel itself, the inside of every bend showed the seam between its two
    limbs as a straight edge, the river falling a metre or two round the bend.
    """
    from simulations.world_gen import floodplain_relics

    record = floodplain_relics._record(heightmap) or {}
    axes = [axis for axis in record.get("axes") or []
            if float(axis.get("width_m") or 0.0) > 0.0 and float(axis.get("depth_m") or 0.0) > 0.0]
    if not axes:
        return None
    shape = elevation.shape
    dx, dy, to_local, _to_uv = alluvial_channels.local_frame(heightmap, shape)
    covered, reworked = np.full(shape, NEVER_YEARS), np.full(shape, NEVER_YEARS)
    reached = np.zeros(shape, dtype=bool)
    widths = []
    for axis in axes:
        frame = floodplain_relics.valley_frame([axis], shape, dx=dx, dy=dy, to_local=to_local)
        mean = float(axis["depth_m"])
        section = mean * SECTION_DEPTH_MEANS[1 if axis.get("braided") else 0]
        plain_widths = max(1.0, 2.0 * float(axis["floodplain_half_width_m"]) / float(axis["width_m"]))
        within = (frame["axis"] >= 0) & (frame["reach"] <= PLAIN_REACH)
        one_covered, one_reworked = _returns(elevation - frame["bank"], section, mean, growth, plain_widths, within)
        covered, reworked = np.minimum(covered, one_covered), np.minimum(reworked, one_reworked)
        reached |= within
        widths.append(plain_widths)
    return covered, reworked, reached, float(np.median(widths)), len(axes)


def _along_channels(heightmap, elevation, growth):
    """Floods read off each carved reach on its own, for a heightmap that carries no valley axis."""
    reaches = alluvial_channels.heightmap_channel_reaches(heightmap)
    if not reaches:
        return None
    shape = elevation.shape
    dx, dy, to_local, _to_uv = alluvial_channels.local_frame(heightmap, shape)
    covered, reworked = np.full(shape, NEVER_YEARS), np.full(shape, NEVER_YEARS)
    reached = np.zeros(shape, dtype=bool)
    for reach in reaches:
        fields = alluvial_channels.channel_fields([reach], shape, dx=dx, dy=dy, to_local=to_local)
        within = np.isfinite(fields["stage_m"]) & (fields["section_depth_m"] > 0.0)
        one_covered, one_reworked = _returns(
            elevation - fields["bank"], np.where(within, fields["section_depth_m"], 1.0),
            np.where(within, fields["mean_depth_m"], 1.0), growth, DEFAULT_FLOODPLAIN_WIDTHS, within)
        covered, reworked = np.minimum(covered, one_covered), np.minimum(reworked, one_reworked)
        reached |= within
    return covered, reworked, reached, DEFAULT_FLOODPLAIN_WIDTHS, len(reaches)


def flood_fields(heightmap, elevation, *, bankfull_to_mean, water=None):
    """Per cell, the years between floods that cover it and between floods that rework it, or ``None``.

    ``None`` for a heightmap without carved channels.  Where several rivers
    reach a cell it takes the one that floods it most often.  Cells of
    ``water`` are always covered.  Also returns a summary for the level's
    model.
    """
    elevation = np.asarray(elevation, dtype=np.float64)
    growth = float(flood_growth(bankfull_to_mean))
    found = _along_valleys(heightmap, elevation, growth) or _along_channels(heightmap, elevation, growth)
    if found is None:
        return None
    covered, reworked, reached, plain_widths, rivers = found
    if water is not None:
        covered, reworked = np.where(water, 0.0, covered), np.where(water, 0.0, reworked)
    land = reached if water is None else reached & ~np.asarray(water, dtype=bool)
    everywhere = np.ones(elevation.shape, dtype=bool) if water is None else ~np.asarray(water, dtype=bool)
    count = max(1, int(everywhere.sum()))
    summary = {
        "rivers": rivers,
        "bankfull_return_years": BANKFULL_RETURN_YEARS,
        "growth_per_efold": round(growth, 3),
        "floodplain_widths": round(float(plain_widths), 2),
        "reworking_depth_share": REWORKING_DEPTH_SHARE,
        "land_covered_within_2_10_100_years": [
            round(float((land & (covered <= limit)).sum()) / count, 4) for limit in (2.0, 10.0, 100.0)],
        "land_reworked_within_2_10_100_years": [
            round(float((land & (reworked <= limit)).sum()) / count, 4) for limit in (2.0, 10.0, 100.0)],
    }
    return {"covered_years": covered, "reworked_years": reworked, "summary": summary}
