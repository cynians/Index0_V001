# Person Simulation Laboratory

The laboratory is a deterministic view into the real Person Simulation. It does not copy movement, task selection, needs, control, navigation, or rendering logic. Instead, it imports the production `PersonSimulation`, `PersonRenderer`, and `Camera`, supplies a small ontology-shaped fixture, and sends pointer events through the production simulation interface.

Simulation advancement uses the normal production chain: `Clock` to `SimulationManager` to `PersonRuntimeSystem`. Screenshots use the production renderer. This prevents a separate test implementation from drifting away from what appears in the application.

Run it from the project root with:

```powershell
& 'C:\Users\logol\Index\.venv\Scripts\python.exe' tools\run_person_sim_lab.py
```

The generated files appear in `artifacts/person_sim_lab/`:

- `01_autonomous_initial.png`
- `02_autonomous_running.png`
- `03_player_forced_queue.png`
- `04_direct_control.png`
- `05_needs_panel.png`
- `06_personality_panel.png`
- `07_knowledge_panel.png`
- `08_tasks_panel.png`
- `09_kitchen_workflow.png`
- `10_meal_completed.png`
- `11_wayfinding_asks.png`
- `12_site_population_context.png`
- `13_site_map_authoring_context.png`
- `person_sim_lab_report.json`

The screenshots are shared visual checkpoints. The map is the ontology-shaped lumber test site: western wild terrain, developed yard, worker barracks, attached kitchen, storage facility, factory hall, authored wall openings, and four residents (two women and two men) assigned as one cook, two laborers, and one overseer. Movement uses the production wall-aware route planner, so structures can be entered only through their openings. The final screenshots render the production person UI over the production simulation, using Mara Voss, the cook, with explicitly authored wishes, goals, Big Five scores, categorized knowledge, interest values, and a strongly held nonviolence conviction. The task panel includes a coerced conflicting assignment so its score, conviction penalty, and reassignment response remain inspectable. The JSON report records the active production class names, positions, needs, active task, queue, work progress, panel models, inventory, and decision explanations. Rerun the laboratory after implementation changes to refresh every artifact.

The kitchen checkpoints exercise the compound food task through the production implementation: collect institution-owned ingredients, travel to the kitchen, validate the person's recipe knowledge against the kitchen production line, its Cooking and Electric Oven Cooking technologies, and its Sink and Electric Oven components, then cook and eat the resulting item. The report records lifecycle transitions, the runtime inventory, recipe recognition, and resulting food fulfillment.

The wayfinding checkpoint assigns the western wood lot to Mara. She knows only that it lies west, begins in that direction, and then seeks directions from another resident when her directional certainty is exhausted. The task panel and JSON report expose the current wayfinding mode, destination, heading, named person being asked, and navigation-decision history.

The two site checkpoints verify the two location launch contexts against the active ontology. `12_site_population_context.png` opens Site Simulation and overlays authored workers, three full pop representatives, the remaining village population aggregate, authored and provisional visitors, and named lightweight travellers on the shared local geometry. It also records Elda Marr's pending lumber-sale decision for overseer Tomas Rhee. `13_site_map_authoring_context.png` opens the ordinary Map context and renders the same encoded bounds, village, road, barracks, kitchen, storage, and factory without projecting runtime people into the map data.

Each run also fingerprints the laboratory harness, production simulation, renderer, person UI, ownership resolver, clock, simulation manager, and camera source files. To detect screenshots left stale by a later code change, run:

```powershell
& 'C:\Users\logol\Index\.venv\Scripts\python.exe' tools\run_person_sim_lab.py --check-current
```

The check fails explicitly until the laboratory is rerun against the changed implementation.
