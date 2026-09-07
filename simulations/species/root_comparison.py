"""Cross-species Roots comparison for the developed live plant catalogue."""
import math
from pathlib import Path

import pygame

from world.plant_catalogue import PlantCatalogue


def comparison_entities(datasets):
    entities = {e['id']: e for rows in datasets.values() for e in rows if e.get('id')}
    catalogue = PlantCatalogue.build(entities)
    candidates = [entities[sid] for sid in catalogue.species_ids
                  if entities[sid].get('plant_growth_behaviour')]
    known = {'taproot', 'fibrous', 'mixed', 'adventitious'}
    return sorted(candidates, key=lambda e: (e.get('root_architecture') not in known, e['id']))


def build_root_comparison(datasets=None):
    from world.persistent_ontology_store import PersistentOntologyStore
    from simulations.species.species_simulation import SpeciesSimulation
    if datasets is None:
        datasets = PersistentOntologyStore(Path(__file__).resolve().parents[2]/'ontology/index0.owl').load_datasets()
    cases = []
    for entity in comparison_entities(datasets):
        sim = SpeciesSimulation(species_entity=entity, seed=303)
        sim.set_lod(2)
        sim.set_age(sim.mature_age_days)
        cases.append(sim)
    return cases


def draw_root_comparison(renderer, screen, cases, page=0, common_scale=False):
    from simulations.species.species_renderer import DiagnosticCamera, root_diagnostic_bounds
    w, h = screen.get_size()
    screen.fill((15, 22, 19))
    font = pygame.font.SysFont('consolas', 15)
    title = pygame.font.SysFont('consolas', 23)
    small = pygame.font.SysFont('consolas', 13)
    def text(value, xy, f=font, color=(214, 222, 201)):
        screen.blit(f.render(value, True, color), xy)
    pages = max(1, math.ceil(len(cases)/6))
    selected = cases[(page % pages)*6:(page % pages+1)*6]
    text('Root comparison | developed plants', (18, 30), title)
    mode = 'same physical scale' if common_scale else 'each root system enlarged to fit'
    text(f'{mode} | maturity 100% | seed 303 | page {page % pages+1}/{pages}', (18, 64))
    text('R: individual comparison   S: change scale   Left / Right: page', (18, 88), small)
    bounds = [root_diagnostic_bounds(s.render_snapshot) for s in cases if s.render_snapshot.stats.get('root_segment_count')]
    shared = (min((b[0] for b in bounds), default=-1), max((b[1] for b in bounds), default=1),
              min((b[2] for b in bounds), default=-1), max((b[3] for b in bounds), default=.1))
    cw, ch = w//3, max(160, (h-300)//2)
    for i, sim in enumerate(selected):
        x, y = (i%3)*cw, 120+(i//3)*ch
        stats = sim.render_snapshot.stats
        text(sim.blueprint.display_name.split(' - ')[0], (x+16, y+8))
        text(f"{stats['root_architecture']} | {sim.blueprint.growth.get('root_depth_class') or 'depth unset'}", (x+16, y+32), small)
        pygame.draw.rect(screen, (55, 65, 51), (x+5, y, cw-10, ch-5), 1)
        if not stats.get('root_segment_count'):
            text('Root traits missing', (x+18, y+90))
            text('No root system inferred from the species name.', (x+18, y+116), small)
            continue
        panel = pygame.Surface((cw-24, ch-98))
        camera = DiagnosticCamera(panel.get_width(), panel.get_height(), shared if common_scale else root_diagnostic_bounds(sim.render_snapshot))
        renderer._draw_individual(panel, sim, camera=camera, roots_only=True)
        screen.blit(panel, (x+12, y+53))
        target = 65/camera.scale
        unit = 10**math.floor(math.log10(target))
        bar = max(v*unit for v in (1, 2, 5) if v*unit <= target)
        by = y+ch-27
        pygame.draw.line(screen, (204, 202, 171), (x+18, by), (x+18+round(bar*camera.scale), by), 2)
        text(f'{bar:g} m', (x+90, by-9), small)
        text(f"depth {stats['root_depth_m']:.2f} m", (x+cw-155, by-9), small)
    text('Brown coarse axes, lighter fine roots and tips; rhizomes remain separate stem organs.', (18, h-166), small)
    text('Diameter / colour are visual defaults. Depth classes are proxies unless a measured maximum is authored.', (18, h-144), small)
