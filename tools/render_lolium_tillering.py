"""Reproduce Lolium diagnostics from live data and labelled trait overrides."""
import json
from pathlib import Path
from types import SimpleNamespace

import pygame

from world.persistent_ontology_store import PersistentOntologyStore
from simulations.species.plant_assets import PlantGrowthSnapshot
from simulations.species.species_simulation import SpeciesSimulation
from simulations.species.species_renderer import SpeciesRenderer, DiagnosticCamera, diagnostic_cell_bounds


def main():
    out = Path('artifacts/lolium_tillering')
    out.mkdir(parents=True, exist_ok=True)
    entity = next(e for e in PersistentOntologyStore(Path('ontology/index0.owl')).load_datasets()['species']
                  if e['id'] == 'spec_lolium_perenne')
    pygame.init()
    pygame.display.set_mode((1, 1))
    renderer = SpeciesRenderer(SimpleNamespace(camera=None))
    font = pygame.font.SysFont('consolas', 19)
    title = pygame.font.SysFont('consolas', 28)

    def sim_for(**overrides):
        sim = SpeciesSimulation(species_entity={**entity, **overrides}, seed=101)
        sim.lod = 1
        sim.set_age(200)
        return sim

    def label(surface, text, xy, large=False):
        surface.blit((title if large else font).render(text, True, (218, 231, 207)), xy)

    def union(snapshots):
        bounds = [diagnostic_cell_bounds(s) for s in snapshots]
        return min(b[0] for b in bounds), max(b[1] for b in bounds), min(b[2] for b in bounds), max(b[3] for b in bounds)

    sim = sim_for()
    baseline = PlantGrowthSnapshot.from_dict(json.loads((out/'baseline_snapshot.json').read_text(encoding='utf-8')))
    sheet = pygame.Surface((1600, 1000))
    sheet.fill((15, 22, 19))
    label(sheet, 'Perennial ryegrass | tillering diagnostics', (24, 20), True)
    label(sheet, '200 days | seed 101 | normal detail | matched physical scale', (24, 62))
    bounds = union([baseline, sim.render_snapshot])
    for i, (snapshot, caption) in enumerate(((baseline, 'BEFORE | one culm, 4 leaves'),
                                           (sim.render_snapshot, 'AFTER | 9 tillers, 27 leaves, 9 spikes'))):
        panel = pygame.Surface((780, 800))
        renderer._draw_individual(panel, sim, snapshot=snapshot, camera=DiagnosticCamera(780, 800, bounds))
        sheet.blit(panel, (10+i*800, 115))
        label(sheet, caption, (24+i*800, 95))
    label(sheet, 'Low clonal spread: compact tuft. Flowering organs remain visible at normal detail.', (24, 945))
    pygame.image.save(sheet, out/'diagnostics.png')

    panel = pygame.Surface((1600, 1000))
    renderer._draw_gallery(panel, sim)
    pygame.image.save(panel, out/'growth_gallery.png')
    renderer._draw_roots(panel, sim)
    pygame.image.save(panel, out/'roots.png')

    cases = [sim_for(clonal_spread=value) for value in ('none', 'low', 'moderate', 'high')]
    bounds = union([s.render_snapshot for s in cases])
    sheet = pygame.Surface((1800, 880)); sheet.fill((15, 22, 19))
    label(sheet, 'Clonal spread | experimental overrides, same age / seed / scale', (24, 20), True)
    records = {}
    for i, (value, case) in enumerate(zip(('none', 'low', 'moderate', 'high'), cases)):
        panel = pygame.Surface((440, 650))
        renderer._draw_individual(panel, case, camera=DiagnosticCamera(440, 650, bounds))
        sheet.blit(panel, (i*450, 100))
        label(sheet, value.upper() + (' (authored)' if value == 'low' else ' (override)'), (i*450+20, 76))
        stats = case.render_snapshot.stats
        label(sheet, f"Tiller radius: {stats['tiller_radius_m']:.3f} m", (i*450+20, 780))
        label(sheet, f"{stats['tiller_count']} tillers | {stats['estimated_leaf_count']} leaves", (i*450+20, 815))
        records[value] = stats
    pygame.image.save(sheet, out/'spread_comparison.png')

    sheet = pygame.Surface((1400, 650)); sheet.fill((15, 22, 19))
    label(sheet, 'Disturbance response | matched Lolium trait overrides', (24, 25), True)
    label(sheet, '200 days | disturbance 0.6 | longer bar = higher vitality', (24, 70))
    response = {}
    for i, value in enumerate(('absent', 'weak', 'moderate', 'strong', 'other_unknown')):
        case = sim_for(resprouting=value)
        outcome = case.get_ecological_outcome({'disturbance': .6})
        response[value] = outcome
        y = 140+i*82
        label(sheet, value + (' (authored)' if value == 'strong' else ''), (24, y))
        pygame.draw.rect(sheet, (47, 68, 48), (290, y, 800, 28))
        pygame.draw.rect(sheet, (130, 177, 89), (290, y, round(800*outcome['vitality']), 28))
        label(sheet, f"{outcome['vitality']:.3f}", (1120, y))
        label(sheet, f"penalty {outcome['disturbance_penalty']:.2f}", (1190, y))
    label(sheet, 'Qualitative response coefficients; no event timing or post-grazing regrowth trajectory.', (24, 590))
    pygame.image.save(sheet, out/'disturbance_comparison.png')
    (out/'results.json').write_text(json.dumps({'spread': records, 'disturbance': response}, indent=2), encoding='utf-8')
    pygame.quit()
    print(out.resolve())


if __name__ == '__main__':
    main()
