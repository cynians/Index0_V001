"""Visual checkpoint for docs/volatile_budget_roadmap_v001.md: reference worlds at LOD0.

Runs the production headless world generation (isolated: nothing reaches the
live ontology) for a fixed set of reference worlds, renders LOD0 true colour
and the dominant-material map for each, and composes one comparison sheet.

    python tools/volatile_showcase.py --out <dir>                 # all worlds
    python tools/volatile_showcase.py --out <dir> --worlds titan,mars
    python tools/volatile_showcase.py --out <dir> --render-only   # re-render stored runs

Outputs in <dir>: <world>/truecolor.png, <world>/materials.png,
<world>/summary.json and volatile_showcase.png.
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

EARTH_TEMPLATE = "silicate_terrestrial"
TITAN = [("O", 58.0), ("H", 7.3), ("Si", 10.0), ("Fe", 6.0), ("Mg", 5.0), ("C", 2.5), ("N", 1.8), ("S", 1.0),
         ("Na", 0.5), ("Cl", 0.3)]
# Taylor & McLennan average Martian crust (+ Mars's low nitrogen).
MARS = [("O", 44.5), ("Si", 23.04), ("Fe", 14.15), ("Al", 5.56), ("Mg", 5.46), ("Ca", 4.95), ("Na", 2.20),
        ("S", 1.2), ("Ti", 0.59), ("Cl", 0.5), ("P", 0.39), ("K", 0.37), ("Mn", 0.28), ("Cr", 0.25), ("H", 0.2),
        ("Ni", 0.045), ("C", 0.01), ("F", 0.004), ("N", 0.0005)]

WORLDS = {
    "earth": {
        "title": "Earth inventory @ 1 AU", "template": EARTH_TEMPLATE,
        "config": dict(periapsis_au=1.0, apoapsis_au=1.0, tectonics_mode="mobile_lid"),
    },
    "venus": {
        "title": "Same Earth inventory @ 0.72 AU", "template": EARTH_TEMPLATE,
        "config": dict(periapsis_au=0.723, apoapsis_au=0.723, tectonics_mode="stagnant_lid"),
    },
    "titan": {
        "title": "Titan-like icy inventory @ 9.5 AU", "elements": TITAN,
        "config": dict(periapsis_au=9.54, apoapsis_au=9.54, radius_earth=0.404, core_radius_fraction=0.4,
                       crust_thickness_km=100.0, angular_velocity_deg_per_hour=0.94, tectonics_mode="inactive"),
    },
    "mars": {
        "title": "Mars crust @ 1.52 AU", "elements": MARS,
        "config": dict(periapsis_au=1.524, apoapsis_au=1.524, radius_earth=0.532, core_radius_fraction=0.5,
                       crust_thickness_km=50.0, angular_velocity_deg_per_hour=14.6, tectonics_mode="stagnant_lid"),
    },
}


def _register_templates():
    from simulations.world_gen.world_gen_sim import WorldGenSimulation

    for name, world in WORLDS.items():
        if world.get("elements"):
            WorldGenSimulation.PLANET_TEMPLATES[f"showcase_{name}"] = {
                "label": world["title"], "planet_class": "terrestrial", "major_elements": list(world["elements"]),
                "water_range": (0.0, 0.1), "volatile_options": ["dry"], "tectonics_options": ["inactive"],
            }


def run_world(name, out_dir):
    from simulations.world_gen.headless_runner import HeadlessWorldGenConfig, HeadlessWorldGenRunner

    world = WORLDS[name]
    _register_templates()
    template = world.get("template") or f"showcase_{name}"
    config = HeadlessWorldGenConfig(
        name=f"Showcase {name}", template_id=template, map_seed=f"volatile-showcase-{name}",
        finish_worldgen=True, regional_refinement_depth=0, render_outputs=False, **world["config"],
    )
    start = time.perf_counter()
    result = HeadlessWorldGenRunner(out_dir / name / "run").run(config)
    print(f"[{name}] LOD0 run {time.perf_counter() - start:.0f}s", flush=True)
    (out_dir / name / "result.json").write_text(json.dumps({"planet_path": result.planet_path,
                                                            "repository_root": result.repository_root}), encoding="utf-8")


def render_world(name, out_dir):
    import pygame

    from simulations.world_gen.material_heatmaps import load_raster_bundle_surface
    from simulations.world_gen.surface_exposure import derive_surface_exposure_model
    from simulations.world_gen.true_color import derive_true_color_model, render_true_color_surface

    info = json.loads((out_dir / name / "result.json").read_text(encoding="utf-8"))
    planet = json.loads(Path(info["planet_path"]).read_text(encoding="utf-8"))
    storage_root = Path(info["repository_root"])
    heightmap = planet["heightmap_model"]
    materials = planet["material_heatmap_model"]
    bundle = storage_root / materials["bundle_path"]
    components = []
    for layer in materials["layers"]:
        component = dict(layer)
        component["surface"] = load_raster_bundle_surface(bundle, layer["bundle_layer_id"])
        components.append(component)
    water = planet.get("water_cycle_model")
    exposure = derive_surface_exposure_model(
        planet, heightmap=heightmap, material_heatmap_model=materials, water_cycle=water,
        surface_evolution=planet.get("surface_evolution_model"),
        surface_geomorphology=planet.get("surface_geomorphology_model"),
    )
    model = derive_true_color_model(
        planet, heightmap=heightmap, natural_material_model=planet["natural_material_model"],
        material_heatmap_model=materials, atmosphere=planet.get("atmosphere_model"), water_cycle=water,
        surface_evolution=planet.get("surface_evolution_model"), surface_exposure=exposure,
        surface_geomorphology=planet.get("surface_geomorphology_model"),
    )
    surface = render_true_color_surface(
        heightmap, model, material_components=components, water_cycle=water,
        surface_evolution=planet.get("surface_evolution_model"), surface_exposure=exposure,
        surface_geomorphology=planet.get("surface_geomorphology_model"), atmosphere=planet.get("atmosphere_model"),
    )
    pygame.image.save(surface, str(out_dir / name / "truecolor.png"))
    composite = load_raster_bundle_surface(bundle, "composite")
    pygame.image.save(pygame.transform.scale(composite, surface.get_size()), str(out_dir / name / "materials.png"))

    atmosphere = planet.get("atmosphere_model") or {}
    budget = atmosphere.get("volatile_budget") or {}
    layers = sorted(materials.get("layers") or [], key=lambda layer: -float(layer.get("coverage_fraction") or 0.0))
    summary = {
        "title": WORLDS[name]["title"],
        "atmosphere_class": atmosphere.get("atmosphere_class"),
        "pressure_bar": atmosphere.get("surface_pressure_bar"),
        "surface_temperature_k": atmosphere.get("estimated_surface_temperature_k"),
        "composition": [(row["molecule"], row["percent"]) for row in atmosphere.get("composition") or []][:4],
        "surface_liquid": budget.get("surface_liquid"),
        "surface_ice_species": budget.get("surface_ice_species"),
        "redox_state": (budget.get("speciation") or {}).get("redox_state"),
        "runaway": budget.get("runaway_greenhouse"),
        "cloud": (atmosphere.get("cloud_model") or {}).get("cloud_class"),
        "map_materials": [(layer.get("material_id"), round(float(layer.get("coverage_fraction") or 0.0), 3))
                          for layer in layers[:6]],
        "roster": [item["material_id"] for item in (planet.get("natural_material_model") or {}).get("likely_materials") or []],
    }
    (out_dir / name / "summary.json").write_text(json.dumps(summary, indent=1, default=str), encoding="utf-8")
    print(f"[{name}] rendered", flush=True)


def _share(percent):
    if percent >= 1.0:
        return f"{percent:.0f}%"
    if percent >= 0.1:
        return f"{percent:.1f}%"
    return f"{percent * 1e4:.0f} ppm"


def _caption(summary):
    gases = ", ".join(f"{molecule} {_share(percent)}" for molecule, percent in summary["composition"][:3])
    liquid = summary.get("surface_liquid") or {}
    seas = (f"seas: {str(liquid['fluid']).replace('_', '-')} {liquid['global_depth_m']:.3g} m" if liquid.get("fluid")
            else "no surface liquid")
    ices = ", ".join(f"{species} ice" for species in summary.get("surface_ice_species") or []) or "no ices"
    top = ", ".join(f"{material[4:].replace('_', ' ')} {share * 100:.0f}%"
                    for material, share in summary["map_materials"] if share >= 0.01)
    return [
        f"{summary['surface_temperature_k']:.0f} K, {summary['pressure_bar']:.3g} bar [{summary['atmosphere_class']}], "
        f"{summary.get('redox_state')}{', runaway greenhouse' if summary.get('runaway') else ''}",
        f"air: {gases or '-'};  {seas};  {ices}",
        f"map: {top}",
    ]


def compose(out_dir, names):
    import pygame

    pygame.init()
    title_font = pygame.font.SysFont("segoeui", 22, bold=True)
    font = pygame.font.SysFont("segoeui", 16)
    panel_w, panel_h, gap = 700, 350, 14
    rows = []
    for name in names:
        summary = json.loads((out_dir / name / "summary.json").read_text(encoding="utf-8"))
        tile = pygame.Surface((panel_w * 2 + gap, 32 + panel_h + 8 + 22 * 3))
        tile.fill((24, 24, 28))
        tile.blit(title_font.render(summary["title"], True, (240, 240, 240)), (4, 2))
        for index, image_name in enumerate(("truecolor.png", "materials.png")):
            image = pygame.transform.smoothscale(pygame.image.load(str(out_dir / name / image_name)), (panel_w, panel_h))
            tile.blit(image, (index * (panel_w + gap), 32))
        for index, line in enumerate(_caption(summary)):
            tile.blit(font.render(line, True, (205, 210, 215)), (6, 32 + panel_h + 6 + index * 22))
        rows.append(tile)
    sheet = pygame.Surface((rows[0].get_width() + 2 * gap, sum(row.get_height() + gap for row in rows) + gap))
    sheet.fill((24, 24, 28))
    y = gap
    for row in rows:
        sheet.blit(row, (gap, y))
        y += row.get_height() + gap
    path = out_dir / "volatile_showcase.png"
    pygame.image.save(sheet, str(path))
    print(path)
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", required=True, help="output directory (outside the repository)")
    parser.add_argument("--worlds", default=",".join(WORLDS), help="comma-separated: " + ", ".join(WORLDS))
    parser.add_argument("--render-only", action="store_true", help="re-render existing runs")
    args = parser.parse_args()
    out_dir = Path(args.out).resolve()
    names = [name.strip() for name in args.worlds.split(",") if name.strip()]
    from world.persistent_ontology_store import PersistentOntologyStore
    from simulations.world_gen.natural_materials import configure_material_catalog

    configure_material_catalog(PersistentOntologyStore(ROOT / "ontology" / "index0.owl").load_datasets().get("materials") or [])
    import pygame

    pygame.init()
    pygame.display.set_mode((1, 1))
    for name in names:
        if not args.render_only:
            run_world(name, out_dir)
        render_world(name, out_dir)
    compose(out_dir, names)


if __name__ == "__main__":
    main()
