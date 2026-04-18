import os
import re

import pygame


class CardWikiRenderer:
    PARAGRAPH_GAP = 8
    IMAGE_GAP = 10
    EMPTY_HINT = "No general article yet. Add text and embed images with ![caption](path)"
    LINK_PATTERN = re.compile(r"\[\[([^\]]+)\]\]")

    @staticmethod
    def _load_image_surface(image_path):
        if not image_path:
            return None

        normalized_path = os.path.normpath(image_path)
        candidate_paths = [normalized_path]
        if not os.path.isabs(normalized_path):
            candidate_paths.append(os.path.normpath(os.path.join(os.getcwd(), normalized_path)))

        for candidate in candidate_paths:
            if not os.path.exists(candidate):
                continue
            try:
                return pygame.image.load(candidate).convert_alpha()
            except Exception:
                return None

        return None

    @staticmethod
    def _wrap_text_lines(text, font, max_width):
        if text is None:
            return [""]

        max_width = max(20, int(max_width))
        wrapped_lines = []

        for paragraph in str(text).splitlines() or [""]:
            words = paragraph.split(" ")

            if not words:
                wrapped_lines.append("")
                continue

            current_line = ""
            for word in words:
                candidate = word if not current_line else f"{current_line} {word}"

                if font.size(candidate)[0] <= max_width:
                    current_line = candidate
                    continue

                if current_line:
                    wrapped_lines.append(current_line)
                    current_line = word
                else:
                    split_word = word
                    while split_word:
                        chunk = split_word
                        while chunk and font.size(chunk)[0] > max_width:
                            chunk = chunk[:-1]

                        if not chunk:
                            break

                        wrapped_lines.append(chunk)
                        split_word = split_word[len(chunk):]

                    current_line = ""

            if current_line or paragraph == "":
                wrapped_lines.append(current_line)

        return wrapped_lines or [""]

    @staticmethod
    def wrap_edit_lines(text, font, max_width):
        text = str(text or "")
        max_width = max(20, int(max_width))
        lines = []
        line = ""
        line_start = 0

        for index, char in enumerate(text):
            if char == "\n":
                lines.append({"text": line, "start": line_start, "end": index})
                line = ""
                line_start = index + 1
                continue

            candidate = line + char
            if line and font.size(candidate)[0] > max_width:
                lines.append({"text": line, "start": line_start, "end": index})
                line = char
                line_start = index
            else:
                line = candidate

        lines.append({"text": line, "start": line_start, "end": len(text)})
        return lines

    @classmethod
    def _draw_edit_text(cls, screen, font, inner_rect, text, cursor_index=None, show_cursor=False):
        text = str(text or "")
        cursor_index = max(0, min(len(text), int(cursor_index or 0)))
        color = (240, 240, 240)
        lines = cls.wrap_edit_lines(text, font, inner_rect.width)
        y = inner_rect.y
        cursor_drawn = False

        for line_info in lines:
            line_text = line_info["text"]
            line_start = line_info["start"]
            line_end = line_info["end"]

            line_surface = font.render(line_text, True, color)
            screen.blit(line_surface, (inner_rect.x, y))

            if show_cursor and line_start <= cursor_index <= line_end:
                cursor_text = line_text[:max(0, cursor_index - line_start)]
                cursor_x = inner_rect.x + font.size(cursor_text)[0]
                pygame.draw.line(screen, (245, 248, 255), (cursor_x, y), (cursor_x, y + font.get_linesize() - 2), 1)
                cursor_drawn = True

            y += font.get_linesize()
            if y > inner_rect.bottom:
                break

        if show_cursor and not cursor_drawn:
            cursor_x = inner_rect.x
            cursor_y = min(inner_rect.bottom - font.get_linesize(), y)
            pygame.draw.line(screen, (245, 248, 255), (cursor_x, cursor_y), (cursor_x, cursor_y + font.get_linesize() - 2), 1)

    @classmethod
    def _resolve_link_markup(cls, text, resolve_link_label=None):
        def replace_match(match):
            entity_ref = match.group(1).strip()
            if not entity_ref:
                return ""
            if resolve_link_label is None:
                return entity_ref
            resolved = resolve_link_label(entity_ref)
            return resolved or entity_ref

        return cls.LINK_PATTERN.sub(replace_match, str(text or ""))

    @classmethod
    def _parse_blocks(cls, wiki_text):
        text = str(wiki_text or "").strip()
        if not text:
            return [{"kind": "text", "text": cls.EMPTY_HINT}]

        blocks = []
        paragraph_lines = []

        def flush_paragraph():
            if paragraph_lines:
                blocks.append({"kind": "text", "text": "\n".join(paragraph_lines)})
                paragraph_lines.clear()

        for raw_line in text.splitlines():
            stripped = raw_line.strip()
            if stripped.startswith("![") and "](" in stripped and stripped.endswith(")"):
                flush_paragraph()
                alt_text = stripped[2:stripped.index("]")]
                path = stripped[stripped.index("](") + 2:-1].strip()
                blocks.append({"kind": "image", "alt": alt_text, "path": path})
                continue

            if not stripped:
                flush_paragraph()
                continue

            paragraph_lines.append(raw_line)

        flush_paragraph()
        return blocks

    @classmethod
    def measure_content(cls, wiki_text, font, rect, resolve_link_label=None):
        blocks = cls._parse_blocks(wiki_text)
        inner_width = max(80, rect.width - 20)
        total_height = 0

        for index, block in enumerate(blocks):
            if block["kind"] == "text":
                rendered_text = cls._resolve_link_markup(block["text"], resolve_link_label=resolve_link_label)
                wrapped_lines = cls._wrap_text_lines(rendered_text, font, inner_width)
                total_height += max(1, len(wrapped_lines)) * font.get_linesize()
            else:
                image_surface = cls._load_image_surface(block.get("path"))
                if image_surface is not None:
                    src_w = max(1, image_surface.get_width())
                    src_h = max(1, image_surface.get_height())
                    scale = min(inner_width / src_w, 240 / src_h)
                    total_height += max(60, int(src_h * scale))
                else:
                    total_height += font.get_linesize() * 2

            if index < len(blocks) - 1:
                total_height += cls.PARAGRAPH_GAP

        return total_height + 20

    @classmethod
    def draw_content(cls, screen, font, rect, wiki_text, is_editing=False, resolve_link_label=None, cursor_index=None):
        pygame.draw.rect(screen, (34, 38, 48), rect)
        pygame.draw.rect(screen, (104, 110, 124), rect, 1)

        inner_rect = rect.inflate(-10, -10)
        y = inner_rect.y
        clip_before = screen.get_clip()
        screen.set_clip(inner_rect.clip(clip_before))

        try:
            if is_editing:
                show_cursor = (pygame.time.get_ticks() // 500) % 2 == 0
                cls._draw_edit_text(screen, font, inner_rect, wiki_text, cursor_index=cursor_index, show_cursor=show_cursor)
                return

            blocks = cls._parse_blocks(wiki_text)
            for index, block in enumerate(blocks):
                if block["kind"] == "text":
                    color = (240, 240, 240) if is_editing else (218, 222, 232)
                    rendered_text = cls._resolve_link_markup(block["text"], resolve_link_label=resolve_link_label)
                    wrapped_lines = cls._wrap_text_lines(rendered_text, font, inner_rect.width)
                    for line in wrapped_lines:
                        line_surface = font.render(line, True, color)
                        screen.blit(line_surface, (inner_rect.x, y))
                        y += font.get_linesize()
                else:
                    image_surface = cls._load_image_surface(block.get("path"))
                    if image_surface is not None:
                        src_w = max(1, image_surface.get_width())
                        src_h = max(1, image_surface.get_height())
                        scale = min(inner_rect.width / src_w, 240 / src_h)
                        target_w = max(1, int(src_w * scale))
                        target_h = max(60, int(src_h * scale))
                        scaled = pygame.transform.smoothscale(image_surface, (target_w, target_h))
                        image_rect = scaled.get_rect(topleft=(inner_rect.x, y))
                        pygame.draw.rect(screen, (24, 28, 38), image_rect.inflate(6, 6))
                        pygame.draw.rect(screen, (124, 132, 146), image_rect.inflate(6, 6), 1)
                        screen.blit(scaled, image_rect)
                        y = image_rect.bottom + 4
                        if block.get("alt"):
                            alt_surface = font.render(block["alt"], True, (188, 192, 202))
                            screen.blit(alt_surface, (inner_rect.x, y))
                            y += font.get_linesize()
                    else:
                        missing_text = f"[missing image] {block.get('path', '')}"
                        missing_surface = font.render(missing_text, True, (220, 170, 170))
                        screen.blit(missing_surface, (inner_rect.x, y))
                        y += font.get_linesize() * 2

                if index < len(blocks) - 1:
                    y += cls.PARAGRAPH_GAP
        finally:
            screen.set_clip(clip_before)
