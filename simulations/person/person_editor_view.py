"""Draws the Person Editor (simulations/person/person_editor.py) and records its controls.

The screen is the person so far on the left (figure and summary) and the
current step's controls on the right, with the steps along the top and
Save, Revert, New person, Person Sim, Back and Next along the bottom. Every
control is a hitbox dict; PersonSimulation hands clicks on them to
person_editor.click.
"""

from __future__ import annotations

import pygame

from simulations.person import person_editor as editor
from simulations.person.person_genetics import BODY_TRAITS, SKIN_TONES
from ui.fonts import get_font
from world.personality import AXES, POPULATION_MEAN, POPULATION_SD, WORDS_FIELD, birth_seed
from world.place_tree import place_tree


BACKGROUND = (11, 15, 21)
PANEL = (17, 23, 32)
PANEL_EDGE = (58, 76, 99)
TEXT = (230, 235, 242)
DIM = (151, 170, 194)
FAINT = (98, 112, 132)
GOLD = (231, 199, 105)
GREEN = (126, 196, 142)
AMBER = (226, 160, 92)
BUTTON = (35, 47, 62)
BUTTON_EDGE = (77, 99, 125)
CHOSEN = (52, 64, 82)
AXIS_LABELS = {
    "openness": "Openness", "conscientiousness": "Conscientious.", "extraversion": "Extraversion",
    "agreeableness": "Agreeableness", "neuroticism": "Neuroticism",
}
AXIS_SHORT = {"openness": "O", "conscientiousness": "C", "extraversion": "E", "agreeableness": "A", "neuroticism": "N"}
ROW_H = 26
SIDEBAR_W = 250


def _fonts():
    return {
        "title": get_font(22, bold=True), "head": get_font(15, bold=True),
        "body": get_font(14), "small": get_font(13), "tiny": get_font(11),
    }


def _fit(font, text, width):
    text = str(text)
    if font.size(text)[0] <= width:
        return text
    while text and font.size(text + "…")[0] > width:
        text = text[:-1]
    return text + "…"


def _text(screen, font, text, color, pos, width=None):
    rendered = font.render(_fit(font, text, width) if width else str(text), True, color)
    screen.blit(rendered, pos)
    return rendered.get_height()


def _wrap(font, text, width):
    lines, line = [], ""
    for word in str(text).split():
        candidate = f"{line} {word}".strip()
        if line and font.size(candidate)[0] > width:
            lines.append(line)
            line = word
        else:
            line = candidate
    return lines + ([line] if line else [])


def _button(screen, font, rect, label, hitboxes, hitbox=None, active=False, enabled=True):
    fill = CHOSEN if active else (BUTTON if enabled else (27, 31, 38))
    pygame.draw.rect(screen, fill, rect, border_radius=4)
    pygame.draw.rect(screen, GOLD if active else (BUTTON_EDGE if enabled else (55, 61, 70)), rect, 2 if active else 1, border_radius=4)
    rendered = font.render(_fit(font, label, rect.width - 8), True, TEXT if enabled else FAINT)
    screen.blit(rendered, rendered.get_rect(center=rect.center))
    if enabled and hitbox is not None:
        hitboxes.append({**hitbox, "rect": rect})


def _input(screen, font, rect, state, input_id, placeholder, hitboxes):
    focused = state.get("focus") == input_id
    value = state["inputs"].get(input_id, "")
    pygame.draw.rect(screen, (8, 12, 18), rect, border_radius=4)
    pygame.draw.rect(screen, GOLD if focused else BUTTON_EDGE, rect, 2 if focused else 1, border_radius=4)
    shown = (value + "|") if focused else (value or placeholder)
    color = TEXT if value or focused else FAINT
    rendered = font.render(_fit(font, shown, rect.width - 14), True, color)
    screen.blit(rendered, rendered.get_rect(midleft=(rect.x + 8, rect.centery)))
    hitboxes.append({"kind": "focus", "input": input_id, "rect": rect})


def _age_text(now, born):
    age = int(now) - int(born)
    return f"age {age} in {now}" if age >= 0 else f"born {-age} years after {now}"


def _scrolled(state, key, total, visible):
    offset = max(0, min(int(state["scroll"].get(key, 0)), max(0, total - visible)))
    state["scroll"][key] = offset
    return offset


