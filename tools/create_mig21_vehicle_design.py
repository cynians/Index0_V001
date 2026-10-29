"""Author and render the MiG-21 vehicle-designer verification entity."""

import copy
import os
import sys
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from simulations.vehicle.vehicle_design import VehicleDesignController
from simulations.vehicle.vehicle_design_simulation import VehicleDesignSimulation
from simulations.vehicle.vehicle_renderer import VehicleRenderer
from tools.render_vehicle_designer_preview import draw_chrome
from world.persistent_ontology_store import PersistentOntologyStore


ENTITY_ID = "veh_mikoyan_gurevich_mig_21_f13"
OUTPUT = ROOT / "artifacts" / "vehicle_designer" / "mig21"


def point_in_polygon(x, y, points):
    inside = False
    previous = points[-1]
    for current in points:
        x1, y1 = previous
        x2, y2 = current
        if (y1 > y) != (y2 > y):
            denominator = y2 - y1
            if abs(denominator) < 1e-9:
                previous = current
                continue
            crossing_x = (x2 - x1) * (y - y1) / denominator + x1
            if x < crossing_x:
                inside = not inside
        previous = current
    return inside


def normalized_cell(grid, row, column):
    return (column + 0.5) / len(grid[row]), (row + 0.5) / len(grid)


def author_hull(controller):
    side = controller.hull_silhouettes["right"]
    for row in range(len(side)):
        for column in range(len(side[row])):
            x, y = normalized_cell(side, row, column)
            center_y = 0.57
            fuselage_radius = 0.115 * (0.35 + 0.65 * min(1.0, x / 0.18, (1.0 - x) / 0.34))
            fuselage = abs(y - center_y) <= max(0.018, fuselage_radius)
            nose = x > 0.72 and abs(y - center_y) <= 0.115 * max(0.0, (1.0 - x) / 0.28)
            tail_fin = point_in_polygon(x, y, ((0.08, 0.55), (0.18, 0.12), (0.29, 0.20), (0.31, 0.55)))
            canopy = point_in_polygon(x, y, ((0.65, 0.48), (0.70, 0.37), (0.81, 0.38), (0.84, 0.52)))
            side[row][column] = bool(fuselage or nose or tail_fin or canopy)
    controller.hull_silhouettes["left"] = [list(row) for row in side]

    top = controller.hull_silhouettes["top"]
    for row in range(len(top)):
        for column in range(len(top[row])):
            x, y = normalized_cell(top, row, column)
            fuselage_half_width = 0.055 * (0.45 + 0.55 * min(1.0, x / 0.15, (1.0 - x) / 0.30))
            fuselage = abs(y - 0.5) <= max(0.012, fuselage_half_width)
            delta_wing = point_in_polygon(x, y, ((0.24, 0.08), (0.67, 0.43), (0.67, 0.57), (0.24, 0.92)))
            tailplane = point_in_polygon(x, y, ((0.06, 0.31), (0.23, 0.43), (0.23, 0.57), (0.06, 0.69)))
            top[row][column] = bool(fuselage or delta_wing or tailplane)
    controller.hull_silhouettes["bottom"] = [list(row) for row in top]

    for view_id in ("front", "rear"):
        grid = controller.hull_silhouettes[view_id]
        for row in range(len(grid)):
            for column in range(len(grid[row])):
                x, y = normalized_cell(grid, row, column)
                fuselage_width = 0.125 if view_id == "front" else 0.145
                fuselage_height = 0.175 if view_id == "front" else 0.195
                fuselage = ((x - 0.5) / fuselage_width) ** 2 + ((y - 0.58) / fuselage_height) ** 2 <= 1.0
                wing_center = 0.615 - 0.035 * min(1.0, abs(x - 0.5) / 0.45)
                wing = abs(y - wing_center) <= 0.022 and 0.045 <= x <= 0.955
                fin = point_in_polygon(x, y, ((0.475, 0.57), (0.505, 0.105), (0.55, 0.57)))
                grid[row][column] = bool(fuselage or wing or fin)


def paint_line(controller, layer_kind, view_id, predicate, color):
    layer = controller.get_paint_layer(layer_kind, view_id)
    mask = controller.get_effective_hull_grid(view_id)
    for row in range(len(layer)):
        for column in range(len(layer[row])):
            if not mask[row][column]:
                continue
            x, y = normalized_cell(layer, row, column)
            if predicate(x, y):
                layer[row][column] = color


