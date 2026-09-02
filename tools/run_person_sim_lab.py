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
from simulations.map.map_renderer import MapRenderer
from simulations.map.map_simulation import MapSimulation
from simulations.person.person_renderer import PersonRenderer
from simulations.person.person_simulation import PersonSimulation
from simulations.person.site_simulation import SiteSimulation
from ui.ui_manager import UIManager
from world.world_model import WorldModel
from world.simulation_context import SimulationContext


DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "artifacts" / "person_sim_lab"
SCREEN_SIZE = (1200, 800)
IMPLEMENTATION_SOURCES = (
    PROJECT_ROOT / "tools" / "run_person_sim_lab.py",
    PROJECT_ROOT / "simulations" / "person" / "person_simulation.py",
    PROJECT_ROOT / "simulations" / "person" / "site_simulation.py",
    PROJECT_ROOT / "simulations" / "person" / "person_renderer.py",
    PROJECT_ROOT / "simulations" / "map" / "map_simulation.py",
    PROJECT_ROOT / "simulations" / "map" / "map_renderer.py",
    PROJECT_ROOT / "world" / "ownership_resolver.py",
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
                "is_employed_by": ["producer_lab_farm"],
                "is_employed_as": "job_lab_subsistence_farmer",
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
                "knowledge_records": [
                    {"entity": "person_lab_friend", "interest": 0.88, "familiarity": 0.82},
                    {"entity": "location_person_sim_lab", "interest": 0.61, "familiarity": 0.93},
                    {"entity": "institution_person_sim_lab", "interest": 0.73, "familiarity": 0.69},
                    {
                        "entity": "idea_lab_nonviolence",
                        "interest": 0.91,
                        "familiarity": 0.76,
                        "conviction": 0.96,
                        "stance": "deeply held",
                    },
                    {"entity": "technology_lab_irrigation", "interest": 0.79, "familiarity": 0.57},
                    {"entity": "recipe_simple_cooked_meal", "interest": 0.86, "familiarity": 0.81, "source": "learned recipe"},
                ],
            },
            "person_lab_friend": {
                "id": "person_lab_friend",
                "type": "person",
                "_dataset": "people",
                "pretty_name": "Mara, trusted colleague",
            },
            "idea_lab_nonviolence": {
                "id": "idea_lab_nonviolence",
                "type": "idea",
                "_dataset": "ideas",
                "pretty_name": "Covenant of Nonviolence",
                "behavioral_rules": {
                    "forbids": ["kill"],
                    "alternatives": {"kill": "Kitchen or medical duty"},
                },
            },
            "technology_lab_irrigation": {
                "id": "technology_lab_irrigation",
                "type": "technology",
                "_dataset": "technologies",
                "pretty_name": "Closed-loop irrigation",
            },
            "tech_cooking": {
                "id": "tech_cooking", "type": "technology", "_dataset": "technologies",
                "pretty_name": "Cooking",
            },
            "tech_electric_oven": {
                "id": "tech_electric_oven", "type": "technology", "_dataset": "technologies",
                "pretty_name": "Electric Oven Cooking", "parent_technology": "tech_cooking",
            },
            "component_kitchen_sink": {
                "id": "component_kitchen_sink", "type": "component", "_dataset": "components",
                "pretty_name": "Kitchen Sink",
            },
            "component_electric_oven": {
                "id": "component_electric_oven", "type": "component", "_dataset": "components",
                "pretty_name": "Electric Oven",
            },
            "item_food_ingredients": {
                "id": "item_food_ingredients", "type": "item", "_dataset": "items",
                "pretty_name": "Meal Ingredients", "item_class": "food ingredient",
                "inventory_unit": "portion", "stackable": True,
                "ownership_records": ["ownership_person_test_ingredients"],
            },
            "item_cooked_meal": {
                "id": "item_cooked_meal", "type": "item", "_dataset": "items",
                "pretty_name": "Simple Cooked Meal", "item_class": "prepared food",
                "inventory_unit": "meal", "stackable": True,
                "consumable": True, "food_satiation": 58,
            },
            "recipe_simple_cooked_meal": {
                "id": "recipe_simple_cooked_meal", "type": "recipe", "_dataset": "recipes",
                "pretty_name": "Simple Cooked Meal Recipe",
                "input_items": ["item_food_ingredients"], "output_items": ["item_cooked_meal"],
                "input_requirements": [{"item": "item_food_ingredients", "quantity": 1}],
                "output_yields": [{"item": "item_cooked_meal", "quantity": 1}],
                "required_technologies": ["tech_cooking", "tech_electric_oven"],
                "required_components": ["component_kitchen_sink", "component_electric_oven"],
            },
            "location_person_test_kitchen": {
                "id": "location_person_test_kitchen", "type": "location", "_dataset": "locations",
                "pretty_name": "Person Test Kitchen", "location_class": "building",
                "ownership_records": ["ownership_person_test_kitchen"],
            },
            "location_person_test_pantry": {
                "id": "location_person_test_pantry", "type": "location", "_dataset": "locations",
                "pretty_name": "Person Test Pantry", "location_class": "storage site",
                "inventory_items": [{"item": "item_food_ingredients", "quantity": 6}],
                "ownership_records": ["ownership_person_test_ingredients"],
            },
            "producer_person_test_kitchen": {
                "id": "producer_person_test_kitchen", "type": "producer", "_dataset": "producers",
                "pretty_name": "Person Test Kitchen", "producer_class": "kitchen",
                # Static stand-in for what EntityLoader.populate_employment_rosters()
                # would derive from person_lab_worker's is_employed_by in the real ontology.
                "employed_people": ["person_lab_worker"],
                "production_technologies": ["tech_cooking", "tech_electric_oven"],
                "assigned_components": ["component_kitchen_sink", "component_electric_oven"],
                "production_lines": [{
                    "line_id": "line_person_test_cooked_meal", "product_id": "item_cooked_meal",
                    "location_id": "location_person_test_kitchen",
                    "recipe_ids": ["recipe_simple_cooked_meal"],
                    "employed_technology_ids": ["tech_cooking", "tech_electric_oven"],
                    "assigned_component_ids": ["component_kitchen_sink", "component_electric_oven"],
                }],
            },
            "ownership_person_test_kitchen": {
                "id": "ownership_person_test_kitchen", "type": "ownership", "_dataset": "ownerships",
                "owner_entities": ["institution_person_sim_lab"],
                "owned_assets": ["location_person_test_kitchen"], "use_policy": "institutional",
                "permitted_users": ["institution_person_sim_lab"],
            },
            "ownership_person_test_ingredients": {
                "id": "ownership_person_test_ingredients", "type": "ownership", "_dataset": "ownerships",
                "owner_entities": ["institution_person_sim_lab"],
                "owned_assets": ["item_food_ingredients", "location_person_test_pantry"], "use_policy": "institutional",
                "permitted_users": ["institution_person_sim_lab"],
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
                # This stub is a plain dict, not routed through
                # EntityLoader.populate_employment_rosters(), so
                # employed_people has to be set by hand here to mirror what
                # the real derivation would compute from is_employed_by.
                "employed_people": ["person_lab_worker"],
                "production_lines": [
                    {
                        "line_id": "line_lab_food",
                        "product_id": "item_lab_food",
                        "job_ids": ["job_lab_subsistence_farmer"],
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
        self.entities["person_lab_worker"].update({
            "pretty_name": "Mara Voss",
            "sex": "female",
            "simulation_site": "location_lumber_test_site",
            "site_position": [25, -6],
            "residence": "location_lumber_test_barracks",
            "is_employed_by": ["producer_person_test_kitchen"],
            "is_employed_as": "job_lumber_site_cook",
            "is_employed_at": "location_person_test_kitchen",
            "associated_locations": ["location_lumber_test_site", "location_person_test_kitchen"],
        })
        self.entities["person_lab_worker"]["knowledge_records"].extend([
            {"entity": "location_lumber_test_barracks", "familiarity": 0.95, "navigation_knowledge": "route"},
            {"entity": "location_person_test_kitchen", "familiarity": 1.0, "navigation_knowledge": "route"},
            {"entity": "location_person_test_pantry", "familiarity": 0.9, "navigation_knowledge": "route"},
            {"entity": "location_lumber_test_factory", "familiarity": 0.35, "navigation_knowledge": "direction", "direction_hint": [1, 0.35]},
            {"entity": "location_lumber_test_woodlot", "familiarity": 0.25, "navigation_knowledge": "direction", "direction_hint": [-1, 0]},
        ])
        self.entities["location_person_test_kitchen"].update({
            "pretty_name": "Barracks Kitchen",
            "site_class": "kitchen",
            "building_class": "attached kitchen",
            "bounds": {"min_x": 20, "max_x": 30, "min_y": -10, "max_y": -2},
            "openings": [
                {"side": "north", "center": 25, "width": 3, "opening_class": "interior doorway"},
                {"side": "south", "center": 25, "width": 2, "opening_class": "exterior door"},
            ],
            "map_color": "#6e6252",
        })
        self.entities.update({
            "location_lumber_test_site": {
                "id": "location_lumber_test_site", "type": "location", "_dataset": "locations",
                "pretty_name": "Lumber Processing Test Site", "location_class": "site",
                "site_class": "industrial residential test site",
                "bounds": {"min_x": -44, "max_x": 46, "min_y": -27, "max_y": 27},
                "layout_structures": [
                    "location_lumber_test_barracks", "location_person_test_kitchen",
                    "location_lumber_test_storage", "location_lumber_test_factory",
                ],
                "resident_people": [
                    "person_lab_worker", "person_lumber_laborer_elias",
                    "person_lumber_laborer_nia", "person_lumber_overseer_tomas",
                ],
                "simulation_points": [
                    {"id": "bed", "label": "Barracks Bed", "position": [14, -16], "asset_id": "location_lumber_test_barracks"},
                    {"id": "kitchen", "label": "Kitchen", "position": [25, -6], "asset_id": "location_person_test_kitchen"},
                    {"id": "food", "label": "Food Store", "position": [15, 15], "asset_id": "location_person_test_pantry"},
                    {"id": "job", "label": "Factory Work", "position": [35, 10], "asset_id": "location_lumber_test_factory"},
                    {"id": "target", "label": "Western Wood Lot", "position": [-29, 4], "asset_id": "location_lumber_test_woodlot"},
                ],
                "terrain_zones": [
                    {"label": "Western Wild Terrain", "bounds": {"min_x": -44, "max_x": 0, "min_y": -27, "max_y": 27}, "color": "#334d3b"},
                    {"label": "Developed Yard", "bounds": {"min_x": 0, "max_x": 46, "min_y": -27, "max_y": 27}, "color": "#57554b"},
                ],
                "representational_layers": ["heightmap", "true color"],
            },
            "location_lumber_test_barracks": {
                "id": "location_lumber_test_barracks", "type": "location", "_dataset": "locations",
                "pretty_name": "Worker Barracks", "location_class": "building", "building_class": "barracks",
                "bounds": {"min_x": 8, "max_x": 30, "min_y": -22, "max_y": -10},
                "openings": [
                    {"side": "west", "center": -16, "width": 3, "opening_class": "exterior door"},
                    {"side": "south", "center": 25, "width": 3, "opening_class": "kitchen doorway"},
                ], "map_color": "#536271",
            },
            "location_lumber_test_storage": {
                "id": "location_lumber_test_storage", "type": "location", "_dataset": "locations",
                "pretty_name": "Lumber Storage Facility", "location_class": "building", "building_class": "warehouse",
                "bounds": {"min_x": 8, "max_x": 22, "min_y": 8, "max_y": 22},
                "openings": [{"side": "west", "center": 15, "width": 4, "opening_class": "loading door"}],
                "map_color": "#625a49",
            },
            "location_lumber_test_factory": {
                "id": "location_lumber_test_factory", "type": "location", "_dataset": "locations",
                "pretty_name": "Lumber Factory Hall", "location_class": "building", "building_class": "factory hall",
                "bounds": {"min_x": 26, "max_x": 44, "min_y": 2, "max_y": 20},
                "openings": [{"side": "west", "center": 10, "width": 4, "opening_class": "industrial doorway"}],
                "map_color": "#58616a",
            },
            "location_lumber_test_woodlot": {
                "id": "location_lumber_test_woodlot", "type": "location", "_dataset": "locations",
                "pretty_name": "Western Wood Lot", "location_class": "wild terrain",
            },
            "person_lumber_laborer_elias": {
                "id": "person_lumber_laborer_elias", "type": "person", "_dataset": "people",
                "pretty_name": "Elias Kern", "sex": "male", "site_position": [33, 12],
                "is_employed_by": ["producer_lumber_test_factory"],
                "is_employed_as": "job_lumber_site_laborer",
                "is_employed_at": "location_lumber_test_factory",
                "knowledge_records": [
                    {"entity": "location_lumber_test_factory", "navigation_knowledge": "route"},
                    {"entity": "location_lumber_test_storage", "navigation_knowledge": "route"},
                    {"entity": "location_lumber_test_woodlot", "navigation_knowledge": "route"},
                ],
            },
            "person_lumber_laborer_nia": {
                "id": "person_lumber_laborer_nia", "type": "person", "_dataset": "people",
                "pretty_name": "Nia Vale", "sex": "female", "site_position": [17, 15],
                "is_employed_by": ["producer_lumber_test_factory"],
                "is_employed_as": "job_lumber_site_laborer",
                "is_employed_at": "location_lumber_test_factory",
                "knowledge_records": [
                    {"entity": "location_lumber_test_factory", "navigation_knowledge": "route"},
                    {"entity": "location_lumber_test_storage", "navigation_knowledge": "route"},
                    {"entity": "location_lumber_test_woodlot", "navigation_knowledge": "direction", "direction_hint": [-1, 0]},
                ],
            },
            "person_lumber_overseer_tomas": {
                "id": "person_lumber_overseer_tomas", "type": "person", "_dataset": "people",
                "pretty_name": "Tomas Rhee", "sex": "male", "site_position": [39, 8],
                "is_employed_by": ["producer_lumber_test_factory"],
                "is_employed_as": "job_lumber_site_overseer",
                "is_employed_at": "location_lumber_test_site",
                "knowledge_records": [
                    {"entity": "location_lumber_test_site", "navigation_knowledge": "route"},
                    {"entity": "location_lumber_test_factory", "navigation_knowledge": "route"},
                    {"entity": "location_lumber_test_storage", "navigation_knowledge": "route"},
                    {"entity": "location_lumber_test_woodlot", "navigation_knowledge": "route"},
                ],
            },
            "job_lumber_site_cook": {
                "id": "job_lumber_site_cook", "type": "job", "_dataset": "jobs", "pretty_name": "Site Cook",
                "job_criticality": 0.55,
            },
            "job_lumber_site_laborer": {
                "id": "job_lumber_site_laborer", "type": "job", "_dataset": "jobs", "pretty_name": "Lumber Laborer",
                "job_criticality": 0.6,
            },
            "job_lumber_site_overseer": {
                "id": "job_lumber_site_overseer", "type": "job", "_dataset": "jobs", "pretty_name": "Site Overseer",
                "job_criticality": 0.7,
            },
            "producer_lumber_test_factory": {
                "id": "producer_lumber_test_factory", "type": "producer", "_dataset": "producers",
                "pretty_name": "Lumber Test Factory",
                "employer_discipline_level": 0.55,
                # Static stand-in for the real derivation, same as
                # producer_person_test_kitchen above.
                "employed_people": [
                    "person_lumber_laborer_elias", "person_lumber_laborer_nia",
                    "person_lumber_overseer_tomas",
                ],
            },
        })

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
            if key in {"point_id", "label", "source", "phase", "lifecycle_state", "action_label", "step_index", "maslow_tier"}
        } or None,
        "queue": [
            {
                key: value
                for key, value in task.items()
                if key in {"point_id", "label", "source", "phase", "lifecycle_state", "action_label", "step_index", "maslow_tier"}
            }
            for task in simulation.task_queue
        ],
        "navigation": {
            "mode": simulation.navigation_mode,
            "destination_entity_id": simulation.navigation_destination_entity_id,
            "heading": simulation.navigation_heading,
            "route_points": list(simulation.navigation_path),
            "history": list(simulation.navigation_history[:5]),
        },
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
        width=SCREEN_SIZE[0],
        height=SCREEN_SIZE[1],
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

    knowledge_path = output_dir / "07_knowledge_panel.png"
    _render_with_ui(renderer, ui_manager, simulation, camera, knowledge_path, "knowledge")
    report["artifacts"]["knowledge_panel"] = knowledge_path.name
    report["knowledge_panel_model"] = simulation.get_knowledge_panel_model()

    simulation.set_control_mode(simulation.CONTROL_AUTONOMOUS)
    simulation.needs["food"] = 18.0
    simulation.assign_external_task(
        "target",
        label="Fire on designated target",
        issuer_label="Conscript authority",
        duty_weight=0.92,
        coercion=0.78,
        action_tags=["kill"],
        alternative_point_id="job",
    )
    simulation._begin_next_queued_task()
    tasks_path = output_dir / "08_tasks_panel.png"
    _render_with_ui(renderer, ui_manager, simulation, camera, tasks_path, "tasks")
    report["artifacts"]["tasks_panel"] = tasks_path.name
    report["task_panel_model"] = simulation.get_task_panel_model()

    food_simulation = PersonSimulation(
        world_model=world,
        person_entity_id="person_lab_worker",
        year=2400,
    )
    food_simulation.set_control_mode(food_simulation.CONTROL_DIRECT)
    food_position = food_simulation.test_points["food"]["position"]
    food_simulation.position = [food_position[0], food_position[1]]
    _click_world(food_simulation, camera, food_simulation.test_points["food"]["position"])
    _advance(food_simulation, 6.0)
    kitchen_path = output_dir / "09_kitchen_workflow.png"
    report["snapshots"].append(_snapshot(food_simulation, "kitchen_workflow"))
    _render_with_ui(renderer, ui_manager, food_simulation, camera, kitchen_path, "tasks")
    report["artifacts"]["kitchen_workflow"] = kitchen_path.name

    for _ in range(80):
        if food_simulation.active_task is None:
            break
        _advance(food_simulation, 1.0)
    meal_path = output_dir / "10_meal_completed.png"
    report["snapshots"].append(_snapshot(food_simulation, "meal_completed"))
    _render_with_ui(renderer, ui_manager, food_simulation, camera, meal_path, "tasks")
    report["artifacts"]["meal_completed"] = meal_path.name
    report["food_workflow"] = {
        "known_recipe": food_simulation._knows_entity("recipe_simple_cooked_meal"),
        "inventory": dict(food_simulation.runtime_inventory),
        "food_fulfillment": round(food_simulation.needs["food"], 3),
        "decision_history": list(food_simulation.decision_history),
    }

    wayfinding_simulation = PersonSimulation(
        world_model=world,
        person_entity_id="person_lab_worker",
        year=2400,
    )
    wayfinding_simulation.assign_player_task("target")
    wayfinding_simulation._begin_next_queued_task()
    # Long enough to exhaust the first direction-only probe, but the newly
    # selected resident is not reached until a later update.  The snapshot
    # therefore captures the transparent "asking around" transition.
    _advance(wayfinding_simulation, 6.0)
    wayfinding_path = output_dir / "11_wayfinding_asks.png"
    report["snapshots"].append(_snapshot(wayfinding_simulation, "wayfinding_asks"))
    _render_with_ui(renderer, ui_manager, wayfinding_simulation, camera, wayfinding_path, "tasks")
    report["artifacts"]["wayfinding_asks"] = wayfinding_path.name
    report["wayfinding"] = {
        "mode": wayfinding_simulation.navigation_mode,
        "destination_entity_id": wayfinding_simulation.navigation_destination_entity_id,
        "history": list(wayfinding_simulation.navigation_history),
    }

    # The site checkpoint deliberately reads the active ontology rather than
    # the older single-person fixture.  This catches repository/map/runtime
    # mismatches such as a location opening as an empty planetary workspace.
    site_world = WorldModel()
    site_simulation = SiteSimulation(site_world, "location_lumber_test_site", year=2400)
    camera.x, camera.y = site_simulation.get_center()
    camera.zoom = site_simulation.get_initial_camera_zoom(*SCREEN_SIZE)
    site_path = output_dir / "12_site_population_context.png"
    _render_with_ui(renderer, ui_manager, site_simulation, camera, site_path, None)
    report["artifacts"]["site_population_context"] = site_path.name
    report["site_population"] = {
        "site_id": site_simulation.site_root_id,
        "bounds": dict(site_simulation.bounds),
        "full_simulations": len(site_simulation.agent_simulations),
        "presences": [
            {
                "id": item.get("id"), "label": item.get("label"),
                "kind": item.get("presence_kind"),
                "detail": item.get("simulation_detail"),
                "count": item.get("count"),
                "ontology_status": item.get("ontology_status"),
            }
            for item in site_simulation.presences
        ],
        "decisions": list(site_simulation.site_decisions),
    }

    # The companion checkpoint exercises the other launch affordance.  This
    # is the editable/authored map context; it consumes the same ontology site
    # geometry but intentionally contains no runtime population projection.
    site_map_simulation = MapSimulation(SimulationContext(
        year=2400,
        root_entity_id="location_lumber_test_site",
        world_model=site_world,
    ))
    camera.x, camera.y = site_map_simulation.get_center()
    camera.zoom = site_map_simulation.get_initial_camera_zoom(*SCREEN_SIZE)
    site_map_renderer = MapRenderer(app_view)
    site_map_path = output_dir / "13_site_map_authoring_context.png"
    _render_with_ui(site_map_renderer, ui_manager, site_map_simulation, camera, site_map_path, None)
    report["artifacts"]["site_map_authoring_context"] = site_map_path.name
    report["site_map"] = {
        "site_id": site_map_simulation.context.root_entity_id,
        "bounds": dict(site_map_simulation.bounds),
        "world_units_to_meters": site_map_simulation.world_units_to_meters,
        "layers": [
            {
                "entity_id": layer.get("entity_id"),
                "label": layer.get("label"),
                "shape": layer.get("shape"),
            }
            for layer in site_map_simulation.get_layers()
        ],
    }

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