def draw_person_editor(renderer, screen, sim):
    state = sim._ensure_person_editor()
    world_model = sim.world_model
    fonts = _fonts()
    width, height = screen.get_size()
    right = max(760, width - SIDEBAR_W)
    screen.fill(BACKGROUND)
    hitboxes = []
    draft = state["draft"]

    title = f"Person Editor | {draft.get('pretty_name') or 'Unnamed person'}"
    note = "new, not saved" if state["is_new"] else ("unsaved changes" if state["dirty"] else "saved")
    _text(screen, fonts["title"], title, TEXT, (22, 14), right - 200)
    _text(screen, fonts["small"], note, AMBER if state["dirty"] else GREEN, (right - 170, 22), 170)

    tab_w = (right - 20) // len(editor.STEPS)
    for index, step in enumerate(editor.STEPS):
        rect = pygame.Rect(20 + index * tab_w, 50, tab_w - 6, 32)
        _button(screen, fonts["body"], rect, f"{index + 1}  {step['label']}", hitboxes,
                {"kind": "step", "step": step["id"]}, active=state["step"] == step["id"])
        if editor.step_done(state, step["id"], world_model):
            pygame.draw.circle(screen, GREEN, (rect.right - 12, rect.centery), 4)

    workspace = pygame.Rect(20, 92, right - 20, max(420, height - 92 - 96))
    preview = pygame.Rect(workspace.x, workspace.y, 230, workspace.height)
    panel = pygame.Rect(preview.right + 12, workspace.y, workspace.right - preview.right - 12, workspace.height)
    for rect in (preview, panel):
        pygame.draw.rect(screen, PANEL, rect, border_radius=8)
        pygame.draw.rect(screen, PANEL_EDGE, rect, 1, border_radius=8)
    _draw_preview(renderer, screen, fonts, sim, state, preview)
    inner = panel.inflate(-36, -32)
    {
        "person": _draw_person_step,
        "birth": _draw_birth_step,
        "parents": _draw_parents_step,
        "genetics": _draw_genetics_step,
        "personality": _draw_personality_step,
        "life": _draw_life_step,
        "review": _draw_review_step,
    }[state["step"]](screen, fonts, sim, state, inner, hitboxes)

    _text(screen, fonts["small"], state.get("status") or "", (191, 204, 220), (22, workspace.bottom + 10), right - 40)
    footer_y = height - 50
    can_save = state["dirty"] and (bool(draft.get("pretty_name")) or not state["is_new"])
    x = 20
    for label, kind, enabled, width_px in (
        ("Save", "save", can_save, 100), ("Revert", "revert", state["dirty"], 100),
        ("New person", "new", True, 120), ("Person Sim", "simulation", not state["is_new"], 120),
    ):
        _button(screen, fonts["body"], pygame.Rect(x, footer_y, width_px, 34), label, hitboxes, {"kind": kind}, enabled=enabled)
        x += width_px + 10
    index = editor.STEP_IDS.index(state["step"])
    _button(screen, fonts["body"], pygame.Rect(right - 230, footer_y, 110, 34), "< Back", hitboxes,
            {"kind": "back"}, enabled=index > 0)
    _button(screen, fonts["body"], pygame.Rect(right - 110, footer_y, 110, 34), "Next >", hitboxes,
            {"kind": "next"}, enabled=index < len(editor.STEPS) - 1)
    sim.set_person_editor_hitboxes(hitboxes)


def _draw_preview(renderer, screen, fonts, sim, state, rect):
    world_model = sim.world_model
    draft = state["draft"]
    decoded = editor.editor_appearance(state)
    ground = (rect.centerx, rect.y + 286)
    renderer._draw_spindly_figure(
        screen, ground, 250, tuple(decoded["skin_tone"]["color"]),
        body_shape=decoded["body_shape"], clothing=sim.get_person_editor_clothing(), face=True,
    )
    y = ground[1] + 14
    width = rect.width - 24
    year = draft.get("start_year")
    tree = place_tree(world_model)
    place = draft.get("birth_location")
    lines = [
        (fonts["head"], draft.get("pretty_name") or "Unnamed person", TEXT),
        (fonts["small"], str(draft.get("sex") or "sex not set").capitalize(), DIM),
        (fonts["small"], (f"Born {year}, age {sim.year - int(year)}" if sim.year >= int(year) else f"Born {year}, after {sim.year}")
         if year is not None else "Birth year not set", DIM),
        (fonts["small"], f"in {tree.label(place)}" if place else "Birthplace not set", DIM),
    ]
    parents = editor.parent_ids(state, world_model)
    if parents:
        lines.append((fonts["tiny"], "Child of " + " and ".join(editor.entity_label(world_model, item) for item in parents), DIM))
    words = [str(word) for word in draft.get(WORDS_FIELD) or []]
    lines += [(fonts["tiny"], line, GOLD) for line in _wrap(fonts["tiny"], ", ".join(words), width)[:3]] if words else []
    for field, label in (("residence", "Home"), ("is_employed_as", "Job")):
        if draft.get(field):
            lines.append((fonts["tiny"], f"{label}: {editor.entity_label(world_model, draft.get(field))}", DIM))
    readiness = editor.readiness(state, world_model)
    lines.append((fonts["tiny"], f"Readiness: {readiness['tier']}", GREEN if readiness["tier"] == "authored" else AMBER))
    for font, text, color in lines:
        if y > rect.bottom - 16:
            break
        y += _text(screen, font, text, color, (rect.x + 12, y), width) + 3


