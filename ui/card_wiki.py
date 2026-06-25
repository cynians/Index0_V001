import os
import re

import pygame


class CardWikiRenderer:
    PARAGRAPH_GAP = 8
    HEADLINE_GAP = 6
    SECTION_GAP = 8
    SECTION_PAD = 8
    LINK_PAD_X = 6
    LINK_PAD_Y = 2
    IMAGE_GAP = 10
    EMPTY_HINT = "No general article yet. Add text and embed images with ![caption](path)"
    LINK_PATTERN = re.compile(r"\[\[([^\]]+)\]\]")
    TASK_PATTERN = re.compile(r"^\s*\(\)\s+(.+?)\s*$")

    @classmethod
    def extract_link_refs(cls, wiki_text):
        refs = []
        seen = set()
        for match in cls.LINK_PATTERN.finditer(str(wiki_text or "")):
            ref = match.group(1).strip()
            if not ref or ref in seen:
                continue
            seen.add(ref)
            refs.append(ref)
        return refs

    @classmethod
    def extract_tasks(cls, wiki_text):
        tasks = []
        task_number = 0
        for raw_line in str(wiki_text or "").splitlines():
            match = cls.TASK_PATTERN.match(raw_line)
            if not match:
                continue
            task_number += 1
            text = match.group(1).strip()
            if text:
                tasks.append({"task_number": task_number, "text": text})
        return tasks

    @staticmethod
    def _scaled_font(font, scale=1.0, bold=False):
        size = max(10, int(round(font.get_linesize() * scale)))
        return pygame.font.SysFont("consolas", size, bold=bold)

    @staticmethod
    def _coerce_color(value, fallback):
        if isinstance(value, (list, tuple)) and len(value) >= 3:
            try:
                return tuple(max(0, min(255, int(part))) for part in value[:3])
            except (TypeError, ValueError):
                return fallback

        text = str(value or "").strip()
        if text.startswith("#") and len(text) == 7:
            try:
                return (
                    int(text[1:3], 16),
                    int(text[3:5], 16),
                    int(text[5:7], 16),
                )
            except ValueError:
                return fallback
        return fallback

    @classmethod
    def _text_chunks(cls, text):
        chunks = re.split(r"(\s+)", str(text or ""))
        return [chunk for chunk in chunks if chunk]

    @classmethod
    def _inline_segments(cls, text, resolve_link_label=None):
        segments = []
        cursor = 0
        for match in cls.LINK_PATTERN.finditer(str(text or "")):
            before = text[cursor:match.start()]
            for chunk in cls._text_chunks(before):
                segments.append({"kind": "text", "text": chunk})

            entity_ref = match.group(1).strip()
            if entity_ref:
                label = entity_ref
                if resolve_link_label is not None:
                    label = resolve_link_label(entity_ref) or entity_ref
                segments.append({"kind": "link", "text": str(label), "ref": entity_ref})
            cursor = match.end()

        for chunk in cls._text_chunks(str(text or "")[cursor:]):
            segments.append({"kind": "text", "text": chunk})
        return segments

    @classmethod
    def _layout_inline_segments(cls, text, font, max_width, resolve_link_label=None):
        max_width = max(20, int(max_width))
        segments = cls._inline_segments(text, resolve_link_label=resolve_link_label)
        if not segments:
            return [[{"kind": "text", "text": "", "width": 0}]]

        lines = []
        current = []
        current_w = 0
        for segment in segments:
            label = segment["text"]
            if segment["kind"] == "link":
                width = font.size(label)[0] + cls.LINK_PAD_X * 2 + 5
            else:
                width = font.size(label)[0]

            if current and current_w + width > max_width:
                lines.append(current)
                current = []
                current_w = 0
                if segment["kind"] == "text" and label.isspace():
                    continue

            if width > max_width and segment["kind"] == "text":
                remaining = label
                while remaining:
                    chunk = remaining
                    while chunk and font.size(chunk)[0] > max_width:
                        chunk = chunk[:-1]
                    if not chunk:
                        break
                    if current:
                        lines.append(current)
                        current = []
                        current_w = 0
                    chunk_w = font.size(chunk)[0]
                    lines.append([{"kind": "text", "text": chunk, "width": chunk_w}])
                    remaining = remaining[len(chunk):]
                continue

            placed = dict(segment)
            placed["width"] = width
            current.append(placed)
            current_w += width

        if current:
            lines.append(current)
        return lines or [[{"kind": "text", "text": "", "width": 0}]]

    @classmethod
    def _measure_inline_text(cls, text, font, max_width, resolve_link_label=None):
        lines = cls._layout_inline_segments(text, font, max_width, resolve_link_label=resolve_link_label)
        return len(lines) * max(font.get_linesize(), font.get_linesize() + cls.LINK_PAD_Y * 2)

    @classmethod
    def _draw_inline_text(
        cls,
        screen,
        font,
        text,
        x,
        y,
        max_width,
        color,
        resolve_link_label=None,
        link_color=None,
        resolve_link_color=None,
        resolve_link_palette=None,
    ):
        lines = cls._layout_inline_segments(text, font, max_width, resolve_link_label=resolve_link_label)
        line_h = max(font.get_linesize(), font.get_linesize() + cls.LINK_PAD_Y * 2)
        text_color = (242, 247, 255)

        for line in lines:
            cursor_x = x
            for segment in line:
                segment_text = segment.get("text", "")
                if segment.get("kind") == "link":
                    palette = None
                    if resolve_link_palette is not None:
                        palette = resolve_link_palette(segment.get("ref", ""))
                    color_value = link_color
                    if palette is None and resolve_link_color is not None:
                        resolved_color = resolve_link_color(segment.get("ref", ""))
                        if resolved_color is not None:
                            color_value = resolved_color
                    fill = cls._coerce_color((palette or {}).get("fill") if isinstance(palette, dict) else color_value, (54, 76, 112))
                    border = cls._coerce_color((palette or {}).get("border") if isinstance(palette, dict) else None, None)
                    if border is None:
                        border = (
                            min(255, fill[0] + 70),
                            min(255, fill[1] + 70),
                            min(255, fill[2] + 70),
                        )
                    band = cls._coerce_color((palette or {}).get("band") if isinstance(palette, dict) else None, None)
                    box_rect = pygame.Rect(
                        cursor_x,
                        y + 1,
                        int(segment.get("width", 0)),
                        max(16, font.get_linesize() + cls.LINK_PAD_Y),
                    )
                    pygame.draw.rect(screen, fill, box_rect)
                    if band is not None:
                        pygame.draw.rect(screen, band, pygame.Rect(box_rect.x, box_rect.y, min(5, box_rect.width), box_rect.height))
                    pygame.draw.rect(screen, border, box_rect, 1)
                    segment_text_color = cls._coerce_color((palette or {}).get("text") if isinstance(palette, dict) else None, text_color)
                    surface = font.render(segment_text, True, segment_text_color)
                    text_x = box_rect.x + cls.LINK_PAD_X + (5 if band is not None else 0)
                    screen.blit(surface, (text_x, box_rect.y + cls.LINK_PAD_Y - 1))
                else:
                    surface = font.render(segment_text, True, color)
                    screen.blit(surface, (cursor_x, y))
                cursor_x += int(segment.get("width", 0))
            y += line_h
        return y

    @classmethod
    def _collect_inline_link_rects(cls, text, font, x, y, max_width, resolve_link_label=None):
        lines = cls._layout_inline_segments(text, font, max_width, resolve_link_label=resolve_link_label)
        line_h = max(font.get_linesize(), font.get_linesize() + cls.LINK_PAD_Y * 2)
        hitboxes = []

        for line in lines:
            cursor_x = x
            for segment in line:
                segment_w = int(segment.get("width", 0))
                if segment.get("kind") == "link":
                    rect = pygame.Rect(
                        cursor_x,
                        y + 1,
                        segment_w,
                        max(16, font.get_linesize() + cls.LINK_PAD_Y),
                    )
                    hitboxes.append(
                        {
                            "ref": segment.get("ref", ""),
                            "label": segment.get("text", ""),
                            "rect": rect,
                        }
                    )
                cursor_x += segment_w
            y += line_h
        return hitboxes, y

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
        list_items = []
        task_items = []

        def flush_paragraph():
            if paragraph_lines:
                blocks.append({"kind": "text", "text": "\n".join(paragraph_lines)})
                paragraph_lines.clear()

        def flush_list():
            if list_items:
                blocks.append({"kind": "list", "items": list(list_items)})
                list_items.clear()

        def flush_tasks():
            if task_items:
                blocks.append({"kind": "tasks", "items": list(task_items)})
                task_items.clear()

        def flush_all():
            flush_paragraph()
            flush_list()
            flush_tasks()

        for raw_line in text.splitlines():
            stripped = raw_line.strip()
            if stripped.startswith("![") and "](" in stripped and stripped.endswith(")"):
                flush_all()
                alt_text = stripped[2:stripped.index("]")]
                path = stripped[stripped.index("](") + 2:-1].strip()
                blocks.append({"kind": "image", "alt": alt_text, "path": path})
                continue

            if stripped.startswith("!!") and stripped[2:].strip():
                flush_all()
                blocks.append({"kind": "headline", "level": 2, "text": stripped[2:].strip()})
                continue

            if stripped.startswith("!") and stripped[1:].strip():
                flush_all()
                blocks.append({"kind": "headline", "level": 1, "text": stripped[1:].strip()})
                continue

            task_match = cls.TASK_PATTERN.match(raw_line)
            if task_match:
                flush_paragraph()
                flush_list()
                task_items.append(task_match.group(1).strip())
                continue

            if stripped.startswith("- ") and stripped[2:].strip():
                flush_paragraph()
                flush_tasks()
                list_items.append(stripped[2:].strip())
                continue

            if not stripped:
                flush_all()
                continue

            flush_list()
            flush_tasks()
            paragraph_lines.append(raw_line)

        flush_all()
        return blocks

    @staticmethod
    def _slug(text):
        slug = re.sub(r"[^a-z0-9]+", "_", str(text or "").strip().lower()).strip("_")
        return slug or "section"

    @classmethod
    def _section_groups(cls, wiki_text):
        blocks = cls._parse_blocks(wiki_text)
        groups = []
        current = {"section_id": "intro", "title": "General", "level": 0, "blocks": []}
        headline_index = 0

        for block in blocks:
            if block.get("kind") == "headline":
                if current["blocks"]:
                    groups.append(current)
                headline_index += 1
                title = str(block.get("text") or f"Section {headline_index}").strip()
                current = {
                    "section_id": f"{headline_index}_{cls._slug(title)}",
                    "title": title,
                    "level": block.get("level", 1),
                    "blocks": [block],
                }
                continue
            current["blocks"].append(block)

        if current["blocks"] or not groups:
            groups.append(current)
        return groups

    @classmethod
    def _block_height(cls, block, font, width, resolve_link_label=None):
        if block["kind"] == "headline":
            headline_font = cls._scaled_font(font, 1.35 if block.get("level") == 1 else 1.12, bold=True)
            return cls._measure_inline_text(
                block["text"],
                headline_font,
                width,
                resolve_link_label=resolve_link_label,
            )
        if block["kind"] == "text":
            return cls._measure_inline_text(
                block["text"],
                font,
                width,
                resolve_link_label=resolve_link_label,
            )
        if block["kind"] in {"list", "tasks"}:
            item_width = max(20, width - 24)
            line_h = max(font.get_linesize(), font.get_linesize() + cls.LINK_PAD_Y * 2)
            total = 0
            for item in block.get("items", []):
                total += max(
                    line_h,
                    cls._measure_inline_text(
                        item,
                        font,
                        item_width,
                        resolve_link_label=resolve_link_label,
                    ),
                ) + 3
            return max(line_h, total)

        image_surface = cls._load_image_surface(block.get("path"))
        if image_surface is not None:
            src_w = max(1, image_surface.get_width())
            src_h = max(1, image_surface.get_height())
            scale = min(width / src_w, 240 / src_h)
            return max(60, int(src_h * scale)) + (font.get_linesize() if block.get("alt") else 0)
        return font.get_linesize() * 2

    @classmethod
    def _section_layout(cls, wiki_text, font, rect, resolve_link_label=None, scroll_y=0):
        inner_rect = rect.inflate(-10, -10)
        y = inner_rect.y - max(0, int(scroll_y or 0))
        layouts = []
        content_width = max(40, inner_rect.width - cls.SECTION_PAD * 2)

        for group in cls._section_groups(wiki_text):
            content_h = 0
            for index, block in enumerate(group["blocks"]):
                content_h += cls._block_height(block, font, content_width, resolve_link_label=resolve_link_label)
                if index < len(group["blocks"]) - 1:
                    content_h += cls.HEADLINE_GAP if block.get("kind") == "headline" else cls.PARAGRAPH_GAP

            min_section_h = max(font.get_linesize() + cls.SECTION_PAD * 2, font.get_linesize() + 18)
            section_h = max(min_section_h, content_h + cls.SECTION_PAD * 2)
            section_rect = pygame.Rect(inner_rect.x, y, inner_rect.width, section_h)
            layouts.append(
                {
                    **group,
                    "section_rect": section_rect,
                    "content_rect": pygame.Rect(
                        section_rect.x + cls.SECTION_PAD,
                        section_rect.y + cls.SECTION_PAD,
                        content_width,
                        max(1, section_h - cls.SECTION_PAD * 2),
                    ),
                }
            )
            y = section_rect.bottom + cls.SECTION_GAP
        return layouts

    @classmethod
    def section_text(cls, section):
        lines = []
        for block in section.get("blocks", []):
            if block.get("kind") == "headline":
                marker = "!!" if block.get("level") == 2 else "!"
                lines.append(f"{marker} {block.get('text', '')}".strip())
            elif block.get("kind") == "image":
                lines.append(f"![{block.get('alt', '')}]({block.get('path', '')})")
            elif block.get("kind") == "list":
                lines.extend(f"- {item}" for item in block.get("items", []))
            elif block.get("kind") == "tasks":
                lines.extend(f"() {item}" for item in block.get("items", []))
            else:
                lines.append(str(block.get("text", "")))
        return "\n\n".join(line for line in lines if line)

    @classmethod
    def measure_content(cls, wiki_text, font, rect, resolve_link_label=None):
        probe_rect = pygame.Rect(0, 0, rect.width, rect.height)
        layouts = cls._section_layout(wiki_text, font, probe_rect, resolve_link_label=resolve_link_label)
        if not layouts:
            return 20
        return layouts[-1]["section_rect"].bottom - probe_rect.y + 5

    @classmethod
    def link_hitboxes(cls, wiki_text, font, rect, resolve_link_label=None, scroll_y=0):
        if font is None or rect is None:
            return []

        hitboxes = []
        inner_rect = rect.inflate(-10, -10)
        for section in cls._section_layout(
            wiki_text,
            font,
            rect,
            resolve_link_label=resolve_link_label,
            scroll_y=scroll_y,
        ):
            y = section["content_rect"].y
            for index, block in enumerate(section["blocks"]):
                if block["kind"] == "headline":
                    block_font = cls._scaled_font(font, 1.35 if block.get("level") == 1 else 1.12, bold=True)
                elif block["kind"] == "text":
                    block_font = font
                elif block["kind"] in {"list", "tasks"}:
                    for item in block.get("items", []):
                        block_hitboxes, y = cls._collect_inline_link_rects(
                            item,
                            font,
                            section["content_rect"].x + 24,
                            y,
                            max(20, section["content_rect"].width - 24),
                            resolve_link_label=resolve_link_label,
                        )
                        for hitbox in block_hitboxes:
                            hitbox["section_id"] = section["section_id"]
                        hitboxes.extend(block_hitboxes)
                        y += 3
                    block_font = None
                else:
                    y += cls._block_height(block, font, section["content_rect"].width, resolve_link_label=resolve_link_label)
                    block_font = None

                if block_font is not None:
                    block_hitboxes, y = cls._collect_inline_link_rects(
                        block["text"],
                        block_font,
                        section["content_rect"].x,
                        y,
                        section["content_rect"].width,
                        resolve_link_label=resolve_link_label,
                    )
                    for hitbox in block_hitboxes:
                        hitbox["section_id"] = section["section_id"]
                    hitboxes.extend(block_hitboxes)

                if index < len(section["blocks"]) - 1:
                    y += cls.HEADLINE_GAP if block.get("kind") == "headline" else cls.PARAGRAPH_GAP

        visible_hitboxes = []
        for hitbox in hitboxes:
            clipped = hitbox["rect"].clip(inner_rect)
            if clipped.width <= 0 or clipped.height <= 0:
                continue
            item = dict(hitbox)
            item["rect"] = clipped
            visible_hitboxes.append(item)
        return visible_hitboxes

    @classmethod
    def section_hitboxes(cls, wiki_text, font, rect, resolve_link_label=None, scroll_y=0):
        if font is None or rect is None:
            return []
        inner_rect = rect.inflate(-10, -10)
        hitboxes = []
        for section in cls._section_layout(
            wiki_text,
            font,
            rect,
            resolve_link_label=resolve_link_label,
            scroll_y=scroll_y,
        ):
            clipped = section["section_rect"].clip(inner_rect)
            if clipped.width <= 0 or clipped.height <= 0:
                continue
            hitboxes.append(
                {
                    "section_id": section["section_id"],
                    "title": section["title"],
                    "text": cls.section_text(section),
                    "rect": clipped,
                }
            )
        return hitboxes

    @classmethod
    def draw_content(
        cls,
        screen,
        font,
        rect,
        wiki_text,
        is_editing=False,
        resolve_link_label=None,
        link_color=None,
        resolve_link_color=None,
        resolve_link_palette=None,
        section_colors=None,
        text_color=None,
        cursor_index=None,
        scroll_y=0,
    ):
        pygame.draw.rect(screen, (34, 38, 48), rect)
        pygame.draw.rect(screen, (104, 110, 124), rect, 1)

        inner_rect = rect.inflate(-10, -10)
        scroll_y = max(0, int(scroll_y or 0))
        y = inner_rect.y - scroll_y
        clip_before = screen.get_clip()
        screen.set_clip(inner_rect.clip(clip_before))

        try:
            if is_editing:
                show_cursor = (pygame.time.get_ticks() // 500) % 2 == 0
                edit_rect = pygame.Rect(
                    inner_rect.x,
                    inner_rect.y - scroll_y,
                    inner_rect.width,
                    inner_rect.height + scroll_y,
                )
                cls._draw_edit_text(screen, font, edit_rect, wiki_text, cursor_index=cursor_index, show_cursor=show_cursor)
                return

            section_colors = section_colors if isinstance(section_colors, dict) else {}
            sections = cls._section_layout(
                wiki_text,
                font,
                rect,
                resolve_link_label=resolve_link_label,
                scroll_y=scroll_y,
            )
            for section_index, section in enumerate(sections):
                section_id = section["section_id"]
                default_color = section_colors.get("default")
                alternate_color = section_colors.get("alternate")
                automatic_color = alternate_color if alternate_color and section_index % 2 else default_color
                fill = cls._coerce_color(section_colors.get(section_id) or automatic_color, (32, 38, 50))
                border = (
                    min(255, fill[0] + 60),
                    min(255, fill[1] + 60),
                    min(255, fill[2] + 60),
                )
                local_text = text_color or ((20, 24, 32) if (0.2126 * fill[0] + 0.7152 * fill[1] + 0.0722 * fill[2]) / 255.0 >= 0.58 else (230, 234, 244))
                headline_color = local_text

                pygame.draw.rect(screen, fill, section["section_rect"])
                pygame.draw.rect(screen, border, section["section_rect"], 1)

                y = section["content_rect"].y
                for index, block in enumerate(section["blocks"]):
                    if block["kind"] == "headline":
                        headline_font = cls._scaled_font(font, 1.35 if block.get("level") == 1 else 1.12, bold=True)
                        y = cls._draw_inline_text(
                            screen,
                            headline_font,
                            block["text"],
                            section["content_rect"].x,
                            y,
                            section["content_rect"].width,
                            headline_color,
                            resolve_link_label=resolve_link_label,
                            link_color=link_color,
                            resolve_link_color=resolve_link_color,
                            resolve_link_palette=resolve_link_palette,
                        )
                    elif block["kind"] == "text":
                        y = cls._draw_inline_text(
                            screen,
                            font,
                            block["text"],
                            section["content_rect"].x,
                            y,
                            section["content_rect"].width,
                            local_text,
                            resolve_link_label=resolve_link_label,
                            link_color=link_color,
                            resolve_link_color=resolve_link_color,
                            resolve_link_palette=resolve_link_palette,
                        )
                    elif block["kind"] == "list":
                        item_x = section["content_rect"].x + 24
                        item_w = max(20, section["content_rect"].width - 24)
                        for item in block.get("items", []):
                            bullet_y = y + max(5, font.get_linesize() // 2)
                            pygame.draw.circle(screen, local_text, (section["content_rect"].x + 8, bullet_y), 3)
                            y = cls._draw_inline_text(
                                screen,
                                font,
                                item,
                                item_x,
                                y,
                                item_w,
                                local_text,
                                resolve_link_label=resolve_link_label,
                                link_color=link_color,
                                resolve_link_color=resolve_link_color,
                                resolve_link_palette=resolve_link_palette,
                            )
                            y += 3
                    elif block["kind"] == "tasks":
                        item_x = section["content_rect"].x + 24
                        item_w = max(20, section["content_rect"].width - 24)
                        for item in block.get("items", []):
                            box_rect = pygame.Rect(section["content_rect"].x + 3, y + 3, 12, 12)
                            pygame.draw.rect(screen, local_text, box_rect, 1)
                            y = cls._draw_inline_text(
                                screen,
                                font,
                                item,
                                item_x,
                                y,
                                item_w,
                                local_text,
                                resolve_link_label=resolve_link_label,
                                link_color=link_color,
                                resolve_link_color=resolve_link_color,
                                resolve_link_palette=resolve_link_palette,
                            )
                            y += 3
                    else:
                        image_surface = cls._load_image_surface(block.get("path"))
                        if image_surface is not None:
                            src_w = max(1, image_surface.get_width())
                            src_h = max(1, image_surface.get_height())
                            scale = min(section["content_rect"].width / src_w, 240 / src_h)
                            target_w = max(1, int(src_w * scale))
                            target_h = max(60, int(src_h * scale))
                            scaled = pygame.transform.smoothscale(image_surface, (target_w, target_h))
                            image_rect = scaled.get_rect(topleft=(section["content_rect"].x, y))
                            pygame.draw.rect(screen, (24, 28, 38), image_rect.inflate(6, 6))
                            pygame.draw.rect(screen, border, image_rect.inflate(6, 6), 1)
                            screen.blit(scaled, image_rect)
                            y = image_rect.bottom + 4
                            if block.get("alt"):
                                alt_surface = font.render(block["alt"], True, local_text)
                                screen.blit(alt_surface, (section["content_rect"].x, y))
                                y += font.get_linesize()
                        else:
                            missing_text = f"[missing image] {block.get('path', '')}"
                            missing_surface = font.render(missing_text, True, (220, 170, 170))
                            screen.blit(missing_surface, (section["content_rect"].x, y))
                            y += font.get_linesize() * 2

                    if index < len(section["blocks"]) - 1:
                        y += cls.HEADLINE_GAP if block.get("kind") == "headline" else cls.PARAGRAPH_GAP
        finally:
            screen.set_clip(clip_before)
