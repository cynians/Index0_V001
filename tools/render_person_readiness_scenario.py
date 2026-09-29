"""Cycle-1 visual check for person data-completeness readiness.

Reuses the production LabWorld fixture from run_person_sim_lab.py (the same
ontology-shaped worker used by docs/person_sim_lab.md) as the "authored"
reference, and adds two additional fixture people -- a partially authored
stub and a blank one -- to render the three readiness tiers side by side
through the real PersonSimulation and PersonRenderer.
"""

import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pygame

from engine.camera import Camera
from simulations.person.person_renderer import PersonRenderer
from simulations.person.person_simulation import PersonSimulation
from tools.run_person_sim_lab import LabWorld

SCREEN_SIZE = (1200, 800)
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "artifacts" / "person_readiness_scenario"

SPARSE_STUB_ID = "person_readiness_sparse_stub"
EMPTY_STUB_ID = "person_readiness_empty_stub"


def _augment_world(world):
    world.entities[SPARSE_STUB_ID] = {
        "id": SPARSE_STUB_ID,
        "type": "person",
        "_dataset": "people",
        "pretty_name": "Unplaced Stranger",
        "affiliated_institutions": ["institution_person_sim_lab"],
        "knowledge_records": [{"entity": "location_person_sim_lab", "interest": 0.4}],
    }
    world.entities[EMPTY_STUB_ID] = {
        "id": EMPTY_STUB_ID,
        "type": "person",
        "_dataset": "people",
    }
    return world


def _render_scenario(renderer, camera, world, person_id, output_path):
    simulation = PersonSimulation(world_model=world, person_entity_id=person_id, year=2400)
    camera.x, camera.y = simulation.get_center()
    camera.zoom = simulation.get_initial_camera_zoom(*SCREEN_SIZE)
    surface = pygame.Surface(SCREEN_SIZE)
    renderer.draw(surface, simulation)
    pygame.image.save(surface, str(output_path))
    return simulation.get_character_creation_panel_model()


def run(output_dir=DEFAULT_OUTPUT_DIR):
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    pygame.init()
    pygame.font.init()
    camera = Camera(*SCREEN_SIZE)
    app_view = SimpleNamespace(
        camera=camera,
        default_font=pygame.font.SysFont("consolas", 16),
        width=SCREEN_SIZE[0],
        height=SCREEN_SIZE[1],
    )
    renderer = PersonRenderer(app_view)
    world = _augment_world(LabWorld())

    scenarios = (
        ("authored", "person_lab_worker", "01_authored_mara_voss.png"),
        ("sparse", SPARSE_STUB_ID, "02_sparse_unplaced_stranger.png"),
        ("empty", EMPTY_STUB_ID, "03_empty_stub.png"),
    )

    report = {}
    for expected_tier, person_id, filename in scenarios:
        readiness = _render_scenario(renderer, camera, world, person_id, output_dir / filename)
        report[expected_tier] = {
            "person_id": person_id,
            "screenshot": filename,
            **readiness,
        }
        print(f"{expected_tier}: tier={readiness['tier']} score={readiness['score']:.2f} missing={readiness['missing']}")

    # Cycle 2 refinement: asset placer walkthrough, using the empty stub
    # (guaranteed to be in_void) as the blank canvas.
    placer_sim = PersonSimulation(world_model=world, person_entity_id=EMPTY_STUB_ID, year=2400)
    camera.x, camera.y = placer_sim.get_center()
    camera.zoom = placer_sim.get_initial_camera_zoom(*SCREEN_SIZE)

    placer_sim.select_asset_for_placement("food")
    surface = pygame.Surface(SCREEN_SIZE)
    renderer.draw(surface, placer_sim)
    pygame.image.save(surface, str(output_dir / "04_placement_mode_selected_food.png"))

    placer_sim.place_selected_asset((40.0, -30.0))
    surface = pygame.Surface(SCREEN_SIZE)
    renderer.draw(surface, placer_sim)
    pygame.image.save(surface, str(output_dir / "05_after_placing_food_at_new_position.png"))
    report["placement_walkthrough"] = {
        "person_id": EMPTY_STUB_ID,
        "screenshots": ["04_placement_mode_selected_food.png", "05_after_placing_food_at_new_position.png"],
        "placed_food_position": list(placer_sim.test_points["food"]["position"]),
        "placed_flag": placer_sim.test_points["food"]["placed"],
    }

    (output_dir / "person_readiness_report.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )
    pygame.quit()
    return report


if __name__ == "__main__":
    run()
