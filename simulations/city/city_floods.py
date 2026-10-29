"""How often the river covers a city's ground, as a picture to lay over its map.

A city stands on a Site, and a Site with a carved river tells for every cell
how often that river's floods cover it (``world_gen/river_floods.py``).
This draws it: the ground the river is on every other year, within ten
years, within a hundred, each fainter than the last; ground no flood
reaches is left clear.  Nothing is decided here: it is what a builder would
want to see before choosing where to build.
"""

from __future__ import annotations

import numpy as np
import pygame

FLOOD_FIELD = "flood_return_period_years"
# Years between floods up to which ground is drawn in each tone (red, green, blue, alpha), the commonest first.
FLOOD_TONES = (
    (2.0, (96, 60, 200, 150)),
    (10.0, (70, 110, 220, 110)),
    (100.0, (90, 160, 230, 60)),
)
FLOOD_PICTURE_LONG_SIDE_PX = 768


def flood_legend():
    """What each tone of the picture stands for, for whoever shows it."""
    return [(f"within {years:.0f} years", tone) for years, tone in FLOOD_TONES]


def has_floods(substrate):
    """Whether a city's ground tells how often it is flooded."""
    return substrate is not None and (getattr(substrate, "fields", None) or {}).get(FLOOD_FIELD) is not None


def flood_picture(substrate, bounds, long_side_px=FLOOD_PICTURE_LONG_SIDE_PX):
    """An RGBA picture of ``bounds``: tinted where the river's floods reach, or ``None`` where none does."""
    if not has_floods(substrate):
        return None
    width_m, height_m = bounds["max_x"] - bounds["min_x"], bounds["max_y"] - bounds["min_y"]
    scale = long_side_px / max(width_m, height_m)
    columns, rows = max(2, round(width_m * scale)), max(2, round(height_m * scale))
    x, y = np.meshgrid(bounds["min_x"] + (np.arange(columns) + 0.5) * width_m / columns,
                       bounds["min_y"] + (np.arange(rows) + 0.5) * height_m / rows)
    years = np.nan_to_num(np.asarray(substrate.sample_array(FLOOD_FIELD, x, y, np.inf), dtype=np.float64), nan=np.inf)
    water = np.asarray(substrate.open_water_array(x, y), dtype=bool)
    # Blue first: the order the display keeps, which blits many times faster than any other.
    bgra = np.zeros((rows, columns, 4), dtype=np.uint8)
    for limit, (red, green, blue, alpha) in reversed(FLOOD_TONES):
        bgra[(years <= limit) & ~water] = (blue, green, red, alpha)
    if not bgra[..., 3].any():
        return None
    return pygame.image.frombuffer(bgra.tobytes(), (columns, rows), "BGRA")
