# City Prototype Creation Process

How to build a city prototype from nothing by walking the real application:
generate a planet, refine down to a town-sized site, found a city on it,
sharpen a parcel, place a building, and check the city from its parent maps.

Treat "city prototype", "create a city prototype", or "walk the city
creation" as a reference to this document. It is the process; the design is
in [city_simulation_concept_v001.md](city_simulation_concept_v001.md).

First run: 2026-10-01, producing `planet_cityworld_prototype` and
`city_refined_lod4_e7fa59b8b3_01` in Test System Prime (§6).

## 1. Ground rules

1. **The application must be closed.** The run writes to the live ontology
   store; two writers are not safe.
2. **Everything is real.** The driver starts the actual `App`. Every planet,
   region, city and building it creates persists. There is no sandbox. A
   mis-scripted click is a real edit: the first run dropped a barracks into
   the river that way.
3. **Do it through the UI.** Buttons, clicks, wheel, keys. Programmatic
   shortcuts are allowed only to *resume* (reopening a region map), and are
   logged as shortcuts.
4. **Look at the screenshots.** Assertions say the state changed; only the
   picture says the map shows it. Two real bugs in this run were visible only
   in images (§5).
5. **Long steps go to the background** and the run must be resumable.
   Generation is about a minute per LOD.
6. A store backup from before the first run is in
   `artifacts/city_simulation_model/`.

## 2. Tooling

| File | Purpose |
|---|---|
| `tools/app_driver.py` | `Driver`: headless SDL, 1600x900 window, queued events through the app's own `_process_events` / `_update_frame` / `_render_frame`, screenshots, helpers for cards, buttons, wheel, drag. Isolates the card-draft cache. |
| `tools/city_prototype_walkthrough.py` | The whole process as resumable stages. State and screenshots under `.cache/city_prototype/<slug>/`. |

```bash
"C:\Users\logol\Index\.venv\Scripts\python.exe" tools/city_prototype_walkthrough.py --name "Cityworld Prototype"
```

Stages: `planet refine found patch blueprint parents`. Run a subset with
`--stages`, limit work per run with `--max-rolls` and `--max-refinements`.

Driver facts worth knowing:

- Import `app_driver` before anything that imports pygame.
- Drive frames with `Driver.frame()`. Calling `app.draw()` directly skips
  the screen clear and ghosts the previous screen into the shot.
- A card with one launch affordance shows a single button (`launch_rect`),
  not a mode row. `launch_from_card` handles both.
- Wheel zoom is anchored on the cursor. Left-drag pans.
- Sidebar buttons report plain string ids; card and designer actions report
  dicts.

## 3. The process

### 3.1 Planet (World Gen)

1. Repository: search the star system, open its card, press **World Gen**.
2. Click the orbit view once for a circular orbit. **The radius decides the
   climate.** Around Test System Prime's star, 0.957 AU gives about 297 K
   estimated surface temperature; 1.185 AU froze every roll, although the
   orbit tooltip there promised +20 °C.
3. **Enter**, type the name, **Enter**.
4. Press **Random Generic**, then the primary button at every stage: crust,
   atmosphere, regime, terrain (about 40 s), heightmap (about 30 s), water
   cycle.
5. Judge the result before completing. Wanted: ocean 30–80 %, mean
   temperature 281–298 K, at least five rivers, some temperate land.
6. If not: **Back** (confirm with Enter) five times to the crust stage, press
   **Random Generic** again, repeat. About 2.5 minutes per roll.
7. **Complete Worldgen**.

Do not use the "Oxygenated ocean plate world" template for this: it gave 97 %
ocean. Do not put the planet on an orbit another planet already uses: the two
overlap exactly on the orbit view and cannot be told apart by clicking.

### 3.2 Refinement (Map)

Open the planet's card and press **Map**. Per level:

1. Choose the site from the map's own data (`pick_site`): a point on a river,
   scored by Köppen class, discharge, perennial flow, flatness and, for LOD1
   and LOD2, nearness to a coast.
2. Drag the point to the screen centre, wheel in until the visible width is
   the target.
3. Press **Refine View to \<Level\>** (sidebar, TERRAIN). The whole screen is
   the window, so regions come out 16:9. The new region opens in its own tab.

