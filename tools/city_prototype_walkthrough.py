"""Build a city prototype by clicking through the real application.

Drives the actual ``App`` (see ``tools/app_driver.py``) through the whole
creation process documented in ``docs/City_Prototype_Creation_Process.md``:

    planet     World Gen: orbit, name, Random Generic, every stage; re-rolls
               until the world is temperate with land and rivers
    refine     Map: pick a river site from the map's own data, frame it,
               "Refine View to <Level>" down to a town-sized LOD4 region
    found      Map: "Found City Here" on that region
    patch      City map: "Refine View to Parcel" on a parcel -> LOD5 patch,
               composited into the city map
    blueprint  Blueprint Designer: "Place on Map" -> the city; a click on open
               water is refused, then the building goes on dry ground
    parents    "Up To Parent" from the city to the planet; the city is drawn
               on every map on the way

Everything is real and persists in the live ontology.  Close the application
first.  Generation is slow (about a minute per LOD); the run is resumable --
state lives in ``.cache/city_prototype/<slug>/state.json`` and a second run
continues where the first stopped.

    python tools/city_prototype_walkthrough.py --name "Cityworld Prototype"
    python tools/city_prototype_walkthrough.py --name "Cityworld Prototype" --stages refine --max-refinements 2
"""

from __future__ import annotations

import argparse
import json
import math
import time

from app_driver import Driver, PROJECT_ROOT  # noqa: E402  (selects headless SDL before pygame loads)

import numpy as np
import pygame

from simulations.city import city_site
from simulations.world_gen.regional_refinement import map_physical_dimensions_m


STAGES = ("planet", "refine", "found", "patch", "blueprint", "parents")
AU_M = 149_597_870_700.0

# Visible window per level, metres wide.  The window is the whole 16:9 screen.
REFINEMENT_WIDTH_M = {1: 1_600_000.0, 2: 160_000.0, 3: 20_000.0, 4: 3_200.0}
PATCH_WIDTH_M = 320.0

# How much a settler would like each Koeppen class.
CLIMATE_WEIGHT = {
    "Cfb": 1.0, "Cfa": 0.95, "Csb": 0.9, "Csa": 0.85, "Cwb": 0.8, "Cwa": 0.75,
    "Dfb": 0.6, "Dfa": 0.6, "Cfc": 0.5, "Aw": 0.4, "Am": 0.35, "BSk": 0.35, "BSh": 0.3, "Af": 0.3,
    "Dfc": 0.2, "BWk": 0.08, "BWh": 0.05, "ET": 0.03,
}


# ---------------------------------------------------------------------------
# Site choice
# ---------------------------------------------------------------------------

def _nearest(rows, u, v):
    height, width = len(rows), len(rows[0])
    return rows[min(height - 1, max(0, int(round(v * (height - 1)))))][min(width - 1, max(0, int(round(u * (width - 1)))))]


def _cells_to_nearest(mask, max_steps):
    """Chebyshev distance in cells to the nearest True cell, capped."""
    distance = np.full(mask.shape, max_steps + 1, dtype=int)
    reached = mask.copy()
    distance[reached] = 0
    for step in range(1, max_steps + 1):
        grown = reached.copy()
        grown[1:, :] |= reached[:-1, :]
        grown[:-1, :] |= reached[1:, :]
        grown[:, 1:] |= reached[:, :-1]
        grown[:, :-1] |= reached[:, 1:]
        grown[1:, 1:] |= reached[:-1, :-1]
        grown[:-1, :-1] |= reached[1:, 1:]
        grown[1:, :-1] |= reached[:-1, 1:]
        grown[:-1, 1:] |= reached[1:, :-1]
        distance[grown & ~reached] = step
        reached = grown
    return distance


