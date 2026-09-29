"""Compare three live-ontology root candidates using the Species Sim renderer."""
import argparse
import json
import math
from pathlib import Path
from types import SimpleNamespace

import pygame

from simulations.species.species_renderer import SpeciesRenderer, DiagnosticCamera, diagnostic_cell_bounds, root_diagnostic_bounds
from simulations.species.species_simulation import SpeciesSimulation
from world.persistent_ontology_store import PersistentOntologyStore


CANDIDATES = ("spec_quercus_robur", "spec_lolium_perenne", "spec_nymphaea_alba")


def root_bounds(snapshot):
    return root_diagnostic_bounds(snapshot)


def render(output):
    output.mkdir(parents=True, exist_ok=True)
    pygame.init()
    pygame.display.set_mode((1, 1))
    rows = PersistentOntologyStore(Path("ontology/index0.owl")).load_datasets()["species"]
    entities = {row["id"]: row for row in rows}
    renderer = SpeciesRenderer(SimpleNamespace(camera=None))
    sheet = pygame.Surface((1440, 960))
    sheet.fill((18, 23, 20))
    font = pygame.font.SysFont("consolas", 17)
    title = pygame.font.SysFont("consolas", 23)
    sheet.blit(title.render("Root architecture | three ontology candidates", True, (235, 239, 226)), (24, 16))
    sheet.blit(font.render("Independent view scales. Dimensions are runtime proxies; no measured depths are authored.", True, (180, 191, 180)), (24, 52))
    records = []
    mature_sims = []
    growth_sheet = pygame.Surface((1440, 900))
    growth_sheet.fill((18, 23, 20))
    for col, species_id in enumerate(CANDIDATES):
        entity = entities[species_id]
        sim = SpeciesSimulation(species_entity=entity, seed=303)
        sim.set_age(sim.mature_age_days)
        name = entity["common_name"].split(" - ")[0]
        x = col * 480
        sheet.blit(title.render(name, True, (230, 238, 226)), (x + 20, 92))
        label = f"{entity['root_architecture']} / {entity['root_depth_class']}"
        sheet.blit(font.render(label, True, (177, 198, 173)), (x + 20, 126))
        for y, roots_only, height in ((154, False, 330), (524, True, 300)):
            panel = pygame.Surface((460, height))
            bounds = root_bounds(sim.render_snapshot) if roots_only else diagnostic_cell_bounds(sim.render_snapshot)
            camera = DiagnosticCamera(460, height, bounds)
            renderer._draw_individual(panel, sim, camera=camera, roots_only=roots_only)
            # Scale bar is projected horizontal distance, in metres.
            bar = 10 ** math.floor(math.log10(100 / camera.scale))
            pygame.draw.line(panel, (216, 216, 186), (20, height - 16), (20 + round(bar * camera.scale), height - 16), 2)
            panel.blit(font.render(f"{bar:g} m", True, (216, 216, 186)), (20, height - 40))
            sheet.blit(panel, (x + 10, y))
        sheet.blit(font.render("Root detail (enlarged)", True, (230, 238, 226)), (x + 20, 495))
        stats = sim.get_growth_summary()
        mature_sims.append(SpeciesSimulation(species_entity=entity, seed=303))
        mature_sims[-1].set_age(mature_sims[-1].mature_age_days)
        sim.set_active_simulation_panel_tab("roots")
        root_view = pygame.Surface((1200, 800))
        renderer.draw(root_view, sim)
        pygame.image.save(root_view, output / f"{species_id}_roots.png")
        for i, line in enumerate((f"Depth below crown: {stats['root_depth_m']:.2f} m",
                                  f"Radial diameter: {stats['root_spread_m']:.2f} m",
                                  f"Representative axes: {stats['root_length_m']:.2f} m",
                                  f"Depth source: {stats['root_depth_source']}")):
            sheet.blit(font.render(line, True, (192, 203, 188)), (x + 20, 839 + i * 26))
        stages = []
        for row, fraction in enumerate((0.1, 0.4, 1.0)):
            sim.set_age(sim.mature_age_days * fraction)
            stages.append(sim.get_growth_summary())
            panel = pygame.Surface((460, 252))
            # Reuse the mature bounds so growth remains comparable within a column.
            camera = DiagnosticCamera(460, 252, bounds)
            renderer._draw_individual(panel, sim, camera=camera, roots_only=True)
            growth_sheet.blit(panel, (x + 10, row * 300 + 40))
            growth_sheet.blit(font.render(f"{name} | maturity {fraction:.0%}", True, (223, 233, 216)), (x + 18, row * 300 + 12))
        records.append({"species_id": species_id, "source": "live_quadstore_decoded_projection",
                        "traits": {k: entity.get(k) for k in ("root_architecture", "root_depth_class", "max_root_depth")},
                        "root_profile": sim.blueprint.growth["root_profile"], "mature": stats, "stages": stages})
    pygame.image.save(sheet, output / "root_comparison.png")
    pygame.image.save(growth_sheet, output / "root_growth_stages.png")
    common_sheet = pygame.Surface((1440, 460))
    common_sheet.fill((18, 23, 20))
    all_bounds = [root_bounds(sim.render_snapshot) for sim in mature_sims]
    common_bounds = (min(b[0] for b in all_bounds), max(b[1] for b in all_bounds),
                     min(b[2] for b in all_bounds), max(b[3] for b in all_bounds))
    for col, sim in enumerate(mature_sims):
        panel = pygame.Surface((460, 340))
        camera = DiagnosticCamera(460, 340, common_bounds)
        renderer._draw_individual(panel, sim, camera=camera, roots_only=True)
        pygame.draw.line(panel, (216, 216, 186), (20, 320), (20 + round(camera.scale), 320), 2)
        panel.blit(font.render("1 m", True, (216, 216, 186)), (20, 295))
        common_sheet.blit(panel, (col * 480 + 10, 100))
        common_sheet.blit(font.render(sim.blueprint.display_name.split(" - ")[0], True, (223, 233, 216)), (col * 480 + 20, 70))
    common_sheet.blit(title.render("Roots at the same scale | runtime depth-class dimensions", True, (223, 233, 216)), (20, 20))
    pygame.image.save(common_sheet, output / "root_common_scale.png")
    (output / "root_comparison.json").write_text(json.dumps(records, indent=2), encoding="utf-8")
    pygame.quit()
    print(output.resolve())


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("artifacts/root_comparison"))
    render(parser.parse_args().output)