def _draw_person_step(screen, fonts, sim, state, rect, hitboxes):
    draft = state["draft"]
    _text(screen, fonts["head"], "WHO THEY ARE", TEXT, rect.topleft)
    y = rect.y + 34
    _text(screen, fonts["small"], "Name", DIM, (rect.x, y))
    _input(screen, fonts["body"], pygame.Rect(rect.x, y + 20, min(440, rect.width), 34), state, "name", "Click and type a name", hitboxes)
    y += 64
    id_note = "made from the name; fixed once saved" if state["is_new"] else "stored id"
    _text(screen, fonts["tiny"], f"Id: {draft.get('id')}  ({id_note})", FAINT, (rect.x, y), rect.width)
    y += 34
    _text(screen, fonts["small"], "Sex", DIM, (rect.x, y))
    for index, sex in enumerate(editor.SEXES):
        _button(screen, fonts["body"], pygame.Rect(rect.x + index * 120, y + 20, 110, 32), sex["label"], hitboxes,
                {"kind": "sex", "sex": sex["id"]}, active=draft.get("sex") == sex["id"])
    y += 80
    for line in (
        "Then: where and when they were born, their genetics, their personality, and their life.",
        "Any step can be opened from the top. Nothing is written to the repository until Save.",
    ):
        _text(screen, fonts["small"], line, DIM, (rect.x, y), rect.width)
        y += 22


def _draw_birth_step(screen, fonts, sim, state, rect, hitboxes):
    world_model = sim.world_model
    draft = state["draft"]
    tree = place_tree(world_model)
    _text(screen, fonts["head"], "BIRTH", TEXT, rect.topleft)
    y = rect.y + 30
    _text(screen, fonts["small"], "Year of birth", DIM, (rect.x, y))
    x = rect.x
    row_y = y + 20
    for delta in (-100, -10, -1):
        _button(screen, fonts["small"], pygame.Rect(x, row_y, 44, 30), f"{delta}", hitboxes, {"kind": "year_delta", "delta": delta})
        x += 48
    _input(screen, fonts["body"], pygame.Rect(x, row_y, 90, 30), state, "year", "year", hitboxes)
    x += 94
    for delta in (1, 10, 100):
        _button(screen, fonts["small"], pygame.Rect(x, row_y, 44, 30), f"+{delta}", hitboxes, {"kind": "year_delta", "delta": delta})
        x += 48
    year = draft.get("start_year")
    if year is not None:
        _text(screen, fonts["small"], _age_text(sim.year, year), DIM, (x + 8, row_y + 7))
    y = row_y + 44
    _draw_chosen_place(screen, fonts, state, tree, "birth_location", "Place of birth", pygame.Rect(rect.x, y, rect.width, 44), hitboxes)
    _draw_place_browser(screen, fonts, state, world_model, "birth_location",
                        pygame.Rect(rect.x, y + 52, rect.width, rect.bottom - y - 52), hitboxes)


def _draw_chosen_place(screen, fonts, state, tree, field, title, rect, hitboxes):
    place = state["draft"].get(field)
    _text(screen, fonts["small"], title, DIM, rect.topleft)
    if not place:
        _text(screen, fonts["body"], "not chosen: pick one below", FAINT, (rect.x, rect.y + 18), rect.width)
        return
    label = tree.label(place) if place in tree.places else place
    width = _text(screen, fonts["body"], label, GOLD, (rect.x, rect.y + 18), rect.width - 280)
    chain = " > ".join(tree.label(item) for item in tree.chain(place)[:-1])
    if field == "birth_location":
        existed = tree.existed(place, state["draft"].get("start_year"))
        _text(screen, fonts["tiny"], tree.existence_text(place, state["draft"].get("start_year")),
              AMBER if existed is False else (GREEN if existed else FAINT), (rect.right - 270, rect.y + 2), 240)
    label_w = min(rect.width - 300, fonts["body"].size(label)[0])
    _text(screen, fonts["tiny"], f"in {chain}" if chain else "", FAINT, (rect.x + label_w + 12, rect.y + 22), rect.width - label_w - 60)
    _button(screen, fonts["tiny"], pygame.Rect(rect.right - 26, rect.y + 16, 24, 22), "x", hitboxes, {"kind": "place_clear", "field": field})


