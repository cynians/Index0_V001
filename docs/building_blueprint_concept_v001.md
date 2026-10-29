# Building Blueprint Concept v001

Status: concept agreed 2026-09-23; slices 1–5 implemented the same day — see
§8 for what shipped, where it lives, and what is still open.

## 1. Goal

A building is authored once as a **blueprint** and then placed any number of
times, in any simulation context that has a map. Authoring has two stages:

1. **Grundriss** — the floorplan: geometry, dimensions, storeys, openings, and
   the derived floor space.
2. **Design** — surfacing the geometry with materials and Pixel Studio
   artwork, producing a 3D dataspace carried by 2D assets.

Out of scope for now: vehicles (they keep their own designer), construction as
a process (cost, labour, time), and procedural/placeholder building
generation. The data below is shaped so those can be added without migration.

## 2. Blueprint vs placed building

| | Blueprint | Placed building |
|---|---|---|
| What it is | A reusable building type (like a species) | A `location_class: building` location entity |
| Holds | Geometry, surfaces, materials, fixed items, artwork | Position, rotation, parent location, owner, condition |
| Reference | — | `building_blueprint: <blueprint id>` |
| Ontology footprint | One entity per blueprint version | One entity per placed building |

Heavy payload (wall graph, surfaces, pixel layers) lives in a fingerprinted
asset file, `assets/buildings/<blueprint_id>.json.gz`, following the plant
blueprint precedent (`assets/plants/`, `PlantBlueprint`). The ontology entity
carries the semantic summary: name, storey count, gross/net floor area, room
list, materials used, fixed items, predecessor/successor.

### 2.1 Versioning — placed buildings never change retroactively

Editing a blueprint affects only buildings placed *afterwards*. Existing
buildings keep the version they were placed from.

- Each blueprint version is its own entity: *Modular Housing Mk Ia*,
  *Modular Housing Mk Ib*, linked by `predecessor` / `successor` (same
  vocabulary as the technology timeline).
- A blueprint is **editable** until its first placement, then **released**
  (locked). Editing a released blueprint forks a new version entity; the
  placement tools default to the newest version.
- A placed building references the exact version id, so rendering and
  simulation of an existing Mk Ia building are stable forever.

### 2.2 Rooms and fixtures stay inside the blueprint

A city must not create millions of room entities. Rooms and fixed items are
defined once in the blueprint with stable local keys and are addressed on a
placed building as:

```
<building_id>#room:<room_key>
<building_id>#fixture:<fixture_key>
```

A real ontology entity is created only when something needs to refer to it:
an ownership record, a resident, a stored item, damage state, a quest. The
materialised entity records its origin (`blueprint_room_key`) so it stays tied
to the geometry.

Existing `room` location entities created by today's BuildingSimulation stay
valid; they become the "materialised" form.

## 3. Stage 1 — Grundriss

### 3.1 Authoring: rooms first, walls derived

Adapts the existing polygon drafting (`MapSimulation` spatial-feature drafts,
already narrowed to rooms by `BuildingSimulation`).

- **Snap grid** by default (default pitch 0.5 m, adjustable), with a modifier
  key for **free placement**. Snapping also targets existing vertices and
  edges so adjacent rooms share edges exactly.
- **Live measurement**: while drawing, the segment under construction shows
  its length in metres; closed edges show their length on hover; the draft
  shows running area once three points exist.
- Edges shared by two rooms become **interior walls**; edges on the outline
  become **exterior walls**. Walls carry a wall class (thickness, height) with
  a blueprint default and per-wall override.
- **Openings** are placed on wall edges. This generalises the existing
  person-sim `openings` (`side`/`center`/`width`) to arbitrary walls:

```json
{"key": "o3", "wall": "w12", "offset_m": 1.2, "width_m": 0.9,
 "sill_m": 0.0, "head_m": 2.1, "opening_class": "door"}
```

### 3.2 Storeys and vertical features

- `levels`: ordered list with `elevation_m` and `ceiling_height_m`.
- Each room and wall belongs to a level. A level may copy the outline of the
  one below as its starting point.
- Stairs / lift / ladder: a vertical feature spanning two or more levels with
  a footprint on each.
- Roof: parameters only in v001 (`flat | gable | hip | shed`, pitch, ridge
  direction, overhang).

### 3.3 Derived, never authored

| Metric | Source |
|---|---|
| Footprint area | Ground-level outline |
| Gross floor area (per level, total) | Level outlines |
| Net usable area (per room, total) | Room polygon minus half wall thickness per edge |
| Perimeter, height, enclosed volume | Outline + levels + roof |

These are written to the blueprint entity summary on save so other systems
(site aggregation, market, logistics) can read them without loading geometry.

### 3.4 Fixed items

A blueprint may include fixed items — built-ins that come with every placed
building (kitchen sink, oven, bunk beds). Function continues to come from
items, never from a room label: a room is a kitchen because it contains a
sink and an oven.

```json
{"key": "f1", "item": "item_kitchen_sink", "level": 0, "room": "r2",
 "x_m": 3.4, "y_m": 0.3, "rotation_deg": 180}
```

