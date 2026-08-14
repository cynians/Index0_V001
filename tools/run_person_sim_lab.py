"""Run the real Person Simulation in a deterministic shared test laboratory.

This harness intentionally contains no person-simulation or rendering logic.
It imports the production PersonSimulation, PersonRenderer, and Camera classes,
supplies ontology-shaped fixture entities, sends scripted public commands, and
writes inspectable artifacts. Consequently, rerunning it always reflects the
current implementation rather than a separately maintained mock.
"""

import argparse
import hashlib
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
from ui.ui_manager import UIManager


DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "artifacts" / "person_sim_lab"
SCREEN_SIZE = (1200, 800)
IMPLEMENTATION_SOURCES = (
    PROJECT_ROOT / "simulations" / "person" / "person_simulation.py",
    PROJECT_ROOT / "simulations" / "person" / "person_renderer.py",
    PROJECT_ROOT / "engine" / "clock.py",
    PROJECT_ROOT / "engine" / "simulation_manager.py",
    PROJECT_ROOT / "engine" / "camera.py",
    PROJECT_ROOT / "ui" / "ui_manager.py",
)


class LabWorld:
    """Small ontology-shaped projection used only as deterministic input."""

    def __init__(self):
        self.entities = {
            "person_lab_worker": {
                "id": "person_lab_worker",
                "type": "person",
                "_dataset": "people",
                "pretty_name": "Laboratory Worker",
                "person_class": "test person",
                "employment_assignments": ["employment_lab_farmer"],
                "affiliated_institutions": ["institution_person_sim_lab"],
                "associated_locations": ["location_person_sim_lab"],
                "wishes": ["Eat a quiet meal with colleagues"],
                "goals": ["Establish a dependable harvest"],
                "big_five_openness": 0.72,
                "big_five_conscientiousness": 0.84,
                "big_five_extraversion": 0.38,
                "big_five_agreeableness": 0.67,
                "big_five_neuroticism": 0.29,
                "personality_adjectives": ["curious", "dutiful", "reserved"],
            },
            "employment_lab_farmer": {
                "id": "employment_lab_farmer",
                "type": "employment",
                "_dataset": "employments",
                "pretty_name": "Laboratory Farming Assignment",
                "job": "job_lab_subsistence_farmer",
                "employed_people": ["person_lab_worker"],
                "production_context": "producer_lab_farm",
                "production_line_id": "line_lab_food",
            },
            "job_lab_subsistence_farmer": {
                "id": "job_lab_subsistence_farmer",
                "type": "job",
                "_dataset": "jobs",
                "pretty_name": "Subsistence Farmer",
                "job_subtype": "subsistence farmer",
            },
            "institution_person_sim_lab": {
                "id": "institution_person_sim_lab",
                "type": "institution",
                "_dataset": "institutions",
                "pretty_name": "Person Simulation Laboratory",
            },
            "location_person_sim_lab": {
                "id": "location_person_sim_lab",
                "type": "location",
                "_dataset": "locations",
                "pretty_name": "Person Simulation Test Map",
                "location_class": "test_map",
            },
            "producer_lab_farm": {
                "id": "producer_lab_farm",
                "type": "producer",
                "_dataset": "producers",
                "pretty_name": "Laboratory Farm",
                "production_lines": [
                    {
                        "line_id": "line_lab_food",
                        "product_id": "item_lab_food",
                        "job_ids": ["job_lab_subsistence_farmer"],
                        "employment_ids": ["employment_lab_farmer"],
                        "employed_technology_ids": [],
                    }
                ],
            },
            "item_lab_food": {
                "id": "item_lab_food",
                "type": "item",
                "_dataset": "items",
                "pretty_name": "Laboratory Food",
            },
        }

    def get_entity(self, entity_id):
        return self.entities.get(entity_id)

    def get_timeline_items(self):
        return []


def _implementation_provenance():
    source_hashes = {}
    combined = hashlib.sha256()
    for path in IMPLEMENTATION_SOURCES:
        relative = path.relative_to(PROJECT_ROOT).as_posix()
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        source_hashes[relative] = digest
        combined.update(relative.encode("utf-8"))
        combined.update(digest.encode("ascii"))
    return {
        "fingerprint": combined.hexdigest(),
        "source_hashes": source_hashes,
    }


def _snapshot(simulation, label):
    active = dict(simulation.active_task or {})
    return {
        "label": label,
        "implementation": {
            "simulation_class": f"{simulation.__class__.__module__}.{simulation.__class__.__name__}",
            "runtime_system_class": f"{simulation.system.__class__.__module__}.{simulation.system.__class__.__name__}",
        },
        "control_mode": simulation.control_mode,
        "position": [round(value, 4) for value in simulation.position],
        "needs": {key: round(value, 3) for key, value in simulation.needs.items()},
        "work_due": round(simulation.work_due, 3),
        "completed_jobs": simulation.completed_jobs,
        "active_task": {
            key: value
            for key, value in active.items()
            if key in {"point_id", "label", "source", "phase", "maslow_tier"}
        } or None,
        "queue": [
            {
                key: value
                for key, value in task.items()
                if key in {"point_id", "label", "source", "phase", "maslow_tier"}
            }
            for task in simulation.task_queue
        ],
        "status": simulation.last_status,
    }


