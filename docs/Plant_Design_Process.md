# Plant Design Process

The living process document for developing plant and fungal species in Index 0. It
originated as an exact handoff to Claude, written for an agent that has an
ordinary shell, filesystem, Python, web access and image-viewing capability
but none of Codex's internal tools; it now also covers outsourcing the
literature research (§5), stem/branch asset design (§6a), tree
growth-architecture fields that drive real trunk/crown variety (§6b),
preferring one continuous authored parameter over a per-species code edit
(§6f), creating a new pixel-art asset from a real reference photograph
(§6g), correctly distinguishing cone vs. flower reproductive structures and
generating real fruit placements (§6h), an explicit agent-created,
review-before-persistence asset pathway (§6i), where assets are stored and what
is committed (§1a), critiquing renders against real
reference photographs (§9a), and closing each pass with a search for a
generalization-test candidate elsewhere in the live ontology (§11a). Work
from:

```text
C:\Users\logol\PycharmProjects\Index0_V001
```

The job is not complete when a species card contains plausible fields. A plant
development pass must leave a scientifically defensible ontology record, a
reusable deterministic simulation response, observable renderer evidence,
tests, and a short implementation document.

## Invocation and token-efficient reading

Treat `plant_design_procedure.md`, `plant_design_process.md`, and
`Plant_Design_Process.md` as references to this canonical document. The file
currently lives at `docs/Plant_Design_Process.md`; do not create a duplicate
when the user uses one of the alternate names.

Do not print or load the entire document into the conversation on every run.
Read the heading index first, then load only the current phase and any section
it explicitly requires. For a fresh session the minimum startup is:

1. read §0, §1 and §1a;
2. run `git status --short` without narrating the complete dirty-file list;
3. run §0a, show the contact sheet, state each `NEEDS_AUTHORING` status, and
   wait for the user's choice;
4. after the choice, read §3-§5a and continue phase by phase;
5. consult later sections only when that phase is reached.

For a refinement pass on an already selected species, begin with §9a's
comparison of the current simulation visuals against real-life photographs,
before choosing or implementing changes. Inspect arrangement, shape and
general appearance, then select the two most significant observed differences
as the pass's refinement targets.

Keep the exact commands, paths, candidate metadata, and evidence artifacts,
but summarize routine command output. Existing unrelated worktree changes are
important as a preservation constraint, not useful conversation payload.

## 0. Before starting: pick the next species from 3 random candidates

This is the entry point of the whole process — run it **before** the user
names a species, not after. It replaces "the user tells Claude a plant" with
"Claude offers 3 random candidates and the user picks one," and it doubles
as the mechanics-regression baseline (§0c) for whichever mechanic work
happens during the resulting pass.

### 0a. Generate the candidates

```powershell
py -m tools.plant_mechanics_regression_sample select
py -m tools.plant_mechanics_regression_sample render --status before
```

Owner's decision (2026-10-07): fungi, including mushrooms and lichens, are
part of the regular plant procedure from now on. The procedure's name stays
the same; this is workflow scope, not a change to biological taxonomy.

`select` draws 3 random leaf (terminal) descendants from the combined
`cladis_plants_plantae` and `cladis_fungi` pool in the live ontology
(`PlantCatalogue.leaf_species_ids` — an actual species with no taxonomic
child of its own, never an intermediate clade), chooses a representative
mature display age for each, and writes the choice to
`artifacts/plant_mechanics_regression/sample.json` so the exact same three
individuals can be regenerated later. `render --status before` renders that
manifest at the current mechanics, one PNG per candidate under
`artifacts/plant_mechanics_regression/before/`, plus a combined
`before_contact_sheet.png`.

The default `select --scope all` samples that combined pool uniformly; an
individual draw need not include both kingdoms. Use `--scope plants` or
`--scope fungi` when the user requests that restriction. Explicit lichen
or mushroom-only requests narrow the fungal pool accordingly and record
the actual scope in the manifest. Never select an intermediate taxon.

For a requested next batch, omit species the user has identified as done or
that have a completed species design record: repeat `select --exclude SPECIES_ID`
for those known IDs. Exclusions are recorded in the manifest; the remaining
terminal pool is sampled uniformly. An authored field count alone is not a
completion marker. Exclude after determining terminal membership, so removing
a species never promotes its taxonomic parent into the candidate pool.

### 0b. Show the user the 3 candidates and ask which one to develop

Owner's decision (2026-10-11): candidate previews always show somewhat mature
organisms so juvenile development cannot be mistaken for a broken mechanism.
The default now chooses full structural maturity in a healthy leafy or flowering
phase; configured fungi show mature bodies in a flush. This is a deterministic
display age on the model clock, not a biological calendar estimate. Record the
exact `age_days` and reuse it for before/after regression, even if traits change.
Do not silently retime a baseline. Historical manifests retain their sampled
fractional age; re-present them in a separate mature manifest when requested.
Read recorded `life_state`, especially on such older juvenile or leafless cases.
Panels report seasonal foliage state and use independently fitted scales;
equal panel heights do not imply equal physical heights. Use separately labelled
growth-stage evidence when testing development itself.

Send the rendered image(s) to the user and ask them to pick one. Call out
`select`'s `NEEDS_AUTHORING` flag (zero authored simulation trait fields,
counting `PLANT_TRAIT_FIELDS` and `FUNGAL_TRAIT_SCHEMA_FIELDS`)
explicitly for each candidate:

- A candidate with one or more authored fields is not necessarily complete.
  Report the `authored_field_count`: a low non-zero count can mean a sparse
  placeholder whose render is still mostly driven by runtime defaults (for
  example, four basic growth/height fields). Picking one starts with §3's
  authored-versus-resolved inspection; classify it as a data-composition or
  underdeveloped-field pass from that evidence, not from the boolean flag.
- A candidate flagged `NEEDS_AUTHORING` is an actual bare stub — its render
  is only the generic fallback shape. For an unauthored fungus, explicitly
  label a plant fallback as unresolved rather than implying fungal morphology.
  This is normally the interesting
  option when the user wants a genuinely *new* plant, since it means the
  ontology has a taxon placeholder with no card yet.

If none of the 3 fit what the user wants this session, re-run `select` for
a fresh draw (this overwrites the manifest, so do this before, not after,
committing to a candidate). Once the user picks one, that species' id
becomes `species_id` for §1 onward — proceed straight to §3's inspection and
§5a's questionnaire hand-off for it.

### 0c. Close the loop: regression-check all 3 candidates, not just the chosen one

After the chosen species' own development work (mechanism implementation,
field authoring, asset work) is implemented and verified, re-render the
*original* 3-candidate manifest and compare:

```powershell
py -m tools.plant_mechanics_regression_sample render --status after
py -m tools.plant_mechanics_regression_sample compare
```

`compare` reports `UNCHANGED`/`CHANGED` per sampled species (placement
counts, bounds, blueprint fingerprint, life state) and writes side-by-side
before/after images to `artifacts/plant_mechanics_regression/comparison/`.
Checking all 3 — not only the one just developed — is the point: an
unexpected `CHANGED` result on one of the *other two* candidates means a
grammar/mechanism change made during this pass leaked into species the pass
never touched. Investigate that before finishing, the same way §9a's
two-defect fix surfaces a photograph mismatch.

This is a broad smoke check across the live population, not a substitute
for §7's fixed-seed baseline or §9's paired-treatment comparison for the
specific mechanism under development.

## 1. Non-negotiable project contracts

Ordinary passes may select either a plant or a fungus. Verify the selected
species' actual ancestry before research or authoring, then use the relevant
plant, lichen or mushroom recipe. Keep fungal taxonomy under Fungi; do not
add vascular plant organs or plant-only fields merely to reuse the lab.
Fungi with an unsupported body plan remain eligible for selection: inspect
and develop the missing shared mechanism rather than inventing a bracket
recipe or treating the generic plant fallback as their finished appearance.

For an explicitly requested lichen pass, verify the existing species' Fungi
ancestry instead of asserting Plantae membership. Keep its taxonomy unchanged.
Scope the three-candidate sample to live terminal lichen taxa, record that
scope in its manifest, and reuse the same render/compare functions in a
separate output directory. The shared authoring tool now also accepts verified
fungal species with `plant_growth_form=lichen`,
`plant_growth_behaviour=surface_covering` and an explicit
`surface_growth_profile`. This is growth-lab eligibility, not plant membership.
Adapt the research questionnaire to thallus dimensions, substrates, hydration
and spore reproduction; omit vascular organs. Surface recipes do not propagate
by taxonomic consensus. Mosses may opt into the same support geometry with
their own body profile. See `docs/species_sim_lecanora_muralis_v001.md`.

For an explicitly requested mushroom pass, verify Fungi ancestry and scope
the candidate sample to non-lichen terminal fungal species. Keep the same
fixed sample/seed comparison loop. Use a `fungal_growth_profile` with a
supported body form; the initial shared recipe is a wood-associated bracket.
This is Species Sim eligibility, never Plantae membership. Separate the
persistent mycelial colony from individual fruiting bodies in research and
life timing. Omit vascular organs and plant-only dropdowns. The §5a handoff
still applies unless direct research is requested; adapt its rows to fungal
feeding modes, substrates, cap/stalk dimensions, pores, spores, colony versus
body persistence and uncertainty. Shared authoring validates fungal recipes
against verified ancestry. Body recipes and sprites do not inherit through
taxonomic consensus. See `docs/species_sim_cerioporus_squamosus_v001.md`.

1. The persistent SQLite ontology quadstore is the live semantic authority.
   `ontology/index0.owl` is an RDF/XML checkpoint and can lag behind it.
2. Inspect ordinary entities through:

   ```python
   PersistentOntologyStore(Path("ontology/index0.owl")).load_datasets()
   ```

   Describe that result as the **decoded projection of the live quadstore**.
3. Never edit `ontology/index0.owl` as text. Persist through `EntityLoader` or
   the application, then export a checkpoint only after verification.
4. Determine whether something is a plant through `PlantCatalogue` ancestry
   below `cladis_plants_plantae`. A plant-like name or a `plant_growth_form`
   field is not sufficient evidence.
5. Preserve the species' stable ID, parent relations and unrelated fields.
   Do not rename an ID or repair taxonomy unless the task explicitly includes
   that migration.
6. Authored values, inherited values, runtime defaults and experimental
   overrides are different things. Label them and never silently persist a
   runtime default or experimental treatment as a biological fact.
7. Unknown is valid. Use `other_unknown` or leave an open field absent when
   evidence is insufficient. Do not fill a catalogue for visual convenience.
8. Simulation code must be trait-driven and reusable. Do not branch on a
   species ID.
9. Preserve the user's unrelated working-tree changes. Never use destructive
   Git cleanup commands.
10. Treat numeric grammar constants and normalized visual controls as
    qualitative simulation coefficients unless a source directly measures the
    same quantity and unit.
11. Coarse growth categories are not a ceiling on architectural detail.
    Reusable subpatterns may refine sympodial, monopodial, transitional,
    mixed or other growth patterns when the existing grammar cannot represent
    the observed plant. Keep the coarse botanical field and the visual recipe
    separate; follow §6l rather than adding a species-ID code branch.
12. Every authored asset and final plant composition must be usable in BioSim.
    A good isolated icon or zoomed Species Editor render is insufficient.
    Verify attachment, scale, silhouette and bounds through the production
    BioSim renderers at ordinary scene sizes; follow §6m before completion.

Start every pass with:

```powershell
git status --short
```

Record which relevant files were already modified. Work around unrelated
changes rather than reverting them.

## 1a. Asset storage, packing and what is committed (changed 2026-10-29)

Read this at startup with §0 and §1. It replaces every older instruction or
habit that names `assets/illustrations/`, `assets/cards/` or
`assets/test_assets/`: those folders no longer exist.

**Where assets live.** An asset sits in the folder of the entity it belongs
to, `assets/<category>/...`. `world/asset_folders.py` decides the category
from that entity's dataset: species and clades below `cladis_archaeplastida`
or `cladis_fungi` are `plants`, other species are `animals`, locations are
`maps`, and an illustration belongs to its parent. For a plant or fungus pass:

| What | Where |
|---|---|
| Module and organ pictures and their Pixel Studio documents | `assets/plants/illustrations/<sanitized_id>_pixel.png` and `.layers.json.gz` |
| Plant blueprints | `assets/plants/blueprints/` (unchanged) |
| Species Sim preview fixtures (preview wood, rock test asset) | `assets/plants/preview/` |

Never write a folder name by hand. Pixel Studio's `asset_path` and
`document_path` (used by `tools.author_plant_assets`) and the knowledge
browser's import pick the folder. If a pass's new asset lands anywhere but
`assets/plants/illustrations/`, the illustration entity's `parents` is
missing or wrong: fix the parent instead of moving the file.

**Reading assets in code.** Code that opens an asset goes through
`engine/asset_files.py`: `load_image`, `open_gzip_text`, `read_bytes`,
`read_text`, `exists` and `revision`, never `pygame.image.load`, `gzip.open`,
`Path.read_*` or `Path.stat()` on an asset path. Pass the path as the
ontology stores it. The same call then reads loose files while developing and
packs in a packed build; a direct file call works today and breaks there.
Caches that code writes and reads itself (growth snapshots, kept plant
pictures) are not assets and stay plain file calls.

**Packing and committing assets.** Git ignores everything in `assets/` and
commits one pack per category in `asset_packs/` instead. The pre-commit hook
rebuilds the packs from the loose files (`py -m tools.pack_assets
--repository`); when one changed, it stops the commit and the next commit
carries it. Nothing to do in a pass: work on the loose files only, and never
edit or hand-build a pack. In a fresh clone or worktree `assets/` is empty
until `py -m tools.pack_assets --unpack`; run that before touching assets
there. `build/asset_packs/` (`py -m tools.pack_assets`) is a separate packed
build with every asset; it is never committed.