Loose and later-installed items belong to the placed building, not the
blueprint.

## 4. Stage 2 — Design

### 4.1 Surfaces are derived from geometry

Every wall face (inner and outer), floor, ceiling, and roof plane becomes a
**surface**: a flat 2D rectangle/polygon with a known size in metres and its
openings cut out. The geometry positions the surfaces in 3D; each surface's
artwork is 2D. This is the plant model-space contract applied to buildings
(`dimensions: 3, asset_dimension: 2, projection: orthographic`).

### 4.2 Materials carry repeating textures

Same mechanism as tree bark: a species points at a texture-mode Pixel Studio
document through `plant_bark_texture_set_ref`, and runtime tiles it with
seed-shuffled character tiles (`world/texture_sets.py`,
`docs/texture_set_representation_v001.md`).

- Material entities gain `material_texture_set_ref` — a seamless base tile
  plus sparse character tiles, authored in Pixel Studio texture mode.
- Each surface references a **material** (brick, timber, concrete, sheet
  steel). Its look comes from the material's texture set, tiled at the global
  building pixel density, so a 12 m wall needs one small authored tile.
- Keeping the material semantic (not just a picture) means later construction
  cost, weathering, and fire/damage can read it directly.
- Surface-level overrides: tint, a different material, and **detail layers**
  (signage, trim, stains) painted on top of the tiled material.

### 4.3 Views needed now

Only the views required for design are in scope:

- **Top-down** — plan view; floors and roofs.
- **Face-on elevations** — N / E / S / W façades per level, plus interior
  wall faces per room.

Façade views open in Pixel Studio through `open_embedded` (multi-view + hard
masks, the route the vehicle designer uses). The mask is the surface outline
minus openings, so detail painting cannot leak into windows.

Later, per simulation context and not part of this concept's first slices:
isometric(-ish) in Biosphere, top-down when flying over in Map, and
textured interiors in person view. All are projections of the same
blueprint data.

### 4.4 Pixel density

One fixed density for all buildings (proposal: 16 px/m) so buildings, items,
and people share scale. Stored on the blueprint's `model_space` so it can be
revised per schema version.

### 4.5 Known gap

`PixelArtEditorUI.send_to_companion` only supports single-view illustrations.
Companion editing of façades needs the embedded multi-view path extended.

## 5. Placing blueprints in simulation contexts

A placed building stores `building_blueprint`, `position`, `rotation_deg`,
and `parent_location`. Each context reads the blueprint at its own level of
detail:

| Context | Representation |
|---|---|
| Planet / region map | Point, or footprint outline at high zoom |
| Site map, person sim | Footprint, walls, openings, rooms, fixtures; pathing through openings |
| Biosphere | Footprint as occupied/sealed ground (isometric look later) |
| Design / close view | Textured surfaces |

## 6. Slices

1. **Blueprint + single-level Grundriss.** Blueprint entity and asset file;
   snap/free polygon drafting with live lengths and area; derived walls;
   openings; derived areas; fixed items.
2. **Placement.** Place a blueprint version on a site map with rotation;
   person sim reads placed buildings instead of hand-authored bounds.
   Validation: rebuild the four lumber-compound buildings (barracks, kitchen,
   warehouse, factory hall) as blueprints.
3. **Versioning.** Release-on-first-placement lock, fork to new version,
   predecessor/successor links.
4. **Storeys.** Levels, vertical features, roof parameters.
5. **Design.** Derived surfaces, `material_texture_set_ref`, material
   assignment, top-down + elevation views in Pixel Studio, detail layers.

Each slice that touches entity data also updates the matching
`tools/author_*.py` schema definitions.

## 7. Open questions

- Snap pitch default: 0.5 m, or 0.25 m for interior fitting work?
- Should detail layers be allowed to span several surfaces (a banner across a
  corner), or is one surface per layer enough?
- When a fixed item is removed from one placed building (sink ripped out),
  that building's fixture state must be materialised — confirm that this is
  the trigger for creating the fixture entity.

## 8. Implementation status (2026-09-23)

### 8.1 Where things live

| Piece | File |
|---|---|
| Data model, derivation (walls, outline, gross/net area, openings, surfaces, roof), placement transforms, entity summary | `simulations/building/blueprint_model.py` |
| Asset files `assets/buildings/<id>.json.gz` + entity merge helper | `simulations/building/blueprint_store.py` |
| Top-down and N/E/S/W facade projections (shared by renderer, picking, Pixel Studio) | `simulations/building/blueprint_views.py` |
| Material look: `display_color` or tiled `material_texture_set_ref` | `simulations/building/material_visuals.py` |
| Blueprint Designer (tools, snapping, levels, roof, materials, versioning, Pixel Studio bridge) | `simulations/building/blueprint_designer_simulation.py` |
| Blueprint Designer screen (panels, canvas, pickers) | `simulations/building/blueprint_designer_renderer.py` |
| Map ghost placement + drawing placed blueprints on site maps | `simulations/building/blueprint_placement.py` |
| Ontology: schema, location/material fields, construction materials, lumber-compound blueprints | `tools/author_building_blueprint_model.py` |

