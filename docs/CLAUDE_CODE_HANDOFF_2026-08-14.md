# Claude Code Handoff — 2026-08-14

## Repository state

- Workspace: `C:\Users\logol\PycharmProjects\Index0_V001`
- Current branch: `codex`
- Starting commit for this work: `6666a29 version 0.1.51`
- The work described below is not committed or staged.
- Preserve the existing dirty worktree. Do not reset or overwrite it.
- The six untracked pixel-dragonfly illustration files under `assets/illustrations/` were not created as part of the person/site work and should be treated as user-owned unrelated files.

## Architectural rules confirmed today

1. The ontology is the sole durable source of entities and semantic facts. Python dictionaries, renderer palettes, indexes, and projections may only be disposable caches constructed from ontology state.
2. Ontology mutations are staged and become durable only when the user explicitly saves. Do not silently persist runtime simulation state.
3. World generation does not need legacy compatibility. No generated planets are currently intended to remain persistent while worldgen matures.
4. Planetary true-color, height, material, and Köppen views are abiotic. Vegetation belongs to a future Biosphere layer and simulation; do not paint generic green vegetation into these layers.
5. A simulation mode is a viewpoint over shared ontology facts, not a second source of world truth.

These rules are recorded in `docs/conceptual_layer_overview_v006.txt` and in architecture notes at the top of relevant worldgen/map files.

## Major person-simulation work completed

### Embodied person runtime

`simulations/person/person_simulation.py` now contains the production person-control vertical slice rather than a detached mock. It supports:

- autonomous RimWorld-like task selection and direct click control;
- needs and nonlinear urgency, including food and rest;
- wishes and goals;
- Big Five personality values;
- categorized knowledge with interest, familiarity, stance, and conviction;
- internally generated intentions and externally assigned duties;
- inspectable scoring and plain-language decision explanations;
- duty/need/conviction conflicts and alternative assignments;
- task lifecycle states and interruptions;
- item possession and institution-owned storage;
- recipe-driven food production and consumption;
- wall/opening-aware movement;
- knowledge-bounded pathfinding: known routes, direction-only travel, continuing uncertainly, or asking another person for directions.

### Person UI

`ui/ui_manager.py` and `simulations/person/person_renderer.py` now provide:

- a compact time strip at the top;
- a compact dossier at the bottom/left instead of the former debug dump;
- separate right-side overlays for Needs, Personality, Knowledge, and Tasks;
- a Maslow-style needs pyramid plus Wishes and Goals;
- a five-axis Big Five radar view;
- knowledge grouped by card/entity category;
- task provenance, score contributions, conflicts, and recent decision history.

### Ownership, items, kitchen, and production

New or expanded code includes:

- `world/ownership_resolver.py`
- `tools/author_person_food_ownership_model.py`
- `ui/card_production.py`
- `ui/card_site.py`

The active ontology was authored with ownership records, item inventory fields, a Recipe entity type, a test kitchen, Cooking and Electric Oven Cooking technologies, Sink and Electric Oven components, ingredients, a cooked meal, and employment/job links.

The food workflow is currently:

1. Person becomes hungry.
2. Person knows `recipe_simple_cooked_meal`.
3. Person collects institution-owned ingredients from the pantry.
4. Person moves through authored openings to the kitchen.
5. The production line verifies recipe, required components, and employed technologies.
6. A cooked-meal item enters transient possession.
7. The person eats it and food fulfillment rises.

Production records of the old form “Producer X — Production of Item Y” are no longer required as separate card state when the same relationship is implicit in the producer's Production tab and the produced vehicle/item.

## Lumber Processing Test Site

The ontology-backed test site is `location_lumber_test_site`. Its shared encoded geometry includes:

- expanded local bounds of roughly 145 × 145 metres;
- western wild terrain/wood lot;
- developed lumber yard;
- worker barracks;
- attached kitchen;
- storage facility;
- lumber factory hall;
- eastern road/logistics placeholder;
- northern `North Road Village`.

Four authored workers live at the site: two women and two men, assigned as one cook, two laborers, and one overseer.

The northern village is owned by `institution_test_city_council` and contains `pop_lumber_neighbor_village`, a 30-person cultural pop. The site projection creates:

- three deterministic full representative villagers;
- one aggregate representing the remaining 27 generic villagers;
- authored visitor Elda Marr, seeking lumber for house repairs;
- named horse driver Orin Pell, materialized on site entry;
- municipal inspector Ilyra Sen, plausibly sourced from `pop_test_city_population_1` because the council owns the village;
- named lightweight travellers Saro Kest and Vela Dorn, promoted to full people when interacted with.

Elda's request creates a pending sell/refuse proprietor decision assigned to overseer Tomas Rhee. This is presently an external task allocation and not yet a polished decision-dialogue UI.

## Two distinct location launch contexts

This was the final correction and must be preserved.

A compatible site/location card now presents two launch buttons:

1. **Map**
   - Launch mode: `map`
   - Opens the authored location/map workspace.
   - Displays and edits ontology-encoded bounds, road, village, buildings, openings, and future surface layers.
   - Does not contain runtime people, their queues, or movement state.

