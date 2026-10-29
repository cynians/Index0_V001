"""Render the actual cross-species Compare view and save its live inputs."""
import json
import math
from pathlib import Path
from types import SimpleNamespace

import pygame

from simulations.species.root_comparison import build_root_comparison
from simulations.species.species_renderer import SpeciesRenderer


def main():
    out = Path('artifacts/root_visuals_after')
    out.mkdir(parents=True, exist_ok=True)
    pygame.init(); pygame.display.set_mode((1, 1))
    cases = build_root_comparison()
    renderer = SpeciesRenderer(SimpleNamespace(camera=None))
    host = cases[0]
    host.diagnostic_view = 'compare'
    host.comparison_subject = 'roots'
    host._root_comparison_cases = cases
    for shared in (False, True):
        host.root_comparison_common_scale = shared
        for page in range(math.ceil(len(cases)/6)):
            host.root_comparison_page = page
            screen = pygame.Surface((1800, 1100))
            renderer._draw_compare(screen, host)
            pygame.image.save(screen, out/f"compare_{'shared' if shared else 'detail'}_{page+1}.png")
    records = [{'species_id': s.species_id, 'root_profile': s.blueprint.growth['root_profile'],
                'visual_profile': s.blueprint.growth['root_visual_profile'], 'stats': s.render_snapshot.stats}
               for s in cases]
    (out/'functional_plants.json').write_text(json.dumps(records, indent=2), encoding='utf-8')
    pygame.quit()
    print([s.species_id for s in cases])


if __name__ == '__main__':
    main()
