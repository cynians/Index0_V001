"""Continuous physical-coordinate noise for persistent geological detail."""

import math
from functools import lru_cache

from simulations.world_gen.map_seed import seed_range


def _fade(value):
    """Quintic interpolation with continuous first and second derivatives."""
    value = max(0.0, min(1.0, float(value)))
    return value * value * value * (value * (value * 6.0 - 15.0) + 10.0)


def _lerp(a, b, amount):
    return float(a) + (float(b) - float(a)) * float(amount)


@lru_cache(maxsize=120_000)
def _gradient(seed, key, cell_x, cell_y, periodic_cells_x):
    if periodic_cells_x > 0:
        cell_x %= periodic_cells_x
    angle = seed_range(
        str(seed or ""),
        f"geological-gradient:{key}:{cell_x}:{cell_y}:{periodic_cells_x}",
        0.0,
        math.tau,
    )
    return math.cos(angle), math.sin(angle)


def gradient_noise_m(seed, key, x_m, y_m, wavelength_m, *, period_x_m=None):
    """Sample seamless 2-D gradient noise using physical coordinates."""
    wavelength = max(0.01, float(wavelength_m))
    gx, gy = float(x_m) / wavelength, float(y_m) / wavelength
    x0, y0 = math.floor(gx), math.floor(gy)
    tx, ty = gx - x0, gy - y0
    periodic_cells = 0
    if period_x_m is not None and float(period_x_m) > 0.0:
        periodic_cells = max(1, int(round(float(period_x_m) / wavelength)))

    def dot(ix, iy, dx, dy):
        grad_x, grad_y = _gradient(str(seed or ""), str(key or ""), int(ix), int(iy), periodic_cells)
        return grad_x * dx + grad_y * dy

    n00 = dot(x0, y0, tx, ty)
    n10 = dot(x0 + 1, y0, tx - 1.0, ty)
    n01 = dot(x0, y0 + 1, tx, ty - 1.0)
    n11 = dot(x0 + 1, y0 + 1, tx - 1.0, ty - 1.0)
    value = _lerp(_lerp(n00, n10, _fade(tx)), _lerp(n01, n11, _fade(tx)), _fade(ty))
    return max(-1.0, min(1.0, value * 1.55))


def fractal_noise_m(
    seed,
    key,
    x_m,
    y_m,
    wavelength_m,
    *,
    octaves=4,
    lacunarity=2.03,
    gain=0.5,
    period_x_m=None,
):
    total = 0.0
    amplitude = 1.0
    amplitude_sum = 0.0
    wavelength = max(0.01, float(wavelength_m))
    for octave in range(max(1, int(octaves))):
        total += gradient_noise_m(
            seed,
            f"{key}:octave_{octave}",
            x_m,
            y_m,
            wavelength,
            period_x_m=period_x_m,
        ) * amplitude
        amplitude_sum += amplitude
        wavelength /= max(1.01, float(lacunarity))
        amplitude *= float(gain)
    return max(-1.0, min(1.0, total / max(1e-9, amplitude_sum)))


def warped_fold_relief_m(
    seed,
    key,
    x_m,
    y_m,
    wavelength_m,
    strike_radians,
    *,
    period_x_m=None,
):
    """Return a centred fold-and-thrust relief signal in [-1, 1]."""
    cs, sn = math.cos(strike_radians), math.sin(strike_radians)
    along = float(x_m) * cs + float(y_m) * sn
    across = -float(x_m) * sn + float(y_m) * cs
    wavelength = max(1.0, float(wavelength_m))
    warp = fractal_noise_m(
        seed,
        f"{key}:warp",
        x_m,
        y_m,
        wavelength * 2.4,
        octaves=3,
        gain=0.52,
        period_x_m=period_x_m,
    )
    along_warp = fractal_noise_m(
        seed,
        f"{key}:along",
        x_m,
        y_m,
        wavelength * 1.15,
        octaves=3,
        gain=0.48,
        period_x_m=period_x_m,
    )
    phase = math.tau * (across / wavelength + warp * 0.28)
    primary = (1.0 - abs(math.sin(phase))) ** 2.2
    secondary = (1.0 - abs(math.sin(phase * 0.53 + warp * 1.7))) ** 2.6
    ridge = primary * 0.68 + secondary * 0.32
    modulation = 0.68 + 0.32 * (along_warp * 0.5 + 0.5)
    # The analytical mean of these sharpened folds is about 0.30.  Centring
    # prevents refinement from raising an entire mountain window.
    return max(-1.0, min(1.0, (ridge * modulation - 0.30) * 1.72))


