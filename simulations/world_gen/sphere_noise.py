"""Seamless, isotropic noise on a planet's sphere.

Map-space sinusoids such as ``sin(k*u + m*v)`` draw tilted stripes across an
equirectangular map (they look like a diagonal sine curve) and break at the
date line whenever ``k`` is not an integer.  Sampling a 3-D value-noise
lattice at each point's position on the unit sphere has no seam, no
preferred direction and no pinching at the poles, and a regional map samples
exactly the same field as the planet map it refines.

Inputs are planet-global map coordinates: ``u`` in [0, 1] west to east,
``v`` in [0, 1] north to south.
"""

from __future__ import annotations

import hashlib
import math
from functools import lru_cache

import numpy as np

_OCTAVE_SPREAD = (0.183, 0.133, 0.118, 0.111)


def _seed_int(map_seed, key):
    digest = hashlib.sha256(f"{map_seed}|{key}".encode("utf-8")).digest()
    return np.uint64(int.from_bytes(digest[:8], "little"))


def _lattice_value(seed, ix, iy, iz):
    """Deterministic value in [0, 1) for integer lattice points (splitmix64 mixing)."""
    with np.errstate(over="ignore"):
        h = (
            ix.astype(np.uint64) * np.uint64(0x9E3779B97F4A7C15)
            ^ iy.astype(np.uint64) * np.uint64(0xC2B2AE3D27D4EB4F)
            ^ iz.astype(np.uint64) * np.uint64(0x165667B19E3779F9)
            ^ seed
        )
        h = (h ^ (h >> np.uint64(30))) * np.uint64(0xBF58476D1CE4E5B9)
        h = (h ^ (h >> np.uint64(27))) * np.uint64(0x94D049BB133111EB)
        h = h ^ (h >> np.uint64(31))
    return (h >> np.uint64(11)).astype(np.float64) / float(1 << 53)


def _value_noise_3d(x, y, z, seed):
    ix, iy, iz = np.floor(x), np.floor(y), np.floor(z)
    fx, fy, fz = x - ix, y - iy, z - iz
    sx = fx * fx * (3.0 - 2.0 * fx)
    sy = fy * fy * (3.0 - 2.0 * fy)
    sz = fz * fz * (3.0 - 2.0 * fz)
    ix, iy, iz = ix.astype(np.int64), iy.astype(np.int64), iz.astype(np.int64)
    result = 0.0
    for dx in (0, 1):
        wx = sx if dx else 1.0 - sx
        for dy in (0, 1):
            wy = sy if dy else 1.0 - sy
            for dz in (0, 1):
                wz = sz if dz else 1.0 - sz
                result = result + wx * wy * wz * _lattice_value(seed, ix + dx, iy + dy, iz + dz)
    return result


def sphere_positions(u, v):
    """Unit-sphere (x, y, z) of planet map coordinates."""
    u = np.asarray(u, dtype=np.float64)
    v = np.asarray(v, dtype=np.float64)
    longitude = u * math.tau
    latitude = (0.5 - v) * math.pi
    cos_latitude = np.cos(latitude)
    return cos_latitude * np.cos(longitude), cos_latitude * np.sin(longitude), np.sin(latitude)


def sphere_fbm(map_seed, key, u, v, features=3.0, octaves=3, persistence=0.5):
    """Fractal value noise on the sphere, roughly uniform in [0, 1].

    ``features`` is the number of large blobs across one planetary radius
    (about ``2 * pi * features`` around the equator).  Scalars in, float
    out; arrays in, array out.
    """
    scalar = np.ndim(u) == 0 and np.ndim(v) == 0
    x, y, z = sphere_positions(u, v)
    seed = _seed_int(map_seed, key)
    total = np.zeros(np.broadcast(x, y, z).shape, dtype=np.float64)
    amplitude = 1.0
    norm = 0.0
    frequency = float(features)
    for octave in range(max(1, int(octaves))):
        offset = 17.31 * (octave + 1)
        total = total + amplitude * _value_noise_3d(
            x * frequency + offset, y * frequency - offset, z * frequency + 0.5 * offset,
            seed + np.uint64(octave * 0x9E37),
        )
        norm += amplitude
        amplitude *= persistence
        frequency *= 2.0
    value = total / norm
    # Summed octaves bunch around 0.5 (measured spread 0.18 / 0.13 / 0.12 /
    # 0.11 for 1-4 octaves); rescale to a spread of 0.2 so 95 % of the
    # surface lies within [0.1, 0.9].
    spread = _OCTAVE_SPREAD[min(len(_OCTAVE_SPREAD), max(1, int(octaves))) - 1]
    value = np.clip(0.5 + (value - 0.5) * (0.2 / spread), 0.0, 1.0)
    return float(value) if scalar else value


def sphere_signed(map_seed, key, u, v, features=3.0, octaves=3):
    """``sphere_fbm`` mapped to [-1, 1]."""
    value = sphere_fbm(map_seed, key, u, v, features=features, octaves=octaves)
    return value * 2.0 - 1.0


@lru_cache(maxsize=96)
def _table(map_seed, key, features, octaves):
    """``sphere_fbm`` precomputed on a lat/lon table fine enough for its top octave."""
    top_frequency = float(features) * 2.0 ** (max(1, int(octaves)) - 1)
    width = int(max(64, min(1024, math.ceil(top_frequency * math.tau * 6.0))))
    height = width // 2 + 1
    u = (np.arange(width, dtype=np.float64) / width)[None, :]
    v = (np.arange(height, dtype=np.float64) / (height - 1))[:, None]
    table = sphere_fbm(map_seed, key, u, v, features=features, octaves=octaves)
    # One wrapped column so interpolation across the date line is seamless.
    return np.concatenate([table, table[:, :1]], axis=1), width, height


def sphere_fbm_table(map_seed, key, u, v, features=3.0, octaves=3):
    """``sphere_fbm`` through a cached table: fast for per-cell loops and arrays alike."""
    table, width, height = _table(str(map_seed), str(key), float(features), int(octaves))
    if np.ndim(u) == 0 and np.ndim(v) == 0:
        x = (float(u) % 1.0) * width
        y = min(max(float(v), 0.0), 1.0) * (height - 1)
        x0, y0 = int(x), int(y)
        y1 = min(height - 1, y0 + 1)
        tx, ty = x - x0, y - y0
        top = table[y0, x0] * (1.0 - tx) + table[y0, x0 + 1] * tx
        bottom = table[y1, x0] * (1.0 - tx) + table[y1, x0 + 1] * tx
        return float(top * (1.0 - ty) + bottom * ty)
    u, v = np.broadcast_arrays(np.asarray(u, dtype=np.float64), np.asarray(v, dtype=np.float64))
    x = np.mod(u, 1.0) * width
    y = np.clip(v, 0.0, 1.0) * (height - 1)
    x0 = np.minimum(np.floor(x).astype(np.int64), width - 1)
    y0 = np.minimum(np.floor(y).astype(np.int64), height - 1)
    y1 = np.minimum(height - 1, y0 + 1)
    tx, ty = x - x0, y - y0
    top = table[y0, x0] * (1.0 - tx) + table[y0, x0 + 1] * tx
    bottom = table[y1, x0] * (1.0 - tx) + table[y1, x0 + 1] * tx
    return top * (1.0 - ty) + bottom * ty


def sphere_signed_table(map_seed, key, u, v, features=3.0, octaves=3):
    """``sphere_fbm_table`` mapped to [-1, 1]."""
    return sphere_fbm_table(map_seed, key, u, v, features=features, octaves=octaves) * 2.0 - 1.0
