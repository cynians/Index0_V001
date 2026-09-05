import colorsys
import gzip
import io
import json
import os

import pygame

from world.texture_sets import TextureSet, cell_key, parse_cell_key


class PixelArtEditorUI:
    def __init__(self, host):
        self.host = host

    @property
    def state(self):
        return getattr(self.host, "pixel_art_editor", None)

    @state.setter
    def state(self, value):
        self.host.pixel_art_editor = value

    @property
    def painting(self):
        return bool(getattr(self.host, "pixel_art_painting", False))

    @painting.setter
    def painting(self, value):
        self.host.pixel_art_painting = bool(value)

    @property
    def pixel_art_editor(self):
        return self.state

    @property
    def layout(self):
        return self.host.layout

    @property
    def LINE_HEIGHT(self):
        return self.host.LINE_HEIGHT

    def _ellipsize_text(self, text, font, max_width):
        return self.host._ellipsize_text(text, font, max_width)

    def _pixel_editor_metric_size(self):
        return self.metric_size()

    def _pixel_canvas_size_for_entity(self, entity, metric_size_m):
        return self.host._pixel_canvas_size_for_entity(entity, metric_size_m)

    def open(self, illustration_id):
        if self.host.world_model is None or not illustration_id:
            return False
        illustration = self.host.world_model.get_entity(illustration_id)
        if not isinstance(illustration, dict):
            return False
        if str(illustration.get("idea_class") or "").strip().lower() != "illustration":
            return False

        parent = self.host._parent_entity_for_illustration(illustration)
        existing_size = illustration.get("depicted_size_m") or illustration.get("metric_size_m")
        size_text = "" if existing_size in (None, "") else str(existing_size)
        setup_mode = str(illustration.get("pixel_editor_mode") or "single")
        if setup_mode not in {"single", "orthographic", "texture"}:
            setup_mode = "single"
        dimension_buffers = {
            "length": str(illustration.get("depicted_length_m") or size_text),
            "width": str(illustration.get("depicted_width_m") or ""),
            "height": str(illustration.get("depicted_height_m") or ""),
        }
        self.state = {
            "stage": "size",
            "illustration_id": illustration_id,
            "illustration": illustration,
            "parent_entity": parent,
            "metric_size_buffer": size_text,
            "metric_size_cursor": len(size_text),
            "setup_mode": setup_mode,
            "dimension_buffers": dimension_buffers,
            "dimension_cursors": {key: len(value) for key, value in dimension_buffers.items()},
            "active_dimension": "length",
            "views": {},
            "active_view": "single",
            "status": "Enter depicted size in meters",
            "color": (236, 240, 246),
            "hsv": colorsys.rgb_to_hsv(236 / 255.0, 240 / 255.0, 246 / 255.0),
            "pixels": [],
            "layers": [],
            "active_layer": 0,
            "canvas_width": 0,
            "canvas_height": 0,
            "tool": "brush",
            "shape_filled": False,
            "shape_start": None,
            "shape_end": None,
            "brush_size": 1,
            "pressure_size": True,
            "pressure": 1.0,
            "zoom": 1.0,
            "pan": [0.0, 0.0],
            "panning": False,
            "pan_anchor": None,
            "show_grid": True,
            "mirror_x": False,
            "onion_skin": False,
            "undo_stack": [],
            "redo_stack": [],
            "stroke_before": None,
            "stroke_changed": False,
            "dirty": False,
            "revision": 0,
            "composite_cache": None,
            "last_paint_cell": None,
            "active_slider": None,
            "tool_hitboxes": {},
            "brush_size_hitboxes": {},
            "clear_rect": None,
            "reference_surface": None,
            "reference_rect": None,
            "anchor_mode": None,
            "attachment_point_px": None,
            "growth_axis_px": None,
            "setup_mode_hitboxes": {},
            "dimension_hitboxes": {},
            "view_hitboxes": {},
            "texture_grid": {"columns": 3, "rows": 3},
            "texture_base_layers": None,
            "texture_variants": {},
            "texture_active_cell": None,
            "texture_seed": int(illustration.get("texture_seed") or 17),
            "texture_cell_hitboxes": {},
            "texture_action_hitboxes": {},
        }
        self.painting = False
        return True

    def close(self):
        self.state = None
        self.painting = False
        return True

    def request_close(self):
        editor = self.state
        if isinstance(editor, dict) and editor.get("dirty") and not editor.get("confirm_close"):
            editor["confirm_close"] = True
            editor["status"] = "Unsaved changes — press Close or Esc again to discard"
            return True
        return self.close()

    def metric_size(self):
        editor = self.state if isinstance(self.state, dict) else {}
        try:
            return max(0.0, float(str(editor.get("metric_size_buffer") or "").replace(",", ".")))
        except ValueError:
            return None

    def dimension_value(self, name):
        editor = self.state if isinstance(self.state, dict) else {}
        try:
            return max(0.0, float(str((editor.get("dimension_buffers") or {}).get(name) or "").replace(",", ".")))
        except ValueError:
            return None

    def _new_view(self, width, height, name):
        pixels = self._blank_pixels(width, height)
        return {
            "name": name,
            "width": width,
            "height": height,
            "layers": [{"name": "Layer 1", "visible": True, "opacity": 1.0, "pixels": pixels}],
            "active_layer": 0,
            "undo_stack": [],
            "redo_stack": [],
            "revision": 0,
            "composite_cache": None,
            "zoom": 1.0,
            "pan": [0.0, 0.0],
        }

    def _sync_active_view(self):
        editor = self.state
        if not isinstance(editor, dict) or not editor.get("views"):
            return
        view = editor["views"].get(editor.get("active_view"))
        if not isinstance(view, dict):
            return
        view.update({
            "width": int(editor.get("canvas_width") or 0),
            "height": int(editor.get("canvas_height") or 0),
            "layers": editor.get("layers") or [],
            "active_layer": int(editor.get("active_layer") or 0),
            "undo_stack": editor.get("undo_stack") or [],
            "redo_stack": editor.get("redo_stack") or [],
            "revision": int(editor.get("revision") or 0),
            "composite_cache": editor.get("composite_cache"),
            "zoom": float(editor.get("zoom", 1.0)),
            "pan": list(editor.get("pan") or [0.0, 0.0]),
        })

    def switch_view(self, view_id):
        editor = self.state
        if not isinstance(editor, dict) or view_id not in (editor.get("views") or {}):
            return False
        self.finish_stroke()
        self._sync_active_view()
        view = editor["views"][view_id]
        editor["active_view"] = view_id
        editor["canvas_width"] = int(view.get("width") or 1)
        editor["canvas_height"] = int(view.get("height") or 1)
        editor["layers"] = view.get("layers") or []
        editor["active_layer"] = int(view.get("active_layer") or 0)
        editor["undo_stack"] = view.setdefault("undo_stack", [])
        editor["redo_stack"] = view.setdefault("redo_stack", [])
        editor["revision"] = int(view.get("revision") or 0)
        editor["composite_cache"] = view.get("composite_cache")
        editor["zoom"] = float(view.get("zoom", 1.0))
        editor["pan"] = list(view.get("pan") or [0.0, 0.0])
        self._active_layer()
        editor["status"] = f"{view.get('name', view_id.title())} view — {editor['canvas_width']} x {editor['canvas_height']} px"
        return True

    def _orthographic_view_sizes(self, length, width, height):
        longest = max(length, width, height)
        base_size = self.host._pixel_canvas_size_for_entity(self.state.get("parent_entity"), longest)
        pixels_per_meter = max(base_size) / max(0.001, longest)

        def size(horizontal, vertical):
            return max(8, round(horizontal * pixels_per_meter)), max(8, round(vertical * pixels_per_meter))

        return {
            "front": size(length, height),
            "side": size(width, height),
            "top": size(length, width),
        }

    def begin_canvas(self):
        editor = self.state
        if not isinstance(editor, dict):
            return False
        mode = editor.get("setup_mode", "single")
        dimensions = None
        if mode == "orthographic":
            dimensions = {name: self.dimension_value(name) for name in ("length", "width", "height")}
            if any(value is None or value <= 0 for value in dimensions.values()):
                editor["status"] = "Length, width, and height must all be positive meter values"
                return True
            view_sizes = self._orthographic_view_sizes(dimensions["length"], dimensions["width"], dimensions["height"])
            views = {view_id: self._new_view(*view_sizes[view_id], f"{view_id.title()}") for view_id in ("front", "side", "top")}
            width, height = view_sizes["front"]
        else:
            metric_size_m = self.metric_size()
            if metric_size_m is None or metric_size_m <= 0:
                editor["status"] = "Size must be a positive meter value"
                return True
            width, height = self.host._pixel_canvas_size_for_entity(editor.get("parent_entity"), metric_size_m)
            views = {"single": self._new_view(width, height, "Single")}
        existing_surface = None
        loaded_layers = None
        loaded_views = None
        loaded_texture = None
        document = {}
        document_path = str((editor.get("illustration") or {}).get("pixel_document_path") or "").strip()
        if document_path:
            candidate = os.path.normpath(str(self.host.PROJECT_ROOT / document_path))
            try:
                with gzip.open(candidate, "rt", encoding="utf-8") as handle:
                    document = json.load(handle)
                doc_width, doc_height = int(document.get("width") or 0), int(document.get("height") or 0)
                candidate_layers = document.get("layers")
                candidate_views = document.get("views")
                loaded_texture = TextureSet.from_dict(document.get("texture_set")) if mode == "texture" else None
                if mode == "orthographic" and isinstance(candidate_views, dict) and all(key in candidate_views for key in ("front", "side", "top")):
                    loaded_views = candidate_views
                if loaded_texture is not None:
                    width, height, loaded_layers = loaded_texture.width, loaded_texture.height, loaded_texture.base_layers
                elif doc_width > 0 and doc_height > 0 and isinstance(candidate_layers, list) and candidate_layers:
                    width, height, loaded_layers = doc_width, doc_height, candidate_layers
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                loaded_layers = None
        media_path = str((editor.get("illustration") or {}).get("media_path") or "").strip()
        if media_path and loaded_layers is None and loaded_views is None and mode == "single":
            candidate = os.path.normpath(str(self.host.PROJECT_ROOT / media_path))
            if os.path.isfile(candidate):
                try:
                    existing_surface = pygame.image.load(candidate).convert_alpha()
                    width, height = existing_surface.get_size()
                except (pygame.error, OSError):
                    existing_surface = None
        pixels = self._blank_pixels(width, height)
        if existing_surface is not None:
            for y in range(height):
                for x in range(width):
                    color = existing_surface.get_at((x, y))
                    if color.a:
                        pixels[y][x] = (color.r, color.g, color.b)
        if mode in {"single", "texture"}:
            single = views["single"]
            single["layers"] = loaded_layers or [{"name": "Layer 1", "visible": True, "opacity": 1.0, "pixels": pixels}]
            single["active_layer"] = max(0, min(int((document if loaded_layers else {}).get("active_layer", 0)), len(single["layers"]) - 1))
        elif loaded_views:
            views = loaded_views
        editor["stage"] = "canvas"
        editor["views"] = views
        initial_view = "front" if mode == "orthographic" else "single"
        editor["active_view"] = None
        editor["dirty"] = False
        self.switch_view(initial_view)
        if mode == "texture":
            grid = (loaded_texture.to_dict().get("grid") if loaded_texture is not None else None) or {"columns": 3, "rows": 3}
            editor["texture_grid"] = {
                "columns": max(1, int(grid.get("columns") or 3)),
                "rows": max(1, int(grid.get("rows") or 3)),
            }
            editor["texture_base_layers"] = self._snapshot_layers(loaded_texture.base_layers if loaded_texture is not None else editor.get("layers") or [])
            editor["texture_variants"] = {
                variant.key: self._snapshot_layers(variant.layers)
                for variant in (loaded_texture.variants.values() if loaded_texture is not None else [])
            }
            editor["texture_seed"] = int(loaded_texture.seed if loaded_texture is not None else editor.get("texture_seed") or 17)
            editor["texture_active_cell"] = None
            editor["status"] = f"Texture mode — paint the base tile, then click a surrounding tile to activate it"
        module_anchor = document.get("module_anchor") if isinstance(document, dict) else None
        if not isinstance(module_anchor, dict):
            module_anchor = (editor.get("illustration") or {}).get("pixel_module_anchor") or {}
        point = module_anchor.get("attachment_point") if isinstance(module_anchor, dict) else None
        axis = (module_anchor.get("growth_vector") or module_anchor.get("growth_axis")) if isinstance(module_anchor, dict) else None
        if isinstance(point, (list, tuple)) and len(point) >= 2:
            editor["attachment_point_px"] = (
                round(max(0.0, min(1.0, float(point[0]))) * max(0, editor["canvas_width"] - 1)),
                round(max(0.0, min(1.0, float(point[1]))) * max(0, editor["canvas_height"] - 1)),
            )
        if isinstance(axis, (list, tuple)) and len(axis) >= 2:
            editor["growth_axis_px"] = (float(axis[0]), float(axis[1]))
        if loaded_views:
            editor["status"] = "Restored front, side, and top drawing views"
        elif mode == "texture" and loaded_texture is not None:
            editor["status"] = f"Restored texture base and {len(editor.get('texture_variants') or {})} character tiles"
        elif loaded_layers:
            editor["status"] = f"Restored {len(loaded_layers)} layers"
        elif existing_surface is not None:
            editor["status"] = f"Editing existing {width} x {height} px image"
        return True

    @staticmethod
    def _blank_pixels(width, height):
        return [[None for _ in range(width)] for _ in range(height)]

    @staticmethod
    def _copy_pixels(pixels):
        return [list(row) for row in pixels]

    def _layers(self):
        editor = self.state
        if not isinstance(editor, dict):
            return []
        layers = editor.get("layers")
        if not isinstance(layers, list) or not layers:
            pixels = editor.get("pixels")
            if isinstance(pixels, list):
                layers = [{"name": "Layer 1", "visible": True, "opacity": 1.0, "pixels": pixels}]
                editor["layers"] = layers
            else:
                return []
        return layers

    def _active_layer(self):
        editor = self.state
        layers = self._layers()
        if not isinstance(editor, dict) or not layers:
            return None
        index = max(0, min(int(editor.get("active_layer") or 0), len(layers) - 1))
        editor["active_layer"] = index
        editor["pixels"] = layers[index]["pixels"]  # Compatibility with the original editor contract.
        return layers[index]

    def _snapshot(self):
        return self._snapshot_layers(self._layers())

    def _snapshot_layers(self, layers):
        return [{
            "name": str(layer.get("name") or "Layer"),
            "visible": bool(layer.get("visible", True)),
            "opacity": float(layer.get("opacity", 1.0)),
            "reference_only": bool(layer.get("reference_only", False)),
            "locked": bool(layer.get("locked", False)),
            "pixels": self._copy_pixels(layer.get("pixels") or []),
        } for layer in layers]

    def _texture_mode(self):
        editor = self.state
        return isinstance(editor, dict) and editor.get("stage") == "canvas" and editor.get("setup_mode") == "texture"

    def _texture_center(self):
        editor = self.state
        grid = editor.get("texture_grid") or {"columns": 3, "rows": 3}
        return (int(grid.get("columns") or 3) // 2, int(grid.get("rows") or 3) // 2)

    def _texture_store_current(self):
        """Commit the tile currently being painted into the sparse texture state."""
        editor = self.state
        if not self._texture_mode():
            return
        snapshot = self._snapshot_layers(self._layers())
        active = parse_cell_key(editor.get("texture_active_cell"))
        if active is None:
            editor["texture_base_layers"] = snapshot
        else:
            editor.setdefault("texture_variants", {})[cell_key(*active)] = snapshot

    def _texture_layers_for_cell(self, x, y):
        editor = self.state
        if not self._texture_mode():
            return []
        active = parse_cell_key(editor.get("texture_active_cell"))
        if active == (int(x), int(y)):
            return self._layers()
        if (int(x), int(y)) == self._texture_center():
            return editor.get("texture_base_layers") or self._layers()
        key = cell_key(x, y)
        return (editor.get("texture_variants") or {}).get(key) or editor.get("texture_base_layers") or self._layers()

    def _texture_load_cell(self, x, y):
        editor = self.state
        if not self._texture_mode():
            return False
        self.finish_stroke()
        self._sync_active_view()
        self._texture_store_current()
        x, y = int(x), int(y)
        center = self._texture_center()
        key = cell_key(x, y)
        newly_activated = (x, y) != center and key not in (editor.get("texture_variants") or {})
        if newly_activated:
            editor.setdefault("texture_variants", {})[key] = self._snapshot_layers(editor.get("texture_base_layers") or self._layers())
        layers = self._texture_layers_for_cell(x, y)
        editor["texture_active_cell"] = None if (x, y) == center else key
        editor["layers"] = self._snapshot_layers(layers)
        editor["active_layer"] = 0
        editor["undo_stack"] = []
        editor["redo_stack"] = []
        editor["revision"] = int(editor.get("revision") or 0) + 1
        editor["composite_cache"] = None
        self._active_layer()
        editor["dirty"] = editor.get("dirty", False) or newly_activated
        if (x, y) == center:
            editor["status"] = "Base tile selected — edits repeat everywhere"
        elif newly_activated:
            editor["status"] = f"Activated character tile {x + 1},{y + 1} — paint its unique marks"
        else:
            editor["status"] = f"Editing character tile {x + 1},{y + 1}"
        return True

    def deactivate_texture_cell(self):
        editor = self.state
        active = parse_cell_key(editor.get("texture_active_cell")) if isinstance(editor, dict) else None
        if not self._texture_mode() or active is None:
            return False
        self._texture_store_current()
        editor.setdefault("texture_variants", {}).pop(cell_key(*active), None)
        editor["texture_active_cell"] = None
        editor["layers"] = self._snapshot_layers(editor.get("texture_base_layers") or self._layers())
        editor["active_layer"] = 0
        editor["undo_stack"] = []
        editor["redo_stack"] = []
        editor["composite_cache"] = None
        self._active_layer()
        editor["dirty"] = True
        editor["status"] = f"Deactivated character tile {active[0] + 1},{active[1] + 1} — it repeats the base again"
        return True

    def shuffle_texture_seed(self):
        editor = self.state
        if not self._texture_mode():
            return False
        editor["texture_seed"] = int(editor.get("texture_seed") or 17) + 1
        editor["status"] = f"Shuffle preview seed {editor['texture_seed']}"
        return True

    def _texture_set(self):
        editor = self.state
        if not self._texture_mode():
            return None
        self._texture_store_current()
        width = int(editor.get("canvas_width") or 1)
        height = int(editor.get("canvas_height") or 1)
        grid = editor.get("texture_grid") or {"columns": 3, "rows": 3}
        texture = TextureSet(
            width=width,
            height=height,
            base_layers=self._snapshot_layers(editor.get("texture_base_layers") or self._layers()),
            grid_columns=max(1, int(grid.get("columns") or 3)),
            grid_rows=max(1, int(grid.get("rows") or 3)),
            seed=int(editor.get("texture_seed") or 17),
            texture_id=str((editor.get("illustration") or {}).get("id") or editor.get("illustration_id") or ""),
        )
        for key, layers in (editor.get("texture_variants") or {}).items():
            parsed = parse_cell_key(key)
            if parsed is not None:
                texture.add_variant(parsed[0], parsed[1], self._snapshot_layers(layers))
        return texture

    def _mark_dirty(self):
        editor = self.state
        if isinstance(editor, dict):
            editor["dirty"] = True
            editor["revision"] = int(editor.get("revision") or 0) + 1
            editor["composite_cache"] = None

    def _restore_snapshot(self, snapshot):
        editor = self.state
        if not isinstance(editor, dict) or not isinstance(snapshot, list) or not snapshot:
            return False
        editor["layers"] = snapshot
        editor["active_layer"] = min(int(editor.get("active_layer") or 0), len(snapshot) - 1)
        self._active_layer()
        self._mark_dirty()
        return True

    def _push_undo(self, snapshot=None):
        editor = self.state
        if not isinstance(editor, dict):
            return
        stack = editor.setdefault("undo_stack", [])
        stack.append(snapshot if snapshot is not None else self._snapshot())
        if len(stack) > 30:
            del stack[0]
        editor["redo_stack"] = []

    def undo(self):
        editor = self.state
        if not isinstance(editor, dict) or not editor.get("undo_stack"):
            return False
        editor.setdefault("redo_stack", []).append(self._snapshot())
        self._restore_snapshot(editor["undo_stack"].pop())
        editor["status"] = "Undo"
        return True

    def redo(self):
        editor = self.state
        if not isinstance(editor, dict) or not editor.get("redo_stack"):
            return False
        editor.setdefault("undo_stack", []).append(self._snapshot())
        self._restore_snapshot(editor["redo_stack"].pop())
        editor["status"] = "Redo"
        return True

    def add_layer(self):
        editor = self.state
        if not isinstance(editor, dict):
            return False
        self._push_undo()
        layers = self._layers()
        width, height = int(editor.get("canvas_width") or 0), int(editor.get("canvas_height") or 0)
        index = min(len(layers), int(editor.get("active_layer") or 0) + 1)
        layers.insert(index, {"name": f"Layer {len(layers) + 1}", "visible": True, "opacity": 1.0, "pixels": self._blank_pixels(width, height)})
        editor["active_layer"] = index
        self._active_layer()
        self._mark_dirty()
        editor["status"] = "Layer added"
        return True

    def duplicate_layer(self):
        editor = self.state
        layer = self._active_layer()
        if not isinstance(editor, dict) or layer is None:
            return False
        if layer.get("reference_only"):
            editor["status"] = "Use <- Trace to replace the reference layer"
            return False
        self._push_undo()
        duplicate = {**layer, "name": f"{layer.get('name', 'Layer')} copy", "pixels": self._copy_pixels(layer["pixels"])}
        index = int(editor.get("active_layer") or 0) + 1
        self._layers().insert(index, duplicate)
        editor["active_layer"] = index
        self._active_layer()
        self._mark_dirty()
        return True

    def delete_layer(self):
        editor = self.state
        layers = self._layers()
        if not isinstance(editor, dict) or len(layers) <= 1:
            if isinstance(editor, dict):
                editor["status"] = "A document needs at least one layer"
            return False
        active_index = int(editor.get("active_layer") or 0)
        drawing_layer_count = sum(1 for layer in layers if not layer.get("reference_only"))
        if not layers[active_index].get("reference_only") and drawing_layer_count <= 1:
            editor["status"] = "A document needs at least one drawing layer"
            return False
        self._push_undo()
        layers.pop(active_index)
        editor["active_layer"] = min(int(editor.get("active_layer") or 0), len(layers) - 1)
        self._active_layer()
        self._mark_dirty()
        return True

    def move_layer(self, delta):
        editor = self.state
        layers = self._layers()
        if not isinstance(editor, dict) or not layers:
            return False
        old = int(editor.get("active_layer") or 0)
        if layers[old].get("reference_only"):
            editor["status"] = "The reference trace stays at the bottom"
            return False
        lowest_drawing_index = 1 if layers and layers[0].get("reference_only") else 0
        new = max(lowest_drawing_index, min(len(layers) - 1, old + int(delta)))
        if old == new:
            return False
        self._push_undo()
        layers.insert(new, layers.pop(old))
        editor["active_layer"] = new
        self._active_layer()
        self._mark_dirty()
        return True

    def toggle_layer_visibility(self, index):
        layers = self._layers()
        if not (0 <= int(index) < len(layers)):
            return False
        self._push_undo()
        layer = layers[int(index)]
        layer["visible"] = not bool(layer.get("visible", True))
        self._mark_dirty()
        return True

    def select_layer(self, index):
        editor = self.state
        layers = self._layers()
        if not isinstance(editor, dict) or not (0 <= int(index) < len(layers)):
            return False
        editor["active_layer"] = int(index)
        self._active_layer()
        editor["status"] = str(layers[int(index)].get("name") or "Layer")
        return True

    def set_color_from_hsv(self, channel, value):
        editor = self.state
        if not isinstance(editor, dict):
            return False
        hue, saturation, brightness = editor.get("hsv", (0.0, 0.0, 1.0))
        value = max(0.0, min(1.0, float(value)))
        if channel == "h":
            hue = value
        elif channel == "s":
            saturation = value
        elif channel == "v":
            brightness = value
        red, green, blue = colorsys.hsv_to_rgb(hue, saturation, brightness)
        editor["hsv"] = (hue, saturation, brightness)
        editor["color"] = (
            int(round(red * 255)),
            int(round(green * 255)),
            int(round(blue * 255)),
        )
        return True

    def set_color_rgb(self, color):
        editor = self.state
        if not isinstance(editor, dict):
            return False
        try:
            red, green, blue = [max(0, min(255, int(part))) for part in color[:3]]
        except (TypeError, ValueError):
            return False
        editor["color"] = (red, green, blue)
        editor["hsv"] = colorsys.rgb_to_hsv(red / 255.0, green / 255.0, blue / 255.0)
        return True

    def set_tool(self, tool):
        editor = self.state
        tool_labels = {
            "brush": "Brush selected", "eraser": "Eraser selected", "eyedropper": "Color picker selected", "fill": "Fill selected",
            "rectangle": "Rectangle: drag on the canvas", "triangle": "Triangle: drag on the canvas",
            "trapezoid": "Trapezoid: drag on the canvas", "line": "Line: drag on the canvas",
            "circle": "Circle: drag on the canvas",
        }
        if not isinstance(editor, dict) or tool not in tool_labels:
            return False
        editor["tool"] = tool
        editor["status"] = tool_labels[tool]
        return True

    def set_brush_size(self, brush_size):
        editor = self.state
        if not isinstance(editor, dict):
            return False
        try:
            brush_size = int(brush_size)
        except (TypeError, ValueError):
            return False
        brush_size = max(1, min(16, brush_size))
        editor["brush_size"] = brush_size
        editor["status"] = f"Brush size {brush_size} px"
        return True

    def clear_canvas(self):
        editor = self.state
        if not isinstance(editor, dict) or editor.get("stage") != "canvas":
            return False
        width = int(editor.get("canvas_width") or 0)
        height = int(editor.get("canvas_height") or 0)
        if width <= 0 or height <= 0:
            return False
        layer = self._active_layer()
        if layer is None:
            return False
        if layer.get("locked"):
            editor["status"] = "Reference trace is locked"
            return False
        self._push_undo()
        layer["pixels"] = self._blank_pixels(width, height)
        editor["pixels"] = layer["pixels"]
        self._mark_dirty()
        editor["status"] = f"Cleared {layer.get('name', 'layer')}"
        return True

    def set_slider_from_mouse(self, slider_info, mouse_x):
        rect = slider_info.get("rect") if isinstance(slider_info, dict) else None
        if rect is None or rect.width <= 0:
            return False
        value = (mouse_x - rect.x) / max(1, rect.width)
        return self.set_color_from_hsv(slider_info.get("channel"), value)

    @staticmethod
    def surface_from_image_bytes(data):
        if not data:
            return None
        if isinstance(data, str):
            data = data.encode("utf-8", errors="ignore")
        try:
            return pygame.image.load(io.BytesIO(data)).convert_alpha()
        except (pygame.error, OSError, ValueError):
            pass

        try:
            header_size = int.from_bytes(data[:4], "little")
            bit_count = int.from_bytes(data[14:16], "little") if len(data) >= 16 else 32
            colors_used = int.from_bytes(data[32:36], "little") if len(data) >= 36 else 0
            palette_size = (colors_used or (1 << bit_count if bit_count <= 8 else 0)) * 4
            pixel_offset = 14 + header_size + palette_size
            file_size = 14 + len(data)
            bmp_header = (
                b"BM"
                + file_size.to_bytes(4, "little")
                + (0).to_bytes(4, "little")
                + pixel_offset.to_bytes(4, "little")
            )
            return pygame.image.load(io.BytesIO(bmp_header + data)).convert_alpha()
        except (pygame.error, OSError, ValueError, OverflowError):
            return None

    def load_reference_from_clipboard(self):
        editor = self.state
        if not isinstance(editor, dict):
            return False
        try:
            if not pygame.scrap.get_init():
                pygame.scrap.init()
        except pygame.error:
            editor["status"] = "Clipboard image support is unavailable"
            return True

        surface = None
        for scrap_type in (getattr(pygame, "SCRAP_BMP", "image/bmp"),):
            try:
                data = pygame.scrap.get(scrap_type)
            except pygame.error:
                data = None
            surface = self.surface_from_image_bytes(data)
            if surface is not None:
                break

        if surface is None:
            try:
                text_data = pygame.scrap.get(getattr(pygame, "SCRAP_TEXT", "text/plain"))
            except pygame.error:
                text_data = None
            if text_data:
                try:
                    text = text_data.decode("utf-8", errors="ignore").strip().strip("\x00").strip('"')
                except AttributeError:
                    text = str(text_data).strip().strip('"')
                if text and os.path.exists(text):
                    try:
                        surface = pygame.image.load(text).convert_alpha()
                    except (pygame.error, OSError):
                        surface = None

        if surface is None:
            editor["status"] = "Ctrl+V found no image or image path"
            return True
        editor["reference_surface"] = surface
        editor["status"] = f"Reference loaded: {surface.get_width()} x {surface.get_height()} px"
        return True

    def sample_reference_at(self, mouse_pos):
        editor = self.state
        if not isinstance(editor, dict):
            return False
        surface = editor.get("reference_surface")
        rect = editor.get("reference_rect")
        if surface is None or rect is None or not rect.collidepoint(mouse_pos):
            return False
        ref_x = int((mouse_pos[0] - rect.x) * surface.get_width() / max(1, rect.width))
        ref_y = int((mouse_pos[1] - rect.y) * surface.get_height() / max(1, rect.height))
        ref_x = max(0, min(surface.get_width() - 1, ref_x))
        ref_y = max(0, min(surface.get_height() - 1, ref_y))
        color = surface.get_at((ref_x, ref_y))
        self.set_color_rgb(color)
        editor["status"] = f"Picked #{color.r:02x}{color.g:02x}{color.b:02x} from reference"
        return True

    def paste_reference_as_trace_layer(self):
        editor = self.state
        reference = editor.get("reference_surface") if isinstance(editor, dict) else None
        if not isinstance(editor, dict) or reference is None or editor.get("stage") != "canvas":
            if isinstance(editor, dict):
                editor["status"] = "Paste a reference image first"
            return False
        width = int(editor.get("canvas_width") or 0)
        height = int(editor.get("canvas_height") or 0)
        if width <= 0 or height <= 0:
            return False

        self._push_undo()
        layers = self._layers()
        active_layer = self._active_layer()
        layers[:] = [layer for layer in layers if not layer.get("reference_only")]
        source_w, source_h = max(1, reference.get_width()), max(1, reference.get_height())
        destination_x = max(0, (width - source_w) // 2)
        destination_y = max(0, (height - source_h) // 2)
        source_x = max(0, (source_w - width) // 2)
        source_y = max(0, (source_h - height) // 2)
        copy_width = min(width, source_w)
        copy_height = min(height, source_h)
        pixels = self._blank_pixels(width, height)
        for y in range(copy_height):
            for x in range(copy_width):
                color = reference.get_at((source_x + x, source_y + y))
                if color.a:
                    pixels[destination_y + y][destination_x + x] = (color.r, color.g, color.b)
        trace_layer = {
            "name": "Reference trace",
            "visible": True,
            "opacity": 0.35,
            "reference_only": True,
            "locked": True,
            "pixels": pixels,
        }
        layers.insert(0, trace_layer)
        if active_layer in layers:
            editor["active_layer"] = layers.index(active_layer)
        else:
            editor["active_layer"] = min(1, len(layers) - 1)
        self._active_layer()
        self._mark_dirty()
        placement = "center-cropped" if source_w > width or source_h > height else "centered at 1:1 resolution"
        editor["status"] = f"Reference {placement} as a 35% trace layer (excluded from export)"
        return True

    @staticmethod
    def _shape_tool_names():
        return {"rectangle", "triangle", "trapezoid", "line", "circle"}

    def _canvas_pixel_at(self, mouse_pos):
        editor = self.state
        canvas_rect = editor.get("canvas_rect") if isinstance(editor, dict) else None
        if canvas_rect is None or not canvas_rect.collidepoint(mouse_pos):
            return None
        width = int(editor.get("canvas_width") or 0)
        height = int(editor.get("canvas_height") or 0)
        if width <= 0 or height <= 0:
            return None
        pixel_x = max(0, min(width - 1, int((mouse_pos[0] - canvas_rect.x) * width / max(1, canvas_rect.width))))
        pixel_y = max(0, min(height - 1, int((mouse_pos[1] - canvas_rect.y) * height / max(1, canvas_rect.height))))
        return pixel_x, pixel_y

    def set_anchor_mode(self, mode):
        editor = self.state
        if not isinstance(editor, dict) or mode not in {None, "attachment", "axis"}:
            return False
        editor["anchor_mode"] = mode
        labels = {None: "Drawing mode", "attachment": "Attachment point: click where this module joins the plant", "axis": "Growth vector: click toward the module tip"}
        editor["status"] = labels[mode]
        return True

    def cycle_anchor_mode(self):
        editor = self.state
        if not isinstance(editor, dict):
            return False
        next_mode = {None: "attachment", "attachment": "axis", "axis": None}[editor.get("anchor_mode")]
        return self.set_anchor_mode(next_mode)

    def set_attachment_point(self, mouse_pos):
        editor = self.state
        pixel = self._canvas_pixel_at(mouse_pos)
        if not isinstance(editor, dict) or pixel is None:
            return False
        editor["attachment_point_px"] = pixel
        editor["anchor_mode"] = None
        editor["status"] = f"Attachment point set at {pixel[0]}, {pixel[1]} px"
        self._mark_dirty()
        return True

    def set_growth_axis(self, mouse_pos):
        editor = self.state
        pixel = self._canvas_pixel_at(mouse_pos)
        anchor = editor.get("attachment_point_px") if isinstance(editor, dict) else None
        if not isinstance(editor, dict) or pixel is None or not anchor:
            return False
        dx, dy = pixel[0] - anchor[0], pixel[1] - anchor[1]
        length = max(1.0, (dx * dx + dy * dy) ** 0.5)
        editor["growth_axis_px"] = (dx / length, dy / length)
        editor["anchor_mode"] = None
        editor["status"] = "Growth axis set"
        self._mark_dirty()
        return True

    def _module_anchor_payload(self):
        editor = self.state if isinstance(self.state, dict) else {}
        width = max(1, int(editor.get("canvas_width") or 1))
        height = max(1, int(editor.get("canvas_height") or 1))
        point = editor.get("attachment_point_px") or (width // 2, max(0, height - 1))
        axis = editor.get("growth_axis_px") or (0.0, -1.0)
        return {
            "attachment_point": [round(max(0.0, min(1.0, float(point[0]) / max(1, width - 1))), 4), round(max(0.0, min(1.0, float(point[1]) / max(1, height - 1))), 4)],
            "growth_vector": [round(float(axis[0]), 4), round(float(axis[1]), 4)],
            "growth_axis": [round(float(axis[0]), 4), round(float(axis[1]), 4)],
        }

    @staticmethod
    def _line_cells(start, end):
        x0, y0 = start
        x1, y1 = end
        cells = set()
        dx, dy = abs(x1 - x0), -abs(y1 - y0)
        step_x, step_y = (1 if x0 < x1 else -1), (1 if y0 < y1 else -1)
        error = dx + dy
        while True:
            cells.add((x0, y0))
            if (x0, y0) == (x1, y1):
                return cells
            twice_error = 2 * error
            if twice_error >= dy:
                error += dy
                x0 += step_x
            if twice_error <= dx:
                error += dx
                y0 += step_y

    @staticmethod
    def _polygon_contains(point, vertices):
        x, y = point[0] + 0.5, point[1] + 0.5
        inside = False
        previous_x, previous_y = vertices[-1]
        for current_x, current_y in vertices:
            if (current_y > y) != (previous_y > y):
                crossing_x = (previous_x - current_x) * (y - current_y) / (previous_y - current_y) + current_x
                if x < crossing_x:
                    inside = not inside
            previous_x, previous_y = current_x, current_y
        return inside

    def _shape_cells(self, tool, start, end, filled):
        x1, x2 = sorted((int(start[0]), int(end[0])))
        y1, y2 = sorted((int(start[1]), int(end[1])))
        if tool == "line":
            return self._line_cells(start, end)
        if tool == "rectangle":
            if filled:
                return {(x, y) for y in range(y1, y2 + 1) for x in range(x1, x2 + 1)}
            return (
                {(x, y1) for x in range(x1, x2 + 1)}
                | {(x, y2) for x in range(x1, x2 + 1)}
                | {(x1, y) for y in range(y1, y2 + 1)}
                | {(x2, y) for y in range(y1, y2 + 1)}
            )
        if tool == "circle":
            center_x, center_y = (x1 + x2) / 2.0, (y1 + y2) / 2.0
            radius_x, radius_y = max(0.5, (x2 - x1 + 1) / 2.0), max(0.5, (y2 - y1 + 1) / 2.0)
            inside = set()
            for y in range(y1, y2 + 1):
                for x in range(x1, x2 + 1):
                    if ((x + 0.5 - center_x) / radius_x) ** 2 + ((y + 0.5 - center_y) / radius_y) ** 2 <= 1.0:
                        inside.add((x, y))
            if filled:
                return inside
            return {
                (x, y) for x, y in inside
                if any((x + dx, y + dy) not in inside for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)))
            }

        midpoint = (x1 + x2) / 2.0
        if tool == "triangle":
            vertices = [(midpoint, y1), (x2, y2), (x1, y2)]
        else:  # trapezoid
            inset = (x2 - x1) * 0.25
            vertices = [(x1 + inset, y1), (x2 - inset, y1), (x2, y2), (x1, y2)]
        if not filled:
            cells = set()
            for index, vertex in enumerate(vertices):
                following = vertices[(index + 1) % len(vertices)]
                cells.update(self._line_cells((round(vertex[0]), round(vertex[1])), (round(following[0]), round(following[1]))))
            return cells
        return {
            (x, y) for y in range(y1, y2 + 1) for x in range(x1, x2 + 1)
            if self._polygon_contains((x, y), vertices)
        }

    def _apply_shape(self, start, end):
        editor = self.state
        layer = self._active_layer()
        if not isinstance(editor, dict) or not isinstance(layer, dict) or layer.get("locked"):
            return False
        pixels = layer.get("pixels") or []
        width, height = int(editor.get("canvas_width") or 0), int(editor.get("canvas_height") or 0)
        cells = self._shape_cells(editor.get("tool"), start, end, bool(editor.get("shape_filled")))
        color = tuple(editor.get("color", (236, 240, 246)))
        changed = False
        for x, y in cells:
            if 0 <= x < width and 0 <= y < height and y < len(pixels) and x < len(pixels[y]):
                pixels[y][x] = color
                if editor.get("mirror_x"):
                    pixels[y][width - 1 - x] = color
                changed = True
        if changed:
            self._mark_dirty()
        return changed

    def paint_at(self, mouse_pos):
        editor = self.state
        if not isinstance(editor, dict) or editor.get("stage") != "canvas":
            return False
        pixel = self._canvas_pixel_at(mouse_pos)
        if pixel is None:
            return False
        pixel_x, pixel_y = pixel
        width = int(editor.get("canvas_width") or 0)
        height = int(editor.get("canvas_height") or 0)
        layer = self._active_layer()
        pixels = layer.get("pixels") if isinstance(layer, dict) else None
        if not isinstance(pixels, list) or pixel_y >= len(pixels):
            return False
        if layer.get("locked"):
            editor["status"] = "Reference trace is locked; select a drawing layer"
            return True
        tool = str(editor.get("tool") or "brush")
        if tool == "eyedropper":
            color = self.composite_color_at(pixel_x, pixel_y)
            if color is not None:
                self.set_color_rgb(color)
                editor["status"] = f"Picked #{color[0]:02x}{color[1]:02x}{color[2]:02x}"
            return True
        paint_color = None if tool == "eraser" else tuple(editor.get("color", (236, 240, 246)))
        if tool == "fill":
            target = pixels[pixel_y][pixel_x]
            if target == paint_color:
                return True
            if editor.get("stroke_before") is None:
                editor["stroke_before"] = self._snapshot()
            pending = [(pixel_x, pixel_y)]
            seen = set()
            while pending:
                x, y = pending.pop()
                if (x, y) in seen or not (0 <= x < width and 0 <= y < height) or pixels[y][x] != target:
                    continue
                seen.add((x, y))
                pixels[y][x] = paint_color
                pending.extend(((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)))
            self._mark_dirty()
            editor["stroke_changed"] = True
            return True
        pressure = max(0.05, min(1.0, float(editor.get("pressure", 1.0))))
        requested_size = int(editor.get("brush_size") or 1)
        brush_size = max(1, min(32, round(requested_size * pressure) if editor.get("pressure_size", True) else requested_size))

        def paint_cell(center_x, center_y):
            start_x = center_x - brush_size // 2
            start_y = center_y - brush_size // 2
            for y in range(start_y, start_y + brush_size):
                if y < 0 or y >= height or y >= len(pixels):
                    continue
                row = pixels[y]
                if not isinstance(row, list):
                    continue
                for x in range(start_x, start_x + brush_size):
                    if 0 <= x < width and x < len(row):
                        row[x] = paint_color
                        if editor.get("mirror_x"):
                            mirror_x = width - 1 - x
                            if 0 <= mirror_x < len(row):
                                row[mirror_x] = paint_color

        cells = [(pixel_x, pixel_y)]
        previous = editor.get("last_paint_cell") if self.painting else None
        if isinstance(previous, (tuple, list)) and len(previous) == 2:
            previous_x, previous_y = int(previous[0]), int(previous[1])
            distance = max(abs(pixel_x - previous_x), abs(pixel_y - previous_y))
            if distance > 0:
                cells = [
                    (
                        round(previous_x + (pixel_x - previous_x) * step / distance),
                        round(previous_y + (pixel_y - previous_y) * step / distance),
                    )
                    for step in range(1, distance + 1)
                ]
        for cell_x, cell_y in cells:
            paint_cell(cell_x, cell_y)
        editor["last_paint_cell"] = (pixel_x, pixel_y)
        self._mark_dirty()
        editor["stroke_changed"] = True
        return True

    def composite_color_at(self, x, y, include_reference=True):
        result = None
        for layer in self._layers():
            if not layer.get("visible", True) or (layer.get("reference_only") and not include_reference):
                continue
            pixels = layer.get("pixels") or []
            if not (0 <= y < len(pixels) and 0 <= x < len(pixels[y])):
                continue
            color = pixels[y][x]
            if color is None:
                continue
            opacity = max(0.0, min(1.0, float(layer.get("opacity", 1.0))))
            if result is None or opacity >= 1.0:
                result = tuple(color[:3])
            else:
                result = tuple(round(result[channel] * (1.0 - opacity) + color[channel] * opacity) for channel in range(3))
        return result

    def composite_surface(self, include_reference=True):
        editor = self.state
        if not isinstance(editor, dict):
            return None
        revision = int(editor.get("revision") or 0)
        cached = editor.get("composite_cache")
        cache_key = (revision, bool(include_reference))
        if isinstance(cached, tuple) and len(cached) == 2 and cached[0] == cache_key:
            return cached[1]
        width, height = int(editor.get("canvas_width") or 0), int(editor.get("canvas_height") or 0)
        if width <= 0 or height <= 0:
            return None
        surface = self._render_layers_surface(width, height, self._layers(), include_reference)
        editor["composite_cache"] = (cache_key, surface)
        return surface

    def _render_layers_surface(self, width, height, layers, include_reference=True):
        surface = pygame.Surface((width, height), pygame.SRCALPHA)
        surface.fill((0, 0, 0, 0))
        for layer in layers:
            if not layer.get("visible", True) or (layer.get("reference_only") and not include_reference):
                continue
            layer_surface = pygame.Surface((width, height), pygame.SRCALPHA)
            for y, row in enumerate((layer.get("pixels") or [])[:height]):
                for x, color in enumerate(row[:width]):
                    if color is not None:
                        layer_surface.set_at((x, y), (*tuple(color[:3]), 255))
            layer_surface.set_alpha(round(255 * max(0.0, min(1.0, float(layer.get("opacity", 1.0))))))
            surface.blit(layer_surface, (0, 0))
        return surface

    def finish_stroke(self):
        editor = self.state
        if not isinstance(editor, dict):
            return False
        shape_start, shape_end = editor.get("shape_start"), editor.get("shape_end")
        if shape_start is not None and shape_end is not None:
            editor["stroke_changed"] = self._apply_shape(shape_start, shape_end) or editor.get("stroke_changed", False)
        editor["shape_start"] = None
        editor["shape_end"] = None
        before = editor.get("stroke_before")
        if before is not None and editor.get("stroke_changed"):
            self._push_undo(before)
        editor["stroke_before"] = None
        editor["stroke_changed"] = False
        editor["last_paint_cell"] = None
        editor["active_slider"] = None
        editor["panning"] = False
        editor["pan_anchor"] = None
        previous_tool = editor.pop("stroke_tool_before", None)
        if previous_tool:
            editor["tool"] = previous_tool
        self.painting = False
        return True

    def begin_pan(self, mouse_pos):
        editor = self.state
        if not isinstance(editor, dict):
            return False
        editor["panning"] = True
        editor["pan_anchor"] = (tuple(mouse_pos), tuple(editor.get("pan") or (0.0, 0.0)))
        return True

    def begin_temporary_eraser(self, mouse_pos):
        editor = self.state
        canvas_rect = editor.get("canvas_rect") if isinstance(editor, dict) else None
        if not isinstance(editor, dict) or canvas_rect is None or not canvas_rect.collidepoint(mouse_pos):
            return False
        editor["stroke_tool_before"] = editor.get("tool", "brush")
        editor["tool"] = "eraser"
        return self.handle_click(mouse_pos)

    def asset_path(self, illustration_id, view_id=None):
        safe_id = self.host._sanitize_entity_id(illustration_id) or "illustration"
        suffix = f"_{view_id}" if view_id in {"side", "top"} else ""
        return os.path.join("assets", "illustrations", f"{safe_id}_pixel{suffix}.png").replace("\\", "/")

    def document_path(self, illustration_id):
        safe_id = self.host._sanitize_entity_id(illustration_id) or "illustration"
        return os.path.join("assets", "illustrations", f"{safe_id}_pixel.layers.json.gz").replace("\\", "/")

    def save(self):
        editor = self.state
        if not isinstance(editor, dict) or editor.get("stage") != "canvas":
            if isinstance(editor, dict):
                editor["status"] = "Create the canvas before saving"
            return False
        illustration_id = str(editor.get("illustration_id") or "").strip()
        illustration = self.host.world_model.get_entity(illustration_id) if self.host.world_model is not None else None
        if not isinstance(illustration, dict):
            editor["status"] = "Could not find illustration entry"
            return False
        if editor.get("setup_mode") == "texture":
            self._texture_store_current()
        self._sync_active_view()
        views = editor.get("views") or {}
        mode = editor.get("setup_mode", "single")
        primary_view_id = "front" if mode == "orthographic" else "single"
        primary_view = views.get(primary_view_id)
        if not isinstance(primary_view, dict) or not primary_view.get("layers"):
            editor["status"] = "Pixel canvas is missing"
            return False

        document_rel_path = self.document_path(illustration_id)
        document_abs_path = os.path.normpath(str(self.host.PROJECT_ROOT / document_rel_path))
        view_paths = {}
        try:
            document_views = {}
            for view_id, view in views.items():
                width, height = int(view.get("width") or 0), int(view.get("height") or 0)
                layers = view.get("layers") or []
                if mode == "texture":
                    layers = editor.get("texture_base_layers") or layers
                if width <= 0 or height <= 0 or not layers:
                    raise ValueError(f"{view_id} view is missing")
                rel_path = self.asset_path(illustration_id, view_id)
                abs_path = os.path.normpath(str(self.host.PROJECT_ROOT / rel_path))
                os.makedirs(os.path.dirname(abs_path), exist_ok=True)
                pygame.image.save(self._render_layers_surface(width, height, layers, include_reference=False), abs_path)
                view_paths[view_id] = rel_path
                document_views[view_id] = {
                    "name": str(view.get("name") or view_id.title()),
                    "width": width,
                    "height": height,
                    "active_layer": int(view.get("active_layer") or 0),
                    "layers": self._snapshot_layers(layers),
                    "zoom": float(view.get("zoom", 1.0)),
                    "pan": list(view.get("pan") or [0.0, 0.0]),
                }
            primary_document_view = document_views[primary_view_id]
            document = {
                "version": 2,
                "mode": mode,
                "module_anchor": self._module_anchor_payload(),
                "dimensions_m": {name: self.dimension_value(name) for name in ("length", "width", "height")} if mode == "orthographic" else {"size": self.metric_size()},
                "active_view": editor.get("active_view"),
                "views": document_views,
                "width": primary_document_view["width"],
                "height": primary_document_view["height"],
                "active_layer": primary_document_view["active_layer"],
                "layers": primary_document_view["layers"],
            }
            if mode == "texture":
                texture = self._texture_set()
                document["texture_set"] = texture.to_dict() if texture is not None else None
            temporary_path = document_abs_path + ".tmp"
            with gzip.open(temporary_path, "wt", encoding="utf-8", compresslevel=6) as handle:
                json.dump(document, handle, separators=(",", ":"))
            os.replace(temporary_path, document_abs_path)
        except (pygame.error, OSError, ValueError) as exc:
            editor["status"] = f"Could not save PNG: {exc}"
            return False

        primary_width, primary_height = int(primary_view["width"]), int(primary_view["height"])
        if mode == "orthographic":
            dimensions = {name: self.dimension_value(name) for name in ("length", "width", "height")}
            illustration["depicted_length_m"] = dimensions["length"]
            illustration["depicted_width_m"] = dimensions["width"]
            illustration["depicted_height_m"] = dimensions["height"]
            illustration["depicted_size_m"] = max(dimensions.values())
        else:
            illustration["depicted_size_m"] = self.metric_size()
        illustration["pixel_editor_mode"] = mode
        illustration["pixel_canvas_width"] = primary_width
        illustration["pixel_canvas_height"] = primary_height
        illustration["pixel_art_source"] = "in_engine_pixel_editor"
        primary_layers = (editor.get("texture_base_layers") or primary_view["layers"]) if mode == "texture" else primary_view["layers"]
        illustration["pixel_layer_count"] = sum(1 for layer in primary_layers if not layer.get("reference_only"))
        illustration["pixel_reference_layer_count"] = sum(1 for layer in primary_layers if layer.get("reference_only"))
        illustration["pixel_view_paths"] = view_paths
        illustration["pixel_view_sizes"] = {view_id: [int(view["width"]), int(view["height"])] for view_id, view in views.items()}
        illustration["pixel_document_path"] = document_rel_path
        illustration["pixel_module_anchor"] = self._module_anchor_payload()
        if mode == "texture":
            texture = self._texture_set()
            grid = editor.get("texture_grid") or {"columns": 3, "rows": 3}
            illustration["texture_set_version"] = 1
            illustration["texture_grid_size"] = [int(grid.get("columns") or 3), int(grid.get("rows") or 3)]
            illustration["texture_variant_count"] = len((editor.get("texture_variants") or {}))
            illustration["texture_seed"] = int(editor.get("texture_seed") or 17)
            illustration["texture_runtime_policy"] = "seeded_shuffle_avoid_adjacent_repeat"
        primary_path = view_paths[primary_view_id]
        illustration["media_path"] = primary_path
        if not self.host.assign_illustration_image(illustration_id, primary_path):
            editor["status"] = "PNG saved, but illustration entry was not updated"
            return False
        assign_asset = getattr(self.host, "assign_plant_asset_to_parent", None)
        if callable(assign_asset) and not assign_asset(illustration):
            editor["status"] = "PNG saved, but the plant module link could not be updated"
            return False
        editor["dirty"] = False
        editor["confirm_close"] = False
        editor["status"] = "Saved front, side, and top views" if mode == "orthographic" else f"Saved {primary_path}"
        return True

    def handle_keydown(self, event):
        editor = self.state
        if not isinstance(editor, dict):
            return False
        modifiers = getattr(event, "mod", 0)
        if event.key == pygame.K_ESCAPE:
            return self.request_close()
        if editor.get("stage") == "canvas" and event.key == pygame.K_v and (modifiers & pygame.KMOD_CTRL):
            return self.load_reference_from_clipboard()
        if editor.get("stage") == "canvas":
            if modifiers & pygame.KMOD_CTRL:
                if event.key == pygame.K_z:
                    return self.redo() if modifiers & pygame.KMOD_SHIFT else self.undo()
                if event.key == pygame.K_y:
                    return self.redo()
                if event.key == pygame.K_s:
                    return self.save()
                if event.key == pygame.K_n:
                    return self.add_layer()
            if event.key == pygame.K_b:
                return self.set_tool("brush")
            if event.key == pygame.K_e:
                return self.set_tool("eraser")
            if event.key == pygame.K_i:
                return self.set_tool("eyedropper")
            if event.key == pygame.K_f:
                return self.set_tool("fill")
            if event.key == pygame.K_g:
                editor["show_grid"] = not editor.get("show_grid", True)
                return True
            if event.key == pygame.K_m:
                editor["mirror_x"] = not editor.get("mirror_x", False)
                editor["status"] = "Mirror drawing on" if editor["mirror_x"] else "Mirror drawing off"
                return True
            if editor.get("setup_mode") == "orthographic" and event.key in (pygame.K_1, pygame.K_2, pygame.K_3):
                return self.switch_view({pygame.K_1: "front", pygame.K_2: "side", pygame.K_3: "top"}[event.key])
            if event.key == pygame.K_0:
                editor["zoom"] = 1.0
                editor["pan"] = [0.0, 0.0]
                return True
            if event.key in (pygame.K_LEFTBRACKET, pygame.K_MINUS):
                return self.set_brush_size(int(editor.get("brush_size") or 1) - 1)
            if event.key in (pygame.K_RIGHTBRACKET, pygame.K_EQUALS, getattr(pygame, "K_PLUS", pygame.K_EQUALS)):
                return self.set_brush_size(int(editor.get("brush_size") or 1) + 1)
        if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            return self.begin_canvas() if editor.get("stage") == "size" else self.save()
        if editor.get("stage") != "size":
            return True

        if editor.get("setup_mode") == "orthographic":
            fields = ("length", "width", "height")
            field = editor.get("active_dimension") if editor.get("active_dimension") in fields else "length"
            if event.key == pygame.K_TAB:
                editor["active_dimension"] = fields[(fields.index(field) + (-1 if modifiers & pygame.KMOD_SHIFT else 1)) % len(fields)]
                return True
            buffers = editor.setdefault("dimension_buffers", {})
            cursors = editor.setdefault("dimension_cursors", {})
            buffer_text = str(buffers.get(field) or "")
            cursor = max(0, min(int(cursors.get(field, len(buffer_text)) or 0), len(buffer_text)))
        else:
            field = None
            buffer_text = str(editor.get("metric_size_buffer") or "")
            cursor = max(0, min(int(editor.get("metric_size_cursor", len(buffer_text)) or 0), len(buffer_text)))

        def update_buffer(value, new_cursor):
            if field is None:
                editor["metric_size_buffer"] = value
                editor["metric_size_cursor"] = new_cursor
            else:
                editor["dimension_buffers"][field] = value
                editor["dimension_cursors"][field] = new_cursor

        if event.key == pygame.K_BACKSPACE:
            if cursor > 0:
                update_buffer(buffer_text[:cursor - 1] + buffer_text[cursor:], cursor - 1)
        elif event.key == pygame.K_DELETE:
            if cursor < len(buffer_text):
                update_buffer(buffer_text[:cursor] + buffer_text[cursor + 1:], cursor)
        elif event.key == pygame.K_LEFT:
            update_buffer(buffer_text, max(0, cursor - 1))
        elif event.key == pygame.K_RIGHT:
            update_buffer(buffer_text, min(len(buffer_text), cursor + 1))
        else:
            text = getattr(event, "unicode", "")
            if text and text in "0123456789.,":
                update_buffer(buffer_text[:cursor] + text + buffer_text[cursor:], cursor + len(text))
        return True

    def handle_wheel(self, delta, mouse_pos=None):
        editor = self.state
        if not isinstance(editor, dict) or editor.get("stage") != "canvas":
            return False
        old_zoom = float(editor.get("zoom", 1.0))
        editor["zoom"] = max(0.25, min(16.0, old_zoom * (1.18 ** int(delta))))
        editor["status"] = f"Zoom {editor['zoom'] * 100:.0f}%"
        return True

    def handle_click(self, mouse_pos):
        editor = self.state
        if not isinstance(editor, dict):
            return False
        for key in ("close_rect", "cancel_rect"):
            rect = editor.get(key)
            if rect is not None and rect.collidepoint(mouse_pos):
                return self.request_close()
        primary_rect = editor.get("primary_rect")
        if primary_rect is not None and primary_rect.collidepoint(mouse_pos):
            return self.begin_canvas() if editor.get("stage") == "size" else self.save()
        if editor.get("stage") == "size":
            for mode, rect in (editor.get("setup_mode_hitboxes") or {}).items():
                if rect is not None and rect.collidepoint(mouse_pos):
                    editor["setup_mode"] = mode
                    if mode == "orthographic" and not (editor.get("dimension_buffers") or {}).get("length"):
                        editor.setdefault("dimension_buffers", {})["length"] = str(editor.get("metric_size_buffer") or "")
                    editor["status"] = "Enter one final size" if mode in {"single", "texture"} else "Enter length, width, and height"
                    return True
            for field, rect in (editor.get("dimension_hitboxes") or {}).items():
                if rect is not None and rect.collidepoint(mouse_pos):
                    editor["active_dimension"] = field
                    return True
            return True
        if editor.get("stage") == "canvas":
            if self._texture_mode():
                for key, rect in (editor.get("texture_cell_hitboxes") or {}).items():
                    if rect is not None and rect.collidepoint(mouse_pos):
                        parsed = parse_cell_key(key)
                        if parsed is not None:
                            return self._texture_load_cell(*parsed)
                for action, rect in (editor.get("texture_action_hitboxes") or {}).items():
                    if rect is not None and rect.collidepoint(mouse_pos):
                        if action == "texture_deactivate":
                            return self.deactivate_texture_cell()
                        if action == "texture_shuffle":
                            return self.shuffle_texture_seed()
            for action, rect in (editor.get("action_hitboxes") or {}).items():
                if rect is None or not rect.collidepoint(mouse_pos):
                    continue
                if str(action).startswith("view:"):
                    return self.switch_view(str(action).split(":", 1)[1])
                actions = {
                    "undo": self.undo, "redo": self.redo, "add_layer": self.add_layer,
                    "duplicate_layer": self.duplicate_layer, "delete_layer": self.delete_layer,
                    "layer_up": lambda: self.move_layer(1), "layer_down": lambda: self.move_layer(-1),
                    "reference_to_trace": self.paste_reference_as_trace_layer,
                    "toggle_grid": lambda: editor.__setitem__("show_grid", not editor.get("show_grid", True)) or True,
                    "toggle_mirror": lambda: editor.__setitem__("mirror_x", not editor.get("mirror_x", False)) or True,
                    "toggle_shape_fill": lambda: editor.__setitem__("shape_filled", not editor.get("shape_filled", False)) or True,
                    "anchor_mode": self.cycle_anchor_mode,
                }
                return actions.get(action, lambda: False)()
            for index, rect in (editor.get("layer_hitboxes") or {}).items():
                if rect is not None and rect.collidepoint(mouse_pos):
                    eye_rect = pygame.Rect(rect.x + 6, rect.y + 6, 20, rect.height - 12)
                    return self.toggle_layer_visibility(index) if eye_rect.collidepoint(mouse_pos) else self.select_layer(index)
            for tool, rect in (editor.get("tool_hitboxes") or {}).items():
                if rect is not None and rect.collidepoint(mouse_pos):
                    return self.set_tool(tool)
            for delta, rect in (editor.get("brush_size_hitboxes") or {}).items():
                if rect is not None and rect.collidepoint(mouse_pos):
                    return self.set_brush_size(int(editor.get("brush_size") or 1) + int(delta))
            clear_rect = editor.get("clear_rect")
            if clear_rect is not None and clear_rect.collidepoint(mouse_pos):
                return self.clear_canvas()
            if self.sample_reference_at(mouse_pos):
                return True
            for slider in editor.get("slider_hitboxes", []):
                rect = slider.get("rect")
                if rect is not None and rect.inflate(8, 10).collidepoint(mouse_pos):
                    self.set_slider_from_mouse(slider, mouse_pos[0])
                    editor["active_slider"] = slider
                    return True
            if editor.get("canvas_rect") is not None and editor["canvas_rect"].collidepoint(mouse_pos):
                if editor.get("anchor_mode") == "attachment":
                    return self.set_attachment_point(mouse_pos)
                if editor.get("anchor_mode") == "axis":
                    return self.set_growth_axis(mouse_pos)
                editor["stroke_before"] = self._snapshot()
                editor["stroke_changed"] = False
                if editor.get("tool") in self._shape_tool_names():
                    editor["shape_start"] = self._canvas_pixel_at(mouse_pos)
                    editor["shape_end"] = editor["shape_start"]
                    self.painting = editor["shape_start"] is not None
                    return True
            if self.paint_at(mouse_pos):
                self.painting = True
        return True

    def handle_motion(self, mouse_pos, pressure=None):
        editor = self.state
        if not isinstance(editor, dict):
            return False
        if pressure is not None:
            try:
                editor["pressure"] = max(0.05, min(1.0, float(pressure)))
            except (TypeError, ValueError):
                pass
        if editor.get("panning") and editor.get("pan_anchor"):
            origin, initial = editor["pan_anchor"]
            editor["pan"] = [initial[0] + mouse_pos[0] - origin[0], initial[1] + mouse_pos[1] - origin[1]]
            return True
        active_slider = editor.get("active_slider")
        if active_slider is not None:
            return self.set_slider_from_mouse(active_slider, mouse_pos[0])
        if self.painting:
            if editor.get("shape_start") is not None:
                pixel = self._canvas_pixel_at(mouse_pos)
                if pixel is not None:
                    editor["shape_end"] = pixel
                return True
            return self.paint_at(mouse_pos)
        return True

    def _draw_legacy(self, screen, font):
        editor = self.pixel_art_editor
        if not isinstance(editor, dict) or self.layout is None:
            return

        right_rect = self.layout["right_rect"]
        stage = editor.get("stage")
        modal_w = min(760, max(420, right_rect.width - 72))
        modal_h = 260 if stage == "size" else min(720, max(520, right_rect.height - 72))
        modal_rect = pygame.Rect(
            right_rect.centerx - modal_w // 2,
            right_rect.centery - modal_h // 2,
            modal_w,
            modal_h,
        )
        header_rect = pygame.Rect(modal_rect.x, modal_rect.y, modal_rect.width, 48)
        close_rect = pygame.Rect(modal_rect.right - 38, modal_rect.y + 12, 24, 24)
        cancel_rect = pygame.Rect(modal_rect.right - 210, modal_rect.bottom - 42, 90, 28)
        primary_rect = pygame.Rect(modal_rect.right - 112, modal_rect.bottom - 42, 94, 28)
        editor["rect"] = modal_rect
        editor["close_rect"] = close_rect
        editor["cancel_rect"] = cancel_rect
        editor["primary_rect"] = primary_rect
        editor["slider_hitboxes"] = []
        editor["tool_hitboxes"] = {}
        editor["brush_size_hitboxes"] = {}
        editor["clear_rect"] = None

        overlay = pygame.Surface(screen.get_size(), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 120))
        screen.blit(overlay, (0, 0))
        pygame.draw.rect(screen, (20, 23, 31), modal_rect)
        pygame.draw.rect(screen, (176, 184, 202), modal_rect, 1)
        pygame.draw.rect(screen, (32, 37, 50), header_rect)
        pygame.draw.line(screen, (94, 104, 124), (header_rect.x, header_rect.bottom), (header_rect.right, header_rect.bottom), 1)

        illustration = editor.get("illustration") if isinstance(editor.get("illustration"), dict) else {}
        title = self._ellipsize_text(
            f"Pixel Art: {illustration.get('name') or illustration.get('pretty_name') or editor.get('illustration_id')}",
            font,
            modal_rect.width - 74,
        )
        screen.blit(font.render(title, True, (242, 244, 248)), (modal_rect.x + 14, modal_rect.y + 14))
        pygame.draw.rect(screen, (74, 44, 52), close_rect)
        pygame.draw.rect(screen, (218, 154, 164), close_rect, 1)
        close_surface = font.render("x", True, (255, 232, 236))
        screen.blit(close_surface, close_surface.get_rect(center=close_rect.center))

        if stage == "size":
            input_rect = pygame.Rect(modal_rect.x + 24, modal_rect.y + 94, min(240, modal_rect.width - 48), 32)
            editor["metric_size_rect"] = input_rect
            screen.blit(font.render("depicted size in meters", True, (184, 194, 214)), (input_rect.x, input_rect.y - 20))
            pygame.draw.rect(screen, (35, 40, 54), input_rect)
            pygame.draw.rect(screen, (190, 204, 234), input_rect, 1)
            text = str(editor.get("metric_size_buffer") or "")
            display_text = text or "1.0"
            text_color = (240, 242, 248) if text else (130, 140, 158)
            screen.blit(font.render(display_text, True, text_color), (input_rect.x + 8, input_rect.y + 7))
            cursor = max(0, min(int(editor.get("metric_size_cursor", len(text)) or 0), len(text)))
            cursor_x = input_rect.x + 8 + font.size(text[:cursor])[0]
            pygame.draw.line(screen, (240, 242, 248), (cursor_x, input_rect.y + 7), (cursor_x, input_rect.bottom - 7), 1)

            size_value = self._pixel_editor_metric_size()
            suggested = self._pixel_canvas_size_for_entity(editor.get("parent_entity"), size_value or 1.0)
            y = input_rect.bottom + 18
            for line in (
                f"Suggested canvas: {suggested[0]} x {suggested[1]} px",
                "Canvas size is derived from entry class and depicted metric size.",
                "Enter creates the canvas. Esc cancels.",
            ):
                screen.blit(font.render(line, True, (166, 176, 196)), (modal_rect.x + 24, y))
                y += self.LINE_HEIGHT
            primary_label = "Create"
        else:
            canvas_w = max(1, int(editor.get("canvas_width") or 1))
            canvas_h = max(1, int(editor.get("canvas_height") or 1))
            side_w = min(310, max(240, modal_rect.width // 3))
            canvas_area = pygame.Rect(modal_rect.x + 24, modal_rect.y + 68, modal_rect.width - side_w - 54, modal_rect.height - 128)
            scale = max(1, min(canvas_area.width // canvas_w, canvas_area.height // canvas_h))
            canvas_rect = pygame.Rect(
                canvas_area.x + (canvas_area.width - canvas_w * scale) // 2,
                canvas_area.y + (canvas_area.height - canvas_h * scale) // 2,
                canvas_w * scale,
                canvas_h * scale,
            )
            editor["canvas_rect"] = canvas_rect
            pygame.draw.rect(screen, (14, 16, 22), canvas_area)
            pygame.draw.rect(screen, (84, 94, 116), canvas_area, 1)
            pixels = editor.get("pixels") or []
            checker = [(34, 38, 48), (42, 47, 58)]
            for y in range(canvas_h):
                row = pixels[y] if y < len(pixels) and isinstance(pixels[y], list) else []
                for x in range(canvas_w):
                    cell = pygame.Rect(canvas_rect.x + x * scale, canvas_rect.y + y * scale, scale, scale)
                    pygame.draw.rect(screen, checker[(x + y) % 2], cell)
                    color = row[x] if x < len(row) else None
                    if color is not None:
                        pygame.draw.rect(screen, color, cell)
            if scale >= 6:
                grid_color = (54, 62, 76)
                for x in range(canvas_w + 1):
                    px = canvas_rect.x + x * scale
                    pygame.draw.line(screen, grid_color, (px, canvas_rect.y), (px, canvas_rect.bottom), 1)
                for y in range(canvas_h + 1):
                    py = canvas_rect.y + y * scale
                    pygame.draw.line(screen, grid_color, (canvas_rect.x, py), (canvas_rect.right, py), 1)
            pygame.draw.rect(screen, (186, 198, 224), canvas_rect, 1)

            side_rect = pygame.Rect(modal_rect.right - side_w - 18, modal_rect.y + 68, side_w, modal_rect.height - 128)
            pygame.draw.rect(screen, (27, 31, 42), side_rect)
            pygame.draw.rect(screen, (86, 98, 122), side_rect, 1)
            color = tuple(editor.get("color", (236, 240, 246)))
            preview_rect = pygame.Rect(side_rect.x + 14, side_rect.y + 18, 42, 42)
            pygame.draw.rect(screen, color, preview_rect)
            pygame.draw.rect(screen, (210, 218, 234), preview_rect, 1)
            screen.blit(font.render(f"{canvas_w} x {canvas_h}", True, (226, 232, 242)), (preview_rect.right + 12, preview_rect.y + 3))
            active_tool = str(editor.get("tool") or "brush")
            tool_hint = "pen tip / left click erases" if active_tool == "eraser" else "pen tip / left click paints"
            screen.blit(font.render(tool_hint, True, (156, 166, 186)), (preview_rect.right + 12, preview_rect.y + 24))

            tool_y = preview_rect.bottom + 18
            screen.blit(font.render("Tool", True, (194, 204, 224)), (side_rect.x + 14, tool_y + 4))
            button_x = side_rect.x + 58
            tool_buttons = (
                ("brush", "Brush", pygame.Rect(button_x, tool_y, 68, 24)),
                ("eraser", "Eraser", pygame.Rect(button_x + 74, tool_y, 74, 24)),
            )
            for tool_name, label, button_rect in tool_buttons:
                selected = active_tool == tool_name
                hovered = button_rect.collidepoint(pygame.mouse.get_pos())
                fill = (76, 96, 138) if selected else (42, 48, 62)
                if hovered:
                    fill = (90, 110, 152) if selected else (56, 64, 82)
                pygame.draw.rect(screen, fill, button_rect)
                pygame.draw.rect(screen, (190, 204, 234) if selected else (132, 144, 170), button_rect, 1)
                label_surface = font.render(label, True, (242, 246, 252))
                screen.blit(label_surface, label_surface.get_rect(center=button_rect.center))
                editor["tool_hitboxes"][tool_name] = button_rect

            size_y = tool_y + 34
            brush_size = max(1, min(16, int(editor.get("brush_size") or 1)))
            screen.blit(font.render("Size", True, (194, 204, 224)), (side_rect.x + 14, size_y + 4))
            dec_rect = pygame.Rect(button_x, size_y, 28, 24)
            value_rect = pygame.Rect(dec_rect.right + 6, size_y, 50, 24)
            inc_rect = pygame.Rect(value_rect.right + 6, size_y, 28, 24)
            clear_rect = pygame.Rect(inc_rect.right + 8, size_y, 50, 24)
            for rect_button, label in ((dec_rect, "-"), (inc_rect, "+"), (clear_rect, "Clear")):
                pygame.draw.rect(screen, (42, 48, 62), rect_button)
                pygame.draw.rect(screen, (132, 144, 170), rect_button, 1)
                label_surface = font.render(label, True, (242, 246, 252))
                screen.blit(label_surface, label_surface.get_rect(center=rect_button.center))
            pygame.draw.rect(screen, (26, 30, 40), value_rect)
            pygame.draw.rect(screen, (132, 144, 170), value_rect, 1)
            value_surface = font.render(f"{brush_size}px", True, (230, 236, 248))
            screen.blit(value_surface, value_surface.get_rect(center=value_rect.center))
            editor["brush_size_hitboxes"] = {-1: dec_rect, 1: inc_rect}
            editor["clear_rect"] = clear_rect

            hue, saturation, brightness = editor.get("hsv", (0.0, 0.0, 1.0))
            slider_y = size_y + 42
            for channel, label, value in (("h", "Hue", hue), ("s", "Sat", saturation), ("v", "Val", brightness)):
                screen.blit(font.render(label, True, (194, 204, 224)), (side_rect.x + 14, slider_y - 4))
                slider_rect = pygame.Rect(side_rect.x + 58, slider_y, side_rect.width - 74, 10)
                if channel == "h":
                    for offset in range(slider_rect.width):
                        hue_color = colorsys.hsv_to_rgb(offset / max(1, slider_rect.width - 1), 1.0, 1.0)
                        pygame.draw.line(screen, tuple(int(part * 255) for part in hue_color), (slider_rect.x + offset, slider_rect.y), (slider_rect.x + offset, slider_rect.bottom - 1))
                else:
                    pygame.draw.rect(screen, (82, 96, 126), slider_rect)
                pygame.draw.rect(screen, (184, 196, 222), slider_rect, 1)
                knob_x = slider_rect.x + int(max(0.0, min(1.0, value)) * slider_rect.width)
                pygame.draw.circle(screen, (236, 240, 248), (knob_x, slider_rect.centery), 5)
                editor["slider_hitboxes"].append({"channel": channel, "rect": slider_rect})
                slider_y += 32

            ref_label_y = slider_y + 8
            screen.blit(font.render("Reference", True, (194, 204, 224)), (side_rect.x + 14, ref_label_y))
            ref_area = pygame.Rect(side_rect.x + 14, ref_label_y + 22, side_rect.width - 28, max(80, side_rect.bottom - ref_label_y - 34))
            pygame.draw.rect(screen, (18, 21, 29), ref_area)
            pygame.draw.rect(screen, (82, 94, 118), ref_area, 1)
            reference_surface = editor.get("reference_surface")
            editor["reference_rect"] = None
            if reference_surface is not None:
                src_w = max(1, reference_surface.get_width())
                src_h = max(1, reference_surface.get_height())
                scale_ref = min(ref_area.width / src_w, ref_area.height / src_h)
                target_w = max(1, int(src_w * scale_ref))
                target_h = max(1, int(src_h * scale_ref))
                scaled = pygame.transform.smoothscale(reference_surface, (target_w, target_h))
                ref_rect = scaled.get_rect(center=ref_area.center)
                screen.blit(scaled, ref_rect)
                pygame.draw.rect(screen, (196, 210, 238), ref_rect, 1)
                editor["reference_rect"] = ref_rect
            else:
                for index, line in enumerate(("Ctrl+V reference", "Click image to pick color")):
                    line_surface = font.render(line, True, (140, 150, 170))
                    screen.blit(line_surface, (ref_area.x + 10, ref_area.y + 14 + index * self.LINE_HEIGHT))
            primary_label = "Save PNG"

        mouse_pos = pygame.mouse.get_pos()
        for rect, label, primary in ((cancel_rect, "Cancel", False), (primary_rect, primary_label, True)):
            hovered = rect.collidepoint(mouse_pos)
            fill = (78, 98, 142) if primary else (56, 62, 76)
            if hovered:
                fill = (94, 116, 164) if primary else (70, 78, 96)
            pygame.draw.rect(screen, fill, rect)
            pygame.draw.rect(screen, (192, 208, 240) if primary else (176, 184, 202), rect, 1)
            surface = font.render(label, True, (246, 248, 252))
            screen.blit(surface, surface.get_rect(center=rect.center))
        status = str(editor.get("status") or "").strip()
        if status:
            screen.blit(font.render(status, True, (204, 218, 242)), (modal_rect.x + 24, modal_rect.bottom - 34))

    def _button(self, screen, font, rect, label, *, active=False, enabled=True):
        hovered = enabled and rect.collidepoint(pygame.mouse.get_pos())
        fill = (54, 63, 80)
        border = (91, 104, 128)
        if active:
            fill, border = (54, 105, 139), (108, 190, 225)
        elif hovered:
            fill, border = (68, 79, 100), (133, 150, 180)
        if not enabled:
            fill, border = (32, 37, 48), (55, 63, 78)
        pygame.draw.rect(screen, fill, rect, border_radius=4)
        pygame.draw.rect(screen, border, rect, 1, border_radius=4)
        color = (235, 241, 248) if enabled else (94, 104, 122)
        surface = font.render(label, True, color)
        screen.blit(surface, surface.get_rect(center=rect.center))

    def _draw_editor_canvas(self, screen, canvas_area):
        editor = self.state
        width = max(1, int(editor.get("canvas_width") or 1))
        height = max(1, int(editor.get("canvas_height") or 1))
        fit = min((canvas_area.width - 48) / width, (canvas_area.height - 48) / height)
        scale = max(0.25, fit * float(editor.get("zoom", 1.0)))
        target_w, target_h = max(1, round(width * scale)), max(1, round(height * scale))
        pan = editor.get("pan") or [0.0, 0.0]
        canvas_rect = pygame.Rect(0, 0, target_w, target_h)
        canvas_rect.center = (canvas_area.centerx + int(pan[0]), canvas_area.centery + int(pan[1]))
        editor["canvas_rect"] = canvas_rect

        previous_clip = screen.get_clip()
        screen.set_clip(canvas_area)
        pygame.draw.rect(screen, (11, 14, 20), canvas_area)
        tile = max(4, min(18, round(scale * 4)))
        visible = canvas_rect.clip(canvas_area)
        tile_start_x = ((visible.x - canvas_rect.x) // tile) * tile
        tile_start_y = ((visible.y - canvas_rect.y) // tile) * tile
        for y in range(tile_start_y, visible.bottom - canvas_rect.y, tile):
            for x in range(tile_start_x, visible.right - canvas_rect.x, tile):
                cell = pygame.Rect(canvas_rect.x + x, canvas_rect.y + y, tile, tile).clip(visible)
                pygame.draw.rect(screen, (43, 49, 60) if (x // tile + y // tile) % 2 else (33, 38, 48), cell)
        composite = self.composite_surface()
        if composite is not None:
            if target_w * target_h <= canvas_area.width * canvas_area.height * 3:
                scaled = pygame.transform.scale(composite, (target_w, target_h))
                screen.blit(scaled, canvas_rect)
            else:
                first_x = max(0, int((visible.x - canvas_rect.x) / scale))
                last_x = min(width, int((visible.right - canvas_rect.x) / scale) + 1)
                first_y = max(0, int((visible.y - canvas_rect.y) / scale))
                last_y = min(height, int((visible.bottom - canvas_rect.y) / scale) + 1)
                for y in range(first_y, last_y):
                    for x in range(first_x, last_x):
                        color = composite.get_at((x, y))
                        if color.a:
                            pygame.draw.rect(screen, color, (canvas_rect.x + round(x * scale), canvas_rect.y + round(y * scale), max(1, round(scale)), max(1, round(scale))))
        shape_start, shape_end = editor.get("shape_start"), editor.get("shape_end")
        if shape_start is not None and shape_end is not None:
            preview_color = tuple(editor.get("color", (236, 240, 246)))
            for x, y in self._shape_cells(editor.get("tool"), shape_start, shape_end, bool(editor.get("shape_filled"))):
                if 0 <= x < width and 0 <= y < height:
                    pygame.draw.rect(
                        screen,
                        preview_color,
                        (canvas_rect.x + round(x * scale), canvas_rect.y + round(y * scale), max(1, round(scale)), max(1, round(scale))),
                    )
        if editor.get("show_grid", True) and scale >= 7:
            grid = (53, 63, 77)
            for x in range(width + 1):
                px = canvas_rect.x + round(x * scale)
                pygame.draw.line(screen, grid, (px, canvas_rect.y), (px, canvas_rect.bottom))
            for y in range(height + 1):
                py = canvas_rect.y + round(y * scale)
                pygame.draw.line(screen, grid, (canvas_rect.x, py), (canvas_rect.right, py))
        if editor.get("mirror_x"):
            pygame.draw.line(screen, (97, 184, 218), (canvas_rect.centerx, canvas_rect.y), (canvas_rect.centerx, canvas_rect.bottom), 1)
        anchor = editor.get("attachment_point_px")
        if isinstance(anchor, (list, tuple)) and len(anchor) >= 2:
            anchor_pos = (canvas_rect.x + round(float(anchor[0]) * scale), canvas_rect.y + round(float(anchor[1]) * scale))
            pygame.draw.circle(screen, (255, 214, 92), anchor_pos, max(4, round(4 * min(2.0, scale))), 2)
            pygame.draw.line(screen, (255, 214, 92), (anchor_pos[0] - 7, anchor_pos[1]), (anchor_pos[0] + 7, anchor_pos[1]), 1)
            pygame.draw.line(screen, (255, 214, 92), (anchor_pos[0], anchor_pos[1] - 7), (anchor_pos[0], anchor_pos[1] + 7), 1)
        pygame.draw.rect(screen, (129, 151, 178), canvas_rect, 1)
        screen.set_clip(previous_clip)

    def _draw_texture_overlay(self, screen, font, canvas_area):
        """Show the repeat neighborhood and the deterministic runtime shuffle."""
        editor = self.state
        grid = editor.get("texture_grid") or {"columns": 3, "rows": 3}
        columns, rows = max(1, int(grid.get("columns") or 3)), max(1, int(grid.get("rows") or 3))
        cell_size, gap = 48, 3
        panel_w = max(250, columns * cell_size + (columns - 1) * gap + 24)
        panel_h = rows * cell_size + (rows - 1) * gap + 140
        panel = pygame.Rect(canvas_area.x + 12, canvas_area.y + 12, min(panel_w, canvas_area.width - 24), min(panel_h, canvas_area.height - 24))
        if panel.width < 150 or panel.height < 150:
            return
        panel_surface = pygame.Surface(panel.size, pygame.SRCALPHA)
        panel_surface.fill((18, 24, 34, 238))
        screen.blit(panel_surface, panel)
        pygame.draw.rect(screen, (107, 143, 174), panel, 1, border_radius=6)
        screen.blit(font.render("TEXTURE NEIGHBORHOOD", True, (213, 231, 243)), (panel.x + 10, panel.y + 8))
        small_font = pygame.font.Font(None, 16)
        screen.blit(small_font.render("center = base • click neighbor to activate", True, (142, 169, 188)), (panel.x + 10, panel.y + 29))

        grid_x, grid_y = panel.x + 12, panel.y + 50
        editor["texture_cell_hitboxes"] = {}
        active = parse_cell_key(editor.get("texture_active_cell"))
        center = self._texture_center()
        for y in range(rows):
            for x in range(columns):
                cell_rect = pygame.Rect(grid_x + x * (cell_size + gap), grid_y + y * (cell_size + gap), cell_size, cell_size)
                if cell_rect.right > panel.right - 8 or cell_rect.bottom > panel.bottom - 70:
                    continue
                layers = self._texture_layers_for_cell(x, y)
                pygame.draw.rect(screen, (31, 38, 49), cell_rect)
                if layers:
                    surface = self._render_layers_surface(int(editor.get("canvas_width") or 1), int(editor.get("canvas_height") or 1), layers, include_reference=False)
                    scaled = pygame.transform.scale(surface, (cell_size - 4, cell_size - 4))
                    screen.blit(scaled, (cell_rect.x + 2, cell_rect.y + 2))
                key = cell_key(x, y)
                is_variant = key in (editor.get("texture_variants") or {}) and (x, y) != center
                border = (100, 218, 244) if active == (x, y) else ((235, 191, 92) if is_variant else (80, 96, 116))
                pygame.draw.rect(screen, border, cell_rect, 2 if active == (x, y) else 1)
                editor["texture_cell_hitboxes"][key] = cell_rect

        variant_count = len(editor.get("texture_variants") or {})
        selected = "base" if active is None else f"tile {active[0] + 1},{active[1] + 1}"
        status_y = grid_y + rows * (cell_size + gap) + 3
        screen.blit(small_font.render(f"{variant_count} active exception(s) • editing {selected}", True, (202, 215, 227)), (panel.x + 10, status_y))
        sample = []
        texture = self._texture_set()
        if texture is not None:
            sample = texture.shuffled_variant_keys(5, int(editor.get("texture_seed") or 17))
        sample_text = "shuffle: " + ("  ".join(sample[:3]) if sample else "base only")
        screen.blit(small_font.render(sample_text, True, (139, 170, 187)), (panel.x + 10, status_y + 20))
        action_y = panel.bottom - 32
        deactivate = pygame.Rect(panel.x + 10, action_y, 94, 24)
        shuffle = pygame.Rect(panel.right - 96, action_y, 86, 24)
        self._button(screen, font, deactivate, "Deactivate", enabled=active is not None)
        self._button(screen, font, shuffle, "Shuffle", active=True)
        editor["texture_action_hitboxes"] = {"texture_deactivate": deactivate, "texture_shuffle": shuffle}

    def draw(self, screen, font):
        editor = self.state
        if not isinstance(editor, dict):
            return
        screen_rect = screen.get_rect()
        screen.fill((14, 17, 23))
        editor["rect"] = screen_rect
        editor["slider_hitboxes"] = []
        editor["tool_hitboxes"] = {}
        editor["brush_size_hitboxes"] = {}
        editor["action_hitboxes"] = {}
        editor["layer_hitboxes"] = {}
        editor["texture_cell_hitboxes"] = {}
        editor["texture_action_hitboxes"] = {}

        if editor.get("stage") == "size":
            self._draw_size_workspace(screen, font)
            return

        top_h, bottom_h, tools_w = 54, 30, 72
        properties_w = min(320, max(260, screen_rect.width // 4))
        top = pygame.Rect(0, 0, screen_rect.width, top_h)
        tools = pygame.Rect(0, top_h, tools_w, screen_rect.height - top_h - bottom_h)
        properties = pygame.Rect(screen_rect.width - properties_w, top_h, properties_w, screen_rect.height - top_h - bottom_h)
        canvas_area = pygame.Rect(tools.right, top.bottom, properties.x - tools.right, properties.height)
        bottom = pygame.Rect(0, screen_rect.height - bottom_h, screen_rect.width, bottom_h)
        for rect, color in ((top, (25, 30, 40)), (tools, (22, 27, 36)), (properties, (22, 27, 36)), (bottom, (25, 30, 40))):
            pygame.draw.rect(screen, color, rect)
        pygame.draw.line(screen, (62, 72, 90), (0, top.bottom), (screen_rect.width, top.bottom))
        pygame.draw.line(screen, (62, 72, 90), (properties.x, properties.y), (properties.x, properties.bottom))

        illustration = editor.get("illustration") or {}
        name = illustration.get("name") or illustration.get("pretty_name") or editor.get("illustration_id")
        title_width = 210 if editor.get("setup_mode") == "orthographic" else max(120, top.width - 620)
        title = self._ellipsize_text(str(name), font, title_width)
        screen.blit(font.render("PIXEL STUDIO", True, (112, 199, 229)), (18, 9))
        screen.blit(font.render(title, True, (231, 237, 245)), (18, 29))

        editor["view_hitboxes"] = {}
        if editor.get("setup_mode") == "orthographic":
            view_x = 250
            for index, (view_id, label) in enumerate((("front", "1  Front"), ("side", "2  Side"), ("top", "3  Top"))):
                view_rect = pygame.Rect(view_x + index * 92, 12, 86, 30)
                self._button(screen, font, view_rect, label, active=editor.get("active_view") == view_id)
                editor["action_hitboxes"][f"view:{view_id}"] = view_rect

        button_y = 12
        x = max(260, top.width - 554)
        for action, label, w, enabled in (
            ("undo", "Undo", 58, bool(editor.get("undo_stack"))),
            ("redo", "Redo", 58, bool(editor.get("redo_stack"))),
            ("toggle_grid", "Grid", 54, True),
            ("toggle_mirror", "Mirror", 64, True),
            ("anchor_mode", {"attachment": "Set base", "axis": "Set vector"}.get(editor.get("anchor_mode"), "Guide"), 70, True),
        ):
            rect = pygame.Rect(x, button_y, w, 30)
            active = (action == "toggle_grid" and editor.get("show_grid")) or (action == "toggle_mirror" and editor.get("mirror_x")) or (action == "anchor_mode" and editor.get("anchor_mode"))
            self._button(screen, font, rect, label, active=active, enabled=enabled)
            if enabled:
                editor["action_hitboxes"][action] = rect
            x += w + 7
        cancel = pygame.Rect(top.right - 166, button_y, 68, 30)
        save = pygame.Rect(top.right - 90, button_y, 72, 30)
        self._button(screen, font, cancel, "Close")
        self._button(screen, font, save, "Save", active=True)
        editor["cancel_rect"] = cancel
        editor["close_rect"] = cancel
        editor["primary_rect"] = save

        tool_items = (
            ("brush", "B", "Brush"), ("eraser", "E", "Erase"), ("eyedropper", "I", "Pick"), ("fill", "F", "Fill"),
            ("rectangle", "R", "Rect"), ("triangle", "T", "Tri"), ("trapezoid", "Z", "Trap"),
            ("line", "L", "Line"), ("circle", "O", "Circle"),
        )
        y = tools.y + 10
        for tool_name, label, hint in tool_items:
            rect = pygame.Rect(tools.x + 10, y, 52, 44)
            self._button(screen, font, rect, label, active=editor.get("tool") == tool_name)
            editor["tool_hitboxes"][tool_name] = rect
            hint_surface = pygame.font.Font(None, 14).render(hint, True, (132, 145, 165))
            screen.blit(hint_surface, hint_surface.get_rect(center=(rect.centerx, rect.bottom + 9)))
            y += 52
        y += 2
        shape_mode = pygame.Rect(tools.x + 8, y, 56, 26)
        self._button(screen, font, shape_mode, "Fill" if editor.get("shape_filled") else "Line", active=editor.get("shape_filled"))
        editor["action_hitboxes"]["toggle_shape_fill"] = shape_mode
        y += 34
        dec = pygame.Rect(10, y, 24, 28)
        inc = pygame.Rect(38, y, 24, 28)
        self._button(screen, font, dec, "-")
        self._button(screen, font, inc, "+")
        editor["brush_size_hitboxes"] = {-1: dec, 1: inc}
        size_text = pygame.font.Font(None, 16).render(f"{editor.get('brush_size', 1)} px", True, (183, 197, 216))
        screen.blit(size_text, size_text.get_rect(center=(tools.centerx, y + 40)))

        self._draw_editor_canvas(screen, canvas_area)
        if self._texture_mode():
            self._draw_texture_overlay(screen, font, canvas_area)
        self._draw_properties_panel(screen, font, properties)

        width, height = int(editor.get("canvas_width") or 0), int(editor.get("canvas_height") or 0)
        status = str(editor.get("status") or "Ready")
        screen.blit(font.render(status, True, (172, 187, 207)), (12, bottom.y + 7))
        view_label = f"{str(editor.get('active_view')).title()}   |   " if editor.get("setup_mode") == "orthographic" else ""
        mode_label = "   |   TEXTURE SET" if self._texture_mode() else ""
        info = f"{view_label}{width} x {height} px{mode_label}   |   {float(editor.get('zoom', 1.0)) * 100:.0f}%   |   [ / ] size   Ctrl+Z undo   Ctrl+S save"
        info_surface = font.render(info, True, (134, 149, 169))
        screen.blit(info_surface, (bottom.right - info_surface.get_width() - 14, bottom.y + 7))

    def _draw_size_workspace(self, screen, font):
        editor = self.state
        screen_rect = screen.get_rect()
        panel = pygame.Rect(0, 0, min(620, screen_rect.width - 48), 450)
        panel.center = screen_rect.center
        pygame.draw.rect(screen, (24, 29, 39), panel, border_radius=10)
        pygame.draw.rect(screen, (82, 101, 128), panel, 1, border_radius=10)
        screen.blit(pygame.font.Font(None, 34).render("Create pixel canvas", True, (235, 241, 249)), (panel.x + 30, panel.y + 28))
        screen.blit(font.render("Choose a drawing method, then enter real-world dimensions in meters.", True, (150, 166, 187)), (panel.x + 30, panel.y + 72))
        editor["setup_mode_hitboxes"] = {}
        editor["dimension_hitboxes"] = {}
        mode_y = panel.y + 104
        mode_options = (("single", "Single image"), ("texture", "Repeating texture"), ("orthographic", "3D views: front / side / top"))
        mode_w = (panel.width - 68 - 10 * (len(mode_options) - 1)) // len(mode_options)
        for index, (mode, label) in enumerate(mode_options):
            x = panel.x + 30 + index * (mode_w + 10)
            rect = pygame.Rect(x, mode_y, mode_w, 38)
            self._button(screen, font, rect, label, active=editor.get("setup_mode") == mode)
            editor["setup_mode_hitboxes"][mode] = rect

        input_y = mode_y + 78
        if editor.get("setup_mode") == "orthographic":
            fields = ("length", "width", "height")
            gap = 10
            input_w = (panel.width - 60 - gap * 2) // 3
            buffers = editor.get("dimension_buffers") or {}
            cursors = editor.get("dimension_cursors") or {}
            for index, field in enumerate(fields):
                input_rect = pygame.Rect(panel.x + 30 + index * (input_w + gap), input_y, input_w, 42)
                active = editor.get("active_dimension") == field
                screen.blit(font.render(field.title(), True, (174, 191, 213)), (input_rect.x, input_rect.y - 21))
                pygame.draw.rect(screen, (14, 18, 25), input_rect, border_radius=4)
                pygame.draw.rect(screen, (109, 183, 220) if active else (82, 101, 128), input_rect, 2 if active else 1, border_radius=4)
                text = str(buffers.get(field) or "")
                screen.blit(font.render(text or "1.0", True, (235, 240, 247) if text else (99, 113, 133)), (input_rect.x + 10, input_rect.y + 12))
                unit = font.render("m", True, (147, 163, 184))
                screen.blit(unit, (input_rect.right - unit.get_width() - 10, input_rect.y + 12))
                if active:
                    cursor = max(0, min(int(cursors.get(field, len(text)) or 0), len(text)))
                    cursor_x = input_rect.x + 10 + font.size(text[:cursor])[0]
                    pygame.draw.line(screen, (231, 239, 248), (cursor_x, input_rect.y + 10), (cursor_x, input_rect.bottom - 10))
                editor["dimension_hitboxes"][field] = input_rect
            values = {field: self.dimension_value(field) or 1.0 for field in fields}
            sizes = self._orthographic_view_sizes(values["length"], values["width"], values["height"])
            summary = f"Front {sizes['front'][0]} x {sizes['front'][1]}   Side {sizes['side'][0]} x {sizes['side'][1]}   Top {sizes['top'][0]} x {sizes['top'][1]} px"
            hint = "All three views use one consistent pixels-per-meter scale. Tab moves between dimensions."
        else:
            input_rect = pygame.Rect(panel.x + 30, input_y, panel.width - 60, 42)
            screen.blit(font.render("Final size", True, (174, 191, 213)), (input_rect.x, input_rect.y - 21))
            pygame.draw.rect(screen, (14, 18, 25), input_rect, border_radius=4)
            pygame.draw.rect(screen, (109, 164, 199), input_rect, 1, border_radius=4)
            text = str(editor.get("metric_size_buffer") or "")
            screen.blit(font.render(text or "1.0", True, (235, 240, 247) if text else (99, 113, 133)), (input_rect.x + 12, input_rect.y + 12))
            unit = font.render("meters", True, (147, 163, 184))
            screen.blit(unit, (input_rect.right - unit.get_width() - 12, input_rect.y + 12))
            editor["metric_size_rect"] = input_rect
            cursor = max(0, min(int(editor.get("metric_size_cursor", len(text)) or 0), len(text)))
            cursor_x = input_rect.x + 12 + font.size(text[:cursor])[0]
            pygame.draw.line(screen, (231, 239, 248), (cursor_x, input_rect.y + 10), (cursor_x, input_rect.bottom - 10))
            suggested = self._pixel_canvas_size_for_entity(editor.get("parent_entity"), self.metric_size() or 1.0)
            summary = f"Suggested canvas  {suggested[0]} x {suggested[1]} px"
            hint = "This is the tile size; activated neighbors are stored as sparse exceptions."
        screen.blit(font.render(summary, True, (183, 200, 221)), (panel.x + 30, input_y + 70))
        screen.blit(font.render(hint, True, (139, 156, 178)), (panel.x + 30, input_y + 96))
        cancel = pygame.Rect(panel.right - 220, panel.bottom - 62, 86, 34)
        create = pygame.Rect(panel.right - 122, panel.bottom - 62, 92, 34)
        self._button(screen, font, cancel, "Cancel")
        self._button(screen, font, create, "Create", active=True)
        editor["cancel_rect"] = cancel
        editor["close_rect"] = cancel
        editor["primary_rect"] = create

    def _draw_properties_panel(self, screen, font, rect):
        editor = self.state
        pad = 14
        color = tuple(editor.get("color", (236, 240, 246)))
        screen.blit(font.render("COLOR", True, (137, 155, 180)), (rect.x + pad, rect.y + 14))
        swatch = pygame.Rect(rect.x + pad, rect.y + 36, 52, 52)
        pygame.draw.rect(screen, color, swatch, border_radius=4)
        pygame.draw.rect(screen, (205, 216, 231), swatch, 1, border_radius=4)
        screen.blit(font.render(f"#{color[0]:02X}{color[1]:02X}{color[2]:02X}", True, (225, 232, 241)), (swatch.right + 12, swatch.y + 8))
        pressure = float(editor.get("pressure", 1.0))
        screen.blit(font.render(f"Pressure {pressure * 100:.0f}%", True, (135, 151, 173)), (swatch.right + 12, swatch.y + 29))
        hue, saturation, value = editor.get("hsv", (0.0, 0.0, 1.0))
        slider_y = swatch.bottom + 20
        for channel, label, amount in (("h", "H", hue), ("s", "S", saturation), ("v", "V", value)):
            screen.blit(font.render(label, True, (167, 183, 205)), (rect.x + pad, slider_y - 3))
            slider = pygame.Rect(rect.x + pad + 24, slider_y, rect.width - pad * 2 - 24, 11)
            for offset in range(slider.width):
                ratio = offset / max(1, slider.width - 1)
                if channel == "h":
                    rgb = colorsys.hsv_to_rgb(ratio, 1, 1)
                elif channel == "s":
                    rgb = colorsys.hsv_to_rgb(hue, ratio, value)
                else:
                    rgb = colorsys.hsv_to_rgb(hue, saturation, ratio)
                pygame.draw.line(screen, tuple(round(v * 255) for v in rgb), (slider.x + offset, slider.y), (slider.x + offset, slider.bottom - 1))
            pygame.draw.circle(screen, (245, 248, 252), (slider.x + round(amount * (slider.width - 1)), slider.centery), 6)
            editor["slider_hitboxes"].append({"channel": channel, "rect": slider})
            slider_y += 28

        anchor_y = slider_y + 8
        screen.blit(font.render("MODULE ANCHOR", True, (137, 155, 180)), (rect.x + pad, anchor_y))
        anchor = editor.get("attachment_point_px")
        anchor_text = "Not set — defaults to bottom center" if not anchor else f"Attachment: {anchor[0]}, {anchor[1]} px"
        screen.blit(font.render(anchor_text, True, (194, 207, 225)), (rect.x + pad, anchor_y + 22))
        hint = "Guide cycles: base point, growth vector, off"
        screen.blit(font.render(hint, True, (126, 145, 168)), (rect.x + pad, anchor_y + 42))

        layers_y = anchor_y + 68
        screen.blit(font.render("LAYERS", True, (137, 155, 180)), (rect.x + pad, layers_y))
        button_y = layers_y - 5
        actions = (("add_layer", "+"), ("duplicate_layer", "Dup"), ("layer_up", "Up"), ("layer_down", "Dn"), ("delete_layer", "Del"))
        active_layer = self._layers()[int(editor.get("active_layer") or 0)] if self._layers() else {}
        drawing_layer_count = sum(1 for layer in self._layers() if not layer.get("reference_only"))
        delete_enabled = len(self._layers()) > 1 and (active_layer.get("reference_only") or drawing_layer_count > 1)
        bx = rect.right - pad
        for action, label in reversed(actions):
            w = 38 if len(label) > 1 else 28
            bx -= w
            button = pygame.Rect(bx, button_y, w, 26)
            enabled = action != "delete_layer" or delete_enabled
            self._button(screen, font, button, label, enabled=enabled)
            if enabled:
                editor["action_hitboxes"][action] = button
            bx -= 5
        row_y = layers_y + 28
        active = int(editor.get("active_layer") or 0)
        reference_panel_height = min(230, max(170, rect.height // 3))
        reference_panel_top = rect.bottom - reference_panel_height - pad
        for index in reversed(range(len(self._layers()))):
            if row_y + 38 > reference_panel_top - 8:
                break
            layer = self._layers()[index]
            row = pygame.Rect(rect.x + pad, row_y, rect.width - pad * 2, 36)
            pygame.draw.rect(screen, (52, 69, 88) if index == active else (31, 37, 48), row, border_radius=4)
            pygame.draw.rect(screen, (100, 151, 186) if index == active else (60, 70, 86), row, 1, border_radius=4)
            eye = "o" if layer.get("visible", True) else "-"
            screen.blit(font.render(eye, True, (188, 204, 223)), (row.x + 11, row.y + 10))
            badge_width = 52 if layer.get("reference_only") else 0
            name = self._ellipsize_text(str(layer.get("name") or f"Layer {index + 1}"), font, row.width - 54 - badge_width)
            screen.blit(font.render(name, True, (226, 233, 242)), (row.x + 38, row.y + 10))
            if layer.get("reference_only"):
                badge = pygame.Rect(row.right - 48, row.y + 8, 40, 20)
                pygame.draw.rect(screen, (63, 76, 94), badge, border_radius=3)
                badge_text = pygame.font.Font(None, 13).render("TRACE", True, (142, 198, 222))
                screen.blit(badge_text, badge_text.get_rect(center=badge.center))
            editor["layer_hitboxes"][index] = row
            row_y += 41

        ref_panel = pygame.Rect(rect.x + pad, reference_panel_top, rect.width - pad * 2, reference_panel_height)
        pygame.draw.rect(screen, (15, 19, 26), ref_panel, border_radius=4)
        pygame.draw.rect(screen, (58, 70, 88), ref_panel, 1, border_radius=4)
        screen.blit(font.render("REFERENCE", True, (137, 155, 180)), (ref_panel.x + 10, ref_panel.y + 10))
        reference = editor.get("reference_surface")
        trace_button = pygame.Rect(ref_panel.right - 92, ref_panel.y + 6, 82, 26)
        self._button(screen, font, trace_button, "<- Trace", enabled=reference is not None)
        if reference is not None:
            editor["action_hitboxes"]["reference_to_trace"] = trace_button
        ref_area = pygame.Rect(ref_panel.x + 8, ref_panel.y + 38, ref_panel.width - 16, ref_panel.height - 46)
        editor["reference_rect"] = None
        if reference is None:
            lines = ("Ctrl+V to paste an image", "The preview appears here.", "Click it to pick a color.")
            for i, line in enumerate(lines):
                screen.blit(font.render(line, True, (126, 142, 164)), (ref_area.x + 8, ref_area.y + 10 + i * 20))
        else:
            ratio = min(ref_area.width / reference.get_width(), ref_area.height / reference.get_height())
            size = (max(1, round(reference.get_width() * ratio)), max(1, round(reference.get_height() * ratio)))
            preview = pygame.transform.smoothscale(reference, size)
            preview_rect = preview.get_rect(center=ref_area.center)
            screen.blit(preview, preview_rect)
            pygame.draw.rect(screen, (89, 109, 132), preview_rect, 1)
            editor["reference_rect"] = preview_rect