def branching_mountain_relief_m(
    seed,
    key,
    x_m,
    y_m,
    wavelength_m,
    *,
    period_x_m=None,
):
    """Return a branching ridge/valley network rather than parallel bands.

    Mountain crests follow warped zero contours of two independent continuous
    geological fields. Their intersections, bifurcations and interruptions
    form linked massifs and passes without imposing a repeated sine pattern.
    """
    wavelength = max(1.0, float(wavelength_m))
    warp_x = fractal_noise_m(
        seed, f"{key}:warp-x", x_m, y_m, wavelength * 2.8,
        octaves=3, gain=0.52, period_x_m=period_x_m,
    ) * wavelength * 0.42
    warp_y = fractal_noise_m(
        seed, f"{key}:warp-y", x_m, y_m, wavelength * 3.1,
        octaves=3, gain=0.52, period_x_m=period_x_m,
    ) * wavelength * 0.42
    warped_x, warped_y = float(x_m) + warp_x, float(y_m) + warp_y
    primary = fractal_noise_m(
        seed, f"{key}:primary", warped_x, warped_y, wavelength,
        octaves=4, lacunarity=2.07, gain=0.52, period_x_m=period_x_m,
    )
    secondary = fractal_noise_m(
        seed, f"{key}:secondary",
        warped_x + wavelength * 0.37,
        warped_y - wavelength * 0.23,
        wavelength * 0.63,
        octaves=3, lacunarity=2.13, gain=0.47, period_x_m=period_x_m,
    )
    structure = primary * 0.78 + secondary * 0.22
    ridge = max(0.0, 1.0 - abs(structure) * 2.75) ** 2.7
    massif = fractal_noise_m(
        seed, f"{key}:massif", x_m, y_m, wavelength * 4.6,
        octaves=3, gain=0.50, period_x_m=period_x_m,
    ) * 0.5 + 0.5
    drainage_cut = max(0.0, -fractal_noise_m(
        seed, f"{key}:valley", warped_x, warped_y, wavelength * 0.48,
        octaves=3, gain=0.46, period_x_m=period_x_m,
    )) ** 1.7
    relief = ridge * (0.52 + massif * 0.48) - 0.22 - drainage_cut * 0.18
    return max(-1.0, min(1.0, relief * 1.62))


# --- Array forms -----------------------------------------------------------
# Identical lattice gradients (the cached scalar hash above) evaluated once per
# unique lattice cell, then interpolated for whole coordinate arrays.

try:
    import numpy as np
except ImportError:  # pragma: no cover - minimal installs use the scalar path
    np = None


_PACK_STRIDE = 4_294_967_311  # > 2**32, so an offset y fits below it
_PACK_OFFSET = 2_147_483_648  # makes |cell_y| < 2**31 non-negative


def _gradient_arrays(seed, key, cell_x, cell_y, periodic_cells):
    packed = cell_x.astype(np.int64) * _PACK_STRIDE + (cell_y.astype(np.int64) + _PACK_OFFSET)
    unique, inverse = np.unique(packed, return_inverse=True)
    grad_x = np.empty(unique.size, dtype=np.float64)
    grad_y = np.empty(unique.size, dtype=np.float64)
    unique_x = np.floor_divide(unique, _PACK_STRIDE)
    unique_y = unique - unique_x * _PACK_STRIDE - _PACK_OFFSET
    seed_text = str(seed or "")
    key_text = str(key or "")
    for index, (ix, iy) in enumerate(zip(unique_x.tolist(), unique_y.tolist())):
        grad_x[index], grad_y[index] = _gradient(seed_text, key_text, int(ix), int(iy), periodic_cells)
    inverse = inverse.reshape(cell_x.shape)
    return grad_x[inverse], grad_y[inverse]


def _fade_array(values):
    values = np.clip(values, 0.0, 1.0)
    return values * values * values * (values * (values * 6.0 - 15.0) + 10.0)


