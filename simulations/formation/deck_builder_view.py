"""Drawing for Formation Sim's Deck workspace: the card catalog, the deck's
card tiles grouped by category, the deck's people, and the card editor (see
``deck_builder`` and ``formation_people``)."""

import zlib

import pygame

from simulations.formation.deck_builder import CATEGORY_VOCAB


CATEGORY_COLORS = {
    "Command": (176, 150, 82),
    "Infantry": (112, 142, 92),
    "Armor": (156, 114, 78),
    "Recon": (92, 142, 150),
    "Support": (128, 118, 152),
    "Artillery": (164, 94, 84),
    "Air Defense": (88, 118, 172),
    "Helicopters": (104, 152, 170),
    "Aircraft": (118, 138, 192),
    "Logistics": (142, 140, 104),
    "Naval": (70, 112, 152),
    "Space": (122, 100, 164),
}
ERROR = (214, 120, 104)
GLYPH = (133, 166, 171)
TILE_W, TILE_H, TILE_GAP = 176, 236, 12
PREVIEW_W = 196
ROW_H = 34
PEOPLE_W = 290
PEOPLE_LINE = 18
PERSON_DETAIL_H = 156
LEANING_WORDS = {
    "openness": ("open to new things", "conventional"),
    "conscientiousness": ("dutiful", "careless"),
    "extraversion": ("outgoing", "reserved"),
    "agreeableness": ("easygoing", "hard to get along with"),
    "neuroticism": ("anxious", "steady"),
}


def category_color(category):
    if category in CATEGORY_COLORS:
        return CATEGORY_COLORS[category]
    seed = zlib.crc32(str(category).encode("utf-8"))
    return (90 + seed % 70, 100 + (seed >> 8) % 60, 100 + (seed >> 16) % 70)


def _dark(color, factor=0.42):
    return tuple(int(channel * factor) for channel in color)


def _plural(count, word):
    return f"{count} {word}" if count == 1 else f"{count} {word}s"


def _strength(totals):
    parts = []
    if totals["vehicles"]:
        parts.append(_plural(totals["vehicles"], "vehicle"))
    if totals["items"]:
        parts.append(_plural(totals["items"], "item"))
    parts.append(f"{totals['people']} people")
    return " · ".join(parts)


def _wrap(view, value, width, size, bold=False, lines=2):
    words = str(value or "").split()
    result = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if view._text(candidate, size=size, bold=bold).get_width() <= width or not current:
            current = candidate
        else:
            result.append(current)
            current = word
    if current:
        result.append(current)
    if len(result) > lines:
        result = result[:lines]
        result[-1] = view._fit_design_text(result[-1] + "…", width, size)
    return [view._fit_design_text(line, width, size) for line in result]


