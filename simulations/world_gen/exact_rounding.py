"""Python-compatible decimal rounding for NumPy grids.

World-generation products store rounded floats in nested lists.  Calling the
builtin ``round`` once per cell dominated several vectorised solvers, while
``numpy.round`` differs from it near decimal ties.  ``round_rows`` rounds in
NumPy and hands only the near-tie cells back to the builtin, so the result is
identical to ``[[round(v, digits) for v in row] for row in values]``.
"""

import numpy as np

# |scaled| below this keeps the float64 error of ``value * 10**digits`` far
# under the tie margin (half an ulp at 1e9 is ~6e-8).
_SAFE_SCALED_MAGNITUDE = 1.0e9
_TIE_MARGIN = 1.0e-6


def round_rows(values, digits):
    """Rows of ``round(value, digits)`` for a 2-D float array."""
    values = np.asarray(values, dtype=np.float64)
    scale = 10.0 ** int(digits)
    scaled = values * scale
    rounded = np.rint(scaled) / scale
    with np.errstate(invalid="ignore"):
        fraction = np.abs(scaled - np.trunc(scaled))
        ambiguous = (
            (np.abs(fraction - 0.5) < _TIE_MARGIN)
            | ~np.isfinite(scaled)
            | (np.abs(scaled) >= _SAFE_SCALED_MAGNITUDE)
        )
    rows = rounded.tolist()
    if ambiguous.any():
        for y, x in zip(*np.nonzero(ambiguous)):
            rows[y][x] = round(float(values[y, x]), digits)
    return rows


def height_decimals(spacing_m):
    """Decimals a heightfield of this sample spacing is stored with.

    Centimetres down to Site scale.  At a metre and below, the relief a level
    adds is itself centimetres; rounded to them a gentle slope becomes a
    staircase of level treads one centimetre apart, which shows as contour
    rings in every hillshade and as steps in everything read from height above
    water.
    """
    spacing_m = float(spacing_m or 0.0)
    return 2 if spacing_m <= 0.0 or spacing_m >= 2.0 else 4