def gradient_noise_grid(seed, key, x_m, y_m, wavelength_m, *, period_x_m=None):
    """Array form of ``gradient_noise_m`` (same lattice, same values)."""
    wavelength = max(0.01, float(wavelength_m))
    x_m, y_m = np.broadcast_arrays(np.asarray(x_m, dtype=np.float64), np.asarray(y_m, dtype=np.float64))
    gx = x_m / wavelength
    gy = y_m / wavelength
    x0 = np.floor(gx)
    y0 = np.floor(gy)
    tx = gx - x0
    ty = gy - y0
    periodic_cells = 0
    if period_x_m is not None and float(period_x_m) > 0.0:
        periodic_cells = max(1, int(round(float(period_x_m) / wavelength)))
    ix0 = x0.astype(np.int64)
    iy0 = y0.astype(np.int64)

    def dot(ix, iy, dx, dy):
        cell_x = ix % periodic_cells if periodic_cells > 0 else ix
        grad_x, grad_y = _gradient_arrays(seed, key, cell_x, iy, periodic_cells)
        return grad_x * dx + grad_y * dy

    n00 = dot(ix0, iy0, tx, ty)
    n10 = dot(ix0 + 1, iy0, tx - 1.0, ty)
    n01 = dot(ix0, iy0 + 1, tx, ty - 1.0)
    n11 = dot(ix0 + 1, iy0 + 1, tx - 1.0, ty - 1.0)
    fade_x = _fade_array(tx)
    fade_y = _fade_array(ty)
    top = n00 + (n10 - n00) * fade_x
    bottom = n01 + (n11 - n01) * fade_x
    value = top + (bottom - top) * fade_y
    return np.clip(value * 1.55, -1.0, 1.0)


def fractal_noise_grid(
    seed,
    key,
    x_m,
    y_m,
    wavelength_m,
    *,
    octaves=4,
    lacunarity=2.03,
    gain=0.5,
    period_x_m=None,
):
    """Array form of ``fractal_noise_m``."""
    total = 0.0
    amplitude = 1.0
    amplitude_sum = 0.0
    wavelength = max(0.01, float(wavelength_m))
    for octave in range(max(1, int(octaves))):
        total = total + gradient_noise_grid(
            seed, f"{key}:octave_{octave}", x_m, y_m, wavelength, period_x_m=period_x_m,
        ) * amplitude
        amplitude_sum += amplitude
        wavelength /= max(1.01, float(lacunarity))
        amplitude *= float(gain)
    return np.clip(total / max(1e-9, amplitude_sum), -1.0, 1.0)


def branching_mountain_relief_grid(seed, key, x_m, y_m, wavelength_m, *, period_x_m=None):
    """Array form of ``branching_mountain_relief_m``."""
    wavelength = max(1.0, float(wavelength_m))
    x_m = np.asarray(x_m, dtype=np.float64)
    y_m = np.asarray(y_m, dtype=np.float64)
    warp_x = fractal_noise_grid(
        seed, f"{key}:warp-x", x_m, y_m, wavelength * 2.8,
        octaves=3, gain=0.52, period_x_m=period_x_m,
    ) * wavelength * 0.42
    warp_y = fractal_noise_grid(
        seed, f"{key}:warp-y", x_m, y_m, wavelength * 3.1,
        octaves=3, gain=0.52, period_x_m=period_x_m,
    ) * wavelength * 0.42
    warped_x = x_m + warp_x
    warped_y = y_m + warp_y
    primary = fractal_noise_grid(
        seed, f"{key}:primary", warped_x, warped_y, wavelength,
        octaves=4, lacunarity=2.07, gain=0.52, period_x_m=period_x_m,
    )
    secondary = fractal_noise_grid(
        seed, f"{key}:secondary",
        warped_x + wavelength * 0.37,
        warped_y - wavelength * 0.23,
        wavelength * 0.63,
        octaves=3, lacunarity=2.13, gain=0.47, period_x_m=period_x_m,
    )
    structure = primary * 0.78 + secondary * 0.22
    ridge = np.maximum(0.0, 1.0 - np.abs(structure) * 2.75) ** 2.7
    massif = fractal_noise_grid(
        seed, f"{key}:massif", x_m, y_m, wavelength * 4.6,
        octaves=3, gain=0.50, period_x_m=period_x_m,
    ) * 0.5 + 0.5
    drainage_cut = np.maximum(0.0, -fractal_noise_grid(
        seed, f"{key}:valley", warped_x, warped_y, wavelength * 0.48,
        octaves=3, gain=0.46, period_x_m=period_x_m,
    )) ** 1.7
    relief = ridge * (0.52 + massif * 0.48) - 0.22 - drainage_cut * 0.18
    return np.clip(relief * 1.62, -1.0, 1.0)
