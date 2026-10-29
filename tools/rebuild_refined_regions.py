"""Rebuild stored refined regions from their parents with the current world-generation code.

A refined region keeps the rasters it was generated with; a change to world
generation reaches it only when it is generated again.  This opens each
region's map in the real application (headless) and runs the application's
own rebuild action, so the region keeps its id and footprint and is stored
the way a rebuild from the sidebar would store it.

    python tools/rebuild_refined_regions.py refined_lod4_e7fa59b8b3 refined_lod5_0df56ec100

Give parents before children: a rebuilt parent forgets the children it
listed, and each child re-attaches itself when it is rebuilt in turn.

The application must be closed (two writers on the ontology store are not
safe); the script refuses to start while one is running.  About a minute per
region.  Screenshots before and after go to ``.cache/screenshots/rebuild``.
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def running_applications():
    """Command lines of other processes that have the application open."""
    try:
        listing = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_Process -Filter \"Name like 'python%'\" | ForEach-Object { $_.CommandLine }"],
            capture_output=True, text=True, timeout=60,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    return [line.strip() for line in listing.splitlines() if "app.app" in line]


def main(argv=None):
    region_ids = list(argv if argv is not None else sys.argv[1:])
    if not region_ids:
        print(__doc__)
        return 2
    open_applications = running_applications()
    if open_applications:
        print("The application is open; close it first:")
        for line in open_applications:
            print("  ", line)
        return 1

    sys.path.insert(0, str(PROJECT_ROOT / "tools"))
    import app_driver  # before anything else that imports pygame

    from simulations.world_gen.regional_refinement import map_physical_dimensions_m

    driver = app_driver.Driver("rebuild", PROJECT_ROOT / ".cache" / "screenshots" / "rebuild")
    world = driver.app.world_model
    for region_id in region_ids:
        before = world.get_entity(region_id)
        if not isinstance(before, dict) or before.get("location_role") != "map_refinement_region":
            print(f"{region_id}: not a stored refined region, skipped")
            continue
        revision = int(before.get("refinement_revision", 0) or 0)
        driver.app.navigation.open_region_map_tab(region_id)
        driver.frame(4)
        simulation = driver.sim()
        if simulation is None or simulation.context.root_entity_id != region_id:
            print(f"{region_id}: its map did not open, skipped")
            continue
        print(f"{region_id}: before {driver.shot(region_id + '_before').name}", flush=True)
        began = time.time()
        rebuilt = driver.app.navigation._handle_simple_ui_action("regenerate_current_region", simulation)
        driver.frame(4)
        after = world.get_entity(region_id) or {}
        width_m, height_m = map_physical_dimensions_m(after)
        landforms = [
            item.get("landform") for item in
            ((after.get("heightmap_model") or {}).get("regional_landforms") or {}).get("landforms") or []
        ]
        print(
            f"{region_id}: {'rebuilt' if rebuilt else 'NOT rebuilt'} in {time.time() - began:.0f} s; "
            f"LOD{after.get('map_detail_level')} {width_m:.0f} x {height_m:.0f} m, "
            f"revision {revision} -> {after.get('refinement_revision')}, "
            f"rivers {len((after.get('water_cycle_model') or {}).get('rivers') or [])}, landforms {landforms}; "
            f"after {driver.shot(region_id + '_after').name}",
            flush=True,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