| Level | Target width | First run | Time |
|---|---:|---|---:|
| 1 Macroregion | 1,600 km | 1,604 x 902 km | 58 s |
| 2 Region | 160 km | 158 x 89 km | 96 s |
| 3 Local | 20 km | 20.5 x 11.5 km | 69 s |
| 4 Site | 3.2 km | 3.07 x 1.73 km | 62 s |

### 3.3 City

1. On the LOD4 map the sidebar's **TERRAIN** section offers **Found City
   Here**. Press it; the city map opens, in metres.
2. In the city map, frame a parcel about 300 m wide and press **Refine View
   to Parcel**. The LOD5 patch is refined from the region underneath
   and composited into the city map; the city map stays open. First run:
   302 x 170 m at 0.79 m per sample, 78 s.

### 3.4 Building

1. Repository: open a blueprint's card, press **Blueprint Designer**.
2. **Place on Map**, pick the city.
3. The map opens with the building on the cursor. Left click places, so do
   not drag: wheel in on the spot itself, move, click.
4. Over open water the ghost turns red and the click is refused.

### 3.5 Parent maps

**Up To Parent** from the city leads to its region, then up to the planet.
On each map the city is a marker with its name, plus its footprint outline
once that spans 18 px. Clicking the marker selects the city; **Open Map** on
its selection card opens it.

## 4. What to check

- [ ] Planet verdict line in the log (ocean, temperature, rivers).
- [ ] Each region's size and that a new tab opened.
- [ ] City bounds equal the region's physical size; map is in metres.
- [ ] Patch exists, city map still open, ground inside the patch is sharper.
- [ ] Building's parent is the city; ground LOD under it is the patch's.
- [ ] City marker present on every parent map up to the planet, absent on
      the star system.
- [ ] Screenshots looked at, not only produced.

## 5. Obstacles met on the first run

Fixed:

| Obstacle | Fix |
|---|---|
| A map with a refined child showed that child's terrain as its own, stretched over the whole map (the planet showed its LOD1 patch). | `MapSimulation._own_generated_region` now leaves a map with its own terrain alone. |
| Composited patches drew as black holes. | `_composite_refined_surface` converts a base that has an alpha channel but no per-pixel-alpha flag. |
| At building zoom a patch was drawn from the 2048 px whole-map composite. | New native pass draws each patch from its own surface, feathered at the edges. |
| That pass re-rendered the patch's True Color every frame (3 s per frame). | Child surfaces are cached. |
| A city was invisible from every other map. | Marker and outline on the region and all ancestors; listed in the location tree; "Up To Parent" from the city. |
| Marker hit-test had an 8-world-unit floor, wider than a whole refined region. | Markers may carry `pick_radius_px`. |
| Buildings could be placed in a river. | Placement asks the map's ground substrate and refuses open water. |
| The old walkthrough driver imports `app` in a way that no longer works. | New driver; the old file is untouched. |

Open (not fixed, reported):

- The orbit tooltip's temperature is about 25 K too warm compared with the
  atmosphere stage.
- "Random Generic" often yields an all-ocean world: two of the four rolls here.
- A LOD5 patch is visibly darker than the LOD4 ground around it, so patches
  show as rectangles in the city overview. This is True Color lineage drift
  between levels, not compositing.
- A LOD1 region showed a striped oval artefact north of the site.
- Refined regions are all named "\<parent\> — \<Level\> Patch", so nested names
  truncate to the same text in every list, and the repository search cannot
  find a specific one by name.
- The water-cycle stage's right-hand panel overflows onto the Space Sim
  button.
- During blueprint placement there is no mouse pan (left places, right
  rotates); only wheel and keyboard.
- Frames are slow in a driven session, 0.3–1 s on large maps.

## 6. What the first run left in the ontology

| Entity | What |
|---|---|
| `planet_cityworld_prototype` | The prototype world: 60 % ocean, 285 K, 26 rivers. |
| `refined_lod1_c1de5f027b` … `refined_lod4_e7fa59b8b3` | The refinement chain. |
| `city_refined_lod4_e7fa59b8b3_01` "Settlement 1" | The city, 3071 x 1727 m, hot steppe (BSh), on an intermittent river. |
| `refined_lod5_0df56ec100` | The parcel patch inside the city. |
| `loc_bldg_lumber_worker_barracks_001` | One barracks on the patch. |
| `planet_city_prototype_world` | **Leftover.** The first attempt at 1.185 AU: frozen, generation abandoned mid-roll. Safe to delete. |
