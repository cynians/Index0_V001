# Species Editor v001

## Purpose

Species Editor is the visual calibration workspace between a new plant Species
Card and its organ assets. It keeps a temporary reference photograph beside a
deterministic mature preview so an authored plant can be adjusted without
switching repeatedly between unrelated screens.

The editor deliberately covers intrinsic plant form only. Day/night state,
seasonal context, weather and local soil-water balance remain outside this pass
until their shared space/map/species environment model is ready.

## Range semantics

Not every plant value has the same epistemic status:

- Direct observations and established classifications remain categorical
  dropdowns: axis continuity, branching rhythm and timing, lateral-axis
  orientation, flowering position, leaf arrangement, leaf structure, and so
  on.
- Measurable quantities such as mature height can use literature-backed natural
  ranges in the Species Card.
- Normalized 0..1 controls such as branch droop, crown openness and apical
  control are simulation calibration coordinates. A botanical source can
  constrain their interpretation but usually cannot supply the exact number.

The eight continuous architecture controls therefore store a
`min / typical / max` envelope plus `status` and optional `source`. The mature
preview uses `typical`. Values adjusted in this editor are marked
`provisional_visual_calibration` with source `species_editor_visual_fit`, so
they cannot be mistaken for measured field data. Legacy scalar values remain
readable as point ranges.

## Screen and workflow

The Species Card toolbelt exposes **Species Editor** above **Species Sim Lab**.
Opening it selects the permanent Species Sim editor tab for the current plant.

1. **Reference photo** — paste an image or copied local image path. It remains
   in memory only and is never written to the species record.
2. **Mature preview** — one deterministic mature snapshot is rendered from the
   side and from above. Minimum, typical and maximum modes resolve every
   architecture envelope to that endpoint. Variation mode displays four
   seeded individuals sampled reproducibly inside the ranges at a shared scale.
3. **Species fields** — type to filter every plant field. Categorical fields
   cycle through ontology choices; continuous architecture fields expose
   minimum, typical and maximum handles. Fields requiring richer structures
   point back to the full Species Card.

Save persists the working values to the live ontology entity. Revert restores
the last saved values while retaining the temporary reference image.

The reference can be overlaid on the side view with adjustable opacity, scale
and position. Silhouette mode separates pixels from the averaged corner
background to provide a quick shape-matching aid; it is intentionally a local
visual tool rather than semantic image analysis.

Fields are grouped into Crown, Branches, Shoots, Leaves and Reproduction. A
green marker identifies fields consumed by the current plant preview, and the
list can hide non-visual Species Card fields. Range rows expose their confidence
as measured, literature-constrained, visual fit, or unverified. Undo and redo
retain thirty working-entity states and operate before persistence.

## Pixel-module handoff

Leaf, stem, flower, branch, root and fruit buttons use the existing Species Card
asset workflow and open the matching reusable module in Pixel Studio. The
important first-path actions—leaf, stem and flower—are always visible above the
field list. Returning to Species Sim recreates the plant preview using the
species' current asset references.
The open editor also pulls newly saved module references from the live Species
Card before rebuilding its mature preview.
Pixel image caches probe file modification times at a bounded interval, so
overwriting an existing module path invalidates both the sprite and whole-plant
frame caches without performing filesystem checks for every leaf.

## Performance refinement

The baseline silver-birch editor at 1680×1000 rebuilt the mature tree for every
drag event. A 20-frame measurement recorded 12.77 ms steady-state frames and
1,040.64 ms per dragged update. The refined path:

- defers snapshot regeneration while a range handle is held and rebuilds once
  on release;
- uses LOD 2 for the focused calibration canvas and LOD 1 for the four-plant
  variation grid, while leaving saved/exported snapshots untouched;
- caps represented foliage samples per cohort at four in the main editor and
  two in variation thumbnails;
- reuses fonts, fitted references, plant frames and mode-specific simulations.

The same fixed-seed measurement now records 6.17 ms steady state, 6.12 ms per
drag frame and 267.80 ms for the single LOD-2 release rebuild. These values are local
diagnostic timings, not cross-machine targets.

## Reproducible preview

The editor preview uses seed 303 and authored mature age (LOD 2 focused, LOD 1
variation). Render the typical and four-individual variation screens with:

`py -m tools.render_species_editor_preview`

The resulting image is written to
`artifacts/species_editor_v001/species_editor_birch.png`.
The variation render is
`artifacts/species_editor_v001/species_editor_birch_variation.png`.
