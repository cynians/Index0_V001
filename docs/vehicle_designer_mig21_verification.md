# MiG-21 Vehicle Designer verification

## Purpose

This is an end-to-end visual verification vehicle for the Specification → Hull → Components → Details → Liveries workflow. It is an approximate editor model of a Mikoyan-Gurevich MiG-21F-13, not an archival-scale reconstruction.

Reference: [Smithsonian National Air and Space Museum — MiG-21F-13 Fishbed-C](https://airandspace.si.edu/collection-objects/mikoyan-gurevich-mig-21f-13-fishbed-c/nasm_A19930354000).

## Creation process

1. Create the `vehicles` entity `veh_mikoyan_gurevich_mig_21_f13` with aircraft classification and an approximate 14.7 m × 7.15 m × 4.1 m envelope.
2. Enter sparse characteristic rows for mass, speed, crew, powerplant, and construction, plus design requirements for interception, inlet geometry, the delta planform, and runway operation.
3. Record the semi-monocoque fuselage and integral delta wing as structural features. They satisfy structural requirements but never appear in the component catalog.
4. Draw the side silhouette around a slender circular fuselage, pointed intake nose, raised canopy, and tall swept fin. Author both left and right views.
5. Draw the top and bottom silhouettes from a narrow fuselage, broad delta wing, and small tailplane.
6. Draw distinct front and rear silhouettes from the fuselage section, thin dihedral wing plane, and vertical fin. The polygon rasterizer uses signed edge slopes so swept shapes render correctly in every direction.
7. Inspect the assembled projection, which intersects the Top, Side, and Front silhouette planes like slotted foam-board pieces.
8. Place only installable systems—the turbojet, fuel cells, cockpit, avionics, and landing gear—using shared x/y/z coordinates. Placement clamps the full component footprint inside the vehicle envelope.
9. Paint structural panel stations, centerlines, canopy glazing, and intake details. Verify the dimmed opposite-side projection and the deliberately faint component overlay.
10. Paint the `Soviet Natural Metal · Red 21` livery on the 36 px/m micro-pixel raster with alternating metal panels, a red identification band, and dark intake treatment. Verify that the high-resolution paint is clipped to the resampled hull mask.
11. Persist specification rows, requirements, structural features, silhouettes, component coordinates, details, and livery layers to the authoritative ontology quadstore.
12. Render all five stages through the project’s `VehicleRenderer` and retain the images under `artifacts/vehicle_designer/mig21/`.

## Reproduction

From the project root, run:

```powershell
py tools/create_mig21_vehicle_design.py
```

The script upserts the same stable vehicle ID, so rerunning it refreshes the verification entity rather than creating duplicates.

## Known limits

The six silhouettes constrain a visual hull, but do not uniquely describe concavities, intake depth, undercuts, or surface topology. The assembled projection is therefore a construction aid, not a reconstructed solid mesh.

The numerical sample fields are visualization inputs, not an authoritative technical data sheet. Their source and precision can be refined independently in the ontology.
