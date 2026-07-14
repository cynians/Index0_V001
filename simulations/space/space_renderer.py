import math

import pygame

from simulations.space.orbit_visualizer import draw_orbit
from simulations.space.stellar import AU_M, LY_M, habitable_zone_for_luminosity


class SpaceRenderer:
    """
    Handles rendering for space simulations.
    """

    def __init__(self, app_view):
        self.app_view = app_view
        self._stellar_graph_cache = {}
        self._stellar_layout_cache = {}

    def _iter_neighbour_rows(self, entity):
        rows = entity.get("stellar_neighbours") if isinstance(entity, dict) else None
        if not isinstance(rows, list):
            return []
        return [row for row in rows if isinstance(row, dict) and row.get("system")]

    def _neighbour_distance_ly(self, row):
        try:
            distance = float(row.get("distance_ly"))
        except (TypeError, ValueError):
            return None
        return distance if distance > 0 else None

    def _stable_angle_for_id(self, system_id):
        text = str(system_id or "")
        value = sum((index + 1) * ord(char) for index, char in enumerate(text))
        return (value % 360) / 360.0 * math.tau

    def _distance(self, a, b):
        return math.hypot(a[0] - b[0], a[1] - b[1])

    def _stellar_neighbour_graph(self, sim, max_nodes=80):
        model = getattr(sim, "world_model", None)
        root_id = getattr(sim, "root_system_id", None)
        cache_key = (
            id(model),
            getattr(model, "repository_revision", 0),
            root_id,
            max_nodes,
        )
        cached = self._stellar_graph_cache.get(cache_key)
        if cached is not None:
            return cached

        root = model.get_entity(root_id) if model is not None and root_id else None
        if not isinstance(root, dict):
            return {"root_id": root_id, "entities": {}, "depths": {}, "edges": []}

        entities = {root_id: root}
        depths = {root_id: 0}
        queue = [root_id]
        edges_by_key = {}

        while queue and len(entities) <= max_nodes:
            source_id = queue.pop(0)
            source = entities.get(source_id)
            if not isinstance(source, dict):
                continue

            for row in self._iter_neighbour_rows(source):
                target_id = row.get("system")
                if not target_id or target_id == source_id:
                    continue
                distance_ly = self._neighbour_distance_ly(row)
                target = model.get_entity(target_id) if model is not None else None
                if distance_ly is None or not isinstance(target, dict):
                    continue

                edge_key = tuple(sorted((source_id, target_id)))
                existing = edges_by_key.get(edge_key)
                if existing is None:
                    edges_by_key[edge_key] = {
                        "a": edge_key[0],
                        "b": edge_key[1],
                        "distance_ly": distance_ly,
                    }
                else:
                    existing["distance_ly"] = (existing["distance_ly"] + distance_ly) / 2.0

                if target_id not in entities and len(entities) < max_nodes:
                    entities[target_id] = target
                    depths[target_id] = depths.get(source_id, 0) + 1
                    queue.append(target_id)

        edges = sorted(
            edges_by_key.values(),
            key=lambda edge: (
                min(depths.get(edge["a"], 999), depths.get(edge["b"], 999)),
                edge["distance_ly"],
                edge["a"],
                edge["b"],
            ),
        )
        graph = {"root_id": root_id, "entities": entities, "depths": depths, "edges": edges}
        self._stellar_graph_cache[cache_key] = graph
        if len(self._stellar_graph_cache) > 8:
            self._stellar_graph_cache.pop(next(iter(self._stellar_graph_cache)))
        return graph

    def _solve_position_from_constraints(self, constraints, placed):
        candidates = []
        for left_index in range(len(constraints)):
            anchor_a, radius_a_ly = constraints[left_index]
            pos_a = placed[anchor_a]
            radius_a = radius_a_ly * LY_M
            for right_index in range(left_index + 1, len(constraints)):
                anchor_b, radius_b_ly = constraints[right_index]
                pos_b = placed[anchor_b]
                radius_b = radius_b_ly * LY_M
                baseline = self._distance(pos_a, pos_b)
                if baseline <= 0:
                    continue

                ux = (pos_b[0] - pos_a[0]) / baseline
                uy = (pos_b[1] - pos_a[1]) / baseline
                along = (radius_a * radius_a - radius_b * radius_b + baseline * baseline) / (2.0 * baseline)
                height_sq = radius_a * radius_a - along * along
                height = math.sqrt(max(0.0, height_sq))
                base = (pos_a[0] + ux * along, pos_a[1] + uy * along)
                perpendicular = (-uy, ux)
                candidates.append((base[0] + perpendicular[0] * height, base[1] + perpendicular[1] * height))
                if height > 0:
                    candidates.append((base[0] - perpendicular[0] * height, base[1] - perpendicular[1] * height))

        if not candidates:
            return None, None

        def score(candidate):
            total = 0.0
            for anchor_id, distance_ly in constraints:
                expected = distance_ly * LY_M
                actual = self._distance(candidate, placed[anchor_id])
                scale = max(expected, 1.0)
                total += ((actual - expected) / scale) ** 2
            return total

        best = min(candidates, key=lambda candidate: (score(candidate), candidate[1] < 0, abs(candidate[1]), candidate[0]))
        return best, score(best)

    def _place_from_single_constraint(self, system_id, anchor_id, distance_ly, placed, parent_by):
        anchor_pos = placed[anchor_id]
        radius = distance_ly * LY_M
        parent_id = parent_by.get(anchor_id)
        if parent_id in placed:
            parent_pos = placed[parent_id]
            dx = anchor_pos[0] - parent_pos[0]
            dy = anchor_pos[1] - parent_pos[1]
            length = math.hypot(dx, dy)
            if length > 0:
                return (anchor_pos[0] + dx / length * radius, anchor_pos[1] + dy / length * radius)

        angle = self._stable_angle_for_id(system_id)
        return (anchor_pos[0] + math.cos(angle) * radius, anchor_pos[1] + math.sin(angle) * radius)

    def _stellar_neighbour_layout(self, sim, graph=None):
        graph = graph or self._stellar_neighbour_graph(sim)
        layout_key = id(graph)
        cached = self._stellar_layout_cache.get(layout_key)
        if cached is not None:
            return cached

        root_id = graph["root_id"]
        entities = graph["entities"]
        depths = graph["depths"]
        edges = graph["edges"]
        root = entities.get(root_id)
        if not isinstance(root, dict):
            return {}

        layout = {
            root_id: {
                "entity": root,
                "pos": (0.0, 0.0),
                "depth": 0,
                "distance_ly": 0.0,
            }
        }
        placed = {root_id: (0.0, 0.0)}
        parent_by = {}
        adjacency = {entity_id: [] for entity_id in entities.keys()}

        for edge in edges:
            a_id = edge["a"]
            b_id = edge["b"]
            distance_ly = edge["distance_ly"]
            if a_id not in entities or b_id not in entities:
                continue
            adjacency.setdefault(a_id, []).append((b_id, distance_ly))
            adjacency.setdefault(b_id, []).append((a_id, distance_ly))

        first_edge = next((edge for edge in edges if root_id in {edge["a"], edge["b"]}), None)
        if first_edge is not None:
            first_id = first_edge["b"] if first_edge["a"] == root_id else first_edge["a"]
            first_distance_ly = first_edge["distance_ly"]
            placed[first_id] = (first_distance_ly * LY_M, 0.0)
            parent_by[first_id] = root_id
            layout[first_id] = {
                "entity": entities[first_id],
                "pos": placed[first_id],
                "depth": depths.get(first_id, 1),
                "distance_ly": first_distance_ly,
                "parent_id": root_id,
                "constraint_error": 0.0,
            }

        unresolved = set(entities.keys()) - set(placed.keys())
        while unresolved:
            progress = False
            for system_id in sorted(unresolved, key=lambda item: (depths.get(item, 999), item)):
                constraints = [
                    (neighbor_id, distance_ly)
                    for neighbor_id, distance_ly in adjacency.get(system_id, [])
                    if neighbor_id in placed
                ]
                if not constraints:
                    continue

                if len(constraints) >= 2:
                    position, error = self._solve_position_from_constraints(constraints, placed)
                    if position is None:
                        anchor_id, distance_ly = constraints[0]
                        position = self._place_from_single_constraint(system_id, anchor_id, distance_ly, placed, parent_by)
                        error = None
                else:
                    anchor_id, distance_ly = constraints[0]
                    position = self._place_from_single_constraint(system_id, anchor_id, distance_ly, placed, parent_by)
                    error = None

                parent_id, parent_distance_ly = min(
                    constraints,
                    key=lambda item: (depths.get(item[0], 999), item[0]),
                )
                placed[system_id] = position
                parent_by[system_id] = parent_id
                layout[system_id] = {
                    "entity": entities[system_id],
                    "pos": position,
                    "depth": depths.get(system_id, 1),
                    "distance_ly": parent_distance_ly,
                    "parent_id": parent_id,
                    "constraint_error": error,
                }
                progress = True

            if not progress:
                break
            unresolved = set(entities.keys()) - set(placed.keys())

        self._stellar_layout_cache[layout_key] = layout
        if len(self._stellar_layout_cache) > 8:
            self._stellar_layout_cache.pop(next(iter(self._stellar_layout_cache)))
        return layout

    def _should_draw_stellar_neighbourhood(self, graph, camera, view):
        edges = graph.get("edges", []) if isinstance(graph, dict) else []
        if not edges:
            return False
        distances = []
        for edge in edges:
            try:
                distance = float(edge.get("distance_ly"))
            except (TypeError, ValueError):
                continue
            if distance > 0:
                distances.append(distance)
        if not distances:
            return False
        nearest_px = min(distances) * LY_M * float(getattr(camera, "zoom", 0.0) or 0.0)
        return nearest_px <= max(view.width, view.height) * 1.25

    def _draw_stellar_neighbourhood(self, screen, sim, camera):
        if getattr(sim, "root_body_id", None) is not None:
            return
        graph = self._stellar_neighbour_graph(sim)
        view = self.app_view
        if not self._should_draw_stellar_neighbourhood(graph, camera, view):
            return
        layout = self._stellar_neighbour_layout(sim, graph=graph)
        if len(layout) <= 1:
            return

        root_id = getattr(sim, "root_system_id", None)

        font = view.default_font
        for edge in graph.get("edges", []):
            a_item = layout.get(edge.get("a"))
            b_item = layout.get(edge.get("b"))
            if a_item is None or b_item is None:
                continue
            a_point = camera.world_to_screen(a_item.get("pos", (0.0, 0.0)))
            b_point = camera.world_to_screen(b_item.get("pos", (0.0, 0.0)))
            if a_point is None or b_point is None:
                continue
            pygame.draw.line(screen, (58, 76, 96), a_point, b_point, 1)
            midpoint = ((a_point[0] + b_point[0]) / 2, (a_point[1] + b_point[1]) / 2)
            distance_label = f"{edge.get('distance_ly', 0):.2f} ly"
            label = font.render(distance_label, True, (118, 142, 168))
            screen.blit(label, (int(midpoint[0]) + 4, int(midpoint[1]) + 4))

        for system_id, item in layout.items():
            if system_id == root_id:
                continue
            pos = item.get("pos", (0.0, 0.0))
            point = camera.world_to_screen(pos)
            if point is None:
                continue
            depth = item.get("depth", 1)
            color = (104, 146, 198) if depth == 1 else (76, 98, 128)
            pygame.draw.circle(screen, color, (int(point[0]), int(point[1])), 5 if depth == 1 else 4)
            pygame.draw.circle(screen, (180, 206, 236), (int(point[0]), int(point[1])), 7 if depth == 1 else 6, 1)
            label = font.render(item["entity"].get("name", system_id), True, (172, 198, 228) if depth == 1 else (132, 150, 176))
            screen.blit(label, (int(point[0]) + 9, int(point[1]) - 8))

    def _draw_habitable_zone(self, screen, sim, camera):
        if getattr(sim, "root_body_id", None) is not None:
            return

        system_entity = sim.world_model.get_entity(getattr(sim, "root_system_id", None))
        if not isinstance(system_entity, dict):
            return

        inner_au = system_entity.get("habitable_zone_inner_au")
        outer_au = system_entity.get("habitable_zone_outer_au")
        if inner_au is None or outer_au is None:
            for entry in sim.system.get_entries():
                source = sim.system.get_source_entity_for_space_object(entry.get("object"))
                if not isinstance(source, dict):
                    continue
                if source.get("location_class") != "star" and source.get("body_class") != "star":
                    continue
                luminosity = source.get("luminosity_solar") or source.get("luminosity_l_sun")
                if luminosity is None:
                    continue
                zone = habitable_zone_for_luminosity(luminosity)
                inner_au = zone["habitable_zone_inner_au"]
                outer_au = zone["habitable_zone_outer_au"]
                break

        try:
            inner_au = float(inner_au)
            outer_au = float(outer_au)
        except (TypeError, ValueError):
            return
        if outer_au <= inner_au:
            return

        center = camera.world_to_screen((0.0, 0.0))
        if center is None:
            return

        inner_px_float = inner_au * AU_M * camera.zoom
        outer_px_float = outer_au * AU_M * camera.zoom
        if not math.isfinite(inner_px_float) or not math.isfinite(outer_px_float):
            return
        inner_px = int(inner_px_float)
        outer_px = int(outer_px_float)
        if outer_px <= 1:
            return
        max_radius_px = max(screen.get_width(), screen.get_height()) * 4
        if inner_px > max_radius_px and outer_px > max_radius_px:
            return
        inner_px = max(0, min(inner_px, max_radius_px))
        outer_px = max(0, min(outer_px, max_radius_px))

        zone_bounds = pygame.Rect(
            int(center[0] - outer_px - 3),
            int(center[1] - outer_px - 3),
            outer_px * 2 + 6,
            outer_px * 2 + 6,
        ).clip(screen.get_rect())
        if zone_bounds.width <= 0 or zone_bounds.height <= 0:
            return

        local_center = (
            int(center[0] - zone_bounds.x),
            int(center[1] - zone_bounds.y),
        )
        zone_surface = pygame.Surface(zone_bounds.size, pygame.SRCALPHA)
        pygame.draw.circle(zone_surface, (94, 132, 86, 36), local_center, outer_px)
        if inner_px > 0:
            pygame.draw.circle(zone_surface, (0, 0, 0, 0), local_center, inner_px)
        pygame.draw.circle(zone_surface, (150, 196, 138, 120), local_center, outer_px, 2)
        if inner_px > 0:
            pygame.draw.circle(zone_surface, (150, 196, 138, 110), local_center, inner_px, 2)
        screen.blit(zone_surface, zone_bounds.topleft)

    def _draw_gas_giant_bands(self, screen, rect, layer):
        bands = layer.get("bands") if isinstance(layer.get("bands"), list) else []
        if not bands:
            bands = [layer.get("color", (180, 170, 150))]
        clip = screen.get_clip()
        screen.set_clip(rect.clip(screen.get_rect()))
        band_count = max(1, len(bands))
        for index in range(band_count):
            color = bands[index]
            try:
                color = (int(color[0]), int(color[1]), int(color[2]))
            except (TypeError, ValueError, IndexError):
                color = layer.get("color", (180, 170, 150))
            y0 = rect.y + int(index * rect.height / band_count)
            y1 = rect.y + int((index + 1) * rect.height / band_count)
            pygame.draw.rect(screen, color, pygame.Rect(rect.x, y0, rect.width, max(1, y1 - y0)))
        pygame.draw.ellipse(screen, (18, 20, 24), rect, max(1, rect.width // 28))
        pygame.draw.ellipse(screen, (226, 226, 220), rect, 2)
        screen.set_clip(clip)

    def _draw_readable_label(self, screen, text, pos, color):
        font = self.app_view.default_font
        label = font.render(str(text or ""), True, color)
        label_rect = label.get_rect(topleft=(int(pos[0]), int(pos[1])))
        bg_rect = label_rect.inflate(8, 4)
        pygame.draw.rect(screen, (10, 12, 16), bg_rect)
        pygame.draw.rect(screen, (48, 54, 66), bg_rect, 1)
        screen.blit(label, label_rect)
        return bg_rect

    def _draw_body_focus_ring(self, screen, rect, is_selected, is_hovered):
        if not is_selected and not is_hovered:
            return

        ring_rect = rect.inflate(10 if is_selected else 7, 10 if is_selected else 7)
        color = (255, 226, 112) if is_selected else (126, 218, 252)
        width = 3 if is_selected else 2
        pygame.draw.rect(screen, color, ring_rect, width)

    def draw(self, screen, sim):
        view = self.app_view
        camera = view.camera
        if hasattr(sim, "clear_body_label_hitboxes"):
            sim.clear_body_label_hitboxes()

        root_only_label_zoom = 2.5e-10
        all_children_label_zoom = 2.0e-9

        self._draw_stellar_neighbourhood(screen, sim, camera)
        self._draw_habitable_zone(screen, sim, camera)

        for body in sim.system.get_entries():
            obj = body["object"]
            orbit = getattr(obj, "orbit", None)

            if orbit is None:
                continue

            draw_orbit(screen, camera, orbit)

        for body in sim.system.get_entries():
            obj = body["object"]
            bx, by = obj.get_position()
            source_entity = sim.system.get_source_entity_for_space_object(obj)
            orbit = getattr(obj, "orbit", None)
            parent_obj = getattr(orbit, "parent", None) if orbit is not None else None
            grandparent_obj = None
            if parent_obj is not None:
                parent_orbit = getattr(parent_obj, "orbit", None)
                if parent_orbit is not None:
                    grandparent_obj = getattr(parent_orbit, "parent", None)
            is_star = isinstance(source_entity, dict) and (
                source_entity.get("location_class") == "star"
                or source_entity.get("body_class") == "star"
            )
            is_primary_system_member = (parent_obj is not None and grandparent_obj is None)
            is_subsystem_body = (parent_obj is not None and grandparent_obj is not None)

            layer_stack = body["layers"]
            layers = layer_stack.get_layers() if layer_stack else []

            body_rect = None
            body_pixel_size = 0

            for layer in layers:
                x = layer["x"] + bx
                y = layer["y"] + by
                size = layer["size"]

                center = camera.world_to_screen((x, y))

                if center is None:
                    continue

                projected_size = float(size) * float(camera.zoom)
                if not math.isfinite(projected_size):
                    continue
                # A map-to-space tab switch can briefly retain the map camera's
                # zoom. Keep Pygame Rect values bounded until camera setup lands.
                pixel_size = max(1, min(max(view.width, view.height) * 2, int(abs(projected_size))))
                if is_star:
                    pixel_size = max(18, pixel_size)
                elif is_primary_system_member:
                    pixel_size = max(7, pixel_size)
                elif is_subsystem_body:
                    pixel_size = max(4, pixel_size)

                rect = pygame.Rect(
                    int(center[0] - pixel_size / 2),
                    int(center[1] - pixel_size / 2),
                    pixel_size,
                    pixel_size,
                )

                if (
                    rect.right < 0
                    or rect.left > view.width
                    or rect.bottom < 0
                    or rect.top > view.height
                ):
                    continue

                if is_star:
                    star_color = layer["color"]
                    glow_radius = max(16, min(pixel_size, max(view.width, view.height) // 3 + 32))
                    glow_surface = pygame.Surface((glow_radius * 4, glow_radius * 4), pygame.SRCALPHA)
                    glow_center = (glow_surface.get_width() // 2, glow_surface.get_height() // 2)
                    pygame.draw.circle(
                        glow_surface,
                        (star_color[0], star_color[1], star_color[2], 42),
                        glow_center,
                        glow_radius * 2,
                    )
                    pygame.draw.circle(
                        glow_surface,
                        (star_color[0], star_color[1], star_color[2], 96),
                        glow_center,
                        glow_radius,
                    )
                    screen.blit(
                        glow_surface,
                        (
                            int(center[0]) - glow_center[0],
                            int(center[1]) - glow_center[1],
                        ),
                    )
                    pygame.draw.circle(
                        screen,
                        star_color,
                        (int(center[0]), int(center[1])),
                        max(6, pixel_size // 2),
                    )
                    pygame.draw.circle(
                        screen,
                        (255, 246, 208),
                        (int(center[0]), int(center[1])),
                        max(8, pixel_size // 2 + 2),
                        1,
                    )
                elif layer.get("render_style") == "gas_giant_bands":
                    self._draw_gas_giant_bands(screen, rect, layer)
                else:
                    pygame.draw.rect(screen, layer["color"], rect)
                    pygame.draw.rect(screen, (220, 220, 220), rect, 2)

                body_rect = rect
                body_pixel_size = max(body_pixel_size, pixel_size)

                if rect.width >= 60 and rect.height >= 24:
                    text = view.default_font.render(
                        f"{body['name']} : {layer['name']}",
                        True,
                        (240, 240, 240)
                    )
                    screen.blit(text, (rect.x + 6, rect.y + 6))

            if body_rect is None:
                continue

            source_entity_id = source_entity.get("id") if isinstance(source_entity, dict) else None
            self._draw_body_focus_ring(
                screen,
                body_rect,
                source_entity_id is not None and source_entity_id == getattr(sim, "selected_system_entity_id", None),
                source_entity_id is not None and source_entity_id == getattr(sim, "hover_system_entity_id", None),
            )

            is_root_body = orbit is None

            show_label = False

            if is_root_body:
                show_label = True
            elif camera.zoom < root_only_label_zoom:
                show_label = is_primary_system_member
            elif camera.zoom < all_children_label_zoom:
                show_label = is_primary_system_member
            else:
                show_label = True

            if not show_label:
                continue

            label_anchor = (body_rect.right + 8, body_rect.y - 2)

            label_color = (240, 240, 240)
            if is_subsystem_body and camera.zoom < all_children_label_zoom:
                label_color = (170, 170, 170)

            label_rect = self._draw_readable_label(
                screen,
                body["name"],
                label_anchor,
                label_color,
            )
            if hasattr(sim, "register_body_label_hitbox"):
                sim.register_body_label_hitbox(source_entity_id, label_rect)
