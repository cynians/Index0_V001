# Map Sim reference mode: calibrated reference-image placement

**Status: design proposal, not implemented.** Produced from a live audit of
the Earth location hierarchy (see the Earth-entries bounds pass, 2026-09-05)
plus direct inspection of `simulations/map/map_simulation.py`. Written for
hand-off: scope, data model, and phasing below, not working code.

## The problem this solves

Placing a new location today (the Elbphilharmonie case worked through in the
audit pass) means hand-computing `coords`/`bounds` from memory or a search
engine, in a `map_world` lon/lat-like coordinate space, with no visual
reference to check the result against. That's fine for a handful of
well-known capitals; it doesn't scale to "place this medieval kingdom's
extent," "reconstruct this archaeological site's footprint," or "add this
building precisely," where the source is a map image, not a coordinate.

## Why this is cheaper than it sounds

Two things already exist and don't need to be rebuilt:

1. **The coordinate space is already real-world lon/lat.** Every location
   entity's `coords`/`bounds` uses `coordinate_space: "map_world"` with
   `x = longitude`, `y = -latitude` (confirmed against Berlin, Paris, Fort
   Ross, and 177 Natural-Earth-sourced countries during the audit). A
   calibrated image doesn't need a bespoke projection — it needs an affine
   mapping from image pixels into this one already-universal space.
2. **The placement tools already exist.** `MapSimulation.__init__`
   ([map_simulation.py:210-234](../simulations/map/map_simulation.py#L210))
   already carries a full draft/editing state machine for authoring bounds:
   `is_creating_point_location` / `draft_point_location_class`,
   `is_placing_location_polygon` / `placing_location_points`,
   `is_editing_spatial_feature_polygon`, `is_creating_map_square`. These
   write `coords`/`bounds` in exactly the schema above. Reference Mode does
   **not** need a new way to draw a point or polygon — it needs a calibrated
   image sitting *underneath* those tools so the user has something to trace
   over, plus the layer-toggle affordance to show/hide it. `LAYER_LABELS`
   ([map_simulation.py:106-116](../simulations/map/map_simulation.py#L106))
   is the existing, obvious extension point for a new `"reference_overlay"`
   entry alongside `visual_map`/`heightmap`/`hydrology`/etc.

So the actual new surface area is: import an image, calibrate it into
`map_world` space, render it as a layer, and reuse everything else.

## Data model

Store a reference overlay as an `ideas` entity (`idea_class:
"map_reference"`), the same dataset and `media_path` pattern already used for
Pixel Studio illustrations (plant leaf/flower modules, etc.) — no new asset
pipeline needed:

```
{
  "_dataset": "ideas",
  "type": "idea",
  "idea_class": "map_reference",
  "id": "ref_hamburg_1890_survey",
  "media_path": "assets/map_references/....png",
  "calibration": {
    "coordinate_space": "map_world",
    "anchors": [
      {"pixel": [x_px, y_px], "lon": .., "lat": .., "source_entity_id": "loc_new_001"},
      {"pixel": [x_px, y_px], "lon": .., "lat": ..}
    ],
    "transform": "similarity",           // or "affine" once 3+ anchors exist
    "location_context": "planet_earth",  // generalizes beyond Earth later
  },
  "opacity": 0.75,
  "start_year": 1890,                    // optional: the map's own period
  "end_year": 1890
}
```

`source_entity_id` on an anchor is the key usability win: instead of typing
raw coordinates, a user can pin a corner of a historical map directly to an
*already-placed* ontology location (any of the 270 audited Earth entities
today) and let its authored `coords` supply the anchor's lon/lat. Manual
lon/lat entry remains available for anchors with no existing entity.

This is deliberately **not** a `locations` entity — it's a reference tool,
not a place — and deliberately not planet-specific in shape, matching the
stated future use ("plan maps externally before working them into the sim
directly" for non-Earth worlds).

## UI elements needed

- `LAYER_LABELS["reference_overlay"] = "Reference Overlay"` and the matching
  render path in the map renderer.
- **Import**: reuse the existing illustration/asset file-picker flow (Pixel
  Studio already has one) rather than building a new importer.
- **Calibration**: 2 draggable pin handles on the image (upgradeable to 3+
  for skew/rotation). Each pin either (a) opens a small "snap to existing
  location" search over the `locations` dataset, or (b) accepts typed
  lon/lat. A small inspector shows the computed scale/rotation and, once 3+
  pins exist, residual registration error.
- **Visibility controls**: opacity slider, show/hide toggle, and the usual
  layer-list entry.
- **Authoring bridge**: once calibrated and visible, the existing
  `is_creating_point_location`/`is_placing_location_polygon` tools work
  unmodified — they already write into the same `map_world` space the
  overlay is now registered to. No changes needed there.
- **Save/reload**: persisting the `map_reference` idea entity is what makes
  an overlay reusable across sessions (open the 1890 Hamburg survey again
  next week) — this is what turns it into the "plan maps externally" tool
  the request called out, not just a one-shot tracing aid.

## Phasing

1. **Phase 1 (smallest end-to-end slice)**: single static image import,
   2-point similarity calibration (translate + uniform scale + rotation) via
   manually-typed lon/lat anchors, opacity + visibility toggle, no
   persistence yet. Proves the registration math and the render path.
2. **Phase 2**: "snap anchor to existing location" picker (reuses the 270
   already-placed Earth entities as calibration references — the main
   day-to-day usability win); 3+ point affine for skewed/rotated scans.
3. **Phase 3**: persist/name/reload overlays as `map_reference` idea
   entities; generalize `location_context` beyond Earth for future
   fictional-planet pre-planning.
4. **Phase 4 (explicitly separate, deferred)**: a live OSM/basemap tile
   layer as an alternate, pre-registered overlay source for present-day
   work specifically. Network-dependent and orthogonal to Phases 1-3 — it's
   just another overlay source once the calibration/render/authoring-bridge
   machinery exists, not a prerequisite for it.

## Open questions for whoever implements this

1. Phase 1 scope: is 2-point similarity (no independent X/Y scale, no skew)
   acceptable for a first cut, or does even the first version need full
   affine for scanned historical atlases that are rarely square to a
   lon/lat grid?
2. Where should calibrated overlays live in the UI — a dedicated Map Sim
   panel, or folded into the existing layer-list/toolbelt chrome?
3. Asset size/format limits for imported reference images (historical scans
   and archaeological survey diagrams can be large, high-resolution files).