**What is committed and what stays local.** The user commits by selecting
every file git shows, so `.gitignore` decides. Committed: simulation, world and
UI code, tests and `tests/fixtures/`, the assets above (as packs), the shared tools
(`tools.author_plant_species`, `tools.author_plant_assets`,
`tools.plant_mechanics_regression_sample`, `tools.render_species_views`,
`tools.render_plant_biosim_check` and the other exceptions listed in
`.gitignore`) and this document. Kept on disk but never committed:

- `assets/plant_asset_specs/`, `assets/species_trait_specs/` and
  `assets/reference_credits/`, the inputs of a pass;
- `docs/species_sim_*.md`, the §12 pass record;
- `tools/render_*.py`, i.e. any new comparison or preview script;
- per-species `tools/author_<species>.py` (§6 already forbids new ones);
- `artifacts/`, `build/` and `assets/plants/diagnostics/`.

So:

1. Whatever a later session or the app needs must end up in the ontology,
   code, committed assets or tests, not only in a local record or recipe.
2. A new test does not import a `tools/render_*.py` script and does not read
   the local-only folders. Copy the values it needs into the test or into
   `tests/fixtures/`. About 60 older tests still read recipes; they pass on
   this machine only.
3. A new reusable tool that tests or other tools import is not named
   `render_*.py`, or it gets a `!tools/<name>.py` exception in `.gitignore`.

## 2. Important files

| Purpose | File |
|---|---|
| Live ontology persistence | `world/persistent_ontology_store.py` |
| Entity loading and persistence | `world/entity_loader.py` |
| World/repository refresh | `world/world_model.py` |
| Plantae membership | `world/plant_catalogue.py` |
| Pre-pass mechanics regression sample (§0) | `tools/plant_mechanics_regression_sample.py` |
| Species inheritance/provenance | `world/species_inheritance.py` |
| Plant field schema and exact choices | `world/plant_traits.py` |
| Growth-form/behaviour vocabularies | `world/plant_growth_catalog.py` |
| Ontology → portable blueprint | `simulations/species/plant_assets.py` |
| Structural growth and snapshots | `simulations/species/species_simulation.py` |
| Roots | `simulations/species/root_growth.py`, `root_visuals.py` |
| Renderer and diagnostic tabs | `simulations/species/species_renderer.py` |
| Visual editor state | `simulations/species/species_editor.py` |
| BioSim species profiles | `simulations/biosphere/ecology.py` |
| Soil N/P trait interpretation | `simulations/species/plant_nutrition.py` |
| Soil cycling | `simulations/biosphere/soil_succession.py` |
| Research field catalogue | `docs/plant_species_web_research_instruction.md` |
| Asset reads, loose or packed (§1a) | `engine/asset_files.py` |
| Asset folder of an entity (§1a) | `world/asset_folders.py` |
| Packs for a packed build (§1a) | `tools/pack_assets.py` |
| Example field-development docs | `docs/species_sim_root_architecture_v001.md`, `docs/species_sim_palhinhaea_stoloniferous_v001.md`, `docs/species_sim_sequoia_field_composition_v001.md` |

The core data path is:

```text
live ontology
  → raw species + cladistic parents
  → WorldModel.resolved_species_entity()
  → PlantBlueprint.from_species_entity()
  → blueprint.growth
  → SpeciesSimulation.generate_snapshot()
  → PlantGrowthSnapshot + SpeciesRenderer
  → get_ecological_outcome()
  → optional BioSim population/soil feedback
```

Trace every field through that path before deciding that it is implemented.

## 3. Inspect the target before researching or editing

Use a temporary Python script or an interactive Python session. This is
read-only:

```python
from pathlib import Path
from world.persistent_ontology_store import PersistentOntologyStore
from world.plant_catalogue import PlantCatalogue

species_id = "REPLACE_ME"
datasets = PersistentOntologyStore(Path("ontology/index0.owl")).load_datasets()
entities = {
    row["id"]: row
    for rows in datasets.values()
    if isinstance(rows, list)
    for row in rows
    if isinstance(row, dict) and row.get("id")
}

raw = entities.get(species_id)
assert raw is not None, f"Missing live entity: {species_id}"
catalogue = PlantCatalogue.build(entities)
assert catalogue.is_species(species_id), f"Not a Plantae species: {species_id}"

print(raw)
print("parents:", raw.get("parents"))
```

Then inspect authored versus inherited values through the actual runtime:

```python
from world.world_model import WorldModel
from world.species_inheritance import is_authored_field
from world.plant_traits import PLANT_TRAIT_FIELDS

world = WorldModel()
raw = world.loader.get(species_id)
resolved = world.resolved_species_entity(species_id)

for key in sorted(PLANT_TRAIT_FIELDS):
    raw_value = raw.get(key)
    resolved_value = resolved.get(key)
    if raw_value not in (None, "", [], {}) or resolved_value not in (None, "", [], {}):
        status = "authored" if is_authored_field(raw, key) else "inferred/unknown"
        print(key, status, "raw=", raw_value, "resolved=", resolved_value)
```

Also print the blueprint and fingerprint:

```python
from simulations.species.plant_assets import PlantBlueprint

blueprint = PlantBlueprint.from_species_entity(resolved, species_id)
print(blueprint.fingerprint())
print(blueprint.growth)
```

This establishes three things before implementation:

- exact stored identity, and Plantae ancestry (§1 rule 4) — this is the
  only taxonomy check required; do not research accepted names,
  synonyms, or family placement beyond it (§5a);
- which values are truly authored, and which SpeciesSim actually receives;
- which fields are currently ignored or replaced by runtime defaults.

## 4. Classify the work

Choose one of these scopes explicitly.

### A. Data-composition pass

Use this when existing grammars already represent the plant. Research and
author fields, verify the existing rendering, and add tests for the field
composition. Do not add code merely to make the pass look larger.

### B. Underdeveloped-field pass

Use this when an authored field is ignored, collapses to a generic placeholder,
or has no observable effect. Capture the old behavior, add a reusable
trait-driven mechanism, test contrasts, render a comparison, and document it.

### C. Asset-calibration pass

Use this when biology and grammar are adequate but reusable leaf, stem, branch,
root, flower or fruit modules are missing or visibly wrong. Keep technical
asset fields separate from biological research. Asset references are project
facts; normalized visual-fit values are provisional calibration data.

A pass can combine these scopes only when the user requested the combined
result.

## 5. Research protocol

### 5a. Default path: outsource via a generated questionnaire

The default is **not** for Claude to browse the web itself. At the start of
every species pass, right after the read-only inspection in §3, generate a
compact, copy-paste-ready research questionnaire for the exact target
species and present it to the user in its own fenced block to paste into an
external assistant (e.g. ChatGPT). Then **wait** — do not begin authoring,
independent web research, or asset work until the user pastes back a
response.

Fill in `{SPECIES}` with the stored binomial and common name from §3. Do not
ask the researcher for a taxon check, accepted name, synonyms, family, or
parentage: the live entity's Plantae ancestry is the identity check for this
workflow. The compact prompt deliberately uses dense choice lines and asks
for short evidence phrases rather than prose. **Do not ask for citations** —
the response is trusted as given (see below):

```text
Research {SPECIES}'s intrinsic traits for a simulation ontology. Do not check
or discuss taxonomy. Use only the exact choices below; use Other/unknown when
evidence is insufficient; flag meaningful variation; do not infer tolerance
from habitat presence. Return compact rows: key | choice | confidence (H/M/L)
| evidence phrase (12 words max). Omit fields structurally inapplicable to
the growth form. No citations.

DROPDOWN FIELDS (internal key — allowed values):
plant_growth_form — Tree, Shrub, Subshrub, Forb, Graminoid, Vine, Fern, Moss, Succulent, Aquatic, Other/unknown
plant_growth_behaviour — Iterative/indeterminate shoot, Unbranched/single axis, Determinate/sympodial shoot, Rosette/short-internode, Branched woody architecture, Climbing/twining/scrambling, Creeping/prostrate, Tussock/tillering, Rhizomatous clonal spread, Stoloniferous/runner spread, Suckering/basal clonal spread, Fern/fronding, Basal succulent rosette, Moss mat
plant_lifespan — Ephemeral, Annual, Biennial, Short-lived perennial, Perennial
plant_life_form — Therophyte, Hemicryptophyte, Geophyte, Chamaephyte, Phanerophyte, Hydrophyte, Other/unknown
plant_woodiness — Woody, Herbaceous, Other/unknown
mature_height_class — Dwarf, Low, Medium, Tall, Canopy, Emergent, Other/unknown
growth_rate — Slow, Moderate, Fast, Other/unknown
maturity_rate — Rapid, Fast, Moderate, Slow, Other/unknown
longevity_class — Very short, Short, Moderate, Long, Very long, Other/unknown
leaf_phenology — Evergreen, Deciduous, Semi-deciduous, Drought-deciduous, Marcescent, Other/unknown
leaf_size_class — Very small, Small, Medium, Large, Very large, Other/unknown
leaf_structure — Simple, Pinnately compound, Palmately compound, Scale-like, Needle-like, Frond-like, Other/unknown
leaf_arrangement — Alternate, Opposite, Whorled, Basal, Distichous, Spiral, Fascicled, Other/unknown
leaf_attachment_pattern — Along stem, Terminal cluster, Basal rosette, Basal tuft, Branch tips, Mixed, Other/unknown
leaf_clustering — Solitary, Paired, Tufted, Rosette, Dense cluster, Distributed, Other/unknown
plant_shoot_dimorphism — Single shoot system, Long and short shoots, Other/unknown
plant_leaf_distribution — Along shoot, Mixed long/short shoots, Terminal cluster, Basal rosette, Basal tuft, Other/unknown
plant_flowering_position — Lateral, Terminal, Mixed, Other/unknown
plant_reproductive_structure — Flower, Capitulum/flower head, Cone, Spike, Digitate/anthela spike cluster, Panicle, Compound umbel, Other/unknown
plant_lateral_axis_orientation — Orthotropic, Plagiotropic, Mixed, Pendent, Other/unknown
plant_axis_continuity — Monopodial, Sympodial, Monopodial to sympodial, Mixed, Other/unknown
plant_self_pruning — Strong, Moderate, Light, None, Other/unknown
plant_crown_shape — Conical/pyramidal, Ovoid/rounded, Umbrella/flat-topped, Spreading, Irregular, Other/unknown
photosynthesis_pathway — C3, C4, CAM, Other/unknown
root_architecture — Taproot, Fibrous, Adventitious, Mixed, Other/unknown
root_depth_class — Shallow, Intermediate, Deep, Other/unknown
reproductive_mode — Sexual, Vegetative, Both, Apomictic, Other/unknown
seed_size_class — Tiny, Small, Medium, Large, Very large, Other/unknown
clonal_spread — None, Low, Moderate, High, Other/unknown
resprouting — Absent, Weak, Moderate, Strong, Other/unknown
regeneration_strategy — Seed bank, Vegetative recruitment, Resprouting, Disturbance colonization, Gap recruitment, Mixed, Other/unknown
nitrogen_fixation — None, Associated/facultative, Active/capable, Other/unknown
nutrition_mode — Autotrophic, Parasitic, Hemiparasitic, Mycoheterotrophic, Carnivorous, Mixotrophic, Other/unknown
mycorrhizal_type — None, Arbuscular, Ectomycorrhizal, Ericoid, Orchid, Mixed, Other/unknown
shade_tolerance — Low, Medium, High, Other/unknown
moisture_preference — Very dry, Dry, Mesic, Moist, Wet, Aquatic, Other/unknown
waterlogging_tolerance — Low, Medium, High, Other/unknown
salinity_tolerance — Low, Medium, High, Other/unknown
thermal_range_coldest — Frigid (polar, alpine), Cold (boreal), Cool (cool temperate), Mild (warm temperate), Warm (subtropical), Hot (tropical), Very hot (hot desert), Other/unknown
thermal_range_warmest — Frigid (polar, alpine), Cold (boreal), Cool (cool temperate), Mild (warm temperate), Warm (subtropical), Hot (tropical), Very hot (hot desert), Other/unknown
(the coldest and the warmest climate zone the species grows wild in, read off
its native distribution; the same zone twice if it keeps to one. No exact
temperatures are needed for these two.)

OPTIONAL NUMERIC/LIST FIELDS (give units; mark typical vs. exceptional; skip
if unsupported): mature_height (min_m/max_m), max_root_depth (max_m),
maturity_age (typical_years: age at mature size and regular reproduction),
longevity (typical_years/max_years an individual lives; for clonal plants
one stem or ramet),
leaf_length (min_m/typical_m/max_m), temperature_range (°C: min_c,
optimal_min_c, optimal_max_c, max_c; only where a source states them, the
thermal range above is the general answer), frost_tolerance (min_c),
soil_ph_range (min/max), succulence (organs: leaf/stem/root),
belowground_storage (rhizome/tuber/bulb/corm/storage_root/lignotuber),
pollination (wind/water/bee/moth/bird/bat/generalist_insect/self_pollination),
dispersal (wind/water/gravity/animal_external/animal_ingestion/ballistic/human).

Skip the normalized 0-1 "visual fit" architecture fields (branch droop,
crown openness, leaf cluster density, etc.) — those need reference
photographs and are calibrated separately in the Species Editor, not
researched.

ANSWER FORMAT:
1. Dropdown rows: key | exact choice | H/M/L | evidence phrase.
2. Optional rows: key | value+units | H/M/L | evidence phrase.
3. Uncertainties or important variation, if any.
4. One well-documented distinctive feature, which may be either a functional /
   behavioural mechanism (trigger, process/organs, trade-off, consequence) or
   a visual / morphological characteristic (organ shape, texture, colour,
   architecture, or arrangement, plus its anatomical basis and simulation
   relevance), or "none".
```