def _field_box(view, screen, hitboxes, key, rect, value, placeholder, focused, buffer):
    pygame.draw.rect(screen, (10, 17, 23), rect)
    pygame.draw.rect(screen, view.BORDER_ACTIVE if focused else view.BORDER, rect, 2 if focused else 1)
    text = buffer if focused else value
    color = view.TEXT if text else view.MUTED
    shown = view._fit_design_text(text if text else placeholder, rect.width - 18, 13)
    surface = view._text(shown, color, size=13)
    screen.blit(surface, (rect.x + 8, rect.centery - surface.get_height() // 2))
    if focused:
        caret_x = rect.x + 8 + (surface.get_width() if text else 0) + 1
        pygame.draw.line(screen, view.BORDER_ACTIVE, (caret_x, rect.y + 5), (caret_x, rect.bottom - 5), 2)
    hitboxes[key] = rect


def _small_button(view, screen, hitboxes, key, label, x, y, width=None, active=True, height=22):
    width = width or view._text(label, size=11).get_width() + 14
    button = pygame.Rect(x, y, width, height)
    pygame.draw.rect(screen, (55, 65, 48) if active else view.PANEL_ALT, button)
    pygame.draw.rect(screen, view.BORDER_ACTIVE if active else view.BORDER, button, 1)
    surface = view._text(label, view.TEXT if active else view.MUTED, size=11)
    screen.blit(surface, surface.get_rect(center=button.center))
    if key:
        hitboxes[key] = button
    return button


def _vehicle_glyph(screen, x, y):
    pygame.draw.rect(screen, GLYPH, (x + 1, y + 8, 20, 9), border_radius=2)
    pygame.draw.rect(screen, GLYPH, (x + 6, y + 4, 9, 5))


def _item_glyph(screen, x, y, size=18):
    box = pygame.Rect(x + 2, y + 3, size, size - 4)
    pygame.draw.rect(screen, GLYPH, box, 2)
    pygame.draw.line(screen, GLYPH, (box.x, box.centery), (box.right - 1, box.centery), 2)


def draw_deck_view(view, screen, sim, rect, top, hitboxes):
    deck = sim.deck
    formation_id = deck.target_formation_id()
    x = rect.x + 16
    header_y = top + 40
    title = "DECK  ·  " + deck.formation_label(formation_id)
    screen.blit(view._text(view._fit_design_text(title, rect.width - 460, 17), view.TEXT, size=17, bold=True),
                (x, header_y))

    summary = deck.deck_summary(formation_id) if formation_id else {"rows": [], "groups": [], "totals": deck._empty_totals()}
    totals = summary["totals"]
    faction = sim._faction_label(deck.formation_faction_id(formation_id)) if formation_id else None
    parts = [faction or "No faction owner", _plural(totals["cards"], "card"), _strength(totals)]
    below = deck.subordinate_totals(formation_id) if formation_id else deck._empty_totals()
    if below["cards"]:
        parts.append(f"subordinate decks: {_plural(below['cards'], 'card')}, {_strength(below)}")
    screen.blit(view._text(view._fit_design_text("  ·  ".join(parts), rect.width - 40, 11), view.MUTED, size=11),
                (x, header_y + 25))
    if formation_id:
        short = []
        if totals["short_people"]:
            short.append(f"{totals['short_people']:,} people")
        if totals["short_equipment"]:
            short.append(_plural(totals["short_equipment"], "piece") + " of equipment")
        short_text = ("Understrength: short " + ", ".join(short)) if short else ""
        short_w = view._text(short_text, size=11, bold=True).get_width() + 24 if short_text else 0
        screen.blit(view._text(view._fit_design_text(_sources_line(deck, formation_id), rect.width - 40 - short_w, 11),
                               view.MUTED, size=11), (x, header_y + 41))
        if short_text:
            surface = view._text(short_text, ERROR, size=11, bold=True)
            screen.blit(surface, (rect.right - 16 - surface.get_width(), header_y + 41))
    if deck.notice:
        note_surface = view._text(view._fit_design_text(deck.notice, rect.width - 420, 11), view.ACCENT, size=11,
                                  bold=True)
        screen.blit(note_surface, (rect.right - 16 - note_surface.get_width(), header_y + 3))

    body = pygame.Rect(rect.x + 12, header_y + 64, rect.width - 24, rect.bottom - header_y - 76)
    catalog = pygame.Rect(body.x, body.y, min(300, body.width // 3), body.height)
    area = pygame.Rect(catalog.right + 12, body.y, body.right - catalog.right - 12, body.height)
    _draw_catalog(view, screen, sim, catalog, hitboxes)
    if deck.editor is not None:
        _draw_editor(view, screen, sim, area, hitboxes)
        return
    if formation_id and area.width >= PEOPLE_W + TILE_W + 48:
        people = pygame.Rect(area.right - PEOPLE_W, area.y, PEOPLE_W, area.height)
        area = pygame.Rect(area.x, area.y, area.width - PEOPLE_W - 12, area.height)
        _draw_people(view, screen, sim, formation_id, people, hitboxes)
    _draw_deck(view, screen, sim, summary, area, hitboxes)


def _sources_line(deck, formation_id):
    fielding = deck.fielding
    if not fielding.draws(formation_id):
        return "Blueprint deck: a plan; fielding its cards draws nothing"
    pop_id = fielding.manpower_pop_id(formation_id)
    if pop_id:
        manpower = (f"Manpower: {fielding.label(pop_id)}, {fielding.pop_free(pop_id):,} of "
                    f"{fielding.pop_size(pop_id):,} free")
    else:
        manpower = "Manpower: no pool (set manpower_pop, or give the faction a service pop)"
    depots = fielding.depot_ids(formation_id)
    depot_text = ("Depots: " + ", ".join(fielding.label(depot) for depot in depots)) if depots \
        else "Depots: none (set supply_depot, or give the faction a depot site)"
    destination = fielding.destination_id(formation_id)
    delivery = f"Deliveries to {fielding.label(destination)}" if destination else "Deliveries: no location set"
    return "  ·  ".join((manpower, depot_text, delivery))


def _draw_catalog(view, screen, sim, panel, hitboxes):
    deck = sim.deck
    editing = deck.editor is not None
    pygame.draw.rect(screen, view.PANEL, panel)
    pygame.draw.rect(screen, view.BORDER, panel, 1)
    hitboxes["deck:catalog:panel"] = panel
    screen.blit(view._text("CARDS", view.TEXT, size=13, bold=True), (panel.x + 12, panel.y + 11))
    _small_button(view, screen, hitboxes, None if editing else "deck:catalog:new", "+ New card",
                  panel.right - 92, panel.y + 7, 80, active=not editing)

    search = pygame.Rect(panel.x + 10, panel.y + 38, panel.width - 20, 26)
    _field_box(view, screen, {}, "", search, deck.catalog_query, "Search cards…",
               deck.catalog_search_active, deck.catalog_query)
    if not editing:
        hitboxes["deck:catalog:search"] = search

    chip_x, chip_y = panel.x + 10, search.bottom + 8
    for category in ["*"] + deck.catalog_categories():
        label = "All" if category == "*" else category
        width = view._text(label, size=10).get_width() + 14
        if chip_x + width > panel.right - 10:
            chip_x, chip_y = panel.x + 10, chip_y + 24
        active = (deck.catalog_category or "*") == category
        chip = pygame.Rect(chip_x, chip_y, width, 20)
        color = view.BORDER_ACTIVE if category == "*" else category_color(category)
        pygame.draw.rect(screen, _dark(color) if active else view.PANEL_ALT, chip)
        pygame.draw.rect(screen, color if active else view.BORDER, chip, 1)
        surface = view._text(label, view.TEXT if active else view.MUTED, size=10, bold=active)
        screen.blit(surface, surface.get_rect(center=chip.center))
        if not editing:
            hitboxes[f"deck:catalog:category:{category}"] = chip
        chip_x = chip.right + 5

    listing = pygame.Rect(panel.x + 6, chip_y + 30, panel.width - 12, panel.bottom - chip_y - 36)
    hitboxes["deck:catalog:list"] = listing
    options = deck.catalog()
    clip = screen.get_clip()
    screen.set_clip(listing)
    y = listing.y - deck.catalog_scroll
    for option in options:
        row = pygame.Rect(listing.x + 4, y, listing.width - 8, 52)
        y += 58
        if row.bottom < listing.y or row.y > listing.bottom:
            continue
        color = category_color(option["category"])
        pygame.draw.rect(screen, view.PANEL_ALT, row)
        pygame.draw.rect(screen, view.BORDER, row, 1)
        pygame.draw.rect(screen, color, (row.x, row.y, 5, row.height))
        in_deck = deck.deck_count(option["id"])
        marker_w = 0
        if in_deck:
            marker = view._text(f"×{in_deck}", view.ACCENT, size=13, bold=True)
            marker_w = marker.get_width() + 8
            screen.blit(marker, (row.right - 10 - marker.get_width(), row.y + 6))
        name = view._fit_design_text(option["label"], row.width - 24 - marker_w, 13)
        screen.blit(view._text(name, view.TEXT if not editing else view.MUTED, size=13, bold=True), (row.x + 13, row.y + 6))
        line = f"{option['category']} · {_strength(option['totals'])}"
        screen.blit(view._text(view._fit_design_text(line, row.width - 70, 11), view.MUTED, size=11),
                    (row.x + 13, row.y + 28))
        if not editing:
            hitboxes[f"deck:catalog:card:{option['id']}"] = row.clip(listing)
            edit = _small_button(view, screen, hitboxes, f"deck:catalog:edit:{option['id']}", "Edit",
                                 row.right - 46, row.y + 27, 36, height=18)
            hitboxes[f"deck:catalog:edit:{option['id']}"] = edit.clip(listing)
    deck.content_heights["catalog"] = len(options) * 58
    screen.set_clip(clip)
    if not options:
        lines = ("No cards for this faction yet.", "+ New card makes the first one.") if not deck.catalog_query \
            else ("No cards match the search.",)
        for index, line in enumerate(lines):
            screen.blit(view._text(line, view.MUTED, size=12), (listing.x + 8, listing.y + 6 + index * 20))


def _draw_deck(view, screen, sim, summary, area, hitboxes):
    deck = sim.deck
    pygame.draw.rect(screen, (11, 18, 25), area)
    pygame.draw.rect(screen, view.BORDER, area, 1)
    hitboxes["deck:area"] = area
    if not summary["rows"]:
        lines = ("This deck holds no cards yet.",
                 "Click a card on the left to add it, or + New card to make one.")
        for index, line in enumerate(lines):
            surface = view._text(line, view.TEXT if index == 0 else view.MUTED, size=14 if index == 0 else 12,
                                 bold=index == 0)
            screen.blit(surface, surface.get_rect(center=(area.centerx, area.y + 70 + index * 26)))
        deck.content_heights["deck"] = 0
        return
    columns = max(1, (area.width - 24 + TILE_GAP) // (TILE_W + TILE_GAP))
    clip = screen.get_clip()
    screen.set_clip(area.inflate(-2, -2))
    # Category blocks sit side by side and wrap like words; a category with
    # more cards than a row holds takes whole rows of its own.
    band_y = start = area.y + 12 - deck.deck_scroll
    band_h = 0
    column = 0
    for category, rows in summary["groups"]:
        width = min(columns, len(rows))
        if column and column + width > columns:
            band_y += band_h + 14
            band_h = column = 0
        x = area.x + 12 + column * (TILE_W + TILE_GAP)
        color = category_color(category) if category != "Missing cards" else ERROR
        pygame.draw.rect(screen, color, (x + 2, band_y + 3, 10, 10))
        heading = view._text(category.upper(), view.TEXT, size=12, bold=True)
        screen.blit(heading, (x + 18, band_y))
        detail = _plural(sum(row["count"] for row in rows), "card")
        people = sum(row["count"] * row["totals"]["people"] for row in rows if row["totals"])
        if people:
            detail += f" · {people} people"
        screen.blit(view._text(view._fit_design_text(detail, width * (TILE_W + TILE_GAP) - heading.get_width() - 36, 11),
                               view.MUTED, size=11), (x + 26 + heading.get_width(), band_y + 1))
        for index, row in enumerate(rows):
            tile = pygame.Rect(x + (index % columns) * (TILE_W + TILE_GAP),
                               band_y + 24 + (index // columns) * (TILE_H + TILE_GAP), TILE_W, TILE_H)
            if tile.bottom >= area.y and tile.y <= area.bottom:
                _draw_tile(view, screen, sim, tile, row, hitboxes, area)
        band_h = max(band_h, 24 + ((len(rows) + columns - 1) // columns) * (TILE_H + TILE_GAP) - TILE_GAP)
        column += width
        if column >= columns:
            band_y += band_h + 14
            band_h = column = 0
    deck.content_heights["deck"] = band_y + band_h - start + 24
    screen.set_clip(clip)


def _draw_tile(view, screen, sim, tile, row, hitboxes=None, clip_area=None):
    """One card. ``row`` is a deck_summary row; without hitboxes it is a preview."""
    deck = sim.deck
    card = row["card"] or {}
    color = category_color(row["category"]) if not row.get("missing") else ERROR
    available = row.get("available", True)
    pygame.draw.rect(screen, view.PANEL_ALT, tile)
    pygame.draw.rect(screen, color if available else view.BORDER, tile, 2)
    header = pygame.Rect(tile.x + 2, tile.y + 2, tile.width - 4, 46)
    pygame.draw.rect(screen, _dark(color, 0.5), header)
    for index, line in enumerate(_wrap(view, row["label"], header.width - 16, 12, bold=True)):
        screen.blit(view._text(line, view.TEXT, size=12, bold=True), (header.x + 8, header.y + 5 + index * 17))

    art = pygame.Rect(tile.x + 8, header.bottom + 6, tile.width - 16, 62)
    pygame.draw.rect(screen, (14, 22, 30), art)
    manpower = deck.manpower(card)
    equipment = deck.equipment(card)
    vehicles = [entry for entry in equipment if entry["kind"] == "vehicle"]
    items = [entry for entry in equipment if entry["kind"] == "item"]
    if row.get("missing"):
        surface = view._text("Card not found", ERROR, size=12)
        screen.blit(surface, surface.get_rect(center=art.center))
    elif vehicles:
        entry = vehicles[0]
        shown = min(2, entry["count"])
        step = 68
        left = art.centerx - (shown * step) // 2 - (10 if entry["count"] > shown else 0)
        clip = screen.get_clip()
        screen.set_clip(art.clip(clip))
        for index in range(shown):
            view._draw_vehicle_silhouette(screen, pygame.Rect(left + index * step, art.y + 8, step, 34),
                                          deck.entry_profile(entry))
        screen.set_clip(clip)
        if entry["count"] > shown:
            more = view._text(f"×{entry['count']}", view.TEXT, size=13, bold=True)
            screen.blit(more, (art.right - 6 - more.get_width(), art.y + 6))
        people = row["totals"]["people"] if row.get("totals") else 0
        for index in range(min(8, people)):
            view._draw_person_silhouette(screen, art.x + 6 + index * 12, art.bottom - 20, scale=0.42)
    elif manpower:
        figures = []
        for entry in manpower:
            figures += [entry.get("is_command")] * entry["count"]
        figures = figures[:7]
        left = art.centerx - len(figures) * 11
        for index, command in enumerate(figures):
            view._draw_person_silhouette(screen, left + index * 22, art.y + 10, scale=0.95, command=command)
    elif items:
        for index in range(min(5, sum(entry["count"] for entry in items))):
            _item_glyph(screen, art.centerx - 60 + index * 24, art.centery - 11, 20)

    y = art.bottom + 7
    lines = []
    if row.get("short"):
        lines.append(("short " + deck.fielding.describe_short(row["short"]), ERROR))
    for entry in vehicles:
        lines.append((f"{entry['count']}× {deck.equipment_label(entry)}", view.TEXT))
        crew = deck.entry_crew_size(entry)
        lines.append((f"   + {entry['count'] * crew} crew" if crew else "   no crew listed",
                      view.MUTED if crew else ERROR))
    for entry in manpower:
        lines.append((f"{entry['count']}× {entry['role']}", view.TEXT))
    for entry in items:
        lines.append((f"{entry['count']}× {deck.equipment_label(entry)}", view.MUTED))
    footer_y = tile.bottom - 28
    for index, (line, line_color) in enumerate(lines):
        if y + (15 if index == len(lines) - 1 else 30) > footer_y - 16:
            more = view._text(f"+ {len(lines) - index} more lines", view.MUTED, size=10)
            screen.blit(more, (tile.x + 10, y))
            break
        screen.blit(view._text(view._fit_design_text(line, tile.width - 20, 11), line_color, size=11), (tile.x + 10, y))
        y += 15
    if row.get("totals"):
        strength = _strength(row["totals"]) if available else f"not available in {sim.year}"
        screen.blit(view._text(view._fit_design_text(strength, tile.width - 20, 10), view.MUTED if available else ERROR,
                               size=10), (tile.x + 10, footer_y - 15))

    if hitboxes is None:
        return
    card_id = row["card_id"]
    count = view._text(f"×{row['count']}", view.TEXT, size=16, bold=True)
    screen.blit(count, (tile.x + 10, footer_y + 2))

    def button(key, label, bx, width):
        rect = _small_button(view, screen, hitboxes, key, label, bx, footer_y + 2, width)
        hitboxes[key] = rect.clip(clip_area) if clip_area is not None else rect

    if row.get("missing"):
        button(f"deck:card:remove:{card_id}", "Remove", tile.right - 66, 58)
        return
    button(f"deck:card:minus:{card_id}", "-", tile.right - 112, 24)
    button(f"deck:card:plus:{card_id}", "+", tile.right - 84, 24)
    button(f"deck:card:edit:{card_id}", "Edit", tile.right - 56, 48)


def _draw_editor(view, screen, sim, panel, hitboxes):
    deck = sim.deck
    editor = deck.editor
    draft = editor["draft"]
    focus = editor["focus"]
    pygame.draw.rect(screen, view.PANEL, panel)
    pygame.draw.rect(screen, view.BORDER_ACTIVE, panel, 2)
    hitboxes["deck:editor:panel"] = panel
    x = panel.x + 16
    screen.blit(view._text("NEW CARD" if editor["is_new"] else "EDIT CARD", view.TEXT, size=15, bold=True),
                (x, panel.y + 12))
    owner_ids = sim._relation_ids(draft.get("faction"))
    owner = sim._faction_label(owner_ids[0]) if owner_ids else None
    screen.blit(view._text("Owner · " + (owner or "no faction (every deck can use it)"), view.MUTED, size=11),
                (x + 120, panel.y + 16))

    totals = deck.card_totals(draft)
    preview = pygame.Rect(panel.right - PREVIEW_W - 16, panel.y + 44, PREVIEW_W - 20, TILE_H)
    preview_row = {"card_id": draft.get("id"), "card": draft, "count": 1, "missing": False,
                   "label": draft.get("pretty_name") or draft.get("name") or "Unnamed card",
                   "category": deck.card_category(draft), "totals": totals, "available": True}
    screen.blit(view._text("PREVIEW", view.MUTED, size=10, bold=True), (preview.x, preview.y - 15))
    _draw_tile(view, screen, sim, preview, preview_row)

    form_w = preview.x - x - 24

    def focused(field, entry_id=None):
        return focus == (field, entry_id)

    def label(text, lx, ly):
        screen.blit(view._text(text, view.MUTED, size=10, bold=True), (lx, ly))

    y = panel.y + 44
    label("NAME", x, y)
    _field_box(view, screen, hitboxes, "deck:editor:field:name", pygame.Rect(x, y + 14, form_w, 28),
               draft.get("pretty_name") or draft.get("name") or "", "e.g. GGO Sol Marine Tank Platoon",
               focused("name"), editor["buffer"])
    y += 52
    label("CATEGORY", x, y)
    _field_box(view, screen, hitboxes, "deck:editor:field:card_category", pygame.Rect(x, y + 14, 170, 28),
               draft.get("card_category") or "", "Category", focused("card_category"), editor["buffer"])
    chip_x = chip_left = x + 184
    chip_y = y + 4
    for category in CATEGORY_VOCAB:
        width = view._text(category, size=10).get_width() + 14
        if chip_x + width > x + form_w:
            chip_x, chip_y = chip_left, chip_y + 24
        active = draft.get("card_category") == category
        chip = pygame.Rect(chip_x, chip_y, width, 20)
        color = category_color(category)
        pygame.draw.rect(screen, _dark(color) if active else view.PANEL_ALT, chip)
        pygame.draw.rect(screen, color if active else view.BORDER, chip, 1)
        surface = view._text(category, view.TEXT if active else view.MUTED, size=10, bold=active)
        screen.blit(surface, surface.get_rect(center=chip.center))
        hitboxes[f"deck:editor:category:{category}"] = chip
        chip_x = chip.right + 5
    y = max(y + 52, chip_y + 30)

    footer_y = panel.bottom - 44
    bottom = footer_y - 28
    manpower = draft["card_manpower"]
    equipment = draft["card_equipment"]
    crew_roles = {}
    for entry in equipment:
        for role in deck.entry_crew(entry):
            if isinstance(role, dict):
                name = str(role.get("role") or "Crew")
                crew_roles[name] = crew_roles.get(name, 0) + entry["count"] * int(role.get("count", 0) or 0)
    crew_h = 20 if crew_roles else 0
    sections_top = y
    # The equipment section keeps room for its rows (half the space at most);
    # manpower gets the rest.
    equipment_need = 30 + ROW_H * max(1, len(equipment))
    manpower_room = max(ROW_H, bottom - y - 30 - crew_h - 30 - min(equipment_need - 30, (bottom - y) // 2))

    label("MANPOWER", x, y + 6)
    _small_button(view, screen, hitboxes, "deck:editor:add_personnel", "+ Personnel", x + 84, y)
    y += 30
    if not manpower:
        screen.blit(view._text("No one listed. Crew come with their vehicles; list everyone else here.",
                               view.MUTED, size=11), (x, y + 4))
        y += 24
    shown = len(manpower) if len(manpower) * ROW_H <= manpower_room else max(0, manpower_room // ROW_H - 1)
    for entry in manpower[:shown]:
        _draw_manpower_row(view, screen, hitboxes, editor, entry, pygame.Rect(x, y, form_w, 30), focused)
        y += ROW_H
    if shown < len(manpower):
        screen.blit(view._text(f"+ {len(manpower) - shown} more people entries; remove some to see them.",
                               view.MUTED, size=11), (x, y + 6))
        y += ROW_H
    if crew_roles:
        text = f"+ {totals['crew']} crew from vehicles: " + ", ".join(
            f"{name} {count}" for name, count in crew_roles.items())
        screen.blit(view._text(view._fit_design_text(text, form_w, 11), view.MUTED, size=11), (x, y))
        y += crew_h
    y += 8

    label("EQUIPMENT", x, y + 6)
    add_vehicle = _small_button(view, screen, hitboxes, "deck:editor:add_vehicle", "+ Vehicle", x + 84, y)
    _small_button(view, screen, hitboxes, "deck:editor:add_item", "+ Item", add_vehicle.right + 6, y)
    y += 30
    if not equipment:
        screen.blit(view._text("None. Tanks, transports and weapons go here; a vehicle brings its crew.",
                               view.MUTED, size=11), (x, y + 4))
    for index, entry in enumerate(equipment):
        if y + ROW_H > bottom and index < len(equipment):
            screen.blit(view._text(f"+ {len(equipment) - index} more equipment entries", view.MUTED, size=11),
                        (x, y + 2))
            break
        _draw_equipment_row(view, screen, sim, hitboxes, editor, entry, pygame.Rect(x, y, form_w, 30), focused)
        y += ROW_H

    summary = f"One copy takes · {totals['people']} people"
    if totals["crew"]:
        summary += f" ({totals['personnel']} listed + {totals['crew']} crew)"
    summary += f" · {_plural(totals['vehicles'], 'vehicle')} · {_plural(totals['items'], 'item')}"
    screen.blit(view._text(view._fit_design_text(summary, form_w, 11), view.TEXT, size=11, bold=True),
                (x, footer_y - 20))
    save = _small_button(view, screen, hitboxes, "deck:editor:save", "Save card", panel.right - 196, footer_y + 8,
                         96, height=26)
    _small_button(view, screen, hitboxes, "deck:editor:cancel", "Cancel", save.right + 8, footer_y + 8, 72,
                  active=False, height=26)
    hint = editor["status"] or "Enter saves a field · Tab moves on · Esc steps back"
    screen.blit(view._text(view._fit_design_text(hint, save.x - x - 12, 11), ERROR if editor["status"] else view.MUTED,
                           size=11), (x, footer_y + 14))

    if editor["picker"]:
        _draw_picker(view, screen, sim, pygame.Rect(x, sections_top - 4, form_w, bottom - sections_top), hitboxes)


def _count_controls(view, screen, hitboxes, editor, entry, cx, y, focused):
    entry_id = entry["id"]
    _small_button(view, screen, hitboxes, f"deck:editor:entry_minus:{entry_id}", "-", cx, y + 4, 22)
    _field_box(view, screen, hitboxes, f"deck:editor:entry:{entry_id}:count",
               pygame.Rect(cx + 25, y + 3, 40, 24), str(entry["count"]), "1", focused("count", entry_id),
               editor["buffer"])
    _small_button(view, screen, hitboxes, f"deck:editor:entry_plus:{entry_id}", "+", cx + 68, y + 4, 22)
    return cx + 98


def _draw_manpower_row(view, screen, hitboxes, editor, entry, rowrect, focused):
    entry_id = entry["id"]
    x, y = rowrect.x, rowrect.y
    pygame.draw.rect(screen, view.PANEL_ALT, rowrect)
    pygame.draw.rect(screen, view.BORDER, rowrect, 1)
    view._draw_person_silhouette(screen, x + 7, y + 4, scale=0.5, command=entry.get("is_command"))
    _field_box(view, screen, hitboxes, f"deck:editor:entry:{entry_id}:role",
               pygame.Rect(x + 30, y + 3, 190, 24), entry["role"], "Role", focused("role", entry_id), editor["buffer"])
    _field_box(view, screen, hitboxes, f"deck:editor:entry:{entry_id}:rank",
               pygame.Rect(x + 226, y + 3, 110, 24), entry.get("rank") or "", "Rank", focused("rank", entry_id),
               editor["buffer"])
    cx = _count_controls(view, screen, hitboxes, editor, entry, x + 342, y, focused)
    _small_button(view, screen, hitboxes, f"deck:editor:entry_command:{entry_id}", "Lead", cx, y + 4, 40,
                  active=bool(entry.get("is_command")))
    _small_button(view, screen, hitboxes, f"deck:editor:entry_remove:{entry_id}", "×", rowrect.right - 27, y + 4, 22)


def _draw_equipment_row(view, screen, sim, hitboxes, editor, entry, rowrect, focused):
    deck = sim.deck
    x, y = rowrect.x, rowrect.y
    pygame.draw.rect(screen, view.PANEL_ALT, rowrect)
    pygame.draw.rect(screen, view.BORDER, rowrect, 1)
    if entry["kind"] == "vehicle":
        _vehicle_glyph(screen, x + 4, y + 4)
    else:
        _item_glyph(screen, x + 4, y + 5)
    name = view._fit_design_text(deck.equipment_label(entry), 300, 13)
    screen.blit(view._text(name, view.TEXT, size=13), (x + 32, y + 7))
    cx = _count_controls(view, screen, hitboxes, editor, entry, x + 342, y, focused)
    right = rowrect.right - 32
    if entry["kind"] == "vehicle":
        size = deck.entry_crew_size(entry)
        text, color = (f"crew {size} each", view.MUTED) if size else ("this vehicle lists no crew", ERROR)
    else:
        item = deck._entity(entry["item"])
        text, color = (deck.item_detail(item) if isinstance(item, dict) else "not in the ontology"), view.MUTED
    screen.blit(view._text(view._fit_design_text(text, right - cx - 6, 11), color, size=11), (cx, y + 8))
    _small_button(view, screen, hitboxes, f"deck:editor:entry_remove:{entry['id']}", "×", rowrect.right - 27, y + 4, 22)


def _draw_picker(view, screen, sim, box, hitboxes):
    deck = sim.deck
    kind = deck.editor["picker"]
    pygame.draw.rect(screen, view.PANEL, box)
    pygame.draw.rect(screen, view.BORDER_ACTIVE, box, 2)
    hitboxes["deck:editor:picker:panel"] = box
    title = "ADD VEHICLE" if kind == "vehicle" else "ADD ITEM"
    screen.blit(view._text(f"{title}  ·  type to search", view.TEXT, size=13, bold=True), (box.x + 12, box.y + 10))
    _small_button(view, screen, hitboxes, "deck:editor:picker:close", "Close", box.right - 66, box.y + 7, 54)
    query = pygame.Rect(box.x + 12, box.y + 36, box.width - 24, 26)
    _field_box(view, screen, {}, "", query, "", "Search vehicles…" if kind == "vehicle" else "Search items…", True,
               deck.editor["picker_query"])
    y = query.bottom + 8
    options = deck.picker_options()
    for index, option in enumerate(options):
        row = pygame.Rect(box.x + 12, y, box.width - 24, 26)
        if row.bottom > box.bottom - 8:
            screen.blit(view._text(f"{len(options) - index} more · narrow the search", view.MUTED, size=11),
                        (row.x, row.y + 4))
            break
        pygame.draw.rect(screen, view.PANEL_ALT, row)
        pygame.draw.rect(screen, view.BORDER, row, 1)
        screen.blit(view._text(view._fit_design_text(option["label"], row.width - 190, 12), view.TEXT, size=12),
                    (row.x + 8, row.y + 5))
        detail = view._text(view._fit_design_text(option["detail"], 170, 11), ERROR if option["warn"] else view.MUTED,
                            size=11)
        screen.blit(detail, (row.right - 8 - detail.get_width(), row.y + 6))
        hitboxes[f"deck:editor:picker:pick:{option['id']}"] = row
        y += 29
    if not options:
        noun = "vehicles" if kind == "vehicle" else "items"
        screen.blit(view._text(f"No {noun} in service in {sim.year} match.", view.MUTED, size=12), (box.x + 12, y + 4))


def _draw_people(view, screen, sim, formation_id, panel, hitboxes):
    """The deck's people by role: saved people, representatives, then the crowd."""
    deck = sim.deck
    fielding = deck.fielding
    pygame.draw.rect(screen, view.PANEL, panel)
    pygame.draw.rect(screen, view.BORDER, panel, 1)
    hitboxes["deck:people:panel"] = panel
    screen.blit(view._text("PEOPLE", view.TEXT, size=13, bold=True), (panel.x + 12, panel.y + 11))
    roster = deck.people.roster(formation_id)
    held = sum(row["held"] for row in roster)
    if not fielding.draws(formation_id):
        line = "A plan: nobody is drawn."
    else:
        pop_id = fielding.manpower_pop_id(formation_id)
        line = f"{held:,} held" + (f" from {fielding.label(pop_id)}" if pop_id else ", no manpower pool")
    screen.blit(view._text(view._fit_design_text(line, panel.width - 24, 11), view.MUTED, size=11),
                (panel.x + 12, panel.y + 31))

    chosen = None
    for row in roster:
        for person in row["saved"] + row["representatives"]:
            if person.get("id") == deck.people_selected:
                chosen = (person, row)
    detail_h = PERSON_DETAIL_H if chosen else 40
    listing = pygame.Rect(panel.x + 6, panel.y + 52, panel.width - 12, panel.height - 58 - detail_h)
    hitboxes["deck:people:list"] = listing
    clip = screen.get_clip()
    screen.set_clip(listing)
    y = start = listing.y - deck.people_scroll

    def line_row(key, text, color, bold=False, tag=None, tag_color=None):
        nonlocal y
        rect = pygame.Rect(listing.x + 4, y, listing.width - 8, PEOPLE_LINE)
        y += PEOPLE_LINE
        if rect.bottom < listing.y or rect.y > listing.bottom:
            return
        if key and key == f"deck:people:pick:{deck.people_selected}":
            pygame.draw.rect(screen, view.PANEL_ALT, rect)
            pygame.draw.rect(screen, view.BORDER_ACTIVE, rect, 1)
        tag_w = 0
        if tag:
            surface = view._text(tag, tag_color or view.MUTED, size=10, bold=True)
            tag_w = surface.get_width() + 8
            screen.blit(surface, (rect.right - 4 - surface.get_width(), rect.y + 3))
        screen.blit(view._text(view._fit_design_text(text, rect.width - 22 - tag_w, 11), color, size=11, bold=bold),
                    (rect.x + 16, rect.y + 2))
        if key:
            hitboxes[key] = rect.clip(listing)

    year = int(getattr(sim, "year", 2400) or 2400)
    for row in roster:
        rect = pygame.Rect(listing.x + 4, y, listing.width - 8, 20)
        if rect.bottom >= listing.y and rect.y <= listing.bottom:
            count_surface = view._text(f"×{row['held']:,}", view.ACCENT, size=11, bold=True)
            right = rect.right - 2
            if row.get("short"):
                short_surface = view._text(f"  short {row['short']:,}", ERROR, size=11, bold=True)
                right -= short_surface.get_width()
                screen.blit(short_surface, (right, rect.y + 3))
            right -= count_surface.get_width()
            screen.blit(count_surface, (right, rect.y + 3))
            title = row["role"] + (f" · {row['rank']}" if row["rank"] else "")
            screen.blit(view._text(view._fit_design_text(title, right - rect.x - 10, 12),
                                   view.TEXT, size=12, bold=True), (rect.x, rect.y + 2))
        y += 22
        for person in row["saved"]:
            name = person.get("pretty_name") or person.get("name") or person["id"]
            if person.get("start_year") is not None:
                name += f", {year - int(person['start_year'])}"
            line_row(f"deck:people:pick:{person['id']}", name, view.TEXT, bold=True, tag="saved",
                     tag_color=view.ACCENT)
        for person in row["representatives"]:
            line_row(f"deck:people:pick:{person['id']}", f"{person['name']}, {year - int(person['start_year'])}",
                     view.TEXT)
        if row["crowd"]:
            line_row(None, f"and {row['crowd']:,} more", view.MUTED)
        y += 8
    if not roster:
        empty = "No one yet: the deck holds no cards." if fielding.draws(formation_id) else "No cards in the plan."
        screen.blit(view._text(empty, view.MUTED, size=11), (listing.x + 8, listing.y + 4))
    deck.content_heights["people"] = y - start
    screen.set_clip(clip)

    box = pygame.Rect(panel.x + 6, listing.bottom + 6, panel.width - 12, detail_h - 6)
    pygame.draw.rect(screen, (11, 18, 25), box)
    pygame.draw.rect(screen, view.BORDER, box, 1)
    if chosen is None:
        if roster:
            screen.blit(view._text("Click a name to see them.", view.MUTED, size=10), (box.x + 8, box.y + 8))
        return
    _draw_person_detail(view, screen, sim, chosen, box, hitboxes)


def _draw_person_detail(view, screen, sim, chosen, box, hitboxes):
    deck = sim.deck
    person, row = chosen
    saved = not str(person.get("id", "")).startswith("runtime_")
    x, y = box.x + 8, box.y + 6
    name = person.get("pretty_name") or person.get("name") or person.get("id")
    screen.blit(view._text(view._fit_design_text(name, box.width - 16, 13), view.TEXT, size=13, bold=True), (x, y))
    year = int(getattr(sim, "year", 2400) or 2400)
    lines = []
    born = person.get("start_year")
    if born is not None:
        sex = str(person.get("sex") or "").capitalize()
        lines.append(" · ".join(part for part in (sex, f"{year - int(born)} (born {int(born)})") if part))
    rank = person.get("service_rank")
    lines.append(f"{rank} · {row['role']}" if rank else row["role"])
    if person.get("source_pop"):
        lines.append(f"From {deck.fielding.label(person['source_pop'])}")
    leanings = deck.people.leanings(person)
    if leanings:
        lines.append("Leans " + ", ".join(LEANING_WORDS[axis][0 if value > 0.5 else 1] for axis, value in leanings))
    lines.append("Saved in the ontology." if saved else "A representative: not stored.")
    for index, text in enumerate(lines):
        color = view.ACCENT if index == len(lines) - 1 and saved else view.MUTED
        screen.blit(view._text(view._fit_design_text(text, box.width - 16, 11), color, size=11),
                    (x, y + 20 + index * 16))
    button_y = box.bottom - 28
    if saved:
        _small_button(view, screen, hitboxes, f"deck:people:open:{person['id']}", "Open person", x, button_y)
        _small_button(view, screen, hitboxes, f"deck:people:edit:{person['id']}", "Person Editor", x + 96, button_y)
    else:
        _small_button(view, screen, hitboxes, f"deck:people:save:{person['id']}", "Save as person", x, button_y)