def author_details(controller):
    for view_id in ("right", "left"):
        paint_line(controller, "details", view_id, lambda x, y: abs(y - 0.57) < 0.012, "#d7dde8")
        paint_line(controller, "details", view_id, lambda x, y: any(abs(x - station) < 0.006 for station in (0.18, 0.31, 0.52, 0.67, 0.84)), "#6d7e94")
        paint_line(controller, "details", view_id, lambda x, y: 0.66 < x < 0.82 and 0.36 < y < 0.50, "#27394f")
        paint_line(controller, "details", view_id, lambda x, y: 0.965 < x and abs(y - 0.57) < 0.08, "#202b38")
    for view_id in ("top", "bottom"):
        paint_line(controller, "details", view_id, lambda x, y: abs(y - 0.5) < 0.009, "#d7dde8")
        paint_line(controller, "details", view_id, lambda x, y: abs(x - 0.25) < 0.006 or abs(x - 0.67) < 0.006, "#6d7e94")
    for view_id in ("front", "rear"):
        paint_line(controller, "details", view_id, lambda x, y: abs(x - 0.5) < 0.012, "#d7dde8")


def author_livery(controller):
    livery = controller.liveries[0]
    livery["name"] = "Soviet Natural Metal · Red 21"
    controller.active_livery_id = livery["id"]
    for view_id in controller.ORTHOGRAPHIC_VIEWS:
        layer = controller.get_paint_layer("liveries", view_id)
        mask = controller.get_paint_mask("liveries", view_id)
        for row in range(len(layer)):
            for column in range(len(layer[row])):
                if not mask[row][column]:
                    continue
                x, y = normalized_cell(layer, row, column)
                color = "#aeb8c4" if (row + column) % 5 else "#96a2b0"
                if 0.15 < x < 0.21:
                    color = "#b7443e"
                if x > 0.94:
                    color = "#2c343e"
                layer[row][column] = color


def component_catalog():
    return [
        {
            "id": "mig21_tumansky_r11", "label": "Tumansky R-11F-300", "component_type": "jet_engine_component",
            "entry_type": "component", "dimensions_m": {"x": 4.6, "y": 1.0, "z": 1.0}, "mass_kg": 1124, "power_kw": 0,
            "satisfies_categories": ["propulsion_air", "powertrain"], "operational_groups": ["Powertrain"],
            "subsystem_labels": ["turbojet"],
            "inputs": [{"resource_type": "fuel", "label": "Fuel"}],
            "outputs": [
                {"resource_type": "thrust", "label": "Thrust"},
                {"resource_type": "electrical_power", "label": "Generator Output"},
            ],
        },
        {
            "id": "mig21_cockpit", "label": "Pilot Cockpit", "component_type": "cockpit_component",
            "entry_type": "component", "dimensions_m": {"x": 1.8, "y": 0.8, "z": 1.0}, "mass_kg": 180, "power_kw": 0,
            "satisfies_categories": ["control"], "operational_groups": ["Crew & Control"],
            "subsystem_labels": ["cockpit"],
            "outputs": [{"resource_type": "control_signal", "label": "Pilot Control Input"}],
        },
        {
            "id": "mig21_avionics", "label": "Radar & Avionics", "component_type": "control_component",
            "entry_type": "component", "dimensions_m": {"x": 1.6, "y": 0.7, "z": 0.7}, "mass_kg": 210, "power_kw": 12,
            "satisfies_categories": ["control", "communications_system"], "operational_groups": ["Sensors & Comms"],
            "subsystem_labels": ["radar", "avionics"],
            "inputs": [{"resource_type": "electrical_power", "label": "Electric Supply"}],
        },
        {
            "id": "mig21_fuel_cells", "label": "Fuselage Fuel Cells", "component_type": "fuel_tank_component",
            "entry_type": "assembly", "dimensions_m": {"x": 3.2, "y": 0.9, "z": 0.8}, "mass_kg": 2100, "power_kw": 0,
            "satisfies_categories": ["fuel_storage", "powertrain"], "operational_groups": ["Powertrain"],
            "subsystem_labels": ["fuel system"],
            "outputs": [{"resource_type": "fuel", "label": "Fuel"}],
        },
        {
            "id": "mig21_landing_gear", "label": "Retractable Landing Gear", "component_type": "landing_gear_component",
            "entry_type": "assembly", "dimensions_m": {"x": 2.6, "y": 4.2, "z": 0.5}, "mass_kg": 340, "power_kw": 0,
            "satisfies_categories": ["landing_system"], "operational_groups": ["Mobility"],
            "subsystem_labels": ["landing gear"],
            "inputs": [{"resource_type": "control_signal", "label": "Retraction Signal"}],
        },
    ]


