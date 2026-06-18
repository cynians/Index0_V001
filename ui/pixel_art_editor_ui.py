import colorsys
import io
import os

import pygame


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
        self.state = {
            "stage": "size",
            "illustration_id": illustration_id,
            "illustration": illustration,
            "parent_entity": parent,
            "metric_size_buffer": size_text,
            "metric_size_cursor": len(size_text),
            "status": "Enter depicted size in meters",
            "color": (236, 240, 246),
            "hsv": colorsys.rgb_to_hsv(236 / 255.0, 240 / 255.0, 246 / 255.0),
            "pixels": [],
            "canvas_width": 0,
            "canvas_height": 0,
            "tool": "brush",
            "brush_size": 1,
            "active_slider": None,
            "tool_hitboxes": {},
            "brush_size_hitboxes": {},
            "clear_rect": None,
            "reference_surface": None,
            "reference_rect": None,
        }
        self.painting = False
        return True

    def close(self):
        self.state = None
        self.painting = False
        return True

    def metric_size(self):
        editor = self.state if isinstance(self.state, dict) else {}
        try:
            return max(0.0, float(str(editor.get("metric_size_buffer") or "").replace(",", ".")))
        except ValueError:
            return None

    def begin_canvas(self):
        editor = self.state
        if not isinstance(editor, dict):
            return False
        metric_size_m = self.metric_size()
        if metric_size_m is None or metric_size_m <= 0:
            editor["status"] = "Size must be a positive meter value"
            return True

        width, height = self.host._pixel_canvas_size_for_entity(
            editor.get("parent_entity"),
            metric_size_m,
        )
        editor["stage"] = "canvas"
        editor["canvas_width"] = width
        editor["canvas_height"] = height
        editor["pixels"] = [[None for _ in range(width)] for _ in range(height)]
        editor["status"] = f"{width} x {height} px canvas"
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
        if not isinstance(editor, dict) or tool not in {"brush", "eraser"}:
            return False
        editor["tool"] = tool
        editor["status"] = "Brush selected" if tool == "brush" else "Eraser selected"
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
        editor["pixels"] = [[None for _ in range(width)] for _ in range(height)]
        editor["status"] = "Canvas cleared"
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

    def paint_at(self, mouse_pos):
        editor = self.state
        if not isinstance(editor, dict) or editor.get("stage") != "canvas":
            return False
        canvas_rect = editor.get("canvas_rect")
        if canvas_rect is None or not canvas_rect.collidepoint(mouse_pos):
            return False
        width = int(editor.get("canvas_width") or 0)
        height = int(editor.get("canvas_height") or 0)
        if width <= 0 or height <= 0:
            return False
        pixel_x = int((mouse_pos[0] - canvas_rect.x) * width / max(1, canvas_rect.width))
        pixel_y = int((mouse_pos[1] - canvas_rect.y) * height / max(1, canvas_rect.height))
        pixel_x = max(0, min(width - 1, pixel_x))
        pixel_y = max(0, min(height - 1, pixel_y))
        pixels = editor.get("pixels")
        if not isinstance(pixels, list) or pixel_y >= len(pixels):
            return False
        brush_size = max(1, min(16, int(editor.get("brush_size") or 1)))
        start_x = pixel_x - brush_size // 2
        start_y = pixel_y - brush_size // 2
        paint_color = None if editor.get("tool") == "eraser" else tuple(editor.get("color", (236, 240, 246)))
        for y in range(start_y, start_y + brush_size):
            if y < 0 or y >= height or y >= len(pixels):
                continue
            row = pixels[y]
            if not isinstance(row, list):
                continue
            for x in range(start_x, start_x + brush_size):
                if 0 <= x < width and x < len(row):
                    row[x] = paint_color
        return True

    def asset_path(self, illustration_id):
        safe_id = self.host._sanitize_entity_id(illustration_id) or "illustration"
        return os.path.join("assets", "illustrations", f"{safe_id}_pixel.png").replace("\\", "/")

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
        width = int(editor.get("canvas_width") or 0)
        height = int(editor.get("canvas_height") or 0)
        pixels = editor.get("pixels")
        if width <= 0 or height <= 0 or not isinstance(pixels, list):
            editor["status"] = "Pixel canvas is missing"
            return False

        rel_path = self.asset_path(illustration_id)
        abs_path = os.path.normpath(str(self.host.PROJECT_ROOT / rel_path))
        try:
            os.makedirs(os.path.dirname(abs_path), exist_ok=True)
            surface = pygame.Surface((width, height), pygame.SRCALPHA)
            surface.fill((0, 0, 0, 0))
            for y, row in enumerate(pixels[:height]):
                if not isinstance(row, list):
                    continue
                for x, color in enumerate(row[:width]):
                    if color is not None:
                        surface.set_at((x, y), (*tuple(color[:3]), 255))
            pygame.image.save(surface, abs_path)
        except (pygame.error, OSError, ValueError) as exc:
            editor["status"] = f"Could not save PNG: {exc}"
            return False

        illustration["depicted_size_m"] = self.metric_size()
        illustration["pixel_canvas_width"] = width
        illustration["pixel_canvas_height"] = height
        illustration["pixel_art_source"] = "in_engine_pixel_editor"
        illustration["media_path"] = rel_path
        if not self.host.assign_illustration_image(illustration_id, rel_path):
            editor["status"] = "PNG saved, but illustration entry was not updated"
            return False
        self.close()
        return True

    def handle_keydown(self, event):
        editor = self.state
        if not isinstance(editor, dict):
            return False
        if event.key == pygame.K_ESCAPE:
            return self.close()
        if editor.get("stage") == "canvas" and event.key == pygame.K_v and (getattr(event, "mod", 0) & pygame.KMOD_CTRL):
            return self.load_reference_from_clipboard()
        if editor.get("stage") == "canvas":
            if event.key == pygame.K_b:
                return self.set_tool("brush")
            if event.key == pygame.K_e:
                return self.set_tool("eraser")
            if event.key in (pygame.K_LEFTBRACKET, pygame.K_MINUS):
                return self.set_brush_size(int(editor.get("brush_size") or 1) - 1)
            if event.key in (pygame.K_RIGHTBRACKET, pygame.K_EQUALS, getattr(pygame, "K_PLUS", pygame.K_EQUALS)):
                return self.set_brush_size(int(editor.get("brush_size") or 1) + 1)
        if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            return self.begin_canvas() if editor.get("stage") == "size" else self.save()
        if editor.get("stage") != "size":
            return True

        buffer_text = str(editor.get("metric_size_buffer") or "")
        cursor = max(0, min(int(editor.get("metric_size_cursor", len(buffer_text)) or 0), len(buffer_text)))
        if event.key == pygame.K_BACKSPACE:
            if cursor > 0:
                editor["metric_size_buffer"] = buffer_text[:cursor - 1] + buffer_text[cursor:]
                editor["metric_size_cursor"] = cursor - 1
        elif event.key == pygame.K_DELETE:
            if cursor < len(buffer_text):
                editor["metric_size_buffer"] = buffer_text[:cursor] + buffer_text[cursor + 1:]
        elif event.key == pygame.K_LEFT:
            editor["metric_size_cursor"] = max(0, cursor - 1)
        elif event.key == pygame.K_RIGHT:
            editor["metric_size_cursor"] = min(len(buffer_text), cursor + 1)
        else:
            text = getattr(event, "unicode", "")
            if text and text in "0123456789.,":
                editor["metric_size_buffer"] = buffer_text[:cursor] + text + buffer_text[cursor:]
                editor["metric_size_cursor"] = cursor + len(text)
        return True

    def handle_click(self, mouse_pos):
        editor = self.state
        if not isinstance(editor, dict):
            return False
        for key in ("close_rect", "cancel_rect"):
            rect = editor.get(key)
            if rect is not None and rect.collidepoint(mouse_pos):
                return self.close()
        primary_rect = editor.get("primary_rect")
        if primary_rect is not None and primary_rect.collidepoint(mouse_pos):
            return self.begin_canvas() if editor.get("stage") == "size" else self.save()
        if editor.get("stage") == "canvas":
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
            if self.paint_at(mouse_pos):
                self.painting = True
        return True

    def handle_motion(self, mouse_pos):
        editor = self.state
        if not isinstance(editor, dict):
            return False
        active_slider = editor.get("active_slider")
        if active_slider is not None:
            return self.set_slider_from_mouse(active_slider, mouse_pos[0])
        if self.painting:
            return self.paint_at(mouse_pos)
        return True

    def draw(self, screen, font):
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
            tool_hint = "left click erases" if active_tool == "eraser" else "left click paints"
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