def _draw_place_browser(screen, fonts, state, world_model, field, rect, hitboxes):
    tree = place_tree(world_model)
    searching = bool(state["inputs"].get("place_search", "").strip())
    search_rect = pygame.Rect(rect.right - 200, rect.y, 200, 28)
    _input(screen, fonts["small"], search_rect, state, "place_search", "Search places", hitboxes)
    crumbs = [(None, "All places")] + [(item, tree.label(item)) for item in tree.chain(editor.browsed_place(state, field, world_model))]
    x, limit = rect.x, search_rect.x - 10
    if searching:
        _text(screen, fonts["small"], "Search results", DIM, (rect.x, rect.y + 6))
    else:
        # Show the innermost crumbs that fit.
        shown, used = [], 0
        for place_id, label in reversed(crumbs):
            crumb_w = min(150, fonts["tiny"].size(label)[0] + 16)
            if used + crumb_w + 14 > limit - rect.x and shown:
                break
            shown.insert(0, (place_id, label, crumb_w))
            used += crumb_w + 14
        for place_id, label, crumb_w in shown:
            _button(screen, fonts["tiny"], pygame.Rect(x, rect.y + 2, crumb_w, 24), label, hitboxes,
                    {"kind": "place_browse", "field": field, "place_id": place_id})
            x += crumb_w + 4
            _text(screen, fonts["tiny"], ">", FAINT, (x, rect.y + 7))
            x += 10
    list_rect = pygame.Rect(rect.x, rect.y + 36, rect.width, rect.height - 36)
    pygame.draw.rect(screen, (13, 18, 25), list_rect, border_radius=4)
    rows = editor.place_rows(state, field, world_model)
    visible = max(1, (list_rect.height - 8) // ROW_H)
    offset = _scrolled(state, field, len(rows), visible)
    hitboxes.append({"kind": "scroll_area", "key": field, "rect": list_rect})
    if not rows:
        _text(screen, fonts["small"], "Nothing inside this place. Search, or go back up.", FAINT, (list_rect.x + 10, list_rect.y + 10))
    for index, row in enumerate(rows[offset:offset + visible]):
        row_rect = pygame.Rect(list_rect.x + 4, list_rect.y + 4 + index * ROW_H, list_rect.width - 8, ROW_H - 3)
        pygame.draw.rect(screen, CHOSEN if row["chosen"] else (20, 27, 37), row_rect, border_radius=3)
        if row["chosen"]:
            pygame.draw.rect(screen, GOLD, row_rect, 1, border_radius=3)
        hitboxes.append({"kind": "place_choose", "field": field, "place_id": row["id"], "rect": row_rect})
        name_w = min(320, row_rect.width // 2)
        _text(screen, fonts["small"], row["label"], TEXT, (row_rect.x + 8, row_rect.y + 4), name_w)
        detail = row["class"] + (f"  in {row['within']}" if row["within"] else "")
        _text(screen, fonts["tiny"], detail, FAINT, (row_rect.x + name_w + 16, row_rect.y + 6), row_rect.width - name_w - 130)
        if row["existed"] is False:
            _text(screen, fonts["tiny"], "not then", AMBER, (row_rect.right - 110, row_rect.y + 6))
        if row["opens"]:
            open_rect = pygame.Rect(row_rect.right - 40, row_rect.y + 1, 38, row_rect.height - 2)
            _button(screen, fonts["small"], open_rect, ">", hitboxes, {"kind": "place_browse", "field": field, "place_id": row["id"]})
    if len(rows) > visible:
        _text(screen, fonts["tiny"], f"{offset + 1}-{min(len(rows), offset + visible)} of {len(rows)}, scroll for more",
              FAINT, (list_rect.right - 200, list_rect.bottom + 2))


def _draw_parents_step(screen, fonts, sim, state, rect, hitboxes):
    world_model = sim.world_model
    _text(screen, fonts["head"], "PARENTS (optional)", TEXT, rect.topleft)
    _text(screen, fonts["tiny"], "Up to two people. The genome is drawn from theirs; with none it comes from a seed.",
          FAINT, (rect.x + 170, rect.y + 3), rect.width - 170)
    chosen = editor.parent_ids(state, world_model)
    slot_w = (rect.width - 12) // 2
    for index in range(editor.MAX_PARENTS):
        slot = pygame.Rect(rect.x + index * (slot_w + 12), rect.y + 28, slot_w, 64)
        pygame.draw.rect(screen, CHOSEN if index < len(chosen) else (20, 27, 37), slot, border_radius=5)
        pygame.draw.rect(screen, GOLD if index < len(chosen) else BUTTON_EDGE, slot, 1, border_radius=5)
        if index >= len(chosen):
            _text(screen, fonts["small"], "no parent chosen", FAINT, (slot.x + 10, slot.y + 22))
            continue
        parent = sim.world_model.get_entity(chosen[index]) or {}
        _text(screen, fonts["body"], editor.entity_label(world_model, chosen[index]), GOLD, (slot.x + 10, slot.y + 6), slot.width - 50)
        years = f"{parent.get('start_year', '?')}-{parent.get('end_year', '')}".rstrip("-")
        dna = "DNA saved" if editor.decode_person_dna(parent.get("genetic_dna"))["valid"] else "no DNA saved: their preview genome is used"
        _text(screen, fonts["tiny"], f"{years}  {dna}", DIM, (slot.x + 10, slot.y + 28), slot.width - 20)
        note = editor.parent_note(parent, state["draft"].get("start_year"))
        if note:
            _text(screen, fonts["tiny"], note, AMBER, (slot.x + 10, slot.y + 44), slot.width - 20)
        _button(screen, fonts["tiny"], pygame.Rect(slot.right - 30, slot.y + 6, 24, 22), "x", hitboxes,
                {"kind": "parent", "person_id": chosen[index]})
    y = rect.y + 104
    _text(screen, fonts["small"], "People", DIM, (rect.x, y + 6))
    _input(screen, fonts["small"], pygame.Rect(rect.right - 200, y, 200, 28), state, "people_search", "Search people", hitboxes)
    list_rect = pygame.Rect(rect.x, y + 36, rect.width, rect.bottom - y - 36)
    pygame.draw.rect(screen, (13, 18, 25), list_rect, border_radius=4)
    hitboxes.append({"kind": "scroll_area", "key": "parents", "rect": list_rect})
    rows = editor.parent_rows(state, world_model)
    visible = max(1, (list_rect.height - 8) // ROW_H)
    offset = _scrolled(state, "parents", len(rows), visible)
    if not rows:
        _text(screen, fonts["small"], "Nobody matches.", FAINT, (list_rect.x + 10, list_rect.y + 10))
    for index, row in enumerate(rows[offset:offset + visible]):
        row_rect = pygame.Rect(list_rect.x + 4, list_rect.y + 4 + index * ROW_H, list_rect.width - 8, ROW_H - 3)
        pygame.draw.rect(screen, CHOSEN if row["chosen"] else (20, 27, 37), row_rect, border_radius=3)
        if row["chosen"]:
            pygame.draw.rect(screen, GOLD, row_rect, 1, border_radius=3)
        hitboxes.append({"kind": "parent", "person_id": row["id"], "rect": row_rect})
        _text(screen, fonts["small"], row["label"], TEXT, (row_rect.x + 8, row_rect.y + 4), 260)
        years = "" if row["born"] is None else f"{row['born']}-{row['ended'] if row['ended'] is not None else ''}"
        age = "" if row["age"] is None or row["age"] < 0 else f"age {row['age']} at the birth"
        _text(screen, fonts["tiny"], f"{years}  {age}", FAINT, (row_rect.x + 280, row_rect.y + 6), 220)
        if row["note"]:
            _text(screen, fonts["tiny"], row["note"], AMBER, (row_rect.right - 190, row_rect.y + 6), 180)
    if len(rows) > visible:
        _text(screen, fonts["tiny"], f"{offset + 1}-{min(len(rows), offset + visible)} of {len(rows)}, scroll for more",
              FAINT, (list_rect.right - 200, list_rect.bottom + 2))


def _draw_genetics_step(screen, fonts, sim, state, rect, hitboxes):
    decoded = editor.editor_appearance(state)
    tone = decoded["skin_tone"]
    parents = editor.parent_ids(state, sim.world_model)
    _text(screen, fonts["head"], "GENETICS", TEXT, rect.topleft)
    source = ("from " + " and ".join(editor.entity_label(sim.world_model, item) for item in parents)) if parents else "no parents: from a seed"
    _text(screen, fonts["tiny"], f"Genome {source}", FAINT, (rect.x + 100, rect.y + 3), rect.width - 270)
    _button(screen, fonts["small"], pygame.Rect(rect.right - 150, rect.y - 4, 150, 28),
            "Redraw from parents" if parents else "Reroll genome", hitboxes, {"kind": "reroll_genome"})
    y = rect.y + 30
    _text(screen, fonts["tiny"], "Skin tone", DIM, (rect.x, y))
    card_w = max(104, min(150, rect.width // 3 - 8))
    for index, option in enumerate(SKIN_TONES):
        card = pygame.Rect(rect.x + index * (card_w + 10), y + 16, card_w, 44)
        active = option["id"] == tone["id"]
        pygame.draw.rect(screen, CHOSEN if active else (24, 31, 42), card, border_radius=5)
        pygame.draw.rect(screen, GOLD if active else BUTTON_EDGE, card, 2 if active else 1, border_radius=5)
        pygame.draw.circle(screen, option["color"], (card.x + 22, card.centery), 11)
        _text(screen, fonts["small"], option["label"], TEXT, (card.x + 40, card.centery - 8))
        hitboxes.append({"kind": "skin_tone", "tone_id": option["id"], "rect": card})
    y += 76
    _text(screen, fonts["tiny"], "Body shape loci", DIM, (rect.x, y))
    for index, trait in enumerate(BODY_TRAITS):
        row_y = y + 18 + index * 27
        value = decoded["body_shape"][trait["id"]]
        _text(screen, fonts["tiny"], trait["label"], (210, 219, 231), (rect.x, row_y + 5))
        minus = pygame.Rect(rect.x + 118, row_y, 24, 22)
        track = pygame.Rect(minus.right + 6, row_y + 9, max(60, min(360, rect.width - 190)), 5)
        plus = pygame.Rect(track.right + 7, row_y, 24, 22)
        _button(screen, fonts["small"], minus, "-", hitboxes, {"kind": "body_trait", "trait_id": trait["id"], "delta": -.05})
        _button(screen, fonts["small"], plus, "+", hitboxes, {"kind": "body_trait", "trait_id": trait["id"], "delta": .05})
        pygame.draw.line(screen, (66, 79, 96), track.midleft, track.midright, 3)
        pygame.draw.circle(screen, (224, 194, 102), (round(track.x + value * track.width), track.centery), 5)
    y += 18 + len(BODY_TRAITS) * 27 + 12
    _text(screen, fonts["tiny"], "Clothing items (worn over the body, not DNA)", DIM, (rect.x, y))
    options = [(None, "Naked")]
    for clothing_id in editor.TEST_CLOTHING_IDS:
        entity = sim.get_person(clothing_id) or {}
        options.append((clothing_id, entity.get("pretty_name") or entity.get("name") or clothing_id))
    current = editor.working_clothing_id(state)
    for index, (clothing_id, label) in enumerate(options):
        _button(screen, fonts["tiny"], pygame.Rect(rect.x + index * 130, y + 16, 122, 32), str(label), hitboxes,
                {"kind": "clothing", "clothing_id": clothing_id}, active=current == clothing_id)
    y += 64
    _text(screen, fonts["tiny"], "DNA string", DIM, (rect.x, y))
    dna = str(state["draft"].get("genetic_dna") or "")
    box = pygame.Rect(rect.x, y + 16, min(rect.width, 520), 48)
    pygame.draw.rect(screen, (8, 12, 18), box, border_radius=4)
    pygame.draw.rect(screen, (62, 80, 104), box, 1, border_radius=4)
    midpoint = (len(dna) + 1) // 2
    _text(screen, fonts["tiny"], dna[:midpoint], (155, 213, 190), (box.x + 10, box.y + 8))
    _text(screen, fonts["tiny"], dna[midpoint:], (155, 213, 190), (box.x + 10, box.y + 26))


def _draw_personality_step(screen, fonts, sim, state, rect, hitboxes):
    world_model = sim.world_model
    values = editor.editor_personality(state, world_model)
    _text(screen, fonts["head"], "PERSONALITY", TEXT, rect.topleft)
    parents = editor.parent_ids(state, world_model)
    source = "around the parents" if parents else "around the population"
    _text(screen, fonts["tiny"], f"Birth drawn {source} (seed {birth_seed(state['draft'])})",
          FAINT, (rect.x + 130, rect.y + 3), rect.width - 300)
    _button(screen, fonts["small"], pygame.Rect(rect.right - 150, rect.y - 4, 150, 28), "Reroll birth", hitboxes, {"kind": "reroll_birth"})
    track_x = rect.x + 118
    track_w = max(200, rect.width - 118 - 196)
    y = rect.y + 34
    for axis in AXES:
        entry = values[axis]
        row = pygame.Rect(rect.x, y, rect.width, 44)
        _text(screen, fonts["small"], AXIS_LABELS[axis], TEXT, (row.x, row.y + 14), 112)
        track = pygame.Rect(track_x, row.y + 18, track_w, 10)

        def span(mean, spread, top, bottom):
            left = track.x + max(0.0, mean - spread) * track.width
            right_edge = track.x + min(1.0, mean + spread) * track.width
            return pygame.Rect(round(left), top, max(2, round(right_edge - left)), bottom - top)

        pygame.draw.rect(screen, (30, 38, 50), track)
        pygame.draw.rect(screen, (44, 54, 68), span(POPULATION_MEAN, POPULATION_SD, track.y, track.bottom))
        pygame.draw.rect(screen, (106, 142, 186), span(entry.baseline, entry.baseline_spread, track.y - 3, track.bottom + 3), 1)
        pygame.draw.rect(screen, (150, 128, 64), span(entry.value, entry.spread, track.y + 2, track.bottom - 2))
        pygame.draw.circle(screen, GOLD, (round(track.x + entry.value * track.width), track.centery), 5)
        for parent_name, parent_value in entry.parents:
            parent_x = round(track.x + parent_value * track.width)
            pygame.draw.polygon(screen, (126, 170, 222), [(parent_x, track.bottom + 1), (parent_x - 4, track.bottom + 7), (parent_x + 4, track.bottom + 7)])
            initial = fonts["tiny"].render(parent_name[:1], True, (126, 170, 222))
            screen.blit(initial, initial.get_rect(midtop=(parent_x, track.bottom + 7)))
        for index, (word, place) in enumerate(entry.words[:8]):
            word_x = round(track.x + place * track.width)
            word_y = track.y - 9 if index % 2 == 0 else track.bottom + 9
            pygame.draw.polygon(screen, (222, 140, 180), [(word_x, word_y - 4), (word_x + 4, word_y), (word_x, word_y + 4), (word_x - 4, word_y)])
            label = fonts["tiny"].render(_fit(fonts["tiny"], word, 70), True, (222, 180, 200))
            screen.blit(label, label.get_rect(midbottom=(word_x, word_y - 4)) if index % 2 == 0 else label.get_rect(midtop=(word_x, word_y + 4)))
        side = track.right + 12
        _text(screen, fonts["tiny"], f"{entry.value:.2f} ± {entry.spread:.2f}", TEXT, (side, row.y + 6))
        _text(screen, fonts["tiny"], f"{entry.baseline_source} {entry.baseline:.2f}", FAINT, (side, row.y + 22))
        _button(screen, fonts["small"], pygame.Rect(side + 84, row.y + 10, 24, 24), "-", hitboxes, {"kind": "baseline_delta", "axis": axis, "delta": -.05})
        _button(screen, fonts["small"], pygame.Rect(side + 112, row.y + 10, 24, 24), "+", hitboxes, {"kind": "baseline_delta", "axis": axis, "delta": .05})
        if entry.baseline_source == "authored":
            _button(screen, fonts["tiny"], pygame.Rect(side + 140, row.y + 10, 44, 24), "birth", hitboxes, {"kind": "baseline_reset", "axis": axis})
        y += 46

    y += 4
    chip_x = rect.x
    for axis in (None, *AXES):
        label = "All" if axis is None else AXIS_LABELS[axis]
        _button(screen, fonts["tiny"], pygame.Rect(chip_x, y, 86, 24), label, hitboxes,
                {"kind": "word_axis", "axis": axis}, active=state.get("word_axis") == axis)
        chip_x += 90
    _input(screen, fonts["small"], pygame.Rect(max(chip_x + 6, rect.right - 160), y, min(160, rect.right - chip_x - 6), 24),
           state, "word_search", "Search words", hitboxes)
    words_rect = pygame.Rect(rect.x, y + 30, rect.width, rect.bottom - y - 30 - 40)
    pygame.draw.rect(screen, (13, 18, 25), words_rect, border_radius=4)
    hitboxes.append({"kind": "scroll_area", "key": "words", "rect": words_rect})
    rows = editor.word_rows(state, world_model)
    columns = max(1, words_rect.width // 150)
    chip_w = (words_rect.width - 8) // columns
    visible_rows = max(1, (words_rect.height - 6) // 24)
    first_row = _scrolled(state, "words", (len(rows) + columns - 1) // columns, visible_rows)
    axis = state.get("word_axis")
    for index, row in enumerate(rows[first_row * columns:(first_row + visible_rows) * columns]):
        chip = pygame.Rect(words_rect.x + 4 + (index % columns) * chip_w, words_rect.y + 4 + (index // columns) * 24, chip_w - 4, 21)
        pygame.draw.rect(screen, CHOSEN if row["chosen"] else (22, 29, 39), chip, border_radius=3)
        if row["chosen"]:
            pygame.draw.rect(screen, GOLD, chip, 1, border_radius=3)
        hitboxes.append({"kind": "word", "word": row["label"], "rect": chip})
        if axis:
            place = f"{row['positions'][axis]:.2f}"
        else:
            main = max(row["positions"], key=lambda item: abs(row["positions"][item] - 0.5), default=None)
            place = f"{AXIS_SHORT[main]} {row['positions'][main]:.2f}" if main else ""
        _text(screen, fonts["tiny"], row["label"], GOLD if row["chosen"] else TEXT, (chip.x + 6, chip.y + 4), chip.width - 56)
        _text(screen, fonts["tiny"], place, FAINT, (chip.right - 48, chip.y + 4))
    total_rows = (len(rows) + columns - 1) // columns
    if total_rows > visible_rows:
        _text(screen, fonts["tiny"], f"{len(rows)} words, scroll for more", FAINT, (words_rect.right - 170, words_rect.bottom + 2))
    chosen = [str(word) for word in state["draft"].get(WORDS_FIELD) or []]
    exclusions = editor.chosen_exclusions(state, world_model)
    _text(screen, fonts["small"], "Words: " + (", ".join(chosen) if chosen else "none yet; click words to add them"), TEXT,
          (rect.x, words_rect.bottom + 16), rect.width)
    if exclusions:
        _text(screen, fonts["tiny"], "; ".join(exclusions), AMBER, (rect.x, words_rect.bottom + 34), rect.width)


def _draw_life_step(screen, fonts, sim, state, rect, hitboxes):
    world_model = sim.world_model
    draft = state["draft"]
    _text(screen, fonts["head"], "LIFE", TEXT, rect.topleft)
    _text(screen, fonts["tiny"], "Where they live and work, and what they know with others.", FAINT, (rect.x + 60, rect.y + 3), rect.width - 60)
    tab_w = (rect.width - 12) // len(editor.LIFE_TABS)
    y = rect.y + 28
    for index, tab in enumerate(editor.LIFE_TABS):
        tab_rect = pygame.Rect(rect.x + index * (tab_w + 4), y, tab_w, 44)
        active = state["life_tab"] == tab["id"]
        pygame.draw.rect(screen, CHOSEN if active else BUTTON, tab_rect, border_radius=4)
        pygame.draw.rect(screen, GOLD if active else BUTTON_EDGE, tab_rect, 2 if active else 1, border_radius=4)
        if tab["kind"] == "knowledge":
            value = ", ".join(editor.entity_label(world_model, item) for item in state["shared_knowledge"]) or "none"
        else:
            value = editor.entity_label(world_model, draft.get(tab["id"]), "none")
        _text(screen, fonts["small"], tab["label"], TEXT, (tab_rect.x + 8, tab_rect.y + 4), tab_rect.width - 12)
        _text(screen, fonts["tiny"], value, GOLD if value != "none" else FAINT, (tab_rect.x + 8, tab_rect.y + 24), tab_rect.width - 12)
        hitboxes.append({"kind": "life_tab", "tab": tab["id"], "rect": tab_rect})
    y += 56
    tab = next(item for item in editor.LIFE_TABS if item["id"] == state["life_tab"])
    body = pygame.Rect(rect.x, y, rect.width, rect.bottom - y)
    if tab["kind"] == "place":
        tree = place_tree(world_model)
        _draw_chosen_place(screen, fonts, state, tree, tab["id"], tab["label"], pygame.Rect(body.x, body.y, body.width, 44), hitboxes)
        _draw_place_browser(screen, fonts, state, world_model, tab["id"], pygame.Rect(body.x, body.y + 52, body.width, body.height - 52), hitboxes)
        return
    if tab["kind"] == "job":
        rows = editor.job_rows(state, world_model)
        hitbox_kind, id_key, empty = "job", "job_id", "No jobs in the repository."
        note = "Click a job to choose it; click it again to drop it."
    else:
        rows = editor.knowledge_rows(state, world_model)
        hitbox_kind, id_key, empty = "knowledge", "collection_id", "No shared knowledge collections in the repository."
        note = "Shared collections (a culture, a job's training, local lore) the person's own knowledge includes."
    _text(screen, fonts["tiny"], note, FAINT, (body.x, body.y), body.width)
    list_rect = pygame.Rect(body.x, body.y + 20, body.width, body.height - 20)
    pygame.draw.rect(screen, (13, 18, 25), list_rect, border_radius=4)
    if not rows:
        _text(screen, fonts["small"], empty, FAINT, (list_rect.x + 10, list_rect.y + 10))
    for index, row in enumerate(rows[: max(1, (list_rect.height - 8) // ROW_H)]):
        row_rect = pygame.Rect(list_rect.x + 4, list_rect.y + 4 + index * ROW_H, list_rect.width - 8, ROW_H - 3)
        pygame.draw.rect(screen, CHOSEN if row["chosen"] else (20, 27, 37), row_rect, border_radius=3)
        if row["chosen"]:
            pygame.draw.rect(screen, GOLD, row_rect, 1, border_radius=3)
        mark = "[x]" if row["chosen"] else "[ ]"
        detail = f"  ({row['size']} members)" if "size" in row else ""
        _text(screen, fonts["small"], f"{mark} {row['label']}{detail}", TEXT, (row_rect.x + 8, row_rect.y + 4), row_rect.width - 16)
        hitboxes.append({"kind": hitbox_kind, id_key: row["id"], "rect": row_rect})


def _draw_review_step(screen, fonts, sim, state, rect, hitboxes):
    world_model = sim.world_model
    draft = state["draft"]
    tree = place_tree(world_model)
    decoded = editor.editor_appearance(state)
    values = editor.editor_personality(state, world_model)
    readiness = editor.readiness(state, world_model)
    place = draft.get("birth_location")
    year = draft.get("start_year")
    born = f"{year if year is not None else 'year not set'}"
    if place:
        born += f" in {tree.label(place)} ({tree.existence_text(place, year)})"
    shape = ", ".join(f"{trait['label'].lower()} {decoded['body_shape'][trait['id']]:.2f}" for trait in BODY_TRAITS)
    clothing = editor.working_clothing_id(state)
    rows = [
        ("Name", draft.get("pretty_name") or "not set"),
        ("Id", draft.get("id")),
        ("Sex", draft.get("sex") or "not set"),
        ("Born", born),
        ("Parents", " and ".join(editor.entity_label(world_model, item) for item in editor.parent_ids(state, world_model)) or "none chosen"),
        ("Genetics", f"{decoded['skin_tone']['label']} skin; {shape}"),
        ("Clothing", editor.entity_label(world_model, clothing, "none")),
        ("Personality", "  ".join(f"{AXIS_SHORT[axis]} {values[axis].value:.2f}±{values[axis].spread:.2f}" for axis in AXES)),
        ("Words", ", ".join(str(word) for word in draft.get(WORDS_FIELD) or []) or "none"),
        ("Home", editor.entity_label(world_model, draft.get("residence"))),
        ("Job", editor.entity_label(world_model, draft.get("is_employed_as"))),
        ("Workplace", editor.entity_label(world_model, draft.get("is_employed_at"))),
        ("Knows with others", ", ".join(editor.entity_label(world_model, item) for item in state["shared_knowledge"]) or "none"),
        ("Readiness", f"{readiness['tier']}" + (f"; missing {', '.join(readiness['missing'])}" if readiness.get("missing") else "")),
        ("Save writes", editor.save_summary(state)),
    ]
    _text(screen, fonts["head"], "REVIEW", TEXT, rect.topleft)
    y = rect.y + 32
    for label, value in rows:
        _text(screen, fonts["small"], label, DIM, (rect.x, y), 140)
        lines = _wrap(fonts["small"], value, rect.width - 150) or [""]
        for line in lines[:3]:
            _text(screen, fonts["small"], line, TEXT, (rect.x + 150, y), rect.width - 150)
            y += 20
        y += 6
    if state["is_new"] and not draft.get("pretty_name"):
        _text(screen, fonts["small"], "Give them a name (step 1) to save.", AMBER, (rect.x, y + 6))
