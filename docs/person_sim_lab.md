# Person Simulation Laboratory

The laboratory is a deterministic view into the real Person Simulation. It does not copy movement, task selection, needs, control, or rendering logic. Instead, it imports the production `PersonSimulation`, `PersonRenderer`, and `Camera`, supplies a small ontology-shaped fixture, and sends pointer events through the production simulation interface.

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
- `person_sim_lab_report.json`

The screenshots are shared visual checkpoints. The final two render the production person UI over the production simulation, using a fixture person with explicitly authored wishes, goals, Big Five scores, and adjective markers. The JSON report records the active production class names, positions, needs, active task, queue, work progress, panel models, and status at each checkpoint. Rerun the laboratory after implementation changes to refresh every artifact.

Each run also fingerprints the production simulation, renderer, person UI, clock, simulation manager, and camera source files. To detect screenshots left stale by a later code change, run:

```powershell
& 'C:\Users\logol\Index\.venv\Scripts\python.exe' tools\run_person_sim_lab.py --check-current
```

The check fails explicitly until the laboratory is rerun against the changed implementation.
