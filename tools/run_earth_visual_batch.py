"""Run a sequential slice of the alternating Earthlike visual-fidelity series."""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from simulations.world_gen.headless_runner import (
    HeadlessWorldGenConfig,
    HeadlessWorldGenRunner,
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("start", type=int)
    parser.add_argument("end", type=int)
    args = parser.parse_args()

    series = ROOT / "artifacts" / "headless_worldgen" / "earth-visual-series"
    for index in range(args.start, args.end + 1):
        eccentric = index % 2 == 0
        mode = "eccentric" if eccentric else "generic"
        result = HeadlessWorldGenRunner(series / f"{index:02d}-{mode}").run(
            HeadlessWorldGenConfig(
                name=f"Earth Visual {index:02d} {mode.title()}",
                template_id="oxygenated_ocean_plate_world",
                map_seed=f"earth-visual-{index:02d}",
                periapsis_au=0.88 if eccentric else 1.0,
                apoapsis_au=1.12 if eccentric else 1.0,
                radius_earth=1.0,
                core_radius_fraction=0.55,
                crust_thickness_km=35.0,
                angular_velocity_deg_per_hour=15.0,
                water_fraction=0.71,
                volatile_inventory="earthlike",
                tectonics_mode="mobile_lid",
            )
        )
        summary = json.loads(Path(result.summary_path).read_text(encoding="utf-8"))
        print(
            json.dumps(
                {
                    "index": index,
                    "mode": mode,
                    "temperature_k": summary.get("surface_temperature_k"),
                    "pressure_bar": summary.get("surface_pressure_bar"),
                    "ocean_fraction": summary.get("ocean_fraction"),
                    "river_count": summary.get("river_count"),
                    "contact_sheet": result.contact_sheet,
                },
                sort_keys=True,
            ),
            flush=True,
        )


if __name__ == "__main__":
    main()