When the response comes back, trust it — do not re-research it, do not
spot-check its claims against independent sources, and do not perform an
external taxonomy check. The live-ontology Plantae-ancestry check in §3 is
sufficient for this workflow. The
external assistant did the literature work; Claude's job is to transcribe
it into the schema correctly, not to re-derive or audit it. The one
mechanical check that still applies:

- cross-check every selected value against the exact live schema strings
  (`PLANT_TRAIT_CHOICES` below) — a plausible-sounding label that isn't
  actually in the choice list must be resolved, never transcribed as-is.
  This is a lookup, not a research task.

Everything else — provenance labelling, authoring, testing, rendering
evidence, documentation — proceeds exactly as the rest of this document
describes. The questionnaire only changes who performs the literature
search; it removes the verification step entirely rather than shifting
who does it.

### 5b. Direct research (only if the user asks Claude to research itself)

Skip §5a only when the user explicitly asks Claude to do the research
directly instead of outsourcing it. In that case, since Claude itself is
now the one doing the literature work (not verifying someone else's),
apply a sensible source priority:

1. primary botanical/ecological papers for mechanisms;
2. taxonomic authorities such as Kew POWO or World Flora Online;
3. national or university floras;
4. forestry/agricultural agencies and botanical gardens;
5. curated trait databases.

Use `docs/plant_species_web_research_instruction.md` as the fuller
field-entry questionnaire and report format in this mode. Treat
`PLANT_TRAIT_SCHEMA_FIELDS` and the choice tables in `world/plant_traits.py`
as authoritative: the code may contain newer architecture or quantitative
fields that neither questionnaire has yet incorporated. Cover every active
schema field relevant to the species, and retain the same per-field record
(internal key, exact allowed value, one-sentence reason, confidence,
evidence-vs-inference-vs-visual-fit label) as §5a.

### 5b-i. Life timing: `maturity_age` and `longevity`

Species Sim's age slider runs on a developmental clock set by `maturity_rate`
(30 to 365 days), so that a whole life fits the slider. The Biosphere runs in
real years and maps an organism's real age onto that clock
(`simulations/species/plant_life_timing.py`). The two optional numeric fields
give it the real figures: `maturity_age: {"typical_years": 15}` (mature size
and regular reproduction) and `longevity: {"typical_years": 80, "max_years":
150}`.

When the research returns no figure, leave the field empty. The Biosphere then
derives a generic one from `plant_growth_form`, `maturity_rate`,
`longevity_class` and `plant_lifespan`, and labels it *generic* in its Species
Catalogue. Do not turn a class into a number to fill the field: that hides a
generic figure behind an *authored* label. Authoring either field changes
nothing in Species Sim's own view.

### 5c. Shared: inspect the live schema, never invent a value

Regardless of which path produced the research, inspect the live allowed
values instead of relying on memory before authoring anything:

```python
from world.plant_traits import PLANT_TRAIT_CHOICES, PLANT_TRAIT_SCHEMA_FIELDS
from world.plant_growth_catalog import (
    PLANT_GROWTH_BEHAVIOUR_CHOICES,
    PLANT_GROWTH_FORM_CHOICES,
    PLANT_LIFE_CYCLE_CHOICES,
)

print(PLANT_TRAIT_CHOICES["nitrogen_fixation"])
print(sorted(PLANT_TRAIT_SCHEMA_FIELDS))
print(PLANT_GROWTH_FORM_CHOICES)
print(PLANT_GROWTH_BEHAVIOUR_CHOICES)
print(PLANT_LIFE_CYCLE_CHOICES)
```

Do not invent new dropdown strings in a species row. If the vocabulary is
insufficient, make schema expansion a separate, explicit change with migration
and tests.

### 5d. Prefer a project-derived refinement

After the research response has been checked against the live schema, inspect
the **current working plant** as it is actually resolved, generated and
rendered. Prefer a refinement that addresses a concrete behavior or visual
feature that is underdeveloped, ignored, or unimplemented in the current
project. Use the researcher's distinctive feature only when it fits the
plant's supported traits, the observed gap, and the scope of the pass.

Derive the preferred refinement from project evidence rather than additional web
research:

1. render the plant at a representative mature state with the fixed inputs from
   §7 (the existing §0 preview may be used only when it shows enough detail);
2. compare the render with the resolved blueprint, placements and relevant code
   path;
3. identify one concrete gap whose correction would materially improve this
   plant, such as an authored field with no observable effect, a generic grammar
   standing in for its actual architecture, a missing organ or life-stage
   transition, or a conspicuously inadequate visual treatment;
4. prefer a reusable trait-driven improvement over a species-specific fix, and
   say explicitly when the gap is asset calibration rather than a new mechanic;
5. do not invent a gap merely to provide an option — report `none found` if the
   current implementation already represents the plant adequately.

Before implementation, briefly state the observed problem, the selected
reusable simulation or asset change, and the evidence that would demonstrate
success, then proceed within the user's authorized scope without requiring a
choice between candidates. The project-derived option is the default. Use a
research-derived feature as a fallback when no useful project-derived gap is
found, or include it when it directly supports the selected refinement without
expanding the scope. If neither option fits, report that finding rather than
inventing work. Respect any explicit user preference and the preview/verification
requirements for new assets in §6i. Field authoring from the accepted
questionnaire may be prepared first.

## 6. Authoring fields safely

### Preferred interactive path

Run:

```powershell
py -m app.app
```

Open the species card, then **Species Editor**. The editor provides a fixed-seed
mature preview, minimum/typical/maximum range modes, a four-seed variation view,
temporary reference-image overlay, undo/redo, and live ontology save.

Use the full Species Card for structured ranges/lists that the visual editor
marks as card-only. Save writes the live quadstore. The separate **Save
Ontology** action exports the RDF/XML checkpoint.

### Shell/Python path when no usable GUI is available

Only use this path when the task authorizes ontology mutation. Routine reviewed
species-card updates go through the reusable `tools.author_plant_species`
command. Do **not** create a new `tools/author_<species>.py` for biological,
architecture, module-reference, or wiki-field updates.

Keep the payload in memory so the dry run and apply use exactly the same data:

```powershell
$plantSpeciesId = "REPLACE_ME"
$plantUpdatesJson = @{
    # Use exact internal values from world/plant_traits.py.
    # plant_growth_form = "tree"
} | ConvertTo-Json -Depth 10 -Compress

# Required first pass: validates the live plant, fields, types, exact choices,
# normalized architecture ranges, and prints before/after values. No write.
py -m tools.author_plant_species $plantSpeciesId --updates-json $plantUpdatesJson

# Only after reviewing the dry-run output:
py -m tools.author_plant_species $plantSpeciesId --updates-json $plantUpdatesJson --apply
```

The command accepts either a raw JSON field mapping or an envelope shaped as
`{"species_id": "...", "updates": {...}}`; `--input PATH` and stdin are
available for unusually large payloads. It only updates an existing species
below `cladis_plants_plantae`. It refuses identity, naming, dataset and taxonomy
fields; those require a separately reviewed migration. It also clears inherited
provenance for the authored keys, point-persists only the changed fields, and
reopens the live quadstore to verify the saved values.

After all behavior and tests are verified, repeat the applied command with
`--export-checkpoint` if the task requires `ontology/index0.owl` to be updated:

```powershell
py -m tools.author_plant_species $plantSpeciesId --updates-json $plantUpdatesJson --apply --export-checkpoint
```

Custom asset painting may still need implementation code, and creating a
missing species or clade still needs an explicit taxonomy migration. Once that
work has produced an existing plant row or module paths, use this command for
the species-card fields instead of embedding them in the custom script.

Never call `reimport_ontology_checkpoint()` as part of ordinary species
development: that operation imports the possibly stale RDF/XML checkpoint into
the live store.

### Reference-photo and asset gate (before rendering or critique)

Run this gate immediately after the researched fields pass dry-run review and
before creating the pass's current/final render. Asset work must not discover
its references only after the comparison render already exists.

1. Query the iNaturalist public API and inspect both live whole-plant habit
   photographs and close organ photographs. Record each observation URL,
   image URL, licence/credit, and whether it is a habit or organ reference.
   Use §9a's fallback order when iNaturalist is insufficient.
2. Inspect the resolved blueprint's leaf, stem, branch, root, flower and fruit
   modules. Record which have authored `asset_ref` values and which still use
   renderer fallbacks. A visible generic shape is not an authored asset.
3. Decide the smallest useful visual unit for every missing organ visible in
   the references. Obtain its measured size and live-app canvas resolution as
   required by §6g.
4. When an achievable visible organ still lacks an authored asset, run §6i
   Phase A now with the shared `tools.author_plant_assets` command: create a
   data-only manifest, generate preview-only assets and a fixed-seed mock-up,
   inspect and refine them, then run the same manifest through Phase B within
   the authorized plant-design scope. Wire the assets before producing the render
   that §9/§9a will critique. Do not create a per-species Python authoring or
   preview script.
5. Only skip asset creation when the pass is explicitly data/mechanism-only,
   the organ is not visible at the relevant scale, evidence or measured size
   is insufficient, or the user declines the preview. Record the reason.

The required order is:

```text
research response -> schema review -> iNaturalist reference set
-> module/asset audit -> preview, inspect and refine missing assets -> persist assets
-> current render -> exactly-two-defect reference critique -> final render
```

## 6a. Asset design rules: stem, branch, and root modules

Pixel-art stem/branch/root modules (`plant_stem_module_ref`,
`plant_branch_module_ref`, `plant_root_module_ref`) do not render like
leaf/flower/fruit modules. Get this wrong and the plant looks broken even
when every biological field is correctly authored — this bit a real pass
(Jackal Buchu's branch asset had a baked-in side fork that appeared,
identically rotated, sticking out of every single branch segment across
the whole plant).

**How the renderer actually uses these assets**
(`SpeciesRenderer._draw_structural_asset_path` in
`simulations/species/species_renderer.py`): for every individual
`stem_section`/`branch_section`/`root_section` placement, the renderer
takes the *entire* module image, stretches its height to exactly match
that one segment's length, scales its width to the line width, rotates
the whole sprite rigidly to match that segment's real 3D-projected
direction, and blits it centred on the segment. The same single image is
reused, independently stretched and rotated, at *every* segment of that
kind across the whole plant — this is nothing like the leaf/flower/fruit
path (`_draw_module_asset`), which places one fixed-aspect sprite per
point using the module's `attachment_point`/`growth_axis` anchor.
Consequences:

1. **No anchor system applies.** `attachment_point`/`growth_axis` (set via
   `author_module`'s `anchor` argument) are ignored for stem/branch/root
   modules. Draw the module running straight up the canvas, bottom to
   top; rotation is derived purely from each segment's real direction.
2. **Never bake an off-axis detail into the sprite** — no side forks, no
   attached leaf/bud stubs, no asymmetric silhouette bumps. Forking is
   already generated structurally as separate placements by the growth
   grammar; anything asymmetric drawn into the image gets replicated
   identically, at whatever angle that particular segment happens to be
   rotated to, at every occurrence of that module across the plant. A
   gentle single-direction wobble stayed close to the vertical axis is
   fine (see `paint_stem`/`paint_branch` in
   `tools/author_woods_rose_assets.py`); a distinct stroke that leaves
   the vertical corridor is not.
3. **Design for arbitrary vertical stretch/squash.** The exact same image
   gets scaled to match segment lengths that vary throughout the plant
   and across growth stages — a roughly uniform-width strip tolerates
   this; a shape whose silhouette depends on a specific aspect ratio
   (e.g. a strongly tapered trunk profile) will look wrong at some
   lengths.

**Stem vs. branch: author both, as two distinct modules, not one shared
asset.** The schema and blueprint already treat them as structurally
different: `stem_section` is the thicker primary/main axis (radius
0.035 m default) and `branch_section` is the thinner secondary axis
(radius 0.022 m default, `internode_length_m * 0.8`) — see
`simulations/species/plant_assets.py` around the `PlantModule("stem_section", ...)`
/ `PlantModule("branch_section", ...)` definitions. Reusing one asset for
both (or authoring only `plant_branch_module_ref` and leaving
`plant_stem_module_ref` unset) means the plant's primary axis renders
with the thinner/plainer twig art everywhere, including near the base
where a thicker trunk-like segment is expected. Author:

- `plant_stem_module_ref`: a slightly thicker, plainer strip for the
  primary/basal axis ("trunk" for a tree; the main basal stems of a
  shrub).
- `plant_branch_module_ref`: a thinner strip for secondary/fine
  branching, distinct from the stem module — same straight-vertical,
  no-baked-detail rules apply.

`plant_root_module_ref` follows the identical stretch/rotate rule when
authored, though most existing species leave roots unillustrated
(procedural root rendering handles them — see `root_visuals.py`).

Legacy visual examples (inspection only; do not clone their scripts):
`tools/author_woods_rose_assets.py`'s `paint_stem`/`paint_branch` (clean,
already correct) versus the bug fixed in
`tools/author_agathosma_mundii_assets.py` (see
`docs/species_sim_agathosma_mundii_v001.md` §8a for the concrete
before/after). Encode new structural strips as manifest operations for
`tools.author_plant_assets`.

## 6b. Tree growth-architecture fields now drive real structural variety

For any tree species, actively research and consider authoring
`plant_apical_control` and `plant_lateral_axis_orientation` — don't just
leave them at the generic tree defaults out of habit. As of
`docs/species_sim_tree_architecture_variety_v001.md`, these aren't subtle
numeric tuning anymore:

- **`plant_apical_control`** drives whether the tree builds one trunk or
  forks into 2-3 co-dominant trunks from the base (rolled per individual,
  seeded — low apical control means a real, substantial *chance* of
  forking, not a guarantee every individual forks). If the species has a
  documented single-leader habit (most conifers, many columnar trees),
  author it high (0.8+). If it's documented as commonly low-branching,
  multi-stemmed, or gnarled at maturity (Black Mulberry, many open-grown
  broadleaf trees), author it low-to-moderate (0.25–0.45) — see
  `species_sim_morus_nigra_v001.md` for the worked example.
- **`plant_lateral_axis_orientation`** drives branch inclination and
  therefore overall crown silhouette: `plagiotropic` for a broad,
  low-spreading crown; `orthotropic` for upright branches and a
  columnar/conical crown; `pendent` for a weeping habit (not yet
  exercised by any authored species — a good candidate to look for).

The compact §5a questionnaire already asks for both (added after Silver
Wattle and Black Mulberry both needed a targeted follow-up question to
get a well-justified `apical_control`/`lateral_axis_orientation` value —
the standard dropdown list alone doesn't prompt for real branching habit
specifically). If a species has a genuinely distinctive documented trunk
or crown habit, ask about it directly as a supplementary free-text
question, the same way the N-fixation/heteroblasty question was asked for
Silver Wattle and the branching-habit question for Black Mulberry —
don't rely on the generic dropdown table alone to surface it.

Known limit: `lateral_axis_orientation` alone can't produce a true
low-branching "dome" crown (branch attachment height along the trunk
doesn't respond to it yet) — see `species_sim_morus_nigra_v001.md` §8 if
tackling that gap.

## 6c. Trunk texture: mature trees should look gnarled, not like a smooth tube

Every tree trunk used to render as a smooth, monotonically-tapering tube
at every age and every species — real long-lived or resprouting trees
develop visibly twisted, knotty, irregularly-thickened trunks as they
mature (a mature Black Mulberry's gnarled trunk being the clearest
documented example — see `species_sim_morus_nigra_v001.md` §7a). This is
now handled automatically: `tree_shoots.py`'s `leader_axis()` derives a
per-individual "gnarl amount" from `longevity_class` + `resprouting`
(already-authored traits) scaled by the individual's own `maturity`, and
perturbs the existing per-segment trunk path/radius (spiral twist + a
higher-frequency knot term + one seeded burl bulge) — no new placements,
no new schema field, costs nothing extra at forest scale.

**Longevity alone is the wrong predictor, though** — some very long-lived
trees stay famously straight (coast redwood, most single-leader conifers),
while others characteristically gnarl (mulberries, many sympodial
broadleafs); see `species_sim_morus_nigra_v001.md` §7b for the real
example that caught this (Sequoia's `very_long`+`strong resprouting` data
was giving it near-maximum gnarl before this fix). The mechanism now gates
on `axis_continuity` as the primary signal, with `apical_control` as a
secondary correlate: **monopodial** growth keeps one embryonic-derived
axis dominant for the plant's life — mechanically straight — while
**sympodial** growth proceeds through a succession of different lateral
meristems taking over the lead, the textbook mechanical cause of a
zigzag/crooked axis. Longevity/resprouting/maturity still set how much of
that gated potential is expressed.

**What this means for authoring**: actively research and author
`plant_axis_continuity` first (it's the primary gate — get this wrong and
a species like a redwood will gnarl when it shouldn't, or vice versa),
then `plant_longevity_class` (and `plant_resprouting` where documented)
for every tree species, the same way §6b asks for `apical_control`/
`lateral_axis_orientation`. A `monopodial` species with a documented
single dominant leader (most conifers) will stay comparatively straight
even if long-lived; a `sympodial` species (many broadleafs with a
zigzag/crooked mature habit documented) will gnarl more readily even at
moderate longevity. Species that skip either field still get a
deterministic fallback (a neutral multiplier for unauthored
`axis_continuity`, a per-species jittered value for unauthored
`longevity_class`) rather than one identical constant, so don't treat
leaving them unauthored as a hard blocker — but an explicit,
research-backed value is always better than the fallback, same principle
as every other field in this document.

**`monopodial` needs to mean straight, not just straighter** — see
`species_sim_morus_nigra_v001.md` §7c. Gating only the gnarl term wasn't
enough: a real coast redwood, checked against a reference photo, reads as
essentially perfectly vertical, and the *dominant* remaining source of
wiggle turned out to be `lean` (a pre-existing per-individual directional
tilt from the trunk-multiplicity/lean mechanism, §6b), which wasn't gated
by growth habit at all — plus the small baseline per-segment path noise
every trunk gets regardless of species. When authoring or debugging a
"this should look straight" trait interaction, check *every* source of
per-segment perturbation in `leader_axis()` (lean, the baseline `offset`
wiggle, and gnarl are three separate terms), not just the one most
recently added — and don't assume "reduced" is "enough" for a trait whose
real-world expression is categorical (a redwood isn't "a bit less gnarled
than a mulberry," it's essentially a straight line).

**The gnarl term itself could snap the trunk base and undersample into a
"broken stick" look at its own ceiling** — see
`species_sim_quercus_robur_v001.md` §5. `gnarl_trait` saturates at its
`1.0` clamp for *any* `very_long` + `sympodial` tree (the combination
alone already exceeds the clamp before `apical_control` applies), and two
latent bugs only became obvious at that ceiling on a *tall* species
(English Oak, 40 m) even though the mechanism's own reference species
(Black Mulberry, 10 m) hit the identical ceiling: (1) `gnarl_offset` had no
ramp-in near the trunk base, unlike every other perturbation term, so a
segment right at the root collar could already be metres off-axis; (2)
`gnarl_freq` (up to 3.6 cycles) was sampled by only 12 fixed trunk
segments regardless of species height, undersampling the curve into long
straight rods meeting at sharp elbows rather than a smooth bend — worse
the taller the species, since a taller tree's per-segment metre spacing is
larger for the same fractional swing. Fixed generally in `leader_axis()`
(base taper, lower `gnarl_freq`/`knot_freq` range, amplitude retuned
against the existing tortuosity tests to recover the winding the lower
frequency cost) — not a per-species override. When a gnarl/lean defect
only shows up on one species, check whether it's actually latent in every
species hitting the same clamp/ceiling before assuming the newly-touched
species is the odd one out.

Visible trunk straightness can be authored separately from the botanical
axis-continuity category with `plant_trunk_straightness` (0..1 visual-fit range).
Zero/missing preserves the existing trunk geometry and blueprint fingerprint;
one removes primary-axis drift/lean/meander and within-segment bends in the tree
shoot grammar. Secondary trunks retain a straight inclination so they remain
separated. Do not infer monopodial development solely from a straight photograph.
The untextured bark fallback is already plain; straightness does not establish
bark colour, roughness, burl anatomy or an authored bark asset. See the follow-up
in `docs/species_sim_diospyros_whitei_v001.md`.

## 6d. Crown onset: where the live crown begins along the trunk

Every tree used to start its lowest branch at the same fixed trunk-node
fraction (~25% of height) regardless of species — real trees vary hugely
here. A coast redwood or white pine in a closed stand self-prunes its
lower/shaded branches as it grows, holding a long clear trunk with foliage
only near the top; most open-grown broadleafs (oaks, mulberries) retain
low branches and never develop that clear-bole look. This is a genuinely
different concept from `axis_continuity` (§6c) — that's about the axis's
*shape*, this is about *where the crown begins along it* — and no existing
field captured it, so a new one was added: `plant_self_pruning`
(Strong/Moderate/Light/None/Other-unknown). `tree_shoots.py`'s
`grow_tree_shoots()` maps it to a trunk-node range for the lowest branch,
scaled in with the individual's own `maturity` (a young tree hasn't
self-pruned yet) — unauthored species reproduce the original fixed
behavior exactly, so this costs nothing for already-authored species that
skip the field.

**What this means for authoring**: actively research and author
`plant_self_pruning` for every tree species alongside `axis_continuity`.
Look specifically for documented natural-pruning behavior or a described
"clear bole"/"clear trunk" length in silvicultural sources — conifers
grown for timber are the most reliably documented case (self-pruning is a
literal, named forestry concept tied to wood quality), broadleafs are more
species-specific. See `species_sim_morus_nigra_v001.md` §7d for the coast
redwood example that prompted this, checked against a reference photo.

## 6e. Crown shape: the mature canopy's overall silhouette outline

Every tree used to fill the exact same fixed branch-reach envelope (peak
at 42% of height, tapering off both ways) regardless of species — a
conical "Christmas tree" conifer, a small flat-topped crown on a long
trunk (a mature Scots pine being the textbook case), and a broad spreading
canopy all looked identical apart from height/colour. This is a third,
separate concept from `axis_continuity` (trunk shape) and `self_pruning`
(vertical crown onset) — it's the outline shape itself — captured by a new
field: `plant_crown_shape` (Conical/pyramidal, Ovoid/rounded,
Umbrella/flat-topped, Spreading, Irregular, Other-unknown). Real trees of
most species are more regular/pyramidal when young and only take on their
distinctive mature silhouette with age, so the mechanism blends from the
shared default envelope toward the authored target as `maturity`
increases, rather than snapping to it immediately — unauthored species (and
the explicit `ovoid` choice) get the exact original formula at every
maturity, zero behaviour change.

**What this means for authoring**: actively research and author
`plant_crown_shape` alongside `axis_continuity`/`self_pruning` for every
tree species — this is usually the single most visually distinctive thing
about a tree's silhouette from a distance, and general references
(Wikipedia, field guides) very often describe it directly in prose even
when they don't use the exact silvicultural term (e.g. "Christmas tree
shaped," "flat-topped," "umbrella crown"). See
`species_sim_morus_nigra_v001.md` §7e for the design record (three
examples: Eastern White Pine=conical, Coast Redwood=irregular with a
secondary lower bulge, and a new species added specifically to exercise
this — Scots Pine, `species_sim_pinus_sylvestris_v001.md` — umbrella; and
Nordmann Fir, `species_sim_abies_nordmanniana_v001.md`, the deliberate
counter-example — `conical` that actually *stays* conical at maturity,
via `self_pruning=none` instead of White Pine's `light`).

**Trait interactions can silently cancel each other out.** §7f: a numeric
check (branch reach clearly biased toward the intended part of the height
range) said `crown_shape` was working, but the actual render still looked
wrong — `self_pruning=strong` had already excluded every branch from the
region `crown_shape=conical` needed to widen into, so the two authored
traits were describing a contradictory tree. Also: rounding a branch's
attachment point to the nearest of only 11 discrete trunk nodes collapses
into visible flat bands once `self_pruning` compresses the branch-bearing
zone into a small slice of that range — worth checking for whenever a
"where along the trunk" trait interacts with a "how many discrete slots
are there" limitation elsewhere in the same grammar. General lesson:
after a numeric self-check passes, still zoom into the actual render
before calling a visually-driven trait "verified" — a metric can be
technically true and still not be what the change was supposed to produce.

**§7h — that lesson applied a second time, to the summary sentence
itself**: a follow-up "we don't seem to have really captured the shapes"
found that a *summary claim* ("stays a dense, symmetric cone... down to
near the ground") had the same problem — true of the underlying reach
numbers, not true of the actual picture. Traced correctly this time by
walking each primary branch's own tip position (not the intermediate
per-branch subdivision points a first pass had accidentally averaged in)
and found the geometry itself was fine; the real cause was resolution —
`branch_count` only ever produced ~10-15 primary branches regardless of
species, and `rhythmic` branching used exactly 2 per tier, so a conifer
only ever got ~7 widely-spaced tiers — too few to read as a continuous
cone edge instead of a few flat bands. Fixed by raising branch_count
(~x2.2) and using 3-per-tier for non-opposite rhythmic species.

**Time performance changes with repeated samples, not one run each.** The
first timing pass on that branch-count increase (a single before/after
sample per species) showed an alarming 3-6x render-time increase — worse
than the ~2.2x branch-count increase itself. Repeating each measurement 5x
and taking the median brought most species down to a much more reasonable
~2.5x (in line with the branch-count increase, comparable to the
already-accepted `foliage_cap` precedent, `species_sim_acer_rubrum_v001.md`
§8a) — the single-sample numbers had just been noisy. One species (Ginkgo)
*did* stay a real, repeatable outlier (~4.8x) even after proper
measurement, which was the correct signal to keep investigating rather
than dismiss as noise too.

**Cache pure per-species/per-kind rendering functions — don't recompute
per placement.** Profiling that Ginkgo outlier found `SpeciesRenderer.
_species_tint()` (the deterministic colour jitter every organ without an
authored pixel asset falls back to) was recomputing a fresh
`random.Random()` instance and full HLS colour conversion on *every single
leaf placement*, despite being a pure function of `(species_id, kind)` —
identical output for every leaf of one species. This predates the
branch-count change entirely; the increase just multiplied an
already-wasteful per-leaf cost, making it visible. Memoizing with
`functools.lru_cache` fixed it for every species without a leaf asset, not
just the ones touched this pass. General lesson: when a per-organ
rendering function's output only depends on identity (species, kind, not
the individual placement), it should be cached at that granularity, not
recomputed per placement — check for this specifically when a "more
placements" change causes disproportionate (worse-than-linear) cost.

See `species_sim_morus_nigra_v001.md` §7h for the full investigation and
before/after numbers.

**§7i — scope a shared-grammar fix to the actual pattern that had the
problem, not every species that shares the code path.** The branch-density
fix above (§7h) was applied as one uniform multiplier to every tree,
because that was simplest to reason about and time. A full, unbiased
critique of the whole comparison grid ("analyze the pics and tell me what
you see," not just re-checking the one thing just changed) found it had
silently turned an open-canopy species (Silver Birch,
`crown_openness=0.8`) into a dense solid blob — the discrete-tier banding
problem the fix targeted only exists for `branching_rhythm=="rhythmic"`
species; `diffuse`/`continuous` species already distribute branches
smoothly and never had it, so they only ever paid the cost, not the
benefit. Rescoped the multiplier to the actual affected pattern. General
lesson: when a fix for a specific symptom lives in code shared by many
species, ask *which* species structurally have the symptom before scoping
the fix to "every species using this function" — and re-check the *whole*
comparison grid after a shared-code change, not just the species that
motivated it.

## 6f. Prefer one continuous authored parameter over a per-species code edit

A pass on Coast Redwood needed a genuinely narrower, more columnar crown
than `crown_shape=irregular`'s shared envelope produced (checked against
real reference photographs, §9a). The first attempt hand-edited the
`_crown_shape_targets["irregular"]` width/floor tuple in
`tree_shoots.py` directly — it worked, but it was a one-off number baked
into shared code for whichever species happened to use that dropdown
value, not something another pass could retune without editing code again,
and not something that could vary continuously across a species' own
min/typical/max range or read differently for the *next* narrow-crowned
conifer that gets authored later. **Prefer a new normalised (0..1) visual-fit
field instead**, the same convention as `plant_branch_droop`/
`plant_crown_openness`/etc: `plant_crown_taper` was added (schema entry in
`world/plant_traits.py`, wired through `plant_assets.py` exactly like
`plant_apical_control`, consumed in `tree_shoots.py` as a continuous
multiplier on top of whatever `crown_shape` category already produced) so
the same narrow-column look is one authored number
(`min`/`typical`/`max`), tunable in the Species Editor like any other
slider, reusable by any future species, and — because it defaults to
`0.0` (no behaviour change) — exactly reproduces every already-authored
species' render unless that species explicitly authors a value. The
hand-edited tuple was reverted back to its original shared value once the
field existed. General rule: when a render defect's fix would mean editing
a numeric constant inside a shared grammar function for one species'
benefit, stop and ask whether that constant should instead be a new
authored continuous field (extending `PLANT_ARCHITECTURE_RANGE_FIELDS`)
that the *specific* species dials in — the grammar stays generic, the look
becomes reproducible across many individuals (each seed still varies
naturally through the existing per-branch jitter) and across whatever
species author it next, and nothing needs another code change to recalibrate
later. This is the same "trait-driven, not species-ID branch" principle as
rule §1.8, extended to numeric grammar constants specifically.

Leaf inclination now has an optional example of this pattern:
`plant_leaf_attachment_angle` (0..1 → 0..180° from the local host-shoot
tangent). It is available for iterative herbaceous forb shoots and their
clonal compositions; unauthored values preserve the original leaf pose.
Use it for leaf-to-twig angle matching rather than changing the pixel asset
or phyllotaxis. See
[Leaf attachment angle](species_sim_leaf_attachment_angle_v001.md).

Short-lived iterative subshrubs with along-shoot foliage and terminal capitula
also use the bounded leafy-shoot layout and optional leaf angle. An authored
`plant_inflorescence_profile` with `form=capitulum_cluster`, `unit=capitulum`
composes a bounded cluster from one head asset; head samples remain display
geometry. See [Pussyfoot](species_sim_praxelis_clematidea_v001.md).

Long, straight flowering laterals can now be fitted with optional
`plant_lateral_shoot_length` (fraction of host height) and
`plant_lateral_shoot_curvature` (upward turning strength). Missing controls
preserve legacy geometry; author qualitative ranges against habit photographs
rather than adjusting shared branch constants. See
[Lateral shoot length and curvature](species_sim_lateral_shoots_v001.md).

Tree crowns can also author `plant_primary_branch_density` (0..1 raises the
existing number of primary axes up to threefold, capped at 48) and
`plant_primary_branch_length` (base outward reach relative to tree height).
These are optional visual fits for the shoot-distribution tree grammar;
missing/invalid values preserve its defaults. Prefer these controls over adding
fine twigs to the same sparse shelves or changing a shared reach constant.
See the [Silver Wattle refinement](species_sim_acacia_dealbata_v001.md).

When a mass-flowering tree remains visually green, check whether one reproductive
marker is standing in for a many-leaved cohort and whether the accent sampler
discards dense bloom. The optional `plant_bloom_density` now resolves collective
bloom coverage from native flower units while preserving their metric size and
canonical ecological budgets. See [Collective bloom](species_sim_bloom_cohorts_v001.md).

## 6g. Creating a new pixel-art asset from a real reference photo

Do this whenever a pass needs a `plant_leaf_module_ref` /
`plant_flower_module_ref` / `plant_fruit_module_ref` (or, per §6a, a
stem/branch/root module) that the species doesn't have yet — don't leave
an organ on the generic per-kind fallback shape/colour
(`SpeciesRenderer._color`'s fixed RGB + `_species_tint` jitter, or a
generic marker dot) when an authored asset is achievable in scope, and
never invent a pixel-art silhouette from imagination. The process, worked
example is Coast Redwood's needle-leaf module
(`tools/author_sequoia_sempervirens_leaf_asset.py`):

The §6 reference-photo and asset gate must already have acquired and recorded
the relevant iNaturalist habit/organ references before this section begins.
If it has not, stop and run that gate rather than painting first and looking
for confirming photographs afterward.

**Choose the right smallest *visual* unit first — it is not always the
smallest *biological* unit.** A real conifer carries thousands to millions
of individual needles; a leaf module depicting one needle needs a sprite
drawn (or a fallback shape sized) per needle to look full, which doesn't
scale and still reads as a sparse scatter rather than foliage (found on
the redwood pass: an accurate single-needle asset produced a visibly
threadbare crown). The fix wasn't a bigger/denser asset — it was
recognising that for needle/scale foliage the *shoot* (a short twig with
several needles already on it, matching how real conifer foliage actually
reads from any distance beyond a close-up) is the smallest unit worth
drawing/placing individually; `SpeciesRenderer`'s cluster-drawing loop
stretches/rotates *one* sprite per needle-clad shoot for
`leaf_structure in {"needle_like", "scale_like"}` species (gated on that
existing trait, not a species-ID branch) instead of sampling many
per-needle placements — the same "one placement, one draw" principle
stem/branch segments already use. Ask this question for any organ that
occurs in very large per-plant counts (needles, tiny scale leaves, moss
phyllids, fine root hairs), not just conifers: is there a natural
*cluster* unit (a shoot, a spikelet, a frond segment) real and large
enough to be the placement granularity, rather than the true smallest
biological part?

If a species' leaf module ends up depicting a cluster unit like this,
its own `depicted_size_m` (and any other field consumed by a *structural*
formula elsewhere — check what actually reads `blueprint.module(kind).length_m`
before assuming it only affects rendering) should still be the real
single-organ measurement, not the cluster's size, unless every consuming
formula has been checked. The redwood pass first set `depicted_size_m` to
the shoot's own ~90mm length and broke shoot-length geometry throughout
`tree_shoots.py`, because `leaf_length = leaf_module.length_m` there feeds
the actual simulated shoot-length formula, not just render scale — the
renderer's own per-cluster stretch factor (real cluster length ÷
`module.length_m`) already accounts for the size mismatch, so the module's
authored size never needed to change, only the artwork. Relatedly: a
render-scale fix for one densely-placed organ can reveal that a *different*
existing formula (here, `SpeciesRenderer._draw_fallback_leaf`'s
needle-shaped fallback, sized from that same small single-organ
`module.length_m`) was never designed to represent something the size of a
whole cluster either — collapses to a blob instead of a needle at typical
whole-tree zoom once only one is drawn instead of many overlapping.
Re-check every downstream consumer of a size-driving field before treating
a fix as complete, not just the one call site that motivated it (§7i's
general lesson, applied here to a metric-size field instead of a shared
grammar constant).

1. **Get the organ's real physical size from evidence, not a guess.**
   Check whether the relevant metric field (`leaf_length`, or the
   stem/branch radius defaults in `plant_assets.py`) is already authored;
   if not, find a real measured value (the same source priority as §5) and
   author it — the redwood needle-leaf pass found `leaf_length` had never
   been authored at all (falling back to the generic `leaf_size_class`
   default, ~5x too large for an actual ~12-25mm needle) and authored a
   literature-sourced range before making the asset.
2. **Get a real reference photograph of the specific organ**, not the
   whole plant — a close, in-focus, color-accurate photo of the actual
   leaf/leaf-unit/flower/fruit/stem section. Same source order as §9a:
   iNaturalist API first, Wikimedia Commons fallback. A whole-plant habit
   photo (§9a's photo) is the wrong reference here — it can't show the
   organ's own shape, proportions or color at any useful detail.
3. **Get the canvas resolution from the live app's own formula, not a
   hand-picked number.** The Species/Knowledge-Browser Pixel Studio sizes
   a new illustration's canvas from its `depicted_size_m` through
   `KnowledgeBrowserUI._pixel_canvas_size_for_entity` (a pure function of
   size alone — callable directly, e.g.
   `KnowledgeBrowserUI._pixel_canvas_size_for_entity(None, {"type": "idea"}, depicted_size_m)`):
   organs/objects under 1m get a 75×75 canvas, 1-5m gets 112×112, 5-20m
   gets 150×150, 20-200m gets 225×225, above that 300×300 (each bucket is
   the base size × 1.5). Use *that* resolution for the real organ size —
   don't invent a smaller or larger canvas by hand. (The existing
   `tools/author_*_assets.py` scripts predate this being called out
   explicitly and mostly use smaller hand-picked canvases; matching the
   live formula going forward keeps new assets consistent with what the
   in-app Pixel Studio would actually offer someone authoring the same
   species interactively.)
4. **Paint pixel art whose proportions and colour are drawn from the
   photo.** For leaf/flower/fruit modules (unlike stem/branch/root, §6a):
   one fixed-aspect sprite, drawn base-to-tip vertically in the canvas
   (matching every existing leaf asset's convention) so the
   `attachment_point`/`growth_axis` anchor set via `author_module`'s
   `anchor` argument reads correctly; `_draw_module_asset` places it at
   each organ socket rather than stretching/rotating it per segment like
   §6a's rule. Reuse the shared pipeline
   (`tools.author_plant_assets`) rather than reinventing it. Put the visual
   recipe in `assets/plant_asset_specs/<species_id>.json`; the shared command
   owns manifest validation, live-formula canvas sizing, preview rendering,
   Pixel Studio persistence, module wiring and output verification. Older
   `tools/author_*_assets.py` files are legacy implementations, not templates
   for new work.
5. **Author the illustration entity and wire the reference field** exactly
   as the existing tools do: an `idea_class: illustration` entity with
   `plant_asset_role`/`plant_asset_kind`/`plant_asset_target_field`/
   `depicted_size_m`, then set the species' `plant_<role>_module_ref` and
   `plant_module_anchors` from the saved module.
6. **Render a before/after** (generic fallback vs. the new authored
   asset) as part of the pass's §9 evidence, and a close-up `detail.png`
   if the organ is illegible at whole-plant scale (§9a-i's budget still
   applies — this doesn't add extra kept images beyond what that section
   already allows).
7. **Document it** in the species doc (§12): the reference photo URL and
   source, the depicted size and its evidence, and the canvas resolution
   used.

## 6h. Reproductive structures: cone vs. flower, and fruit had no placement generator at all

Every tree's reproductive placements rendered as a "flower" (generic pink,
or a hardcoded gold for tree/shrub/subshrub shapes specifically), including
conifers — gymnosperms don't have flowers, they bear cones (strobili),
usually small and dry, nothing like an angiosperm's bright reproductive
signal. **Added `plant_reproductive_structure`** (Flower/Cone/Other-unknown,
`world/plant_traits.py`) — trait-driven, not a species-ID branch —
consumed in `SpeciesRenderer._color()` *and* a second, separate hardcoded
gold override in the main placement-drawing loop that the first fix alone
didn't reach (check every place a kind's colour gets set, not just the
first one found). Authored `cone` for the four actually-conifer species
(redwood, both pines, Nordmann fir) — actively research and author this
for every conifer/gymnosperm pass going forward, the same as any other
§6-series field.

**Fruit had no placement-generation code anywhere** — the module/colour/
asset machinery existed (a rose hip module can be authored, per §6g) but
nothing ever called `sim._add(placements, "fruit", ...)`, so an authored
fruit asset was never actually drawn. Added a `fruiting_factor` to
`SpeciesSimulation.life_state()` (ramps in through the reproductive phase
rather than snapping on with flowering — real fruit takes time to develop
— and lingers into early senescence rather than vanishing with it) and
threaded it into `grow_tree_shoots()`, which now places fruit at a
fraction of the same terminal sockets flowers use. Scoped to the tree
growth form only (`_grow_tree`'s `shoot_distribution_grammar` path) —
every currently-authored tree species uses that path, but shrub/tussock/
single-axis growth forms still have no fruit mechanic; a real gap, not
silently patched over.

**A newly-visible co-located organ can be hidden by its own sibling's
draw order.** Fixing the colour bug first didn't make cones visible —
flower/fruit placements were drawn *before* the foliage loop, and the
post-§6g shoot-unit fix's now-properly-sized foliage sprite, drawn at the
same shoot-tip point, painted over the small reproductive marker
underneath it. Fixed by deferring flower/fruit to a `reproductive_overlays`
list (the same pattern `renewal_overlays` already used for a different
occlusion problem) and drawing them *after* the foliage pass. General
lesson: a fix that's visually a no-op isn't necessarily still broken in
the same place it started — verify at an age/state where the new
mechanism should actually be visible (`life_state()`'s factors are 0 at
exactly `mature_age_days`; this needed an older test age to show fruit at
all) before concluding a subsequent fix didn't work.

## 6i. Agent-created assets: preview, inspect, persist and refine

Use this pathway when the user asks the working agent to design, create or
improve a plant and asset work is part of the authorized scope. It is a narrow exception to §5a's default
research handoff: the agent may research the visual references and measured
organ dimensions needed for the asset-calibration pass. It does **not**
silently authorize a broader biological-field composition pass. Unrelated
traits remain unchanged unless the user separately includes them in scope.

User preference recorded 2026-10-02: routine, reversible plant assets and related
field updates within the requested design pass do not need a separate approval
question. Inspect the preview, save and verify the result, and refine anything
that falls short as the work continues. Do not leave an otherwise complete pass
pending approval merely because its visual design can be improved later.

This pathway still has two distinct phases. If the user explicitly asks to see
the work before implementation or requests an approval hold, show the preview
and honor that hold. Otherwise proceed from Phase A to Phase B autonomously.

Use one command for both phases:

```powershell
# Phase A: validates and writes preview artifacts only
py -m tools.author_plant_assets assets\plant_asset_specs\<species_id>.json

# Optional no-render schema/plan check
py -m tools.author_plant_assets assets\plant_asset_specs\<species_id>.json --validate-only

# Phase B: after inspecting the preview, within the authorized design scope
py -m tools.author_plant_assets assets\plant_asset_specs\<species_id>.json --apply
```

The manifest is data, not executable species logic. It records module roles,
metric sizes, normalized anchors, source URLs/credits and declarative
integer-grid drawing operations. The command derives every production canvas
from the live Pixel Studio formula and uses the exact same rendered pixel grid
for preview and persistence. Never add `preview_<species>_assets.py` or
`author_<species>_assets.py` for a routine plant asset pass.

### Phase A — preview-only design (no live writes)

1. Inspect the decoded live-quadstore projection, resolved entity and current
   blueprint as in §3. Record existing module references, anchors, physical
   dimensions and whether the renderer currently uses an authored sprite or a
   fallback.
2. Inspect the closest existing project assets and their manifests. Reuse
   their palette discipline and pixel density, but do not copy a biologically
   different silhouette merely because it already exists. Legacy authoring
   scripts may be read for historical context but must not be cloned.
3. Acquire a close, in-focus real reference for every proposed visual unit,
   following §6g and §9a. Record the source URL, licence/credit, measured size
   source and any interpretation made from the photograph. A whole-plant habit
   photograph cannot substitute for an organ close-up.
4. Choose the smallest useful **visual** unit before painting. For very
   numerous small organs this may be a real cluster unit (needle-clad shoot,
   scale-leaf spray, spikelet), while the biological metric retained by the
   blueprint may still be the single-organ size. State that distinction
   explicitly.
5. Obtain every canvas size from
   `KnowledgeBrowserUI._pixel_canvas_size_for_entity`; do not hand-pick a
   resolution. Paint base-to-tip vertically for leaf/flower/fruit assets and
   define an attachment point plus growth axis. Paint stem/branch/root assets
   as straight, vertically oriented, stretch-safe strips with no baked side
   organs, forks or silhouette features (§6a); anchors are not used for those
   structural modules.
6. Put preview files only under
   `artifacts/<species_id>_asset_preview/`. The minimum review package is one
   labelled design board showing each sprite at native resolution and at
   nearest-neighbour zoom. When renderer behaviour is material, also produce
   one fixed-seed in-memory simulator mock-up using copied entity data and
   temporary asset paths. The mock-up must use the same seed, age, LOD, camera
   and scale as its unmodified control.
7. During Phase A, do **not** create illustration entities, set
   `plant_*_module_ref`, change `plant_module_anchors`, persist through
   `EntityLoader`, export an ontology checkpoint, or place candidate files in
   `assets/plants/illustrations/`. Label every image `PREVIEW ONLY` and state which
   aspects are expected to change after review.
8. Inspect the review package and correct the identified visual defects, then
   proceed to Phase B without asking for routine approval. Show the saved,
   verified result to the user. Wait only if the user explicitly requested a
   preview or approval hold before implementation.

The manifest preview is the production pixel grid: Phase B renders the same
operations again and copies that surface into `PixelArtEditorUI`. The inspected
design therefore cannot drift through a hand-redraw.

### Phase B — verified production asset

After visual inspection within the authorized scope, run the inspected manifest with
`py -m tools.author_plant_assets <manifest> --apply`. The shared command owns
the `PixelEditorHost`/`PixelArtEditorUI` pipeline, illustration upserts, species
reference fields, anchors and file verification. Do not create an all-in-one
`tools/author_<species>.py` or a species-specific asset script: routine card
fields belong in `tools.author_plant_species`, while new reusable drawing
primitives belong in `tools.author_plant_assets`. If the manifest vocabulary
cannot express the design, extend the shared vocabulary and its tests
instead of escaping into per-species Python. Do not save a stand-alone PNG and
call it complete.

For every module the shared tool must produce the full Pixel Studio contract:

- an `idea_class: illustration` entity parented to the species, with
  `plant_asset_role`, `plant_asset_kind`, `plant_asset_target_field`,
  `depicted_size_m` and `media_path`;
- an RGBA PNG at
  `assets/plants/illustrations/<sanitized_id>_pixel.png` (the category folder
  `world/asset_folders.py` picks: plants and fungi share `plants`);
- the editable version-2 Pixel Studio document at
  `assets/plants/illustrations/<sanitized_id>_pixel.layers.json.gz`, including the
  canvas, layers, metric dimensions and module anchor payload;
- illustration metadata populated by `PixelArtEditorUI.save()` such as
  `pixel_editor_mode`, canvas/view sizes, layer counts, `pixel_document_path`,
  `pixel_view_paths`, `pixel_art_source` and `pixel_module_anchor`; and
- the owning species' corresponding `plant_<role>_module_ref`, plus
  `plant_module_anchors[role]` for leaf/flower/fruit assets. The copied anchor
  metadata must include `depicted_size_m` so reproductive sprites keep their
  physical scale without rediscovering the layer document at runtime.

Then verify that the PNG and editable document both exist and reopen through
the Pixel Studio path. Render the normal §9 before/after and, when physical
scale hides the asset, one independently fitted close-up. Inspect the pixels,
run the focused transport/renderer/round-trip tests, and document reference
URLs, sizes, canvas resolutions, refinement decisions and remaining limits.

## 6j. Trunk girth: nothing represented trunk thickness relative to height

Every tree used the same fixed height-fraction trunk radius (`h * .014`)
regardless of species — a slender birch and a stout, pachycaul-style
baobab would render with an identically-proportioned trunk. Flagged as a
follow-up during the trunk-multiplicity/lean pass
(`species_sim_tree_architecture_variety_v001.md`) and picked up during the
English Oak pass (`species_sim_quercus_robur_v001.md` §11), once the
reference photographs made how disproportionately thick a mature oak's
trunk really is impossible to miss. **Added `plant_trunk_girth`** — same
convention as `plant_crown_taper` (§6f): a normalised 0..1 field,
`0` (unauthored) reproducing the exact original radius, `1` a strongly
pachycaul trunk (`girth_multiplier = 1.0 + trunk_girth * 3.0`, up to 4x the
shared-default radius), consumed in `tree_shoots.py`'s `leader_axis()` as a
uniform multiplier on the existing radius formula.

**What this means for authoring**: actively consider `plant_trunk_girth`
for any tree species with a documented disproportionately stout or
disproportionately slender trunk, the same way §6b–§6e ask for the other
architecture fields — most references describe this qualitatively ("massive
girth", "slender bole") rather than with a directly usable numeric
DBH:height ratio, so treat it the same as the other 0..1 visual-fit fields
(§5a: skip it in the research questionnaire, calibrate from a reference
photo in the Species Editor or via the §6 shell path instead).

**Known limit, not attempted this pass**: this only scales the *existing*
taper profile uniformly — it makes the whole trunk proportionally thicker
at every height, not the genuinely different taper *shape* a true baobab
has (a near-cylindrical trunk that stays thick for most of its height, then
narrows abruptly near the crown, rather than tapering smoothly from the
base). A species that needs that distinct silhouette — not just "thicker
than default" — would need a second field or a taper-curve change, not
just a larger `trunk_girth` value.

## 6k. Graminoid leaves ignored `leaf_attachment_pattern`; added a "spike" reproductive structure

Picked up from a §0 candidate pick (Perennial Ryegrass,
`species_sim_lolium_perenne_v001.md`). Two defects found against real
reference photographs (§9a), both fixed as general mechanism/vocabulary
changes, not species-ID branches:

**Leaf placement ignored the species' own authored biology — and the first
fix attempt wasn't actually checked closely enough against the render
before being called done.** `_grow_graminoid_culm` (`species_simulation.py`)
placed one leaf at each of a non-woody culm's first three nodes, spread up
the stem at a fixed near-horizontal angle — regardless of what the species
had authored for `leaf_attachment_pattern`/`leaf_clustering`. For a real
basal/tufted tussock grass this rendered as rigid horizontal "rungs" on an
otherwise bare vertical culm, nothing like a tuft of blades.

The first attempt gated a new placement path on
`leaf_attachment_pattern == "basal"` and clustered the same leaf count (3
per tiller) at the lowest culm node as a small fan of fixed-aspect leaf
*sprites* — each still just one point plus a large render `scale`, no real
geometric length. This was declared fixed from a quick look at the render,
but a closer look (prompted by the user, who insisted on inspecting the
actual PNG rather than trusting the description) showed a rigid radial
starburst, not a tuft — because a single-point "leaf" placement has no
connected path for the renderer to draw; unlike `stem_section`/
`branch_section`/`root_section`, which are drawn as a genuine, optionally
curved line from parent to point (`SpeciesRenderer.
_draw_structural_asset_path`, §6a), "leaf" kind was *only* ever a flat
sprite stamped at one point (`_draw_module_asset`), with no way to bend or
visually connect back to its base.

**Fixed properly** by giving each basal blade the same treatment as a
stem/branch: a real 3D tip position (computed from the tiller's own
azimuth, a steep upward elevation, and a length fraction of the plant's own
height) and an actual curved path via the same `_curved_segment_path`
helper trunks already use for their bend, threaded through
`placement_paths` exactly like every other connected-path organ. The
renderer draws it as a connected line (`SpeciesRenderer._draw_individual`'s
new `basal_graminoid_leaves` branch — gated on `growth_form == "graminoid"`
and `leaf_attachment_pattern == "basal"`) rather than routing it through the
pixel-asset stretch path: a tapered leaf sprite repeated per curve segment
would look worse, not better, per §6a's own stretch-asset rule, so this
deliberately reuses the same plain-line fallback stem/branch already use
when no asset applies. Lolium's own leaf pixel asset became unused by this
change and was cleared rather than left dangling.

Blast radius: the only currently-authored non-woody graminoid affected is
Lolium itself (the other authored graminoid, giant bamboo
`spec_oldeania_alpina`, is woody and already uses the separate
branch-complement path via a different `leaf_attachment_pattern`, so this
change has zero effect on it — confirmed via the §0 regression tool, which
reported it fully `UNCHANGED`). Note: leaf count for a *basal* species is
no longer scaled down by how few culm generations have grown in — a very
young individual now gets its full basal leaf fan as soon as any growth
exists, rather than 0-2 leaves capped by generation count. This is
arguably more correct (real basal leaves emerge from the crown early,
independent of culm height) but is a real, intentional behavior change for
young individuals, not just a cosmetic repositioning — verify ecological
leaf-area consumers if tuning this further.

**General lesson, worth repeating alongside §6e's "a metric can be
technically true and still not be what the change was supposed to
produce":** the render was captured and even glanced at before calling the
first attempt fixed, but not scrutinized — "does this look meaningfully
better than before" is not the same question as "does this look like the
real organism," and only the second one is the actual bar. Always view the
actual output PNG critically against the reference photographs — not a
one-line visual impression — before reporting a render defect as resolved.

**No reproductive-structure category for a narrow, petal-less spike.**
§6h's two-choice `plant_reproductive_structure` (flower/cone) was already
flagged as deliberately incomplete, to be extended only once a real
species needed a third term it couldn't represent — a grass spike
(alternating, distichous spikelets on a bare rachis, no petals) is exactly
that case. Added `"spike"` as a third choice: a distinct straw/olive
`_SPIKE_BASE` colour in `SpeciesRenderer._color()`, and a distinct
fallback shape in `_draw_reproductive_fallback` (a thin central rachis
with alternating short ticks, not the round 5-petal fallback). Also found
and cleared a pre-existing, genuinely mis-authored `plant_flower_module_ref`
pixel asset for Lolium (a bright yellow multi-blob sprite — read as a
generic flower, not any grass's real inflorescence) so the corrected
procedural spike fallback renders instead of a wrong authored asset;
painting a proper hand-authored spike sprite via §6g's process remains a
follow-up, not done this pass.

## 6l. Reusable subpatterns within coarse growth patterns

Owner's decision (2026-10-13): subpatterns may be introduced beneath
sympodial, monopodial and any other growth pattern. A shared category often
describes axis development without adequately describing the mature plant's
geometry. Keep that category; add the smallest reusable architectural recipe
needed to express the observed arrangement. A new topology can justify a
discrete subpattern; a difference in degree should normally use a continuous
visual-fit control (§6f).

The first tree example is `plant_branching_subpattern=decurrent_scaffold`
(editor label: **Decurrent scaffold (oak-like)**). It composes with
`plant_axis_continuity`, retaining a juvenile leader while a mature short bole
divides into substantial, rising scaffold limbs and finer forks. It replaces
the periodic trunk meander and repeated thin tiers for the species that opt
in. English and sessile oak are the initial authored examples. The recipe
can be reused by another tree without testing its ID or genus. Missing or
`other_unknown` retains the established coarse grammar. The initial runtime
support is for trees; extend the relevant growth grammar when a different
growth form needs its own subpattern.

For every new subpattern:

1. Compare the saved plant with real habit photographs (§9a); define the
   observable structural differences before selecting a recipe.
2. Add the field/choice to the live schema vocabulary, authoring validation,
   editor controls, inheritance resolution, portable blueprint and fingerprint.
   Trace it into the actual growth mechanism and renderer. Do not merely add
   a dropdown, or rewrite a botanical category to force a visual effect.
3. State which coefficients are qualitative visual calibration, which facts
   are supported, and what is unresolved. Do not present a project recipe as
   a scientifically measured architectural classification.
4. Bound geometry and grouping budgets; preserve seeded variation, real
   attachment sockets, organ dimensions and canonical quantities across LODs.
   If one displayed spray represents several fine shoots, account for the
   group's leaves/area once and keep rendering samples separate from that
   accounting. Never enlarge an individual leaf to fake a mature canopy.
5. Test unknown/missing values, contrasting inputs, a species outside the
   initial genus, serialization/fingerprints and the BioSim path (§6m).
   Author only the requested species; label other treatments experimental.

Worked example: [Oak scaffold subpattern](species_sim_oak_scaffold_v001.md).

The iterative woody-subshrub example is `plant_shoot_profile.form=basal_subshrub`.
It retains the coarse growth category while describing one rooted basal crown
with bounded slender leafy shoots, ascending laterals and seasonal terminal
head sockets. Shoot/node counts and spread are explicit visual recipes;
they do not imply rhizomes, measured shoot production or seed yield. Missing
recipes retain the existing grammar. See [Narrow-leaved ragwort](species_sim_senecio_inaequidens_v001.md).

Herbaceous crown-forming forbs can opt into `plant_shoot_profile.form=basal_herb`
while retaining `plant_woodiness=herbaceous`. It shares the basal shoot builder
with the woody recipe, but has its own validation/body-plan gate and physical
leaf sizing. A complete compound-leaf asset is one leaf; its leaflet areas are
counted once. Whole-head flower/retained-fruit assets remain aggregate displays,
not individual flowers or seeds. See [Red clover](species_sim_trifolium_pratense_v001.md).

Leafy bryophytes can opt into `plant_growth_form=moss`,
`plant_growth_behaviour=moss_mat` and `plant_shoot_profile.form=leafy_moss`.
This represents a bounded vegetative turf of substrate-attached shoots,
with separate narrow leaves and optional pale hair-points. Footprint,
shoot spacing and branch frequency are representative display controls,
not a colony census. Independent axes must render their own projected
paths and metric widths, including in top views. Explicit scene
`moss_hydration` changes leaf pose and qualitative activity; missing or
invalid wetting stays neutral, and one dry sample does not imply death.
Do not substitute vascular roots, flowers, fruits or seeds for rhizoids
and spore capsules. Keep unsupported organs and life timings unresolved.
See [Woolly fringemoss](species_sim_racomitrium_lanuginosum_v001.md).

## 6m. Every asset must work in BioSim

Owner's requirement (2026-10-13): all plant and fungal assets must render in
a form usable in BioSim, including assets revised during later passes.
Apply this gate to both the reusable organ module and the complete organism.
Keep naturally spreading branches; repair unintended protrusions caused by
the artwork, attachment, rotation, scaling or repeated placement.

Before considering an asset or composition finished:

1. Inspect it attached through the real production renderer, rather than only
   on an isolated asset canvas. Check the attachment point, growth vector,
   measured depicted size, transparency and rotations. Repeated structural
   modules must not stamp baked forks, foliage or decorative protrusions onto
   every trunk/branch/root segment (§6a).
2. Render the full plant at juvenile and mature stages, including a relevant
   seasonal state, from the SpeciesSim elevation/isometric view and the
   BioSim/map top view. Inspect ordinary BioSim scene size and a close view.
   Tiny real organs may need a bounded collective representation at distance;
   zooming in must still expose correctly sized separate organs.
3. Use BioSim's actual grounded sprite/cropping and top-view picture paths
   (`BiosphereBuilderRenderer`, `plant_pictures.top_view`/`map_sprite_at`),
   with ordinary sprite size limits. Inspect a repeated stand when repetition
   could amplify a module defect. A Species Editor screenshot alone does
   not verify these consumers.
4. Check that roots ground the organism correctly, organs stay on their host,
   crown/organ extents are included in metric bounds, silhouettes remain
   recognizable after reduction, and no accidental long appendage, clipping,
   opaque box or oversized asset dominates neighboring plants. Fix the source
   geometry/artwork/anchor or render aggregation rather than hiding the defect
   with arbitrary clipping or per-species scale exceptions.
5. Keep the relevant BioSim views within the final multi-view `after.png`
   (§9a-i). Record sizes, stages, consumer path and any unresolved limits in
   the implementation record. Do not declare an asset BioSim-ready if the
   observed production view still fails this gate.

This gate is required even for data-only or mechanism-only passes when they
change the final rendered plant; existing assets can become unusable under a
new arrangement. It does not require rebuilding unrelated assets during a
targeted pass.

## 7. Capture a baseline before changing behavior

Use fixed inputs:

- seed `303` unless an existing species-specific comparison uses another seed;
- LOD 2 for focused organism/detail work;
- the same age or maturity fraction across A/B treatments;
- the same camera and physical scale;
- the same environment.

Record at least:

- blueprint fingerprint and relevant input fields/provenance;
- age, maturity, life phase and LOD;
- bounds in metres;
- placement/stem/branch/leaf-cluster counts;
- root depth, spread, length and source when applicable;
- mechanism-specific compact metrics;
- ecological outcome when the field affects BioSim.

Useful existing commands include (see §9a-i for the file-naming/keep
policy — render to `before.png`, not a one-off name, and only keep it if
the pass ends up needing a before/after comparison):

```powershell
py -m tools.render_species_editor_preview --species REPLACE_ME --output artifacts/REPLACE_ME/before.png
```

`tools.render_species_growth_gallery` is also available for a growth-stage
view, but its default output is a debugging tool, not something to keep
by default — see §9a-i.

These tools read direct species rows. If the comparison depends on inherited
fields, write the species-specific renderer with:

```python
world = WorldModel()
entity = world.resolved_species_entity(species_id)
simulation = SpeciesSimulation(
    world_model=world,
    species_id=species_id,
    species_entity=entity,
    seed=303,
)
```

Save the baseline before changing the grammar. A “before” image regenerated
after the implementation is not a baseline.

## 8. Implement a missing mechanism

Before coding, state observable acceptance criteria:

- which authored input changes which structural/ecological output;
- which quantities must remain unchanged;
- expected ordering across contrasting treatments;
- bounds that prevent runaway geometry or resources;
- behavior for zero, missing and `other_unknown` values.

Implementation rules:

1. Copy relevant ontology fields into `PlantBlueprint.growth`. This makes the
   blueprint portable and puts the field in its fingerprint automatically.
2. Put general morphology in a shared grammar/helper, not a species branch.
3. Keep organ types separate. Roots are `root_section`; rhizomes/supports are
   not roots; leaves/flowers/fruits remain distinct modules.
4. Preserve z-up metres, parent indices, attachment sockets and deterministic
   random streams.
5. Generate canonical structure once, then filter visible detail by LOD.
   Ecological quantities must not change merely because render LOD changes.
6. Bound node counts, recursion/generations, radii, lengths, resources and
   numeric inputs. Reject or neutralize non-finite values.
7. Include every behavior-changing input and helper/grammar version in cache
   keys or blueprint fingerprints.
8. Missing data should remain visibly unresolved or use a labelled neutral
   runtime default. Never turn missing into a biological extreme.
9. If the field affects ecology, use the same trait interpretation in
   SpeciesSim and BioSim. Do not duplicate incompatible formulas.
10. Do not persist experimental override values.

For N/P specifically, the shared path is
`simulations/species/plant_nutrition.py`. BioSim supplies explicit local pools;
SpeciesSim returns nutrient stress and root-access diagnostics; representative
feedback reaches population growth and soil cycling. Missing nutrient
environment is neutral, while explicit zero is limiting. Mycorrhiza may improve
access to existing P but must not create P. Biological N fixation occurs only
for an authored `active` or `associated` value.

## 9. Build the comparison that proves the mechanism

Use paired treatments with a shared seed, age, LOD, camera and scale.

Preferred order:

1. two genuinely contrasting authored species;
2. one authored species plus a clearly labelled experimental override when the
   live ontology lacks category coverage;
3. a zero/missing control.

Produce:

- a whole-organism shared-scale comparison;
- an enlarged detail if physical scale hides the feature;
- a JSON metrics/provenance report;
- a growth-stage or variation view when the mechanism changes with age;
- a BioSim diagnostic when the mechanism changes soil/population outcomes.

Owner's presentation standard (2026-10-07): finish every design pass with
one multi-view species sheet, using the layout verified on White Water Lily
and Woods Rose. It replaces an editor screenshot or isolated side render as
the primary final presentation. Generate it from the saved, resolved species:

```powershell
py -m tools.render_species_views --species REPLACE_ME --output-dir artifacts/REPLACE_ME
```

The sheet must contain:

- a large isometric whole-organism view;
- a top view of the footprint/canopy;
- a side view showing structure and roots where supported;
- a developmental/lifecycle strip, including flowering and fruiting when
  the saved recipe supports them, or the relevant fungal stages instead.

Fit cameras to the organism's actual bounds. Use one metric envelope and
scale across the stage strip; label independently fitted views or enlarged
details. Preserve physical organ dimensions, the pixel grid and authored
module artwork. Use ground, water or a substrate context appropriate to the
body plan. Label unresolved organs or behaviors rather than inventing them.
For fungi/lichens adapt organ labels, support views and colony/body timing;
extend the shared viewer if that body plan is not yet supported. Do not force
plant flowers, roots or developmental timings onto a fungal recipe.

Inspect the complete sheet before delivery. Save the primary image as
`artifacts/<species_id>/after.png` and its snapshots/metrics as `after.json`,
overwriting those fixed names when refined. This single sheet also supplies
the required growth-stage evidence; retain a separate detail only when the
feature remains illegible. The §9a-i image budget and original three-candidate
regression comparison still apply.

Inspect the actual images. Passing tests cannot tell you that roots obscure the
shoot, millimetre leaves are invisible, canopies clip, colors collapse, or a
camera comparison uses misleading scales. Refine only while a concrete visual
or mechanistic defect remains.

## 9a. Critique the render against real reference photographs, fix exactly two things

Do this for every pass, not only mechanism passes — this caught a genuine
starved-branch-density bug and a baked-fork asset bug on the first species
this was tried on (Jackal Buchu), neither of which any test caught.

**At the beginning of every refinement pass**, inspect the extant simulation
visuals alongside real-life photographs before editing fields, assets or
simulation code. Reuse a current render when it represents the saved state;
otherwise render that state first. Let the observed differences determine
which changes to make. Examine all three aspects:

- **Arrangement:** where organs attach, their spacing, angles and orientation,
  clustering, branching pattern and distribution along the plant.
- **Shape:** organ outlines, proportions and relative sizes, including changes
  with growth stage when relevant.
- **General appearance:** overall silhouette, density, colour, texture and
  visual character.

Choose the two most significant concrete differences across these aspects.
An arrangement or placement difference should lead to inspecting attachment
and growth geometry before deciding whether the asset itself needs editing.

1. **Reuse the reference set acquired at the §6 asset gate.** It must include
   live habit photographs and, when visible organs lacked assets, the close
   organ photographs already used for §6g/§6i asset creation. If the set is
   missing or inadequate, acquire it now and loop back through the asset gate
   before rendering. Prefer iNaturalist. The main
   `inaturalist.org` website is behind an interactive bot challenge that a
   headless/browser tool cannot pass, so use the public API instead, which
   is not gated the same way:

   ```text
   https://api.inaturalist.org/v1/taxa?q=<scientific name>
   https://api.inaturalist.org/v1/observations?taxon_id=<id>&photos=true&order_by=votes&per_page=6
   ```

   Take `default_photo`/observation photo `medium_url`/`large_url` values
   from the JSON response and view those image URLs directly. If
   iNaturalist has no observations for the species (rare, or a very
   obscure/threatened taxon), fall back to Wikimedia Commons, a POWO/WFO
   herbarium image, or a university/extension/botanical-garden photo page
   — in that preference order. Prefer live, growing-habit photographs over
   herbarium sheets when available; note which kind was actually used.
2. **Inspect the current mature preview** at the usual fixed seed/LOD (§7),
   reusing the current evidence already produced for §9 or rendering the
   extant saved state before changes. Include the relevant growth stage when
   the refinement concerns a developing plant.
3. **Compare them side by side** and name **exactly two** concrete,
   specific things about the render that are not optimal or do not
   function/look as intended relative to the real photographs — not vague
   aesthetic taste, not a wishlist. Candidates: silhouette/density
   mismatch (too sparse/too dense/wrong overall shape), wrong branching
   habit (e.g. upright vs. spreading vs. weeping), leaf colour or shape
   clearly off, canopy proportions wrong relative to trunk/stems, a visual
   asset artifact, bark/stem texture or colour mismatch, scale looking
   implausible. If more than two things look wrong, pick the two most
   significant and note the rest as a remaining limit (§9's own limits
   section, not silently dropped).
4. **Fix both** within the same pass when the fix is a genuine defect
   (grammar bug, wrong/missing authored field, bad asset) — most fixes
   found this way are either a data-authoring correction (§6) or a general
   rendering-grammar fix (§8), not a species-specific hack. If a defect
   turns out to need a new mechanic entirely (out of scope for this pass),
   document it as a limitation and, only if the user's request calls for
   it, as a suggested mechanism (§8's format) instead of leaving the
   render visibly wrong with no explanation. If an authored visual-fit
   field (crown openness, leaf cluster density, etc.) doesn't visibly move
   the render as much as its magnitude implies it should, check whether a
   renderer-side sample/draw-count cap is silently overriding it before
   concluding the trait itself needs a more extreme value — Red Maple's
   canopy stayed sparse after authoring dense-canopy traits because
   `SpeciesRenderer._draw_editor_plant_panel`'s `foliage_cap` parameter was
   capping per-cluster sample draws well below what the trait values and
   the panel's own performance budget could actually support.
5. **Document it**: which real photo(s) were used (URL + source), the two
   defects named, and the before/after evidence for each fix, in the
   species doc (§12).

### 9a-i. Artifact budget — keep renders to a minimum

Renders are debugging tools, not deliverables to accumulate. The first
two species run through this process (Jackal Buchu, Red Maple) generated
17 and 12 PNGs respectively — one `editor.png`/`before.png` and one
`editor_v2.png`/`after.png` per species would have told the same story.
Going forward:

- **Reuse fixed filenames, always overwrite.** Render to
  `artifacts/<species_id>/before.png`, `after.png`, and (only if actually
  needed) `detail.png` — never `_v2`/`_v3`/`_fixed`/timestamped variants.
  When a fix supersedes a render, re-render to the *same* filename and
  let it overwrite; don't keep the superseded version around "just in
  case." The species doc's prose carries the narrative of what changed
  between iterations — it does not need a separate image per iteration.
- **Cap the kept set at three images per species**: `before.png` (skip
  entirely if the species started as a bare stub with no prior render
  worth showing — the doc can say so in prose instead), `after.png` (the
  final state, produced once every fix in the pass has landed), and at
  most one `detail.png` close-up, and only when a specific feature (a
  pixel asset, a small structural artifact) is genuinely illegible at
  whole-plant scale.
- **Don't keep tool byproducts as documentation evidence** —
  `_variation.png` grids, growth-stage galleries, comparison images,
  isolated asset-icon montages, and debug crops taken mid-investigation
  are fine to *look at* while working, but delete them once the pass is
  done unless a specific requirement genuinely needs that evidence kept
  (e.g. §9's "growth-stage view when the mechanism changes with age" —
  even then, keep one such image, not one per iteration). Small non-image
  evidence (the growth-gallery JSON metrics report) is cheap and can stay.
- **Delete, don't archive, once superseded.** If an intermediate render
  turns out to be needed for the doc's bug narrative (e.g. showing a
  specific defect that the final `after.png` no longer exhibits), that is
  what `before.png` is for — describe intermediate stages in prose, not
  in additional kept files.

## 10. Tests required in proportion to the change

At minimum cover:

- the selected species' actual Plantae or Fungi membership and correct taxonomic parent;
- exact ontology → resolved entity → blueprint field transport;
- fingerprint changes when a behavior-changing field changes;
- deterministic snapshots for equal seed/inputs;
- finite, bounded geometry and resource pools;
- valid parent indices and attachment sockets;
- expected A/B response direction;
- zero, missing and `other_unknown` behavior;
- blueprint/snapshot serialization round trip;
- stable canonical ecological metrics across LODs;
- reuse by an unrelated synthetic species fixture;
- BioSim handoff when the field affects ecology.

New tests read only committed files (§1a): no local recipes, no
`tools/render_*.py` imports.

Start with the focused tests for touched systems, for example:

```powershell
py -m pytest tests/test_species_editor.py tests/test_species_simulation.py -q
py -m pytest tests/test_root_growth.py tests/test_species_diagnostics.py -q
py -m pytest tests/test_biosphere_soil_nutrients.py tests/test_biosphere_soil_succession.py -q
```

Then run the broader neighboring regression set. Also run:

```powershell
py -m py_compile PATHS_YOU_CHANGED
git diff --check
```

Do not claim the full test suite passed unless you actually ran it.

## 11. Real-app check

Attempt:

```powershell
py -m app.app
```

Open the species card and Species Sim/Species Editor if the environment permits
GUI control. Verify the selected species, mature preview, relevant diagnostic
tab and any saved field.

If the environment cannot inspect the Pygame surface, use the production
`SpeciesRenderer` in a headless preview and say exactly that it is a renderer
preview, not proof of live navigation.

## 11a. Last pass: find a generalization-test candidate

Once the field composition, any mechanism/grammar fix, and the assets are
verified, do one more search before writing the final document: look
through the live ontology for another plant or fungal species that would exercise
the same reusable code path this pass just relied on or fixed, but with a
genuinely different combination of the traits that drive it — not a
near-duplicate of the species just finished.

1. Identify the 2-4 fields that actually drove this pass's mechanism/grammar
   behaviour (not just any authored field) — e.g. for the Jackal Buchu pass
   that would be `plant_growth_form=shrub` and `mature_height_class=dwarf`
   (the combination that exercised the internode-scaling fix in §6/§6a).
2. Query the live ontology (`PlantCatalogue`-derived species list plus
   `WorldModel.resolved_species_entity`) for another species that matches
   on the field(s) that trigger the same code path but differs on at least
   one other dimension that would meaningfully stress it differently
   (a different family, a different height/behaviour combination, a
   different life form, etc.) — something that would plausibly render or
   behave differently through the same mechanism, not just confirm the
   same result twice.
3. Report what was found: candidate id/common name, which aspects match
   (why it would hit the same code path) and which differ (why it's a
   genuinely different combination worth trying), as a documented option
   in the final response — do **not** author or implement it without being
   asked, the same way §13's nitrogen-fixation candidate is a standing
   option, not a task queued for autonomous execution.
4. If no real candidate exists in the live ontology, say so explicitly —
   that the current trait combination is presently unique is itself useful
   information, not a failed search.

## 12. Documentation and final delivery

Create `docs/species_sim_<species-or-field>_v001.md` (kept locally, not
committed, §1a) containing (image
links per §9a-i's budget — before/after/one detail, not every iteration):

1. live ontology identity, actual Plantae/Fungi ancestry evidence and starting fields;
2. complete authored field table with reason/confidence per field, as
   reported by the research;
3. selected underdeveloped field and baseline defect;
4. reusable mechanism and explicit assumptions;
5. comparison setup, paths and observed metrics;
6. refinement decisions;
7. the §9a real-photograph critique: source photo(s)/URLs, the two named
   defects, and the before/after evidence for each fix;
8. exact test commands/results;
9. remaining biological and simulation limits;
10. whether the real app or only the production renderer was inspected;
11. the §11a generalization-test candidate, or an explicit note that none
    was found.

Final response format:

Embed the saved multi-view `after.png` directly in the final response, as
the standard visual presentation. Lead with the resulting appearance and
behavior, then give concise verification and material limits; link the
implementation record for detailed evidence. State whether the sheet is a
production renderer preview or a verified live-app capture.

```text
Outcome first: what the species now does and looks like.
Ontology: what was authored, inferred, corrected or deliberately left unknown.
Mechanism: which reusable code path changed; state that no species-ID branch exists.
Evidence: comparison image and metrics paths.
Reference check: photo source(s) and the two defects found/fixed against them.
Verification: exact tests and app/renderer status.
Limits: what is still qualitative, unresolved or out of scope.
Next candidate: the §11a generalization candidate found, or "none found".
```

Use clickable absolute file links when the client supports them.

## 13. Resolved: nitrogen-fixing candidate (was open, now closed by Silver Wattle)

This section originally flagged that no species had
`nitrogen_fixation = active` or `associated`. Resolved by
`spec_acacia_dealbata` (Silver Wattle) — see
`docs/species_sim_acacia_dealbata_v001.md`. The verification steps this
section used to prescribe (compare explicit `active` against a `none`
override at identical soil N/P; confirm the N-fixation flux appears while
neither treatment creates phosphorus) were run and passed, and are now
the pattern any future N-fixation species pass should repeat — see
`tests/test_species_data_acacia_dealbata.py::test_nitrogen_fixation_adds_a_real_flux_without_creating_phosphorus`.

The original candidate this section flagged, still untouched, is now the
§11a generalization-test follow-up from the Silver Wattle pass:

```text
id: spec_cakkuabdra_haematocephala
common_name: Red Powder Puff
stored binomial_name: Cakkuabdra haematocephala
parent chain: cladis_calliandra
  → cladis_mimosid_clade_mimosoideae
  → cladis_peacock_flowers_caesalpinioideae
  → cladis_bean_family_fabaceae
```

It is the *only other* Fabaceae species in the entire live ontology, and
per its likely intended taxon (*Calliandra haematocephala*) it is a
shrub, not a tree — a genuinely different growth form to test the
N-fixation path against, unlike simply repeating Silver Wattle's tree
combination. The stored binomial evidently intends *Calliandra
haematocephala* but contains a spelling error, still unresolved:

1. verify the accepted taxon and the intended entity;
2. ask for or confirm permission before correcting stable identity/binomial
   data rather than silently repairing it;
3. author `active` only if the retained species-level evidence supports a
   functional fixing symbiosis — do not use family membership alone to
   mark every Fabaceae species as an active fixer, the field is
   species-level and functional, not a taxonomic shortcut.

## 14. Common failure modes

- Reading only `ontology/index0.owl` and missing newer live-store data.
- Creating another `tools/author_<species>.py` for routine species-card field
  updates instead of using `tools.author_plant_species` with dry-run review.
- Matching a plant by name instead of checking Plantae ancestry.
- Treating inherited consensus as authored species evidence.
- Filling unknown fields with plausible guesses.
- Persisting a visual calibration as a measured trait.
- Writing a species-ID conditional into the grammar.
- Changing render detail and accidentally changing ecological quantities.
- Showing different camera scales as if they were a biological contrast.
- Generating the “before” image after changing the code.
- Editing the live store but failing to reload and verify it.
- Exporting or reimporting the checkpoint in the wrong direction.
- Claiming live UI verification after only rendering an off-screen preview.
- Reverting unrelated files in the already-dirty worktree.
- Declaring a render "verified" from a glance instead of actually judging
  it against real reference photographs (§9a) — a render can run cleanly
  through the whole pipeline and still look nothing like the species.
- Baking an asymmetric detail (a side fork, an attached leaf) into a
  stem/branch/root module image — it gets replicated at every segment
  across the whole plant (§6a).
- Skipping the §5a questionnaire hand-off and researching the species
  directly without the user asking for that.
- Authoring `plant_flowering_position` as `Terminal` just to make flowers
  render, when the species' real biology is lateral/axillary — for a
  single-shoot-system tree (`tree_shoots.py`'s grow_tree_shoots), only
  `Terminal` flowering position (or a dimorphic short-shoot species)
  currently produces any flower placement at all; genuinely lateral
  flowering on a single shoot system has no rendering path yet (found on
  the Silver Wattle pass — see `species_sim_acacia_dealbata_v001.md`
  §8a). Document this as a limitation instead of mis-authoring the field.
- Hand-editing a shared grammar constant (e.g. a `_crown_shape_targets`
  tuple in `tree_shoots.py`) to fix one species' silhouette instead of
  adding a new continuous authored field it can dial in (§6f) — the fix
  works but isn't reproducible by a future authoring pass without another
  code edit.
- Leaving a leaf/flower/fruit/stem/branch/root organ on the generic
  per-kind fallback shape/colour when an authored pixel asset was
  achievable in scope, or painting pixel art from imagination instead of
  a real reference photograph of the actual organ, or picking a
  hand-guessed canvas resolution instead of the live app's own
  size-to-pixel-canvas formula (§6g).
- Authoring a leaf/flower/fruit module's `depicted_size_m` to match a
  cluster unit's size (a shoot, a spikelet) instead of the real
  single-organ measurement, without first checking every place
  `blueprint.module(kind).length_m` is read — it usually drives real
  structural formulas (shoot length, leaf area) elsewhere in the grammar,
  not just render scale (§6g).
- Sampling many individual small-organ placements (one per needle, one
  per tiny scale leaf) to make a dense canopy read as full, when the
  natural cluster unit (a needle-clad shoot) would be both the correct
  visual granularity and the only tractable render cost at forest scale
  (§6g).
- Calling a render "fixed" from a quick glance or a one-line visual
  impression instead of actually scrutinizing the PNG against the
  reference photographs — a fix that is a real, measurable improvement
  over the previous defect can still look wrong on its own terms (§6k: a
  ladder-rung leaf placement "fixed" into a rigid radial starburst, caught
  only because the user insisted on looking at the actual image).
