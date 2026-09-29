"""Render a fixed-seed geophyte/control comparison from the live ontology."""

import json
from pathlib import Path
from types import SimpleNamespace

import pygame

from simulations.species.species_renderer import (
    DiagnosticCamera,
    SpeciesRenderer,
    diagnostic_cell_bounds,
)
from simulations.species.species_simulation import SpeciesSimulation
from world.entity_loader import EntityLoader


SPECIES_ID = "spec_codonorhiza_elandsmontana"
TREE_IDS = (
    "spec_betula_pendula",
    "spec_quercus_robur",
    "spec_aesculus_hippocastanum",
)


def _union(bounds):
    return (
        min(item[0] for item in bounds), max(item[1] for item in bounds),
        min(item[2] for item in bounds), max(item[3] for item in bounds),
    )


def main():
    output = Path("artifacts/codonorhiza_geophyte_v001")
    output.mkdir(parents=True, exist_ok=True)
    loader = EntityLoader()
    entity = loader.entities[SPECIES_ID]
    trees = [loader.entities[item] for item in TREE_IDS]
    actual = SpeciesSimulation(species_entity=entity, seed=303)
    control = SpeciesSimulation(species_entity={
        **entity,
        "plant_life_form": "other_unknown",
        "belowground_storage": [],
    }, seed=303)
    for simulation in (actual, control):
        simulation.set_lod(2)
        simulation.set_age(simulation.mature_age_days)

    pygame.init()
    pygame.display.set_mode((1, 1))
    renderer = SpeciesRenderer(SimpleNamespace(camera=None))
    title = pygame.font.SysFont("consolas", 25)
    font = pygame.font.SysFont("consolas", 17)
    small = pygame.font.SysFont("consolas", 14)
    canvas = pygame.Surface((1600, 1080))
    canvas.fill((13, 18, 17))
    canvas.blit(title.render("Plant life form now changes the growth origin", True, (232, 239, 225)), (24, 18))
    canvas.blit(font.render(
        "Birch, oak, horse chestnut: phanerophyte | Elandsberg paintpetal: geophyte",
        True, (177, 199, 180)), (24, 54),
    )
    canvas.blit(small.render(
        "Same species, seed 303, mature age and LOD 2 in both columns. Only life form / supporting organ are overridden in the control.",
        True, (157, 179, 163)), (24, 80),
    )

    cases = ((control, "CONTROL | surface-origin grammar"), (actual, "LIVE ONTOLOGY | geophyte + corm"))
    whole_bounds = _union([diagnostic_cell_bounds(case.render_snapshot) for case, _ in cases])
    # Deliberately use one tight physical frame for the renewal zone.  A full
    # root fit makes a 10–15 mm corm only a few pixels wide and hides the field
    # effect we are trying to judge.
    root_bounds = (-0.16, 0.16, -0.14, 0.06)
    for column, (simulation, caption) in enumerate(cases):
        left = column * 800
        canvas.blit(font.render(caption, True, (225, 207, 125) if column else (190, 198, 188)), (left + 24, 116))

        whole = pygame.Surface((780, 470))
        renderer._draw_individual(
            whole, simulation,
            camera=DiagnosticCamera(whole.get_width(), whole.get_height(), whole_bounds),
        )
        canvas.blit(whole, (left + 10, 150))

        roots = pygame.Surface((780, 340))
        renderer._draw_individual(
            roots, simulation,
            camera=DiagnosticCamera(roots.get_width(), roots.get_height(), root_bounds),
            roots_only=True,
        )
        canvas.blit(roots, (left + 10, 660))
        canvas.blit(small.render("MATCHED RENEWAL-ZONE DETAIL", True, (219, 205, 139)), (left + 24, 674))
        stats = simulation.render_snapshot.stats
        description = (
            f"bud depth {stats['renewal_bud_depth_m']:.3f} m | "
            f"organ {stats['renewal_organ_kind']} | roots begin z={stats['root_growth_origin_z_m']:.3f} m"
        )
        canvas.blit(small.render(description, True, (212, 220, 204)), (left + 24, 1018))

    pygame.draw.line(canvas, (91, 111, 98), (800, 104), (800, 1050), 1)
    pygame.image.save(canvas, output / "life_form_comparison.png")

    result = {
        "species_id": SPECIES_ID,
        "comparison_trees": {
            row["id"]: row.get("plant_life_form") for row in trees
        },
        "control": control.render_snapshot.stats,
        "geophyte": actual.render_snapshot.stats,
        "field_contract": {
            "plant_life_form": "locates the renewal bud",
            "belowground_storage": "names the supporting organ without being inferred from life form",
            "renewal_bud_depth": "runtime default pending an authored measurement",
        },
    }
    (output / "life_form_comparison_metrics.json").write_text(
        json.dumps(result, indent=2), encoding="utf-8",
    )
    pygame.quit()
    print((output / "life_form_comparison.png").resolve())


if __name__ == "__main__":
    main()
