# Highest-detail landscape reference

`highest_lod_example_map` now covers **6 × 6 km / 36 km²** of the Dosewallips
valley, estuary/wetlands and Hood Canal. Its ontology card opens Map or Biosphere.
Restart an already-running app to load the revised recipe.

This is an aggregate tiled highest-detail target with Local/LOD3 footprint
context, **not a 6km Survey patch**. Global LOD contracts remain unchanged.
Retained 6000 × 6000 numeric terrain samples have **1m export spacing**, not
invented 10cm measurements. A 1001 × 1001 / 6m overview supports landscape
display and derived fields; the shared substrate samples native tiles lazily,
including cross-tile interpolation. `reference_window_entity()` exposes
bounded 1–700m native-detail windows in the same physical coordinates.

Sources retained with request metadata/catalogues and SHA-256 checksums:

- [USGS 3DEP](https://elevation.nationalmap.gov/arcgis/rest/services/3DEPElevation/ImageServer):
  numeric elevation mosaic, EPSG:32610, NAVD88. Native 1m projects are catalogued;
  the service is multiresolution, so export spacing alone is not an accuracy claim.
- [USGS NAIP Plus](https://imagery.nationalmap.gov/arcgis/rest/services/USGSNAIPPlus/ImageServer):
  georeferenced aerial reference exported at 3m. Includes canopy/buildings;
  it is not simulated vegetation. Imagery, terrain and land-cover dates differ.
- [NOAA C-CAP](https://coast.noaa.gov/digitalcoast/data/ccapregional.html):
  30m mapped land-cover classes; nearest 10m export adds no measured detail.
- [USFWS NWI](https://www.fws.gov/program/national-wetlands-inventory/web-mapping-services):
  95 mapped wetland/water features, including 57 riverine polygons.
- [Daymet](https://daymet.ornl.gov/web_services): nearest 1km station-interpolated
  cell, 1991–2020 normals. Approximately 1602mm/year, summer-dry Csb.

Local temperature uses an **illustrative 6.5K/km lapse rate**. Exposure and
habitat wetness are derived proxies, not measured fine-scale climate/soil.
Marine NoData stays unknown; the zero-height rendering plane is **not seabed
or local sea level**. Depth/discharge, tides, salinity, soil profiles and natural
species composition remain unknown. Inspector samples identify runtime defaults.
Terrestrial plants are blocked from mapped open water and unknown terrain.
The old European demo populations were removed, with a recoverable v1 snapshot.

Reproduction: acquire `--metadata-only`, then `--tiles`, `--wetlands-only`,
`--imagery-only` using `tools.acquire_highest_lod_reference`. Existing manifests
are protected. `tools.author_highest_lod_example_map --revise` changes only the
recognized old target and its overlay, preserving unrelated fields. Repeat runs
preserve edits; million-cell grids are generated lazily, not persisted as triples.
`tools.render_highest_lod_example_map` writes production-renderer previews and
metrics to `artifacts/highest_lod_example_map_v2`; v1 previews are retained.

The first abstraction experiment now reduces this reference to a 201 × 201,
30m LOD3 parent containing broad elevation, landscape patches, mapped corridors,
boundary portals, climate context and class-specific residual statistics. Three
6m children reconstruct the parent with different bounded detail. This proves
the compact contract and deterministic reconstruction path, but not the entire
planet-to-local chain: the mapped river source still resolves as 35 disconnected
components, so hydrological graph reconciliation is the next important step.
No procedural parent lineage or generator-to-target match is claimed yet.

A separate reference-free run now proves the forward route. Seed `20260915`
used the production generator through 1000km LOD1, 100km LOD2 and 6km LOD3,
then produced three 6m children from the generated 30m abstraction. It selected
a 6088–6153m, cold/dry ET plateau rather than copying this coast. The result is
valid lineage, but its 96 small lakes, 79% endorheic fraction, low runoff and
zero rivers identify hydrological persistence and target-selection checks as
the next realism work. The retained run is `artifacts/reference_free_landscape_v1.i0wg`.
