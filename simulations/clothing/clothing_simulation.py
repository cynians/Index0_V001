"""Repository-backed Clothing Editor hosted in the shared Pixel Studio."""

import json
import os
from pathlib import Path

from engine import asset_files
from engine.clock import Clock
from engine.simulation_manager import SimulationManager
from ui.pixel_art_editor_ui import PixelArtEditorUI
from .clothing_design import (
    CANVAS_HEIGHT, CANVAS_WIDTH, DEFAULT_BODY_SHAPE, SIZE_PROFILES,
    default_garment_pixels, human_reference_pixels,
    normalized_body_shape, warp_clothing_pixels,
)


class ClothingSimulation:
    render_mode = "clothing"
    show_time_ui = False
    LINE_HEIGHT = 20

    def __init__(self, world_model=None, clothing_entity_id="item_test_toga"):
        class _DummySystem:
            def update(self, dt):
                return None

        self.world_model = world_model
        self.clothing_entity_id = clothing_entity_id
        self.sim_clock = Clock(base_dt=1.0)
        self.system = _DummySystem()
        self.sim_manager = SimulationManager(self.sim_clock, self.system)
        self.pixel_art_editor = None
        self.pixel_art_painting = False
        self.pixel_art_editor_ui = PixelArtEditorUI(self)
        self.layout = None
        self.preferred_zoom = 1.0
        self._open_editor()

    @staticmethod
    def _ellipsize_text(text, font, max_width):
        text = str(text or "")
        if font.size(text)[0] <= max_width:
            return text
        while text and font.size(text + "…")[0] > max_width:
            text = text[:-1]
        return text + "…"

    def _entity(self):
        return self.world_model.get_entity(self.clothing_entity_id) if self.world_model is not None else None

    def get_clothing_name(self):
        entity = self._entity() or {}
        return entity.get("pretty_name") or entity.get("name") or self.clothing_entity_id

    def _design_path(self):
        entity = self._entity() or {}
        relative = str(entity.get("clothing_design_ref") or "").strip()
        if not relative:
            safe_id = "".join(ch if ch.isalnum() or ch in "_-" else "_" for ch in self.clothing_entity_id)
            relative = f"assets/clothing/designs/{safe_id}.json"
        return relative.replace("\\", "/")

    def _load_source(self):
        entity = self._entity() or {}
        body = normalized_body_shape(entity.get("clothing_reference_body_shape"))
        path = Path(__file__).resolve().parents[2] / self._design_path()
        try:
            document = json.loads(asset_files.read_text(path))
            pixels = document.get("pixels")
            if isinstance(pixels, list) and pixels and isinstance(pixels[0], list):
                body = normalized_body_shape(document.get("reference_body_shape") or body)
                return pixels, body
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            pass
        style = (entity.get("appearance_profile") or {}).get("silhouette", "toga")
        return default_garment_pixels(style), body

    def _views_and_masks(self):
        source, reference_body = self._load_source()
        self.reference_body_shape = reference_body
        views, masks = {}, {}
        profiles = (("reference", "Reference fit", reference_body),
                    ("small", "Small fit", SIZE_PROFILES["small"]),
                    ("large", "Large fit", SIZE_PROFILES["large"]))
        for view_id, label, body in profiles:
            garment = source if view_id == "reference" else warp_clothing_pixels(source, reference_body, body)
            derived = view_id != "reference"
            views[view_id] = {
                "name": label, "width": CANVAS_WIDTH, "height": CANVAS_HEIGHT,
                "active_layer": 0,
                "layers": [
                    {"name": "Garment design" if not derived else "Derived garment", "visible": True,
                     "opacity": 1.0, "reference_only": False, "locked": derived, "pixels": garment},
                    {"name": "Human DNA guide", "visible": True, "opacity": 0.28,
                     "reference_only": True, "locked": True,
                     "pixels": human_reference_pixels(body)},
                ],
            }
        return views, masks

    def _open_editor(self):
        views, masks = self._views_and_masks()
        opened = self.pixel_art_editor_ui.open_embedded(
            title=f"{self.get_clothing_name()} · Clothing Editor",
            views=views, active_view="reference", masks=masks,
            on_save=self._save_views, finish_on_save=False, context_label="clothing",
        )
        if opened:
            self.pixel_art_editor["status"] = "Paint the garment over the locked human guide; Small and Large are derived previews"
            self.pixel_art_editor["embedded_context"] = "clothing"
        return opened

    def _save_views(self, views, masks):
        reference = views.get("reference") or {}
        garment = next((layer for layer in reference.get("layers") or [] if not layer.get("reference_only")), None)
        if not isinstance(garment, dict):
            return False
        entity = self._entity()
        if not isinstance(entity, dict):
            return False
        body = normalized_body_shape(getattr(self, "reference_body_shape", None))
        relative = self._design_path()
        target = Path(__file__).resolve().parents[2] / relative
        temporary = target.with_suffix(target.suffix + ".tmp")
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary.write_text(json.dumps({
                "version": 1, "canvas": [CANVAS_WIDTH, CANVAS_HEIGHT],
                "reference_body_shape": body, "pixels": garment.get("pixels") or [],
                "sizing_axes": list(DEFAULT_BODY_SHAPE),
            }, separators=(",", ":")), encoding="utf-8")
            os.replace(temporary, target)
        except OSError:
            return False
        for view_id in ("small", "large"):
            view = views.get(view_id) or {}
            layers = view.get("layers") or []
            if layers:
                layers[0]["pixels"] = warp_clothing_pixels(
                    garment.get("pixels") or [], body, SIZE_PROFILES[view_id])
        if self.world_model is not None and hasattr(self.world_model, "set_literal"):
            self.world_model.set_literal(self.clothing_entity_id, "clothing_design_ref", relative)
            self.world_model.set_literal(self.clothing_entity_id, "clothing_reference_body_shape", body)
            self.world_model.set_literal(self.clothing_entity_id, "clothing_sizing_axes", list(DEFAULT_BODY_SHAPE))
        return True

    def is_vehicle_pixel_editor_active(self):
        # UIManager's shared Pixel Studio bridge retains its historical name.
        return isinstance(self.pixel_art_editor, dict) and bool(self.pixel_art_editor.get("embedded"))

    def consumes_global_keydown(self):
        return self.is_vehicle_pixel_editor_active()

    def update(self, dt):
        self.sim_manager.update(dt)

    def handle_event(self, event):
        return False
