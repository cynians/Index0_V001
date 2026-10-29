"""Run a sequential slice of the alternating production edge-stress series."""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from simulations.world_gen.headless_runner import (
    HeadlessWorldGenConfig,
    run_isolated_headless_worldgen,
)


CENTERS = (
    (0.2, 0.2), (0.8, 0.2), (0.2, 0.8), (0.8, 0.8),
    (0.5, 0.2), (0.5, 0.8), (0.2, 0.5), (0.8, 0.5),
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("start", type=int)
    parser.add_argument("end", type=int)
    args = parser.parse_args()

    series = ROOT / "artifacts" / "worldgen" / "retained" / "edge-stress-series"
    for index in range(args.start, args.end + 1):
        mode = "eccentric" if index % 2 else "generic"
        output = series / f"{index:02d}-{mode}.i0wg"
        center_x, center_y = CENTERS[(index - 1) % len(CENTERS)]
        result = run_isolated_headless_worldgen(
            HeadlessWorldGenConfig(
                name=f"Edge Stress {index:02d} {mode.title()}",
                randomize_mode=mode,
                randomizer_seed=42000 + index,
                regional_refinement_depth=2,
                regional_center_x=center_x,
                regional_center_y=center_y,
                render_outputs=False,
            ),
            bundle_path=output,
            retention="retained",
            project_root=ROOT,
        )
        summary = result.summary
        print(
            json.dumps(
                {
                    "index": index,
                    "mode": mode,
                    "template": (
                        summary.get("generated_seed") or {}
                    ).get("planet_template"),
                    "atmosphere": summary.get("atmosphere_class"),
                    "temperature_k": summary.get("surface_temperature_k"),
                    "pressure_bar": summary.get("surface_pressure_bar"),
                    "ocean_fraction": summary.get("ocean_fraction"),
                    "river_count": summary.get("river_count"),
                    "bundle": result.bundle_path,
                },
                sort_keys=True,
            ),
            flush=True,
        )


if __name__ == "__main__":
    main()
