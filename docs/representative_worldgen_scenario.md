# Representative world-generation scenario

The representative scenario is a fast regression fixture for the complete
world-generation detail chain. It uses the production generic planet
randomizer, constrains the result to the `mobile_lid` plate-tectonic branch,
then reproduces the map UI workflow: focus a geographic location, zoom into
the selected footprint, and invoke the visible-region regeneration action.

Run it with:

```text
python tools/run_representative_worldgen.py
```

The default run is:

- generic silicate-terrestrial randomization;
- randomized body size, composition, spin, and map seed with constrained
  water/volatile inputs so the fixture stays in an Earth-like diagnostic
  family;
- deterministic seeded high-relief land/tectonic focus derived from the
  production planetary heightfield (or an explicit latitude/longitude when
  supplied);
- a 1,000 km × 1,000 km LOD1 macroregion followed by a 100 km × 100 km
  LOD2 region;
- all seven nested refinement levels;
- diagnostic images for every stage, every LOD, and every rendered layer.

The active physical footprint schedule is 1,000, 100, 25, 6.25, 1.56,
0.39, and 0.10 km for LOD1 through LOD7. A future LOD8 at 0.03 km remains
reserved until a separate contract is defined. The result summary includes
the resolved center, each level's physical footprint,
sample grid, sample spacing, source bounds, and image paths. The retained
bundle includes:

The runner's fast diagnostic default is 513 x 257 LOD0 scientific support;
that is a runtime compromise, not the canonical LOD0 acceptance target. A
conformance run should use at least 1025 x 513, with 2049 x 1025 reserved for
the denser benchmark.

- planet-level stage screenshots;
- a planet-level contact sheet containing all seven layers;
- one eight-layer contact sheet for each regional detail level;
- individual layer images for every regional detail level;
- a cross-LOD overview comparing True Color, Surface Materials, Climate and
  Rivers, and Annual Precipitation.

Use `--no-render` when visual output is not needed.

## What 100 km × 100 km can test

It is large enough to exercise inheritance from planetary terrain, tectonic
relief, mountain localization, coast and drainage context, climate and
hydrology continuity, material distribution, edge fading, and the complete
descent through the current detail levels. It is small enough that a failed
level can be regenerated repeatedly while tuning the algorithms.

It does not replace a full-planet test. It cannot reliably validate global
plate topology, continent-scale climate circulation, whole-ocean routing, or
planet-wide statistical distributions. Keep one slower planetary smoke test
alongside this fixture, and use the 100 km window as the main detail-level
regression test.

The representative runner does not pass a hand-built child rectangle to the
refinement function. It configures a `MapSimulation` camera and projection
focus, calls `MapSimulation.regenerate_visible_region()`, and records both the
pre-regeneration visible bounds and the bounds returned by that UI path. The
requested physical footprint is used only to set the simulated zoom; the map
interaction code resolves the final child rectangle. The default schedule
deliberately separates the macroregion test from the 100 km regional test so
each child has a parent with meaningful geographic support.

Each regional child also records its production tectonic response and a
compact regional tectonic projection. This distinguishes a failure in the
map-selection route from a failure in the tectonic/geography detail chain.

The eight diagnostic layers are Heightmap Hillshade, True Color, Surface
Materials, Climate and Rivers, Coastal Geomorphology, Surface Temperature,
Annual Precipitation, and Chemical Weathering. True Color and Heightmap
Hillshade must consume the same current LOD heightfield; Surface Materials
must use the same heightfield partition and ontology material profiles.
