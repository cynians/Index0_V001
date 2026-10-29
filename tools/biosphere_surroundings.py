"""The isometric Biosphere beside the map of the same ground.

Look-only: the application is driven with nothing written to the ontology,
so it is safe beside a running application.  A Biosphere shows round its
living area what the map of its ground shows there
(``simulations/biosphere/surroundings.py``; ``docs/biosphere_worldgen_hookup_v001.md``
section 3.8).  This opens a city's map and a Biosphere at a point of the same
ground and sets the two side by side:

    python tools/biosphere_surroundings.py --city city_refined_lod4_29a30fb2ae_01 --at 0.62 0.36
    python tools/biosphere_surroundings.py --city <id> --at 0.62 0.36 --widths 60 250 800 --refine

For each width in metres a sheet: on the left the city's map of that much
ground round the point, laid as the isometric ground lies (turned an eighth
and seen at half height); on the right the Biosphere looked at from as far.
A tree's crown on the left is where its foot is on the right.

It prints, for each width, how many plants of the surroundings the view
draws, and how many of the plants the map draws it has at the same place:
all of them beyond the ground the Biosphere reads for its residents, where
it shows the map's own reading; most of them nearer, where it reads the
ground more closely than the map does.
"""

from __future__ import annotations

import argparse
import math
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from app_driver import PROJECT_ROOT, Driver  # noqa: E402  (must precede every other pygame import)

import numpy as np  # noqa: E402
import pygame  # noqa: E402

from simulations.biosphere import terrain_site  # noqa: E402
from simulations.biosphere.plant_pictures import MAP_SPRITE_DIR, planet_plant_pictures  # noqa: E402
from simulations.city.city_vegetation import city_bounds, city_planet_id  # noqa: E402


DEFAULT_WIDTHS = (60.0, 250.0, 800.0)
YEAR = 2400
ALL = 10 ** 9
WATER, BARE, OFF_MAP = (46.0, 84.0, 132.0), (176.0, 160.0, 124.0), (15.0, 20.0, 18.0)


def _inside(bounds, x, y):
    return (x >= bounds["min_x"]) & (x <= bounds["max_x"]) & (y >= bounds["min_y"]) & (y <= bounds["max_y"])