App wiring: render mode `building_blueprint` (`engine/renderer.py`); launch
mode `blueprint_designer` and action `blueprint_place_on_parent`
(`app/navigation_controller.py`); launch options (`app/launch_affordance_resolver.py`);
`MapSimulation.begin_blueprint_placement` (`simulations/map/map_simulation.py`);
Site Simulation walls (`PersonSimulation._append_blueprint_structure`);
blueprint rooms in the Building workspace (`BuildingSimulation`); Pixel Studio
texture saves link materials (`KnowledgeBrowserUI.assign_texture_set_to_parent`).

### 8.2 How to use it

1. **Create** a *Building Blueprint* from the repository template picker (id
   prefix `bp_`), then launch **Blueprint Designer** from its card.
2. **Grundriss**: *Rectangle Room* (two clicks) or *Draw Room* (click
   corners; close on the first corner, double-click, or Enter). The snap grid
   is on by default (0.1–1 m); hold **Shift** for free placement, **Ctrl** for
   45° steps. Existing corners and edges always attract the cursor, so
   neighbouring rooms share walls exactly. Every segment shows its length
   while you draw, plus the running area. *Select* drags corners (shared
   corners move together), double-click on an edge adds a corner, Delete
   removes. *Opening* places doors, double doors, open doorways, loading
   doors, and windows on the wall under the cursor with distances to both wall
   ends. *Fixed Item* places an item/component from the catalog inside a room
   (R rotates). Levels stack; *Copy outline from below* seeds an upper
   level; *Stair* links a level to the one above. Wall thickness and roof
   (flat/shed/gable/hip, pitch, ridge direction, overhang) are panel controls.
   The right panel shows footprint, gross/net floor area, height, volume, and
   per-room net area.
3. **Design**: pick Top or a facade view, set default materials per role,
   click a surface to override its material (or a room's wall finish in the
   Top/floors view). *Paint in Pixel Studio* opens the view as a canvas at
   16 px/m with the material render as a locked trace layer and painting
   clipped to the building silhouette.
4. **Save** writes the asset and merges the summary (rooms, fixtures,
   materials, floor space) into the full entity.
5. **Place on Map** saves, asks for a site (`map_coordinate_space:
   site_meters`), and opens its map with the building on the cursor (R /
   right-click rotate, Shift+R 15°, click place, Esc cancel). Placing creates
   a `building` location with `building_blueprint`, position, rotation, and a
   footprint `bounds` polygon, adds it to the site's `layout_structures`, and
   **releases** the blueprint.
6. A released blueprint opens read-only; **New Version** forks
   `…_mk_ib` (label `Mk Ia` → `Mk Ib`) with `predecessor`/`successor` links.
   Existing buildings keep the version they were placed from.

Material textures: add an Illustration in Pixel Studio *texture* mode to a
material card; saving it sets the material's `material_texture_set_ref`, and
every surface using that material tiles it (base tile plus seeded character
tiles, like bark).

### 8.3 Lumber compound

The four compound buildings are now blueprints (`bp_lumber_worker_barracks`,
`bp_lumber_attached_kitchen` with the sink and oven as fixed items,
`bp_lumber_storage_shed` with storage racks, `bp_lumber_factory_hall`), and
the building locations point at them. Site Simulation walls, doorways, and
windows come from blueprint geometry; routes are unchanged. Re-running
`tools/author_person_food_ownership_model.py` resets those buildings to plain
boxes — re-run `tools/author_building_blueprint_model.py` afterwards.

### 8.4 Decisions taken while implementing

- Detail painting is per **view** (a facade elevation or the top view), so a
  sign may span several surfaces; details are anchored in view metres.
- Rooms materialise lazily: opening a blueprint room's card in the Building
  workspace creates `<building>__room_<key>` with `blueprint_room_key`.
  Nothing else creates room entities.
- New blueprints start with no materials assigned; unassigned surfaces render
  in a neutral schematic tone rather than a guessed material.
- Openings are stored by plan centre (not by a wall key, as §3.1 sketched)
  and attach to the nearest derived wall, so they survive walls being
  re-derived; moving a corner re-projects them onto their wall.
- The Pixel Studio mask is the whole building silhouette, windows included,
  so frames and curtains can be painted (§4.3 proposed excluding openings).
- Levels are strictly stacked (`elevation_m` follows the heights below) and
  use `height_m` floor-to-floor rather than `ceiling_height_m`.

### 8.5 Still open

- Fixed-item state per placed building (removing the sink from one kitchen)
  is not materialised yet; the trigger question in §7 stands.
- Placement is started from the designer; the site map has no "Place
  Blueprint" button of its own yet.
- Person Simulation reads the ground level only; stairs and upper levels are
  not walkable yet.
- The 1 m person-sim navigation grid can miss door gaps narrower than ~1 m.
- Isometric Biosphere view, top-down flyover rendering, and interior wall
  elevations are later views over the same data.
- Per-wall thickness overrides, surface tints, curved walls, and basements
  are not modelled.
