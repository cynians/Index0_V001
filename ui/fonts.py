"""Shared typography for the application and its simulation renderers."""

from functools import lru_cache

import pygame


# Pygame picks the first installed family; keep portable fallbacks for other hosts.
FONT_FAMILIES = "bahnschrift,segoeui,corbel,dejavusans"
DEFAULT_FONT_SIZE = 16
BROWSER_FONT_SIZE = 16
BROWSER_CONTROL_FONT_SIZE = 13


@lru_cache(maxsize=64)
def get_font(size=DEFAULT_FONT_SIZE, *, bold=False, italic=False):
    """Reuse fonts by size and style instead of loading them during every frame."""
    if get_font.cache_info().currsize == 0:
        # Quit callbacks are removed after shutdown, so register for each session.
        # SDL font objects must never be reused after Pygame starts again.
        pygame.register_quit(get_font.cache_clear)
    return pygame.font.SysFont(FONT_FAMILIES, max(1, int(size)), bold=bold, italic=italic)
