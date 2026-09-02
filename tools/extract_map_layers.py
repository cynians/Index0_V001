"""Render every Map Tools layer for a location side by side into one PNG.

Boots the real App (headless, SDL dummy driver) and drives the exact same
production code path a user clicking through Layer View buttons would hit --
NavigationController.open_region_map_tab, MapSimulation.set_active_layer_kind
/ set_active_climate_display_item, App.draw -- so what this produces is what
the live app would actually show, not a re-implementation of the rendering
logic.

Usage:
    py tools\\extract_map_layers.py <entity_id> [--out PATH] [--columns N]

Example:
    py tools\\extract_map_layers.py refined_lod1_ef077654b1 --out layers.png
"""

import argparse
import os
import sys
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pygame

from app.app import App


LAYER_CONFIGS = [
    # (label, layer_kind attr on MapSimulation, optional setup callable(sim))
    ("Map", "LOCATION_LAYER_KIND", None),
    ("Height", "HEIGHTMAP_LAYER_KIND", None),
    ("True Color", "TRUE_COLOR_LAYER_KIND", None),
    ("Climate - Koppen", "HYDROLOGY_LAYER_KIND", lambda sim: sim.set_active_climate_display_item("koppen")),
    ("Climate - Temperature", "HYDROLOGY_LAYER_KIND", lambda sim: sim.set_active_climate_display_item("annual_temperature")),
    ("Climate - Precipitation", "HYDROLOGY_LAYER_KIND", lambda sim: sim.set_active_climate_display_item("annual_precipitation")),
    ("Materials", "MATERIAL_HEATMAP_LAYER_KIND", None),
    ("Regions", "GROUND_MATERIALS_LAYER_KIND", None),
]


def _label_font():
    return pygame.font.SysFont("consolas", 20, bold=True)


def capture_layer(app, sim, label, layer_kind, setup):
    if setup is not None:
        setup(sim)
    sim.set_active_layer_kind(layer_kind)
    # Two draw passes: the first clears whatever the previous layer / the
    # startup splash left in the framebuffer before this layer's own content
    # settles in (see the biosphere/true-color verification scripts earlier
    # this session for the same pattern).
    app.draw()
    app.draw()
    pygame.display.flip()
    tile = app.screen.copy()
    font = _label_font()
    banner_h = 30
    pygame.draw.rect(tile, (10, 12, 16), pygame.Rect(0, 0, tile.get_width(), banner_h))
    text = font.render(label, True, (235, 240, 246))
    tile.blit(text, (8, 5))
    return tile


def build_grid(tiles, columns):
    if not tiles:
        raise ValueError("No layers captured")
    tile_w, tile_h = tiles[0].get_width(), tiles[0].get_height()
    rows = (len(tiles) + columns - 1) // columns
    grid = pygame.Surface((tile_w * columns, tile_h * rows))
    grid.fill((0, 0, 0))
    for index, tile in enumerate(tiles):
        col = index % columns
        row = index // columns
        grid.blit(tile, (col * tile_w, row * tile_h))
    return grid


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("entity_id", help="Location entity id to open as a Map tab (region draft, generated_region, planet, ...)")
    parser.add_argument("--out", default=None, help="Output PNG path (default: artifacts/map_layers/<entity_id>.png)")
    parser.add_argument("--columns", type=int, default=3, help="Tiles per row in the grid (default: 3)")
    args = parser.parse_args()

    app = App()

    entity = app.world_model.get_entity(args.entity_id)
    if not isinstance(entity, dict):
        print(f"Entity not found: {args.entity_id}")
        sys.exit(1)

    opened = app.navigation.open_region_map_tab(args.entity_id)
    if opened is False:
        print(f"Could not open a Map tab for {args.entity_id} (location_class={entity.get('location_class')!r})")
        sys.exit(1)

    sim = app.get_active_simulation()
    if sim is None or getattr(sim, "render_mode", None) != "map":
        print("Active simulation after opening the tab is not a MapSimulation -- unexpected location_class routing.")
        sys.exit(1)

    available = set(sim.get_available_layer_kinds())
    print(f"Available layer kinds: {sorted(available)}")

    tiles = []
    for label, kind_attr, setup in LAYER_CONFIGS:
        layer_kind = getattr(sim, kind_attr)
        if layer_kind not in available:
            print(f"skip {label!r}: layer kind {layer_kind!r} not available for this location")
            continue
        print(f"capturing {label!r} ({layer_kind})")
        tiles.append(capture_layer(app, sim, label, layer_kind, setup))

    if not tiles:
        print("No layers captured -- nothing to save.")
        sys.exit(1)

    grid = build_grid(tiles, max(1, args.columns))

    out_path = Path(args.out) if args.out else PROJECT_ROOT / "artifacts" / "map_layers" / f"{args.entity_id}.png"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    pygame.image.save(grid, str(out_path))
    print(f"Saved {len(tiles)} layers ({grid.get_width()}x{grid.get_height()}) to {out_path}")


if __name__ == "__main__":
    main()