2. **Site Simulation**
   - Launch mode: `site_people`
   - Opens `SiteSimulation` from `simulations/person/site_simulation.py`.
   - Consumes the same ontology geometry as Map.
   - Adds authored people, pop representatives, aggregate populations, provisional visitors, and person runtime state.

Relevant integration points:

- `app/launch_affordance_resolver.py`
- `app/navigation_controller.py`
- `engine/renderer.py`
- `ui/ui_manager.py`
- `simulations/map/map_simulation.py`
- `simulations/person/site_simulation.py`

Local maps use `map_coordinate_space = "site_meters"`, with one world unit equal to one metre. Planetary hierarchy zoom thresholds are disabled for this context so buildings do not disappear at the overview zoom. This fixed the earlier blank “Lumber Processing Test Site” map.

## Scale-aware population projection

`SitePresenceResolver` implements the current fidelity policy:

- authored people: full individual simulation;
- selected pop representatives: deterministic full people;
- unselected pop remainder: aggregate count;
- plausible named travellers: lightweight records;
- meaningful interaction: promote lightweight record to a full runtime person;
- promoted encounters survive closing/reopening the site simulation during the same application process through a session encounter cache;
- cross-process persistence is intentionally not implemented yet because it must go through explicit staged ontology authoring and Save.

Do not “solve” cross-restart persistence by writing directly into map data or silently mutating the persistent ontology.

## Shared live test laboratory

`tools/run_person_sim_lab.py` imports and executes production simulation, renderer, camera, UI, ownership, and map code. It is specifically meant to prevent a mock test environment from drifting away from the real app.

Artifacts are in `artifacts/person_sim_lab/`. The latest relevant checkpoints are:

- `12_site_population_context.png`: Site Simulation with workers, representatives, aggregate villagers, visitors, travellers, road, village, and buildings.
- `13_site_map_authoring_context.png`: ordinary Map view over the same encoded geometry and no runtime people.
- `person_sim_lab_report.json`: structured provenance and population/map assertions.

The laboratory fingerprints its implementation sources. After changing any participating production file, rerun it and then check freshness:

```powershell
C:\Users\logol\Index\.venv\Scripts\python.exe tools\run_person_sim_lab.py
C:\Users\logol\Index\.venv\Scripts\python.exe tools\run_person_sim_lab.py --check-current
```

## Verification completed

The final focused suite passed 45 tests:

```powershell
C:\Users\logol\Index\.venv\Scripts\python.exe -m unittest tests.test_site_simulation tests.test_author_person_food_ownership_model tests.test_navigation_building tests.test_person_simulation tests.test_person_ui_panels
```

`git diff --check` also passed. The only output was the repository's existing LF-to-CRLF warning.

The site lab report currently verifies:

- local bounds: `min_x=-70`, `max_x=75`, `min_y=-90`, `max_y=55`;
- ten full runtime people;
- two named lightweight travellers;
- 27 villagers represented in aggregate;
- one pending Elda/Tomas proprietor decision;
- seven authored map layers: root site, village, road, factory, barracks, storage, and kitchen;
- map unit scale of one metre per world unit.

## Current limitations and recommended continuation

The cleanest next vertical slice is encounter persistence and site interaction:

1. Add a staged ontology-authoring record for a promoted lightweight person. It should appear in the repository's unsaved-change state and only become durable on Save.
2. Add a selected-person/site dossier so clicking a person opens their needs, personality, knowledge, source pop, purpose, and task state.
3. Turn the pending Elda lumber request into a transparent decision interaction for Tomas/the responsible proprietor, with sell/refuse consequences.
4. Connect the east road placeholder to skeletal logistics: arrivals, cargo/passengers, travel origin, and departure.
5. Add scale adapters so village/site/region maps choose appropriate representative and aggregate counts without simulating everyone.
6. Later connect the local representational height/true-color layers to worldgen/map data. Do not introduce vegetation there; biological surface color must come from Biosphere.

Visual cleanup is still possible. The Site Simulation is functional, but labels around the yard and village can overlap. Treat this as renderer/UI polish, not a data-model change.

## Mountain/worldgen context

The mountain-refinement concept is documented under “Planned Updates — Worldgen Update 1: Mountain Refinement” in `docs/conceptual_layer_overview_v006.txt`.

The recorded current foundation separates coarse crust thickness, strain, uplift, subsidence, volcanic construction, sediment load, flexure, isostasy, and mechanical-lithology response. Detailed 2.5D geological columns, vector faults/folds, and local structure-driven terrain remain the next fundamental mountain layers. The user prefers implementation followed by targeted live world generation and screenshots, not expensive broad automated worldgen runs.

## Important working-tree caution

There are substantial interdependent edits in person simulation, UI, navigation, authoring tools, tests, and documentation. Review the full diff before restructuring. In particular:

- do not delete or reset the untracked `site_simulation.py`, ownership resolver, authoring tool, or their tests;
- do not touch the unrelated untracked pixel illustration assets;
- do not reintroduce a separate semantic registry outside the ontology;
- do not merge Map and Site Simulation back into one mode;
- do not persist promoted people without the explicit Save workflow.