def map_picture(cover, substrate, box, px_per_m):
    """A box of ground as the city's map draws it from straight above: water, ground cover, every tall plant."""
    min_x, min_y, max_x, max_y = box
    size = (max(2, round((max_x - min_x) * px_per_m)), max(2, round((max_y - min_y) * px_per_m)))
    columns, rows = max(2, size[0] // 3), max(2, size[1] // 3)
    x, y = np.meshgrid(min_x + (np.arange(columns) + 0.5) * (max_x - min_x) / columns,
                       min_y + (np.arange(rows) + 0.5) * (max_y - min_y) / rows)
    held = cover.vegetation.bounds
    rgb = np.where(np.asarray(substrate.open_water_array(x, y), dtype=bool)[..., None], np.array(WATER), np.array(BARE))
    rgb = np.where(_inside(held, x, y)[..., None], rgb, np.array(OFF_MAP))
    small = pygame.surfarray.make_surface(np.transpose(rgb.astype(np.uint8), (1, 0, 2)))
    surface = pygame.transform.smoothscale(small.convert_alpha(), size)
    if cover.ground is not None:
        # The map's own picture of its ground cover lies over all its ground: the part of it over the box.
        per_m = cover.ground.get_width() / (held["max_x"] - held["min_x"])
        part = pygame.Rect(round((min_x - held["min_x"]) * per_m), round((min_y - held["min_y"]) * per_m),
                           round((max_x - min_x) * per_m), round((max_y - min_y) * per_m)).clip(cover.ground.get_rect())
        if part.width > 0 and part.height > 0:
            target = pygame.Rect(round((part.x / per_m + held["min_x"] - min_x) * px_per_m),
                                 round((part.y / per_m + held["min_y"] - min_y) * px_per_m),
                                 max(1, round(part.width / per_m * px_per_m)), max(1, round(part.height / per_m * px_per_m)))
            surface.blit(pygame.transform.smoothscale(cover.ground.subsurface(part), target.size), target.topleft)
    tall = cover.field.paint(min_x, min_y, px_per_m, size) if cover.field else None
    if tall is not None:
        surface.blit(tall, (0, 0))
    return surface


def laid_isometric(picture, size, origin):
    """A picture from above laid as the isometric ground lies, its middle at ``origin`` of a panel of ``size``."""
    turned = pygame.transform.rotozoom(picture, -45.0, 1.0)
    turned = pygame.transform.smoothscale(turned, (turned.get_width(), max(1, turned.get_height() // 2)))
    panel = pygame.Surface(size)
    panel.fill(OFF_MAP)
    panel.blit(turned, turned.get_rect(center=(round(origin[0]), round(origin[1]))))
    return panel


def compare(cover, bio, window, box):
    """How many of the plants the map draws in a view the Biosphere has at the same place there."""
    scenery, near, domain = bio.surroundings, bio.resident_flora.vegetation().bounds, bio.bounds
    u0, u1, v0, v1 = window
    plants = scenery.plants(window, budget=ALL)
    mine = {}
    for plant in plants:
        mine.setdefault(plant["species_id"], []).append((plant["x"], plant["y"]))
    kind, x, y, _crown = cover.field.plants_in(box)
    seen = (x - y >= u0) & (x - y <= u1) & (x + y >= v0) & (x + y <= v1) & ~_inside(domain, x, y) & _inside(cover.vegetation.bounds, x, y)
    beyond = ~_inside(near, x, y)
    far, close, left_out = [0, 0], [0, 0], []
    for number, species_id in enumerate(cover.field.species):
        of_kind = seen & (kind == number)
        if not of_kind.any():
            continue
        if scenery.shown.get(species_id) != 1.0:
            left_out.append(species_id[5:])
            continue
        here = np.array(mine.get(species_id, ())).reshape(-1, 2)
        exact = {(round(px, 3), round(py, 3)) for px, py in here.tolist()}
        tolerance = 0.25 * cover.field.spacing_m[number]
        for px, py, is_far in zip(x[of_kind].tolist(), y[of_kind].tolist(), beyond[of_kind].tolist()):
            if is_far:
                far[0] += 1
                far[1] += (round(px, 3), round(py, 3)) in exact
            else:
                close[0] += 1
                close[1] += bool(len(here)) and float(np.min(np.hypot(here[:, 0] - px, here[:, 1] - py))) <= tolerance
    return len(plants), far, close, left_out


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--city", required=True, help="id of a city founded on a refined region")
    parser.add_argument("--at", nargs=2, type=float, metavar=("EAST", "SOUTH"), default=(0.5, 0.5),
                        help="where the Biosphere is opened, as shares of the ground's width and height")
    parser.add_argument("--widths", nargs="+", type=float, default=list(DEFAULT_WIDTHS), help="widths of ground looked at, in metres")
    parser.add_argument("--refine", action="store_true",
                        help="let the Biosphere refine the ground under its living area first (a quarter of a minute a chunk)")
    parser.add_argument("--out", help="folder for the sheets (default: artifacts/biosphere_surroundings/<city>)")
    args = parser.parse_args(argv)

    out = Path(args.out) if args.out else PROJECT_ROOT / "artifacts" / "biosphere_surroundings" / args.city
    out.mkdir(parents=True, exist_ok=True)
    driver = Driver("surroundings", out, read_only=True)
    driver.frame(3)
    app, world = driver.app, driver.app.world_model
    city = world.get_entity(args.city)
    if not isinstance(city, dict) or city.get("location_class") != "city":
        raise SystemExit(f"{args.city} is not a city")
    # The pictures from above are kept between runs; the folder is a cache, not the ontology.
    planet_plant_pictures(world, city_planet_id(world, city)).map_sprite_dir = MAP_SPRITE_DIR

    began = time.time()
    app.navigation.open_region_map_tab(args.city)
    driver.frame(4)
    map_sim = driver.sim()
    map_sim.get_layers()
    cover = (getattr(map_sim, "_resident_vegetation_cache", None) or (None, None))[1]
    if cover is None:
        raise SystemExit("the map of this city shows no plants: nothing is established in its biomes")
    substrate = map_sim.get_ground_substrate()
    print(f"{city.get('name')}: map opened in {time.time() - began:.1f} s; {len(cover.vegetation.cover)} species on it")

    region = world.get_entity(city.get("terrain_source_map_id"))
    bounds = region["bounds"]
    site = terrain_site.found_biosphere_site(
        world, region["id"], (bounds["min_x"] + (bounds["max_x"] - bounds["min_x"]) * args.at[0],
                              bounds["min_y"] + (bounds["max_y"] - bounds["min_y"]) * args.at[1]), year=YEAR)
    began = time.time()
    app.navigation.launch_biosphere_tab(site["id"])
    bio = driver.sim()
    if getattr(bio, "surroundings", None) is None:
        raise SystemExit("the Biosphere opened here has no surroundings (it opens on bare ground)")
    bio.auto_resolve_terrain = bool(args.refine)
    frame = bio.terrain_frame
    if any(abs(frame[key] - city_bounds(city)[key]) > 1.0 for key in frame):
        print(f"  the city's ground {city_bounds(city)} is not the Biosphere's {frame}")
    renderer = app.renderer.biosphere_builder_renderer
    centre = bio.founding_point()
    print(f"Biosphere opened in {time.time() - began:.1f} s at {centre[0]:.0f}, {centre[1]:.0f} m; living area "
          f"{bio.ecology.width:.0f} x {bio.ecology.height:.0f} m; residents {len(bio.resident_flora.species)}")

    def settle(limit=900):
        """Run the application's frames until the view rests, its plants are set out and their pictures painted."""
        began, quiet, pictures = time.time(), 0, -1
        for count in range(limit):
            driver.frame(1)
            layer = renderer._rest_layers.get("plants") or {}
            busy = (bio.surroundings._work is not None or bool(layer.get("pending"))
                    or len(renderer._display_canonical) != pictures
                    or bool(getattr(bio, "_terrain_pending", None)) and bio.auto_resolve_terrain)
            pictures = len(renderer._display_canonical)
            quiet = 0 if busy or time.time() - began < 0.6 else quiet + 1
            if quiet >= 4:
                break
        return count + 1, time.time() - began

    frames, took = settle()
    print(f"  the application drew it in {frames} frames, {took:.1f} s: {bio._vegetation_render_count} plants of its own, "
          f"{bio._surroundings_render_count} of the surroundings")
    shot = driver.shot("biosphere_as_opened")
    print(f"  {shot.name}")

    size = (1280, 720)
    font = pygame.font.SysFont("arial", 16)
    bio.isometric_fullscreen_preview = True
    budget, renderer.sprite_budget_ms = renderer.sprite_budget_ms, None
    settle_seconds, renderer.GROUND_SETTLE_SECONDS = renderer.GROUND_SETTLE_SECONDS, 0.0
    try:
        for width in args.widths:
            bio.isometric_view_zoom = 1.0
            panel = pygame.Surface(size)
            state = renderer._projection(panel, bio)
            bio.isometric_view_zoom = (size[0] / width) / state["scale"]
            began = time.time()
            for _ in range(3):
                renderer.draw(panel, bio)
            state = bio._isometric_projection_state
            window = renderer._vegetation_window(panel, state)
            # The ground the panel shows, and a little more: a square round the view's middle.
            reach = 0.5 * (size[0] / state["scale"] + 2.0 * size[1] / state["scale"]) * 0.5 + 0.1 * width
            box = (state["center_x"] - reach, state["center_y"] - reach, state["center_x"] + reach, state["center_y"] + reach)
            per_m = state["scale"] * math.sqrt(2.0)
            if 2.0 * reach * per_m > 4000.0:
                raise SystemExit(f"a width of {width:.0f} m needs too large a picture of the map; ask for more ground")
            mapped = laid_isometric(map_picture(cover, substrate, box, per_m), size, (state["origin_x"], state["origin_y"]))
            drawn = bio._surroundings_render_count
            shown, far, close, left_out = compare(cover, bio, window, box)
            sheet = pygame.Surface((size[0] * 2 + 12, size[1] + 30))
            sheet.fill((24, 28, 26))
            for number, (picture, title) in enumerate((
                    (mapped, f"The city's map of {width:.0f} m of ground, laid as the isometric ground lies"),
                    (panel, f"The Biosphere opened there, {state['scale']:.1f} px to the metre"))):
                sheet.blit(picture, (number * (size[0] + 12), 30))
                sheet.blit(font.render(title, True, (230, 230, 220)), (number * (size[0] + 12) + 8, 6))
            path = out / f"surroundings_{width:.0f}m.png"
            pygame.image.save(sheet, str(path))
            print(f"{width:6.0f} m: {drawn} plants and tufts of the surroundings drawn, in {time.time() - began:.1f} s")
            print(f"          beyond the ground read for the residents: {far[1]} of the map's {far[0]} tall plants stand at the same place")
            print(f"          within it: {close[1]} of the map's {close[0]}"
                  + (f"; too many to set out one by one at this width: {', '.join(left_out)}" if left_out else ""))
            print(f"          {path}")
    finally:
        renderer.sprite_budget_ms, renderer.GROUND_SETTLE_SECONDS = budget, settle_seconds


if __name__ == "__main__":
    main()
