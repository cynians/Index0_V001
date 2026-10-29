"""Deterministic NumPy lattice noise for world generation.

Everything here is a pure function of integer lattice coordinates and a
seed, so the same global position produces the same value in every map that
covers it (siblings agree along shared edges, parents and children agree
wherever they sample the same coordinates).
"""

from __future__ import annotations

import hashlib

import numpy as np


_MASK64 = np.uint64(0xFFFFFFFFFFFFFFFF)


def seed_int(seed_text, salt=""):
    digest = hashlib.sha256(f"{seed_text}|{salt}".encode("utf-8")).hexdigest()
    return int(digest[:15], 16)


def hash_lattice(ix, iy, seed):
    """Return uint64 hashes for integer lattice coordinates."""
    ix, iy = np.broadcast_arrays(np.asarray(ix, dtype=np.int64), np.asarray(iy, dtype=np.int64))
    ix = ix.astype(np.uint64)
    iy = iy.astype(np.uint64)
    with np.errstate(over="ignore"):
        h = ix * np.uint64(0x9E3779B97F4A7C15)
        h ^= iy * np.uint64(0xC2B2AE3D27D4EB4F)
        h ^= np.uint64(int(seed) & 0xFFFFFFFFFFFFFFFF) * np.uint64(0x165667B19E3779F9)
        h ^= h >> np.uint64(33)
        h *= np.uint64(0xFF51AFD7ED558CCD)
        h ^= h >> np.uint64(33)
        h *= np.uint64(0xC4CEB9FE1A85EC53)
        h ^= h >> np.uint64(33)
    return h & _MASK64


def hash_unit(ix, iy, seed):
    """Uniform floats in [0, 1) from lattice coordinates."""
    return (hash_lattice(ix, iy, seed) >> np.uint64(11)).astype(np.float64) / float(1 << 53)


def value_noise(x, y, seed, *, period_x=None):
    """Smooth value noise in [0, 1]; ``period_x`` wraps the lattice in x."""
    x = np.asarray(x, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)
    x0 = np.floor(x)
    y0 = np.floor(y)
    tx = x - x0
    ty = y - y0
    tx = tx * tx * (3.0 - 2.0 * tx)
    ty = ty * ty * (3.0 - 2.0 * ty)
    ix0 = x0.astype(np.int64)
    iy0 = y0.astype(np.int64)
    ix1 = ix0 + 1
    iy1 = iy0 + 1
    if period_x:
        period = int(period_x)
        ix0 %= period
        ix1 %= period
    a = hash_unit(ix0, iy0, seed)
    b = hash_unit(ix1, iy0, seed)
    c = hash_unit(ix0, iy1, seed)
    d = hash_unit(ix1, iy1, seed)
    return (a * (1.0 - tx) + b * tx) * (1.0 - ty) + (c * (1.0 - tx) + d * tx) * ty


def fbm(x, y, seed, *, octaves=4, gain=0.5, lacunarity=2.0, period_x=None):
    """Fractal sum of value noise, normalised to [0, 1]."""
    total = 0.0
    amplitude = 1.0
    norm = 0.0
    frequency = 1.0
    for octave in range(max(1, int(octaves))):
        period = None if not period_x else int(round(period_x * frequency))
        total = total + amplitude * value_noise(
            np.asarray(x) * frequency,
            np.asarray(y) * frequency,
            seed + octave * 1013,
            period_x=period,
        )
        norm += amplitude
        amplitude *= gain
        frequency *= lacunarity
    return total / max(1e-9, norm)


def domain_warp_uv(u, v, seed, *, amplitude, frequency, octaves=3):
    """Warp global UV by a smooth, u-periodic vector field.

    ``frequency`` is in lattice cells per unit of u (and of 2v, keeping the
    equirectangular aspect); ``amplitude`` is in UV units.
    """
    u = np.asarray(u, dtype=np.float64)
    v = np.asarray(v, dtype=np.float64)
    period = max(1, int(round(frequency)))
    x = u * period
    y = v * period * 0.5
    du = fbm(x, y, seed, octaves=octaves, period_x=period) - 0.5
    dv = fbm(x, y, seed + 7919, octaves=octaves, period_x=period) - 0.5
    return u + du * 2.0 * amplitude, v + dv * 2.0 * amplitude


def worley_cells(x, y, seed, *, jitter=0.9, period_x=None):
    """Nearest jittered lattice feature point for each sample.

    Returns ``(cell_ix, cell_iy, first_distance, second_distance)`` where the
    cell indices identify the owning feature point (wrapped by ``period_x``).
    """
    x = np.asarray(x, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)
    base_x = np.floor(x).astype(np.int64)
    base_y = np.floor(y).astype(np.int64)
    shape = np.broadcast_shapes(x.shape, y.shape)
    best = np.full(shape, np.inf)
    second = np.full(shape, np.inf)
    best_ix = np.zeros(shape, dtype=np.int64)
    best_iy = np.zeros(shape, dtype=np.int64)
    for oy in (-1, 0, 1):
        for ox in (-1, 0, 1):
            cx = base_x + ox
            cy = base_y + oy
            key_x = cx % int(period_x) if period_x else cx
            fx = cx + 0.5 + (hash_unit(key_x, cy, seed) - 0.5) * jitter
            fy = cy + 0.5 + (hash_unit(key_x, cy, seed + 31) - 0.5) * jitter
            distance = np.hypot(x - fx, y - fy)
            closer = distance < best
            second = np.where(closer, best, np.minimum(second, distance))
            best = np.where(closer, distance, best)
            best_ix = np.where(closer, key_x, best_ix)
            best_iy = np.where(closer, cy, best_iy)
    return best_ix, best_iy, best, second