def pick_site(entity, *, want_coast=True, margin=0.16):
    """Choose a town site on a generated map from its own data.

    Scores points along rivers (falling back to any land) by climate,
    discharge, flow regime, flatness and, at the coarse levels, nearness to
    a coast.  Returns ``(u, v, report)`` in the map's local 0..1 frame.
    """
    heightmap = entity["heightmap_model"]
    elevation = np.asarray(heightmap["sample_grid"]["rows"], dtype=float)
    height, width = elevation.shape
    sea_level = float(heightmap.get("sea_level_m") or 0.0)
    water = entity.get("water_cycle_model") or {}
    koppen = (water.get("climate_grid") or {}).get("koppen_rows") or [["?"]]
    land = elevation > sea_level + 1.0
    coast_cells = _cells_to_nearest(~land, max(4, width // 6))
    gradient_y, gradient_x = np.gradient(elevation)
    slope = np.hypot(gradient_x, gradient_y)
    slope_scale = max(1e-9, float(np.percentile(slope[land], 90))) if land.any() else 1.0

    def cell(u, v):
        return (min(height - 1, max(0, int(round(v * (height - 1))))),
                min(width - 1, max(0, int(round(u * (width - 1))))))

    def score(u, v, discharge=0.0, perennial=False, on_river=False):
        if not (margin <= u <= 1 - margin and margin <= v <= 1 - margin):
            return None
        row, column = cell(u, v)
        if not land[row, column]:
            return None
        climate = CLIMATE_WEIGHT.get(str(_nearest(koppen, u, v)), 0.0)
        if climate <= 0.0:
            return None
        value = climate * 3.0
        value += math.log10(1.0 + discharge) * 0.35 + (0.5 if perennial else 0.0) + (0.6 if on_river else 0.0)
        value += 0.6 * (1.0 - min(1.0, slope[row, column] / slope_scale))
        if want_coast:
            coast = coast_cells[row, column] / width
            value += 1.0 if 0.01 <= coast <= 0.12 else (0.4 if coast <= 0.2 else 0.0)
        return value

    best = None
    for river in water.get("rivers") or []:
        discharge = float(river.get("estimated_discharge_m3_s") or 0.0)
        perennial = river.get("flow_regime") == "perennial"
        for point in river.get("display_points") or river.get("points") or []:
            u, v = float(point["x"]), float(point["y"])
            value = score(u, v, discharge, perennial, on_river=True)
            if value is not None and (best is None or value > best[0]):
                best = (value, u, v, {"river": river.get("id"), "discharge_m3_s": round(discharge, 1),
                                      "regime": river.get("flow_regime")})
    if best is None:
        step = max(1, width // 96)
        for row in range(0, height, step):
            for column in range(0, width, step):
                u, v = column / (width - 1), row / (height - 1)
                value = score(u, v)
                if value is not None and (best is None or value > best[0]):
                    best = (value, u, v, {"river": None})
    if best is None:
        raise ValueError("no habitable land on this map")
    value, u, v, report = best
    row, column = cell(u, v)
    report.update({
        "score": round(float(value), 2),
        "koppen": str(_nearest(koppen, u, v)),
        "elevation_above_sea_m": round(float(elevation[row, column] - sea_level), 1),
    })
    return u, v, report


# ---------------------------------------------------------------------------
# Walkthrough
# ---------------------------------------------------------------------------

class Walkthrough:
    def __init__(self, args):
        self.args = args
        slug = "".join(ch if ch.isalnum() else "_" for ch in args.name.lower()).strip("_")
        self.planet_id = f"planet_{slug}"
        self.folder = PROJECT_ROOT / ".cache" / "city_prototype" / slug
        self.folder.mkdir(parents=True, exist_ok=True)
        self.state_path = self.folder / "state.json"
        self.state = json.loads(self.state_path.read_text()) if self.state_path.exists() else {"chain": []}
        self.d = Driver("walk", self.folder / "shots")
        self.d.frame(4)
        self.world = self.d.app.world_model
        self.started = time.time()

    def log(self, message):
        print(f"[{time.time() - self.started:7.1f}s] {message}", flush=True)

    def save(self):
        self.state_path.write_text(json.dumps(self.state, indent=1))

    def shot(self, slug):
        self.log(f"  shot {self.d.shot(slug).name}")

    def to_repository(self):
        if self.d.sim() is not None:
            self.d.press("open_repository")
            self.d.frame(3)

    def open_map(self, entity_id):
        """Resume shortcut: a refined region has no click path from the repository search."""
        self.d.app.navigation.open_region_map_tab(entity_id)
        self.d.frame(4)
        assert self.d.sim().context.root_entity_id == entity_id
        return self.d.sim()

    # -- planet -----------------------------------------------------------

    def planet_is_suitable(self):
        """A temperate world with land and rivers, judged from the generated planet."""
        planet = self.world.get_entity(self.planet_id) or {}
        water = planet.get("water_cycle_model") or {}
        summary = water.get("runoff_summary") or {}
        classes = {str(item.get("code") or item.get("id")): float(item.get("fraction", item.get("area_fraction", 0)) or 0)
                   for item in water.get("koppen_classes") or [] if isinstance(item, dict)}
        temperate = sum(share for code, share in classes.items() if code[:1] in {"C", "D"} and code != "Dfd")
        ocean = float(summary.get("realized_ocean_fraction") or 0)
        temperature = float(summary.get("mean_temperature_k") or 0)
        rivers = int(water.get("river_count") or 0)
        self.log(f"  result: seed={(planet.get('world_gen_seed') or {}).get('map_seed')} ocean={ocean:.2f} "
                 f"T={temperature:.1f} K rivers={rivers} temperate land={temperate:.3f}")
        return (0.30 <= ocean <= 0.80 and self.args.min_temperature_k <= temperature <= 298.0
                and rivers >= 5 and temperate >= 0.01)

    def stage_planet(self):
        d, args = self.d, self.args
        existing = self.world.get_entity(self.planet_id)
        if isinstance(existing, dict) and existing.get("world_gen_complete") and self.planet_is_suitable():
            self.log(f"{self.planet_id} is already complete and suitable")
            return
        self.to_repository()
        d.open_card_by_search(args.system_name, args.system_id)
        d.launch_from_card(args.system_id, "world_gen")
        d.frame(4)
        sim = d.sim()

        def wait_job(label):
            began = time.time()
            reported = time.time()
            while sim.is_worldgen_job_running():
                d.frame(1)
                time.sleep(0.25)
                if time.time() - reported > 45:
                    loading = sim.get_worldgen_loading_state()
                    self.log(f"  {label}: {loading.get('progress', 0):.0%} {loading.get('detail', '')}")
                    reported = time.time()
            d.frame(4)
            self.log(f"  {label} done in {time.time() - began:.0f}s -> {sim.editor_stage}: {sim.commit_status}")

        def select_existing():
            # Planets start at the same orbital phase, so their labels overlap;
            # click a point of this planet's hitbox that no other one covers.
            # Neighbours on close orbits cover it whole at the opening zoom:
            # wheel in on it, as a player would, until they stand apart.
            free = []
            for _ in range(14):
                d.frame(2)
                boxes = list(sim.planet_hitboxes)
                mine = next(rect for entity_id, rect in boxes if entity_id == self.planet_id)
                others = [rect for entity_id, rect in boxes if entity_id != self.planet_id]
                free = [(x, y) for x in range(mine.left, mine.right, 2) for y in range(mine.top, mine.bottom, 2)
                        if 0 <= x < d.app.width and 0 <= y < d.app.height
                        and not any(other.collidepoint((x, y)) for other in others)]
                if free:
                    break
                d.wheel(mine.center, 1)
            assert free, ("another planet sits at the same orbit, so this one cannot be picked on the "
                          "World Gen orbit view; choose a different --orbit-au for a new planet")
            d.click(free[len(free) // 2])
            assert sim.selected_world_gen_planet_id == self.planet_id, sim.selected_world_gen_planet_id

        def back_to_crust():
            for _ in range(8):
                if sim.editor_stage == "crust":
                    return
                before = sim.editor_stage
                d.click_rect(sim.world_gen_back_button_rect)
                assert sim.pending_back_stage, f"Back asked for no confirmation at {before}"
                d.enter()
            assert sim.editor_stage == "crust", sim.editor_stage

        def run_stages():
            for _ in range(20):
                stage = sim.editor_stage
                if stage == "water_cycle" and sim.world_gen_complete_button_rect is not None and sim._world_gen_can_finish():
                    return
                assert sim.crust_save_button_rect is not None, f"no primary button at stage {stage}"
                d.click_rect(sim.crust_save_button_rect)
                wait_job(stage)
            raise SystemExit("worldgen stages did not converge")

        if self.world.get_entity(self.planet_id) is None:
            star = d.app.camera.world_to_screen((0.0, 0.0))
            d.click((star[0], star[1] - args.orbit_au * AU_M * d.app.camera.zoom))
            self.log(f"orbit: {sim.input_buffers}")
            d.enter()
            assert sim.planet_name_prompt_active, "Enter did not open the name prompt"
            d.type_text(args.name)
            d.enter()
            assert sim.selected_world_gen_planet_id == self.planet_id, sim.selected_world_gen_planet_id
            self.log(f"created {self.planet_id}")
        else:
            select_existing()
            self.log(f"resumed {self.planet_id} at stage {sim.editor_stage}")
            if sim.editor_stage == "water_cycle" and self.planet_is_suitable():
                if not (self.world.get_entity(self.planet_id) or {}).get("world_gen_complete"):
                    d.click_rect(sim.world_gen_complete_button_rect)
                    d.frame(4)
                self.log("planet already suitable")
                return

        for attempt in range(1, args.max_rolls + 1):
            back_to_crust()
            d.click_rect(sim.crust_random_generic_button_rect)
            self.log(f"roll {attempt}: Random Generic")
            run_stages()
            self.shot(f"planet_roll_{attempt}")
            if self.planet_is_suitable():
                break
            self.log(f"roll {attempt}: not a temperate world with land and rivers")
        else:
            raise SystemExit("no suitable planet in this run; run again to keep rolling")
        d.click_rect(sim.world_gen_complete_button_rect)
        d.frame(4)
        self.log(f"planet complete: {sim.commit_status}")

    # -- refinement -------------------------------------------------------

    def stage_refine(self):
        d = self.d
        chain = self.state["chain"]
        if len(chain) >= 4:
            self.log(f"refinement chain already complete: {chain}")
            return
        if chain:
            sim = self.open_map(chain[-1])
        else:
            self.to_repository()
            d.open_card_by_search(self.args.name, self.planet_id)
            d.launch_from_card(self.planet_id, "map")
            d.frame(4)
            sim = d.sim()
            assert sim.context.root_entity_id == self.planet_id
            self.shot("planet_map")
        steps = 0
        while len(chain) < 4 and steps < self.args.max_refinements:
            level = len(chain) + 1
            root = sim.get_root_entity()
            u, v, report = pick_site(root, want_coast=level <= 2)
            bounds = sim._entity_map_bounds(root)
            map_point = (bounds["min_x"] + u * (bounds["max_x"] - bounds["min_x"]),
                         bounds["min_y"] + v * (bounds["max_y"] - bounds["min_y"]))
            world_point = sim._map_point_to_world(*map_point)
            fraction = REFINEMENT_WIDTH_M[level] / map_physical_dimensions_m(root)[0]
            self.log(f"LOD{level}: site uv=({u:.4f}, {v:.4f}) {report}")
            d.frame_map_window(world_point, (bounds["max_x"] - bounds["min_x"]) * fraction)
            self.shot(f"lod{level}_framed")
            began = time.time()
            d.press("regenerate_visible_region")
            d.frame(4)
            sim = d.sim()
            region = sim.get_root_entity()
            assert region.get("id") != root.get("id"), "no new region map opened"
            width_m, height_m = map_physical_dimensions_m(region)
            self.log(f"  -> {region['id']} LOD{region.get('map_detail_level')} "
                     f"{width_m / 1000:.2f} x {height_m / 1000:.2f} km in {time.time() - began:.0f}s")
            self.shot(f"lod{level}_region")
            chain.append(region["id"])
            self.save()
            steps += 1

    # -- city -------------------------------------------------------------

    def city(self):
        return self.world.get_entity(self.state["city_id"])

    def stage_found(self):
        d = self.d
        if self.state.get("city_id"):
            if self.world.get_entity(self.state["city_id"]) is not None:
                self.log(f"city already founded: {self.state['city_id']}")
                return
            # A write made while another process has the store open can be lost without an error.
            self.log(f"{self.state['city_id']} is not in the store any more; founding again")
            self.state.pop("city_id")
        assert len(self.state["chain"]) >= 4, "refine to LOD4 first"
        self.open_map(self.state["chain"][-1])
        self.log(f"sidebar offers: '{d.button('found_city').label}'")
        d.press("found_city")
        d.frame(4)
        city = d.sim().get_root_entity()
        assert city.get("location_class") == "city", city.get("location_class")
        self.state["city_id"] = city["id"]
        self.save()
        self.log(f"founded {city['id']} '{city.get('name')}' "
                 f"{city['bounds']['max_x']:.0f} x {city['bounds']['max_y']:.0f} m")
        self.shot("city_founded")

    def stage_patch(self):
        d = self.d
        if self.state.get("patch_id"):
            self.log(f"patch already refined: {self.state['patch_id']}")
            return
        city = self.city()
        self.open_map(city["id"])
        region = self.world.get_entity(self.state["chain"][-1])
        u, v, report = pick_site(region, want_coast=False, margin=0.2)
        point = (u * city["bounds"]["max_x"], v * city["bounds"]["max_y"])
        self.state["site_m"] = list(point)
        self.save()
        self.log(f"patch site {point[0]:.0f}, {point[1]:.0f} m: {report}")
        d.frame_map_window(point, PATCH_WIDTH_M)
        before = {patch["id"] for patch, _ in city_site.refined_patches(self.world, city)}
        began = time.time()
        self.log(f"pressing '{d.button('regenerate_visible_region').label}' from the city map")
        d.press("regenerate_visible_region")
        d.frame(4)
        assert d.sim().context.root_entity_id == city["id"], "refining from the city map left the city map"
        new = [(patch, bounds) for patch, bounds in city_site.refined_patches(self.world, self.city())
               if patch["id"] not in before]
        assert new, "no patch was created"
        patch, bounds_m = new[-1]
        self.state["patch_id"] = patch["id"]
        self.state["patch_bounds_m"] = bounds_m
        self.save()
        heightmap = patch["heightmap_model"]
        self.log(f"patch {patch['id']} LOD{patch.get('map_detail_level')} "
                 f"{heightmap.get('region_width_m'):.0f} x {heightmap.get('region_height_m'):.0f} m, "
                 f"{heightmap.get('sample_spacing_x_m'):.2f} m/sample, {time.time() - began:.0f}s")
        self.shot("city_patch")

    def stage_blueprint(self):
        d = self.d
        if self.state.get("building_id"):
            self.log(f"building already placed: {self.state['building_id']}")
            return
        city = self.city()
        substrate = city_site.city_substrate(self.world, city)
        site_x, site_y = self.state.get("site_m") or (city["bounds"]["max_x"] * 0.4, city["bounds"]["max_y"] * 0.4)
        target = next(((site_x + dx, site_y + dy)
                       for dx, dy in ((25, 18), (-30, 22), (30, -25), (-28, -24), (55, 40), (0, 60))
                       if substrate.terrestrial_habitat_at(site_x + dx, site_y + dy)), (site_x, site_y))
        blueprint = self.world.get_entity(self.args.blueprint)
        assert blueprint is not None, f"blueprint {self.args.blueprint} does not exist"
        self.to_repository()
        d.open_card_by_search(blueprint.get("pretty_name") or blueprint.get("name"), self.args.blueprint)
        d.launch_from_card(self.args.blueprint, "blueprint_designer")
        d.frame(4)
        designer = d.sim()
        d.click_rect(designer.hitboxes["place_on_map"])
        d.frame(2)
        key = f"picker:item:{city['id']}"
        if key not in designer.hitboxes:
            d.type_text(str(city.get("name")))
            d.frame(2)
        assert key in designer.hitboxes, "the city is not offered in the Place on Map picker"
        d.click_rect(designer.hitboxes[key])
        d.frame(4)
        city_map = d.sim()
        assert city_map.context.root_entity_id == city["id"] and city_map.blueprint_placement is not None
        camera = d.app.camera
        # Left click places, so there is no drag-panning here: zoom with the
        # wheel on the spot itself, which keeps it under the cursor.
        water_point = next(((x, y) for x in np.linspace(0.2, 0.8, 25) * city["bounds"]["max_x"]
                            for y in np.linspace(0.2, 0.8, 15) * city["bounds"]["max_y"]
                            if substrate.open_water_at(x, y)), None)
        if water_point is not None:
            d.move(camera.world_to_screen(water_point))
            self.shot("placement_refused_on_water")
            d.click(camera.world_to_screen(water_point))
            assert city_map.blueprint_placement is not None, "a click on open water placed the building"
            self.log(f"click on open water refused: {city_map.blueprint_placement.status}")
        for _ in range(60):
            if d.app.width / camera.zoom <= 140.0 * 1.08:
                break
            d.wheel(camera.world_to_screen(target), 1)
        d.move(camera.world_to_screen(target))
        self.shot("placement_ghost")
        d.click(camera.world_to_screen(target))
        building = self.world.get_entity(city_map.selected_entity_id) or {}
        assert building.get("building_blueprint") == self.args.blueprint, f"nothing placed: {city_map.selected_entity_id}"
        self.state["building_id"] = building["id"]
        self.save()
        self.log(f"placed {building['id']} at {building['blueprint_position']} "
                 f"on LOD{substrate.detail_level_at(*target)} ground, {substrate.elevation(*target):.2f} m")
        self.shot("building_placed")

    def stage_parents(self):
        d = self.d
        city = self.city()
        sim = self.open_map(city["id"])
        d.app.camera_controller.setup_for_sim(sim)
        d.frame(3)
        self.shot("city_overview")
        for hop in range(1, 8):
            if "open_parent_region_map" not in d.buttons():
                break
            d.press("open_parent_region_map")
            d.frame(4)
            sim = d.sim()
            root = sim.get_root_entity()
            shapes = [layer.get("shape") for layer in sim.get_layers() if layer.get("entity_id") == city["id"]]
            self.log(f"up {hop}: {root.get('id')} ({root.get('location_class')}); city drawn as {shapes}")
            assert "marker" in shapes, f"the city is not drawn on {root.get('id')}"
            self.shot(f"parent_{hop}_{root.get('location_class')}")
            if root.get("location_class") in {"planet", "moon"}:
                # Above the planet the map is a star system: another frame, no city.
                break

    def run(self):
        for stage in self.args.stages:
            self.log(f"== {stage}")
            getattr(self, f"stage_{stage}")()
        self.log(f"state: {self.state}")
        self.log(f"screenshots: {self.d.shots_dir}")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--name", default="Cityworld Prototype", help="planet name; its id becomes planet_<slug>")
    parser.add_argument("--system-id", default="system_test_system_prime")
    parser.add_argument("--system-name", default="Test System Prime")
    parser.add_argument("--orbit-au", type=float, default=0.97,
                        help="circular orbit radius. Around Test System Prime's star 0.957 AU gave ~297 K and "
                             "1.185 AU froze every roll; avoid an orbit another planet already uses")
    parser.add_argument("--blueprint", default="bp_lumber_worker_barracks")
    parser.add_argument("--stages", nargs="+", choices=STAGES, default=list(STAGES))
    parser.add_argument("--max-rolls", type=int, default=3, help="Random Generic attempts per run")
    parser.add_argument("--min-temperature-k", type=float, default=281.0,
                        help="coldest mean surface temperature a roll is kept at; a world with ice caps and "
                             "temperate land besides can be several kelvin colder")
    parser.add_argument("--max-refinements", type=int, default=4, help="refinement levels per run")
    args = parser.parse_args(argv)
    try:
        Walkthrough(args).run()
    finally:
        pygame.quit()


if __name__ == "__main__":
    main()