def _advance(simulation, simulation_seconds):
    """Advance through the production Clock -> SimulationManager -> System path."""
    tick_seconds = float(simulation.sim_clock.get_dt())
    tick_count = max(0, int(round(float(simulation_seconds) / tick_seconds)))
    for _ in range(tick_count):
        simulation.update(simulation.sim_clock.tick_interval)


def _click_world(simulation, camera, world_position, button=1):
    """Send the same pointer event that the application routes to the simulation."""
    screen_position = camera.world_to_screen(world_position)
    event = pygame.event.Event(
        pygame.MOUSEBUTTONDOWN,
        {"button": button, "pos": screen_position},
    )
    simulation.handle_pointer_event(event, camera, screen_position)


def _render(renderer, simulation, output_path):
    surface = pygame.Surface(SCREEN_SIZE)
    renderer.draw(surface, simulation)
    pygame.image.save(surface, str(output_path))


def _render_with_ui(renderer, ui_manager, simulation, camera, output_path, panel_mode):
    surface = pygame.Surface(SCREEN_SIZE)
    renderer.draw(surface, simulation)
    ui_manager.person_panel_mode = panel_mode
    ui_manager.rebuild_for_state(
        active_sim=simulation,
        app_width=SCREEN_SIZE[0],
        app_height=SCREEN_SIZE[1],
        camera=camera,
    )
    ui_manager.draw(surface, ui_manager.app_font)
    pygame.image.save(surface, str(output_path))


def run_lab(output_dir=DEFAULT_OUTPUT_DIR):
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    pygame.init()
    pygame.font.init()
    camera = Camera(*SCREEN_SIZE)
    app_view = SimpleNamespace(
        camera=camera,
        default_font=pygame.font.SysFont("consolas", 16),
    )
    renderer = PersonRenderer(app_view)
    ui_manager = UIManager()
    world = LabWorld()
    simulation = PersonSimulation(
        world_model=world,
        person_entity_id="person_lab_worker",
        year=2400,
    )
    camera.x, camera.y = simulation.get_center()
    camera.zoom = simulation.get_initial_camera_zoom(*SCREEN_SIZE)

    report = {
        "lab_contract": "Imports and executes the production person simulation and renderer.",
        "implementation_provenance": _implementation_provenance(),
        "fixture_person_id": simulation.person_entity_id,
        "artifacts": {},
        "snapshots": [],
    }

    initial_path = output_dir / "01_autonomous_initial.png"
    report["snapshots"].append(_snapshot(simulation, "autonomous_initial"))
    _render(renderer, simulation, initial_path)
    report["artifacts"]["autonomous_initial"] = initial_path.name

    _advance(simulation, 11.0)
    autonomous_path = output_dir / "02_autonomous_running.png"
    report["snapshots"].append(_snapshot(simulation, "autonomous_running"))
    _render(renderer, simulation, autonomous_path)
    report["artifacts"]["autonomous_running"] = autonomous_path.name

    _click_world(simulation, camera, simulation.test_points["bed"]["position"])
    _advance(simulation, 2.0)
    forced_path = output_dir / "03_player_forced_queue.png"
    report["snapshots"].append(_snapshot(simulation, "player_forced_queue"))
    _render(renderer, simulation, forced_path)
    report["artifacts"]["player_forced_queue"] = forced_path.name

    simulation.set_control_mode(simulation.CONTROL_DIRECT)
    _click_world(simulation, camera, (5.0, 3.0))
    _advance(simulation, 1.0)
    direct_path = output_dir / "04_direct_control.png"
    report["snapshots"].append(_snapshot(simulation, "direct_control"))
    _render(renderer, simulation, direct_path)
    report["artifacts"]["direct_control"] = direct_path.name

    needs_path = output_dir / "05_needs_panel.png"
    _render_with_ui(renderer, ui_manager, simulation, camera, needs_path, "needs")
    report["artifacts"]["needs_panel"] = needs_path.name
    report["needs_panel_model"] = simulation.get_needs_panel_model()

    personality_path = output_dir / "06_personality_panel.png"
    _render_with_ui(renderer, ui_manager, simulation, camera, personality_path, "personality")
    report["artifacts"]["personality_panel"] = personality_path.name
    report["personality_panel_model"] = simulation.get_personality_panel_model()

    report_path = output_dir / "person_sim_lab_report.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    pygame.quit()
    return report_path


def check_current(output_dir=DEFAULT_OUTPUT_DIR):
    report_path = Path(output_dir).resolve() / "person_sim_lab_report.json"
    if not report_path.exists():
        return False, "No lab report exists; run the laboratory first."
    report = json.loads(report_path.read_text(encoding="utf-8"))
    recorded = (report.get("implementation_provenance") or {}).get("fingerprint")
    current = _implementation_provenance()["fingerprint"]
    if recorded != current:
        return False, "Lab artifacts are stale; rerun the laboratory."
    return True, "Lab artifacts match the current production implementation."


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory receiving screenshots and the JSON trace.",
    )
    parser.add_argument(
        "--check-current",
        action="store_true",
        help="Fail if existing artifacts do not match current production sources.",
    )
    args = parser.parse_args()
    if args.check_current:
        current, message = check_current(args.output_dir)
        print(message)
        raise SystemExit(0 if current else 1)
    report_path = run_lab(args.output_dir)
    print(report_path)


if __name__ == "__main__":
    main()