def place_component(controller, catalog_id, x, y, z):
    instance_id = controller.place_component_in_orthographic_view(catalog_id, "right", x, z)
    controller.move_component_axis(instance_id, "y", y)
    component = controller._get_component_by_instance_id(instance_id)
    component["undefined_axis"] = None
    return instance_id


def build_entity():
    entity = {
        "id": ENTITY_ID,
        "name": "Mikoyan-Gurevich MiG-21F-13",
        "pretty_name": "MiG-21F-13 Fishbed-C",
        "description": "Vehicle Designer end-to-end verification aircraft; approximate editor geometry, not an archival scale model.",
        "type": "vehicle",
        "_dataset": "vehicles",
        "vehicle_class": "aircraft",
        "manufacturer_name": "Mikoyan-Gurevich",
        "dimension_length_m": 14.7,
        "dimension_width_m": 7.15,
        "dimension_height_m": 4.1,
        "component_catalog": component_catalog(),
        "installed_components": [],
        "unit_placeholders": [{"name": "Sn-6"}],
        "tags": ["aircraft", "jet fighter", "delta wing", "vehicle designer verification"],
        "entry_status": "verification sample",
        "vehicle_specifications": [
            {"id": "spec_empty_mass", "label": "Empty mass", "value": "4870", "unit": "kg", "category": "mass"},
            {"id": "spec_max_speed", "label": "Maximum speed", "value": "2125", "unit": "km/h", "category": "performance"},
            {"id": "spec_powerplant", "label": "Powerplant", "value": "Tumansky R-11F-300", "unit": "", "category": "propulsion"},
            {"id": "spec_crew", "label": "Crew", "value": "1", "unit": "person", "category": "operations"},
            {"id": "spec_construction", "label": "Primary construction", "value": "metal semi-monocoque", "unit": "", "category": "structure"},
        ],
        "design_requirements": [
            {"id": "req_interceptor", "label": "Supersonic point interception", "target": "Mach 2 class", "unit": "", "priority": "critical", "notes": "verification brief"},
            {"id": "req_nose_intake", "label": "Nose intake", "target": "variable shock cone", "unit": "", "priority": "high", "notes": "preserve frontal airflow"},
            {"id": "req_delta_planform", "label": "Delta-wing planform", "target": "integral load-bearing structure", "unit": "", "priority": "critical", "notes": "not an installable component"},
            {"id": "req_landing", "label": "Runway operation", "target": "retractable tricycle gear", "unit": "", "priority": "high", "notes": ""},
        ],
        "structural_features": [
            {"id": "mig21_fuselage_structure", "label": "Semi-monocoque fuselage", "feature_type": "primary_structure", "satisfies_categories": ["structure"]},
            {"id": "mig21_delta_wing_structure", "label": "Integral delta wing", "feature_type": "lifting_structure", "satisfies_categories": ["flight_surfaces"]},
        ],
        "source_url": "https://airandspace.si.edu/collection-objects/mikoyan-gurevich-mig-21f-13-fishbed-c/nasm_A19930354000",
    }
    controller = VehicleDesignController(vehicle_entity=entity)
    controller.placed_components = []
    author_hull(controller)
    author_details(controller)
    author_livery(controller)
    place_component(controller, "mig21_tumansky_r11", 4.2, 3.575, 2.1)
    place_component(controller, "mig21_fuel_cells", 7.2, 3.575, 2.1)
    place_component(controller, "mig21_cockpit", 10.7, 3.575, 2.75)
    place_component(controller, "mig21_avionics", 12.5, 3.575, 2.15)
    place_component(controller, "mig21_landing_gear", 7.3, 3.575, 1.0)
    entity["hull_silhouettes"] = controller.get_hull_silhouettes()
    entity["vehicle_detail_layers"] = controller.detail_layers
    entity["vehicle_liveries"] = controller.liveries
    entity["installed_components"] = controller.get_placed_components()
    return entity


class SnapshotWorld:
    def __init__(self, entity):
        self.entity = entity

    def get_entity(self, entity_id):
        return self.entity if entity_id == self.entity.get("id") else None

    def set_literal(self, entity_id, field_name, value):
        if entity_id != self.entity.get("id"):
            return False
        self.entity[field_name] = copy.deepcopy(value)
        return True


