# Vehicle Designer visual system v0.1

## Drafting language

Hull geometry is stored as a filled binary mask but presented as a technical drawing. The renderer derives a live contour from exposed mask-cell edges, overlays physical meter subdivisions, and adds horizontal and vertical construction centerlines. A translucent cyan drafting-film wash preserves immediate draw feedback without turning the hull into a solid-colored sprite.

Opposite-view inheritance uses the same contour treatment in muted grey and is explicitly labelled as a mirrored reference. Component and detail stages retain the physical grid so coordinates remain visually comparable throughout the workflow.

## Livery micro-pixels

Livery rasters use 36 pixels per metre, compared with 9 pixels per metre for the structural hull: four times the linear resolution and sixteen times the editable cell count. Each axis is capped at 1,024 cells to bound memory use on exceptionally large vehicles.

The livery mask is resampled from the effective hull silhouette at livery resolution. Painting, erasing, rendering, copying, pasting, and dimension changes all use this high-resolution raster. Paint outside the resampled silhouette is rejected by the controller and discarded again by the renderer, providing both authoring-time and display-time clipping.

The renderer composes the high-resolution layer into a cached RGBA surface rather than issuing one draw call per micro-pixel every frame. Cache invalidation follows the paint revision, active livery, view, and layer dimensions.

## Interface treatment

The designer uses a restrained blueprint palette, stage-progress chips, rounded cyan-accent controls, selected-stage styling, focused canvas dimension labels, a silhouette-lock status badge, and quieter component ghosts in paint stages. Livery cards distinguish the active surface and label the layer as micro-pixel authored.

## Shared Pixel Studio workflow

Details and Liveries now open the same full-screen Pixel Studio used by Illustration entries. The vehicle workflow therefore inherits the normal brush, eraser, eyedropper, flood fill, geometric shape tools, color controls, layers, layer visibility, undo/redo, mirror drawing, zoom, and pan behavior instead of maintaining a second reduced paint interface.

The handoff is a six-view embedded document. Numbered tabs switch between left, right, front, rear, top, and bottom while retaining independent canvas size, layers, undo history, zoom, and pan for each projection. The first editable layer is returned to the vehicle, while the mirrored opposite-side artwork and projected component boxes are supplied as locked, individually toggleable reference layers. Component references use 18% opacity so they remain available without dominating final artwork.

The hull silhouette is not an ordinary layer. It is passed into Pixel Studio as a hard external mask, drawn as a cyan technical boundary, checked by brushes, fills, mirrored strokes, and shape tools, and checked again when the document is returned to the vehicle. This means hiding or deleting a layer can never disable silhouette clipping. Pressing **Finish** applies all visible non-reference layers to the selected detail or livery raster, persists the vehicle, and returns to Component Coordinates. Closing twice discards unsaved editor changes and also returns to Component Coordinates.

## Verification

The MiG-21 verification entity is regenerated through the real `VehicleRenderer`. Focused tests assert the four-times livery dimensions, reject paint outside the high-resolution silhouette mask, exercise the embedded Pixel Studio write-back, and render the full-screen editor through the normal app UI manager. The combined vehicle and Illustration regression suite also verifies that the original standalone Pixel Studio save/reopen workflow remains intact.
