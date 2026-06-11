import pygame

from engine.clock import Clock
from engine.simulation_manager import SimulationManager
from simulations.phylogeny.clade_graph import (
    all_clade_tree_roots,
    build_clade_children_map,
    clade_label,
    get_phylogeny_entities,
)


class PhylogenySimulation:
    """
    Navigable full-tree view for clades and species.
    """

    NODE_W = 190.0
    NODE_H = 34.0
    X_GAP = 92.0
    Y_GAP = 18.0

    def __init__(self, world_model=None, focus_clade_id=None):
        class _DummySystem:
            def update(self, dt):
                pass

        self.world_model = world_model
        self.focus_clade_id = focus_clade_id
        self.render_mode = "phylogeny"
        self.show_time_ui = False
        self.free_camera_pan = True
        self.world_units_to_meters = 1.0
        self.sim_clock = Clock(base_dt=1.0)
        self.system = _DummySystem()
        self.sim_manager = SimulationManager(self.sim_clock, self.system)
        self.min_zoom = 0.18
        self.max_zoom = 3.0
        self.preferred_zoom = 0.78
        self.selected_clade_id = focus_clade_id
        self.hover_clade_id = None
        self.node_rects = {}
        self.edges = []
        self.bounds = {"min_x": -200.0, "max_x": 2000.0, "min_y": -200.0, "max_y": 2000.0}
        self.is_camera_dragging = False
        self.camera_drag_start_screen_pos = None
        self.camera_drag_start_camera_pos = None
        self.camera_drag_has_moved = False
        self._layout_tree()

    @property
    def year(self):
        return 2400

    def update(self, dt):
        self.sim_manager.update(dt)

    def get_center(self):
        if self.focus_clade_id in self.node_rects:
            rect = self.node_rects[self.focus_clade_id]
            return rect["x"] + rect["width"] / 2.0, rect["y"] + rect["height"] / 2.0
        return (
            (self.bounds["min_x"] + self.bounds["max_x"]) / 2.0,
            (self.bounds["min_y"] + self.bounds["max_y"]) / 2.0,
        )

    def get_title(self):
        entity = self._entity(self.focus_clade_id)
        return f"Phylogeny: {clade_label(entity, self.focus_clade_id)}"

    def _entity(self, entity_id):
        if self.world_model is None or not entity_id:
            return None
        return self.world_model.get_entity(entity_id)

    def _layout_tree(self):
        phylogeny_entities = get_phylogeny_entities(self.world_model)
        children_by_parent = build_clade_children_map(self.world_model)
        roots = all_clade_tree_roots(self.world_model)
        self.node_rects = {}
        self.edges = []
        cursor_y = 0.0

        def place_subtree(clade_id, depth, y_start, ancestry=None):
            ancestry = set(ancestry or set())
            if clade_id in ancestry:
                return y_start + self.NODE_H + self.Y_GAP
            ancestry.add(clade_id)

            children = children_by_parent.get(clade_id, [])
            if not children:
                node_y = y_start
                next_y = y_start + self.NODE_H + self.Y_GAP
            else:
                child_start_y = y_start
                child_centers = []
                for child_id in children:
                    before = child_start_y
                    child_start_y = place_subtree(child_id, depth + 1, child_start_y, ancestry)
                    child_rect = self.node_rects.get(child_id)
                    if child_rect:
                        child_centers.append(child_rect["y"] + child_rect["height"] / 2.0)
                        self.edges.append((clade_id, child_id))
                    elif child_start_y == before:
                        child_start_y += self.NODE_H + self.Y_GAP
                node_y = (min(child_centers) + max(child_centers)) / 2.0 - self.NODE_H / 2.0 if child_centers else y_start
                next_y = max(child_start_y, node_y + self.NODE_H + self.Y_GAP)

            self.node_rects[clade_id] = {
                "x": depth * (self.NODE_W + self.X_GAP),
                "y": node_y,
                "width": self.NODE_W,
                "height": self.NODE_H,
                "label": clade_label(phylogeny_entities.get(clade_id), clade_id),
                "species": (phylogeny_entities.get(clade_id) or {}).get("_dataset") == "species",
                "card_color": (phylogeny_entities.get(clade_id) or {}).get("card_color"),
                "card_header_color": (phylogeny_entities.get(clade_id) or {}).get("card_header_color"),
                "wiki_field_colors": (phylogeny_entities.get(clade_id) or {}).get("wiki_field_colors"),
            }
            return next_y

        for root_id in roots:
            cursor_y = place_subtree(root_id, 0, cursor_y)
            cursor_y += self.Y_GAP * 2

        if self.node_rects:
            min_x = min(rect["x"] for rect in self.node_rects.values()) - 120.0
            min_y = min(rect["y"] for rect in self.node_rects.values()) - 120.0
            max_x = max(rect["x"] + rect["width"] for rect in self.node_rects.values()) + 120.0
            max_y = max(rect["y"] + rect["height"] for rect in self.node_rects.values()) + 120.0
            self.bounds = {"min_x": min_x, "max_x": max_x, "min_y": min_y, "max_y": max_y}

    def get_render_payload(self):
        return {
            "nodes": self.node_rects,
            "edges": self.edges,
            "focus_id": self.focus_clade_id,
            "selected_id": self.selected_clade_id,
            "hover_id": self.hover_clade_id,
            "title": self.get_title(),
            "total_clades": len(self.node_rects),
        }

    def _screen_node_at(self, camera, screen_pos):
        for clade_id, rect in self.node_rects.items():
            top_left = camera.world_to_screen((rect["x"], rect["y"]))
            bottom_right = camera.world_to_screen((rect["x"] + rect["width"], rect["y"] + rect["height"]))
            if top_left is None or bottom_right is None:
                continue
            left = min(top_left[0], bottom_right[0])
            right = max(top_left[0], bottom_right[0])
            top = min(top_left[1], bottom_right[1])
            bottom = max(top_left[1], bottom_right[1])
            if left <= screen_pos[0] <= right and top <= screen_pos[1] <= bottom:
                return clade_id
        return None

    def _begin_camera_drag(self, screen_pos, camera):
        self.is_camera_dragging = True
        self.camera_drag_start_screen_pos = screen_pos
        self.camera_drag_start_camera_pos = (camera.x, camera.y)
        self.camera_drag_has_moved = False

    def _reset_camera_drag(self):
        self.is_camera_dragging = False
        self.camera_drag_start_screen_pos = None
        self.camera_drag_start_camera_pos = None
        self.camera_drag_has_moved = False

    def _update_camera_drag(self, screen_pos, camera):
        if not self.is_camera_dragging:
            return False
        if self.camera_drag_start_screen_pos is None or self.camera_drag_start_camera_pos is None:
            return False

        dx = float(screen_pos[0]) - float(self.camera_drag_start_screen_pos[0])
        dy = float(screen_pos[1]) - float(self.camera_drag_start_screen_pos[1])
        if not self.camera_drag_has_moved and (abs(dx) >= 3.0 or abs(dy) >= 3.0):
            self.camera_drag_has_moved = True

        start_camera_x, start_camera_y = self.camera_drag_start_camera_pos
        zoom = max(float(camera.zoom), 1e-9)
        camera.x = start_camera_x - (dx / zoom)
        camera.y = start_camera_y - (dy / zoom)
        return True

    def handle_pointer_motion(self, event, camera, screen_pos):
        if self._update_camera_drag(screen_pos, camera):
            self.hover_clade_id = None
            return True

        self.hover_clade_id = self._screen_node_at(camera, screen_pos)
        return False

    def handle_pointer_event(self, event, camera, screen_pos):
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            picked_id = self._screen_node_at(camera, screen_pos)
            if picked_id:
                self.selected_clade_id = picked_id
                self.focus_clade_id = picked_id
                return True
            self._begin_camera_drag(screen_pos, camera)
            return True

        if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            if self.is_camera_dragging:
                self._reset_camera_drag()
                return True

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 3:
            self._begin_camera_drag(screen_pos, camera)
            return True

        if event.type == pygame.MOUSEBUTTONUP and event.button == 3:
            if self.is_camera_dragging:
                self._reset_camera_drag()
                return True

        return False
