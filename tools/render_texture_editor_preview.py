"""Render a remote-review preview of Pixel Studio's repeating texture mode."""

import os
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

import pygame

from ui.pixel_art_editor_ui import PixelArtEditorUI


OUTPUT = Path(r"C:\Users\logol\.codex\visualizations\2026\09\02\01a06445-0961-7e70-b041-8bd9cc4e1863\texture_editor_preview.png")


def main():
    pygame.init()
    pygame.display.set_mode((1, 1))
    illustration = {
        "id": "silver_birch_bark_texture_demo",
        "name": "Silver birch bark — texture authoring demo",
        "idea_class": "illustration",
        "pixel_editor_mode": "texture",
        "depicted_size_m": 0.6,
        "texture_seed": 17,
    }
    world_model = SimpleNamespace(get_entity=lambda entity_id: illustration if entity_id == illustration["id"] else None)
    host = SimpleNamespace(
        pixel_art_editor=None,
        pixel_art_painting=False,
        world_model=world_model,
        PROJECT_ROOT=Path.cwd(),
        layout={},
        LINE_HEIGHT=18,
        _parent_entity_for_illustration=lambda value: None,
        _pixel_canvas_size_for_entity=lambda entity, size: (24, 48),
        _sanitize_entity_id=lambda value: value,
        _ellipsize_text=lambda text, font, width: text if font.size(text)[0] <= width else text[: max(1, width // 8)] + "…",
        assign_illustration_image=lambda illustration_id, path: True,
    )
    editor = PixelArtEditorUI(host)
    editor.open(illustration["id"])
    host.pixel_art_editor["metric_size_buffer"] = "0.6"
    editor.begin_canvas()
    state = host.pixel_art_editor
    state["canvas_rect"] = pygame.Rect(0, 0, 240, 480)

    # A compact, repeating birch base: pale bark, vertical grain, and restrained
    # lenticels. The surrounding tiles then demonstrate authored exceptions.
    layer = state["layers"][0]["pixels"]
    for y in range(48):
        for x in range(24):
            layer[y][x] = (218, 218, 198) if x % 7 else (194, 196, 176)
    for x, y in ((4, 6), (16, 17), (8, 31), (20, 40)):
        layer[y][x] = (52, 47, 40)
        if x + 1 < 24:
            layer[y][x + 1] = (93, 79, 61)
    state["texture_base_layers"] = editor._snapshot_layers(state["layers"])

    # Activate three neighbors and paint distinct black-bark patches into each.
    for cell, marks in {
        (0, 1): ((5, 12), (6, 12), (5, 13)),
        (2, 1): ((17, 25), (18, 25), (18, 26), (19, 26)),
        (1, 2): ((10, 37), (11, 37), (10, 38), (14, 43)),
    }.items():
        editor._texture_load_cell(*cell)
        current = state["layers"][0]["pixels"]
        for x, y in marks:
            current[y][x] = (42, 38, 34)
        editor._texture_store_current()
    editor._texture_load_cell(2, 1)
    state["status"] = "Demo ready — three unique bark tiles are activated; click any neighbor to edit it"

    screen = pygame.Surface((1200, 800))
    screen.fill((14, 17, 23))
    font = pygame.font.Font(None, 20)
    editor.draw(screen, font)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    pygame.image.save(screen, OUTPUT)
    pygame.quit()
    print(OUTPUT)


if __name__ == "__main__":
    main()
