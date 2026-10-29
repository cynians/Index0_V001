# Biosphere vegetation rendering

The renderer now fills continuous population patches with deterministic, jittered display instances. Local abundance controls occupancy; each species reuses its own detailed organisms' plant visuals and age. Grass and lichen use map-scale groundcover symbols. Only real representatives are selectable and feed ecology.

Display spacing is a growth-form artistic default, **not an inferred real plant density**. Rendering is capped at 2,400 extra instances, with coarse sampling for large patches and cached sprites. Large-domain overview scaling no longer forces a close-up.

Fixed established 10 × 10 m fixtures: four detailed organisms each; 153 woodland display plants and 829 grass tufts. Warmed renderer timings on this machine: approximately 11 ms woodland / 19 ms grassland. First woodland sprite generation takes roughly 1.4 seconds.

Compare `artifacts/biosphere_vegetation_v001/before.png` and `after.png`; regenerate with `py -3.14 -m tools.render_biosphere_vegetation`. These are production-renderer previews, not live screenshots. Native app capture was unavailable.

Limits: existing plant palettes/organ geometry and synthetic patch boundaries remain; no terrain mesh, measured stand density, or extra individual ecology is introduced by the density layer. Large-patch thinning is a display LOD, not a population change. The subsequent [canopy-light recruitment](biosphere_canopy_recruitment_v001.md) pass connects shade independently of these decorative instances.

Growth-state follow-up: seven deterministic display ages now reuse each species' growth grammar. Spatially grouped age variation favours younger margins, bounded by the local cohort's development. The map height cap also follows stage, keeping saplings distinct even for very tall species. Grass varies blade count and tuft size. These are artistic age distributions, not new simulated recruits, senescence, or changes to the ecological canopy. Real representatives keep their exact snapshots. Fixed before/after: `artifacts/biosphere_growth_states_v001/`; regenerate with `py -3.14 -m tools.render_biosphere_growth_states`. Warmed fixture frames: roughly 15 ms woodland, 13 ms grassland; first woodland prototype generation roughly 3.5 s.
