"""Bounded, authored display colours for leaves without a painted sprite."""

from __future__ import annotations


def leaf_palette(value):
    """Return a portable palette or leave an invalid visual recipe unresolved."""
    if not isinstance(value, dict):
        return None
    palette = {}
    for key in ("mature_rgb", "shade_rgb", "pale_rgb"):
        rgb = value.get(key)
        if (not isinstance(rgb, (list, tuple)) or len(rgb) != 3 or
                any(isinstance(channel, bool) or not isinstance(channel, int)
                    or not 0 <= channel <= 255 for channel in rgb)):
            return None
        palette[key] = list(rgb)
    return {"version": 1, **palette,
            "status": str(value.get("status") or "provisional_leaf_colour_fit")}


def leaf_display_color(palette, placement_index=None):
    """Stable small tone changes; no placement or geometry changes."""
    if placement_index is None:
        return tuple(palette["mature_rgb"])
    tone = (int(placement_index) * 7) % 13
    key = "shade_rgb" if tone < 4 else "pale_rgb" if tone == 12 else "mature_rgb"
    return tuple(palette[key])
