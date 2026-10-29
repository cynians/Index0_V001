"""Render review previews of the live vehicle-designer Pygame renderer."""

import os
import sys
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from simulations.vehicle.vehicle_design_simulation import VehicleDesignSimulation
from simulations.vehicle.vehicle_renderer import VehicleRenderer


OUTPUT = ROOT / "artifacts" / "vehicle_designer"


def seed_hull(simulation):
    for view_id in ("right", "front", "top"):
        grid = simulation.design.hull_silhouettes[view_id]
        height = len(grid)
        width = len(grid[0])
        for row in range(height):
            for column in range(width):
                nx = (column + 0.5) / width * 2.0 - 1.0
                ny = (row + 0.5) / height * 2.0 - 1.0
                if view_id == "right":
                    filled = (nx / 0.96) ** 4 + (ny / 0.68) ** 2 <= 1.0 and not (nx > 0.72 and ny < -0.25)
                elif view_id == "front":
                    filled = (nx / 0.86) ** 2 + (ny / 0.72) ** 2 <= 1.0
                else:
                    filled = (nx / 0.96) ** 4 + (ny / 0.80) ** 4 <= 1.0
                grid[row][column] = filled


def seed_paint(simulation, step):
    layer = simulation.design.get_paint_layer(step, "right")
    mask = simulation.design.get_paint_mask(step, "right")
    for row in range(len(layer)):
        for column in range(len(layer[row])):
            if not mask[row][column]:
                continue
            if step == "details":
                if row % 7 == 0 or column in {len(layer[row]) // 3, len(layer[row]) * 2 // 3}:
                    layer[row][column] = "#d7dde8"
                elif (column + row * 2) % 29 == 0:
                    layer[row][column] = "#4f657f"
            else:
                layer[row][column] = "#4a9b8e" if column < len(layer[row]) * 0.64 else "#d3aa55"
                if abs(row - len(layer) // 2) <= 1:
                    layer[row][column] = "#d7dde8"


def draw_chrome(surface, simulation, step):
    font = pygame.font.Font(None, 21)
    small = pygame.font.Font(None, 18)
    width, height = surface.get_size()
    panel_h = 570 if step in {"details", "liveries"} else 430
    pygame.draw.rect(surface, (26, 30, 39), pygame.Rect(width - 220, 32, 202, panel_h), border_radius=5)
    pygame.draw.rect(surface, (78, 91, 113), pygame.Rect(width - 220, 32, 202, panel_h), 1, border_radius=5)
    surface.blit(font.render("VEHICLE DESIGNER", True, (237, 241, 248)), (width - 205, 47))
    y = 80
    if step == "specifications":
        labels = (("Continue to Hull", True), ("+ Characteristic", False), ("+ Requirement", False), ("Remove Selected Row", False))
    elif step in {"details", "liveries"}:
        labels = (("Finish · Back to Components", True),)
    else:
        labels = (("1  Specification", False), ("2  Hull", step == "hull"), ("3  Components", step == "components"), ("4  Details", False), ("5  Liveries", False))
    for label, active in labels:
        rect = pygame.Rect(width - 205, y, 170, 32)
        pygame.draw.rect(surface, (58, 91, 119) if active else (39, 46, 59), rect, border_radius=3)
        pygame.draw.rect(surface, (139, 183, 218) if active else (78, 91, 110), rect, 1, border_radius=3)
        surface.blit(font.render(label, True, (239, 244, 250)), (rect.x + 10, rect.y + 7))
        y += 40
    dims = simulation.get_vehicle_dimensions_m()
    if step not in {"specifications", "details", "liveries"}:
        for axis, label in (("x", "Length"), ("y", "Width"), ("z", "Height")):
            surface.blit(small.render(f"{label}", True, (153, 164, 183)), (width - 205, y + 7))
            rect = pygame.Rect(width - 123, y, 88, 30)
            pygame.draw.rect(surface, (37, 44, 57), rect, border_radius=3)
            pygame.draw.rect(surface, (82, 98, 121), rect, 1, border_radius=3)
            value = font.render(f"−  {dims[axis]:g} m  +", True, (230, 235, 244))
            surface.blit(value, value.get_rect(center=rect.center))
            y += 40
    elif step in {"details", "liveries"}:
        for row_index, pair in enumerate((("Left", "Right"), ("Front", "Rear"), ("Top", "Bottom"))):
            for column_index, label in enumerate(pair):
                rect = pygame.Rect(width - 205 + column_index * 86, y + row_index * 34, 80, 28)
                pygame.draw.rect(surface, (58, 91, 119) if label.lower() == simulation.selected_hull_view_id else (37, 44, 57), rect, border_radius=3)
                pygame.draw.rect(surface, (99, 119, 146), rect, 1, border_radius=3)
                text = small.render(label, True, (232, 237, 246))
                surface.blit(text, text.get_rect(center=rect.center))
        y += 110
        controls = ("Components: On", "Draw   Erase   Pick", "Brush 1 px", "Light   Steel", "Dark    Rust", "Gold    Teal")
        for label in controls:
            rect = pygame.Rect(width - 205, y, 170, 28)
            pygame.draw.rect(surface, (37, 44, 57), rect, border_radius=3)
            pygame.draw.rect(surface, (82, 98, 121), rect, 1, border_radius=3)
            text = small.render(label, True, (230, 235, 244))
            surface.blit(text, text.get_rect(center=rect.center))
            y += 34
        if step == "liveries":
            for index, label in enumerate(("Copy Livery", "Paste Copy")):
                rect = pygame.Rect(width - 205 + index * 86, y, 80, 28)
                pygame.draw.rect(surface, (48, 67, 87), rect, border_radius=3)
                pygame.draw.rect(surface, (99, 119, 146), rect, 1, border_radius=3)
                text = small.render(label, True, (230, 235, 244))
                surface.blit(text, text.get_rect(center=rect.center))
    if step == "hull":
        surface.blit(small.render("TOOLS", True, (153, 164, 183)), (width - 205, y + 5))
        for index, label in enumerate(("Draw", "Erase", "Clear")):
            rect = pygame.Rect(width - 205 + index * 58, y + 24, 52, 30)
            pygame.draw.rect(surface, (58, 91, 119) if label == "Draw" else (37, 44, 57), rect, border_radius=3)
            pygame.draw.rect(surface, (99, 119, 146), rect, 1, border_radius=3)
            txt = small.render(label, True, (232, 237, 246))
            surface.blit(txt, txt.get_rect(center=rect.center))
        focus_rect = pygame.Rect(width - 205, y + 64, 170, 30)
        pygame.draw.rect(surface, (58, 91, 119) if simulation.hull_focus_mode else (37, 44, 57), focus_rect, border_radius=3)
        pygame.draw.rect(surface, (99, 119, 146), focus_rect, 1, border_radius=3)
        focus_label = "Exit Focus" if simulation.hull_focus_mode else f"Enlarge {simulation.selected_hull_view_id.title()}"
        focus_text = small.render(focus_label, True, (232, 237, 246))
        surface.blit(focus_text, focus_text.get_rect(center=focus_rect.center))

    bar = pygame.Rect(18, height - 274, width - 36, 252)
    pygame.draw.rect(surface, (25, 30, 39), bar, border_radius=6)
    pygame.draw.rect(surface, (76, 91, 112), bar, 1, border_radius=6)
    title = {"specifications": "VEHICLE SPECIFICATION", "hull": "HULL STUDIO", "components": "COMPONENT CATALOG", "details": "STRUCTURAL DETAIL STUDIO", "liveries": "LIVERY STUDIO"}.get(step, "VEHICLE DESIGNER")
    surface.blit(font.render(title, True, (236, 240, 248)), (bar.x + 18, bar.y + 16))
    if step == "specifications":
        lines = (
            "Enter only the metadata, characteristics, and design requirements you currently know.",
            "Blank values remain explicitly unknown; arbitrary characteristic rows are stored in the ontology.",
            "Load-bearing geometry is recorded as structure, separate from installable components.",
        )
        for index, line in enumerate(lines):
            surface.blit(font.render(line, True, (174, 185, 203)), (bar.x + 18, bar.y + 58 + index * 28))
    elif step == "hull":
        lines = (
            "Define the vehicle envelope from all six directions.",
            "Opposite views remain editable while showing an inherited grey guide.",
            "Changing a dimension resamples the linked pixel canvases immediately.",
        )
        for index, line in enumerate(lines):
            surface.blit(font.render(line, True, (174, 185, 203)), (bar.x + 18, bar.y + 58 + index * 28))
    elif step == "components":
        cards = []
        for entry in simulation.design.get_component_catalog()[:3]:
            dims = entry.get("dimensions_m", {})
            cards.append((
                entry.get("label", "Component"),
                f"{dims.get('x', '?')} × {dims.get('y', '?')} × {dims.get('z', '?')} m",
            ))
        for index, (label, dims_label) in enumerate(cards):
            rect = pygame.Rect(bar.x + 18 + index * 210, bar.y + 58, 190, 104)
            pygame.draw.rect(surface, (39, 48, 61), rect, border_radius=4)
            pygame.draw.rect(surface, (91, 119, 148), rect, 1, border_radius=4)
            pygame.draw.rect(surface, (55, 86, 109), pygame.Rect(rect.x + 12, rect.y + 12, 116 + index * 22, 48), border_radius=3)
            surface.blit(font.render(label, True, (237, 241, 247)), (rect.x + 12, rect.y + 68))
            surface.blit(small.render(dims_label, True, (153, 169, 190)), (rect.x + 12, rect.y + 87))
        surface.blit(font.render("Select a catalog card, then click a projection to place it.", True, (174, 185, 203)), (bar.x + 18, bar.y + 184))
    else:
        lines = (
            f"Editing {simulation.selected_hull_view_id.title()} with the standard pixel tools.",
            "Opposite-side paint remains visible as a dimmed placement guide.",
            "Finish returns to the shared-coordinate component layout.",
        )
        for index, line in enumerate(lines):
            surface.blit(font.render(line, True, (174, 185, 203)), (bar.x + 18, bar.y + 58 + index * 28))


def render(step, focus=False):
    simulation = VehicleDesignSimulation()
    simulation.design.placed_components = []
    seed_hull(simulation)
    simulation.set_design_step(step)
    if step in {"details", "liveries"}:
        simulation.enter_paint_screen(step)
        seed_paint(simulation, step)
        simulation.selected_hull_view_id = "left" if step == "details" else "right"
        simulation.design.place_component_in_orthographic_view(
            "comp_engine_inline_compact", "right", 4.8, 1.45,
        )
        if step == "liveries":
            simulation.copy_active_livery()
            simulation.paste_livery()
    if focus:
        simulation.selected_hull_view_id = "right"
        simulation.toggle_hull_focus_mode()
    if step == "components":
        first = simulation.design.place_component_in_orthographic_view("comp_engine_inline_compact", "right", 3.2, 1.25)
        simulation.selected_part_id = first
        simulation.design.set_selected_component(first)
        simulation.design.place_component_in_orthographic_view("comp_engine_vblock_heavy", "top", 7.0, 2.8)

    surface = pygame.Surface((1440, 900))
    surface.fill((15, 18, 24))
    class PreviewCamera:
        def world_to_screen(self, point):
            return point[0] * 10.0, point[1] * 8.0

    app_view = SimpleNamespace(default_font=pygame.font.Font(None, 18), camera=PreviewCamera())
    VehicleRenderer(app_view).draw(surface, simulation)
    draw_chrome(surface, simulation, step)
    suffix = "_focus" if focus else ""
    output_path = OUTPUT / f"vehicle_designer_{step}{suffix}.png"
    pygame.image.save(surface, output_path)
    return output_path


if __name__ == "__main__":
    pygame.init()
    OUTPUT.mkdir(parents=True, exist_ok=True)
    for current_step in ("specifications", "hull", "components", "details", "liveries"):
        print(render(current_step))
    print(render("hull", focus=True))
    pygame.quit()