class PreviewCamera:
    def world_to_screen(self, point):
        return point[0] * 10.0, point[1] * 8.0


def render_stage(entity, step):
    simulation = VehicleDesignSimulation(SnapshotWorld(copy.deepcopy(entity)), ENTITY_ID)
    if step in {"details", "liveries"}:
        simulation.selected_hull_view_id = "left" if step == "details" else "top"
        simulation.enter_paint_screen(step)
    else:
        simulation.set_design_step(step)
    surface = pygame.Surface((1440, 900))
    surface.fill((15, 18, 24))
    font = pygame.font.Font(None, 18)
    if simulation.is_vehicle_pixel_editor_active():
        # Pixel Studio is the real Details/Liveries surface in the app, so the
        # verification image is rendered by that same controller as well.
        simulation.pixel_art_editor_ui.draw(surface, font)
    else:
        app_view = SimpleNamespace(default_font=font, camera=PreviewCamera())
        VehicleRenderer(app_view).draw(surface, simulation)
        draw_chrome(surface, simulation, step)
    output_path = OUTPUT / f"mig21_{step}.png"
    pygame.image.save(surface, output_path)
    return output_path


def registry_units():
    """
    Example vehicle_units for the Vehicle Registry verification pass -- a
    Prototype (ungrouped), a Mk I production batch with the varied fates the
    feature was designed around (a transferred unit, a write-off, and one
    with an unresolved/typed faction link to demonstrate the "unfinished
    link" render path), and one Mk II unit to demonstrate version grouping.
    """
    return [
        {
            "id": "unit_mig21_prototype", "type": "vehicle_unit", "_dataset": "vehicle_units",
            "pretty_name": "Sn-1", "represents_design": ENTITY_ID,
            "serial_number": "Sn-1", "version_label": "Prototype", "year_constructed": 1955,
        },
        {
            "id": "unit_mig21_002", "type": "vehicle_unit", "_dataset": "vehicle_units",
            "pretty_name": "Sn-2", "represents_design": ENTITY_ID,
            "serial_number": "Sn-2", "version_label": "Mk I", "production_line_id": "line_mig21_batch_1",
            "batch_label": "First Production Batch",
        },
        {
            "id": "unit_mig21_003", "type": "vehicle_unit", "_dataset": "vehicle_units",
            "pretty_name": "Sn-3", "represents_design": ENTITY_ID,
            "serial_number": "Sn-3", "version_label": "Mk I", "production_line_id": "line_mig21_batch_1",
        },
        {
            "id": "unit_mig21_004", "type": "vehicle_unit", "_dataset": "vehicle_units",
            "pretty_name": "Sn-4", "represents_design": ENTITY_ID,
            "serial_number": "Sn-4", "version_label": "Mk I", "production_line_id": "line_mig21_batch_1",
            "year_constructed": 1956, "fate_notes": "Transferred to allied air force.",
            "assigned_faction": "Allied Volunteer Air Corps",
        },
        {
            "id": "unit_mig21_005", "type": "vehicle_unit", "_dataset": "vehicle_units",
            "pretty_name": "Sn-5", "represents_design": ENTITY_ID,
            "serial_number": "Sn-5", "version_label": "Mk I", "production_line_id": "line_mig21_batch_1",
            "year_constructed": 1956, "year_destroyed": 1957,
            "fate_notes": "Crashed during flight testing.",
        },
        {
            "id": "unit_mig21_006", "type": "vehicle_unit", "_dataset": "vehicle_units",
            "pretty_name": "Sn-7", "represents_design": ENTITY_ID,
            "serial_number": "Sn-7", "version_label": "Mk II", "production_line_id": "line_mig21_batch_2",
            "batch_label": "Mk II Production Batch", "year_constructed": 1958,
        },
    ]


def main():
    pygame.init()
    OUTPUT.mkdir(parents=True, exist_ok=True)
    entity = build_entity()
    store = PersistentOntologyStore(ROOT / "ontology" / "index0.owl")
    store.persist_entity(entity)
    for unit in registry_units():
        store.persist_entity(unit)
    store.export_rdfxml(ROOT / "ontology" / "index0.owl")
    store.compact_database()
    print(f"Persisted {ENTITY_ID} to {store.database_path}")
    for step in ("specifications", "hull", "components", "details", "liveries"):
        print(render_stage(entity, step))
    pygame.quit()


if __name__ == "__main__":
    main()
