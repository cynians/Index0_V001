# Lichen ground cover in terraforming BioSim

Vesuvius Rock Lichen now reads as pale, granular ground-cover patches, with
short branching tuft marks visible when zoomed in. The same map renderer
distinguishes a fruticose profile from an adpressed crustose profile; it does
not branch on a species ID. Existing lichens without a surface recipe retain
their previous symbol.

## Changes

The BioSim catalogue previously excluded the newly authored fungal species
because they were outside Plantae and lacked the older bootstrap flag.
`BiosphereSimulation._load_species_profiles` now builds a Fungi ancestry
index once and admits verified fungal species with all three explicit inputs:
lichen growth form, surface-covering behaviour and a surface profile. Their
taxonomy remains unchanged. This makes Vesuvius and Wall Lichen available in
the picker, including the pioneer tier selected by the existing growth-form
runtime default.

`BiosphereBuilderRenderer._draw_groundcover` receives the same profile as
ecology. Bounded pixel symbols use deterministic position-based variation,
the profile's thallus form and normalized tuft height. Fruticose cover uses
pale scale marks on short grey axes. Crustose cover uses low clustered
marks. This is a display-only population abstraction: it avoids thousands of
full individual organ snapshots and never adds ecological organisms or
resources. Only real representatives retain selection hitboxes.

## Reproducible preview

```powershell
py -m tools.render_biosphere_lichen_cover --label after
```

The preview reads live generated region `refined_lod4_e7fa59b8b3`, builds an
unpersisted terraforming site at 62% east/36% south, and introduces three
patches with radii 1.7, 1.4 and 1.9 metres. Four panels show barren ground,
abundance 0.25, abundance 0.9 and the same 0.9 population at 4× view zoom.
Populations are explicitly put at a mature display cohort. These are planted
coverage scenarios, **not years of measured lichen colonisation**. The site
reads its existing terrain without creating or saving refinement chunks.
The local generated substrate is nearly uniform at this scale.

- [before.png](../artifacts/biosphere_lichen_cover/before.png): green oval fallback; the otherwise excluded species was admitted only to this diagnostic population.
- [after.png](../artifacts/biosphere_lichen_cover/after.png): actual catalogue admission and profile-driven cover.
- [after_metrics.json](../artifacts/biosphere_lichen_cover/after_metrics.json): source, population controls, terrain status and rendering metrics.

Sparse and established views contain 111 and 392 decorative samples,
respectively, plus four real representatives. Site-scale projection is
35.05 px/m, and the close view is 140.19 px/m. The close view changes neither
population nor positions. Rendering twice produces identical frames and
leaves the ecological summary unchanged.

The underlying species still has unmeasured growth timing, substrate chemistry
requirements and nitrogen-fixation rates. The map symbols do not resolve
individual millimetre scales or replace the SpeciesSim attachment grammar.
This pass changes catalogue eligibility and appearance, and does not author
new biological traits, forecast suitability, or advance terraforming years.

## Verification

```powershell
py -m pytest tests/test_biosphere_lichen_cover.py tests/test_biosphere_vegetation.py tests/test_biosphere_builder.py -q -p no:cacheprovider
```

**29 passed in 5.57 seconds.** Coverage includes real fungal catalogue
admission without Plantae membership, stable density sampling, no ecological
or representative mutation during drawing, deterministic warmed frames,
bounded contrasting symbols, and existing builder/vegetation behavior.
Changed Python files compile; scoped `git diff --check` passes.

The images are previews from the production BioSim renderer, not screenshots
of native application navigation. The preview performs no ontology writes.
Only two images and their metrics are retained for this pass.

See also [Vesuvius Rock Lichen](species_sim_stereocaulon_vesuvianum_v001.md).

## Wall Lichen comparison

The same setup was repeated for `spec_lecanora_muralis` without changing its
biological fields or the shared renderer. Its `placodioid_crustose` profile
selects low olive-green clustered marks, contrasting with the projecting
fruticose symbols in the Vesuvius preview.

```powershell
py -m tools.render_biosphere_lichen_cover --species spec_lecanora_muralis --output artifacts/biosphere_wall_lichen_cover --label after
```

[Wall Lichen preview](../artifacts/biosphere_wall_lichen_cover/after.png) uses
the same terrain, planting locations, abundances and cameras. Sparse and
established views contain 109 and 386 decorative samples, respectively, plus
four real representatives; the close view retains the established population.
The tool now takes its title from the selected species' live name and records
its thallus form in the metrics, instead of using a fixed Vesuvius heading.

Repeat rendering is byte-identical and leaves ecology unchanged. Catalogue
admission, selected profile and overview/close population equality were
verified; the modified preview tool compiles. No biological fields or saved
site were changed. One final image, metrics and a small verification record
are retained in `artifacts/biosphere_wall_lichen_cover`. These are planted
visual scenarios rather than measured spread or ground-chemistry suitability.

## Elegant Sunburst Lichen comparison

`spec_rusavskia_elegans` now has a saved foliose surface profile with an authored
orange palette. Its missing Teloschistales ancestry link was corrected with
user authorization; the actual Fungi catalogue admits and unlocks it. Both
SpeciesSim and BioSim use that palette through the shared surface renderer.

```powershell
py -m tools.render_biosphere_lichen_cover --species spec_rusavskia_elegans --output artifacts/biosphere_sunburst_lichen_cover
```

[Sunburst cover preview](../artifacts/biosphere_sunburst_lichen_cover/after.png)
uses the same generated terrain and planting controls as the other two lichens.
It reads the saved profile with no experimental injection. Every scenario
verifies catalogue admission; repeated draws preserve the frame and ecology.
No world site or population is persisted. Growth rate, reproductive age,
longevity and substrate chemistry remain unresolved or uncalibrated.
See [Sunburst design and verification](species_sim_rusavskia_elegans_v001.md).
