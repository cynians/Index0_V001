"""Run the production world-generation route without opening a window."""

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from simulations.world_gen.headless_runner import (
    HeadlessWorldGenConfig,
    run_isolated_headless_worldgen,
)


def _parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", default="Headless Player Default")
    parser.add_argument("--template", default="silicate_terrestrial")
    parser.add_argument("--seed", default="auto")
    parser.add_argument("--output", default="")
    parser.add_argument("--water", type=float, default=0.5)
    parser.add_argument("--periapsis-au", type=float, default=1.0)
    parser.add_argument("--apoapsis-au", type=float, default=1.0)
    parser.add_argument("--radius-earth", type=float, default=1.0)
    parser.add_argument("--core-radius-fraction", type=float, default=0.55)
    parser.add_argument("--crust-thickness-km", type=float, default=35.0)
    parser.add_argument("--spin-deg-per-hour", type=float, default=15.0)
    parser.add_argument("--volatiles", default="earthlike")
    parser.add_argument("--tectonics", default="unknown")
    parser.add_argument(
        "--replay-contract",
        default="",
        help="Replay a persisted player first-screen generation contract exactly.",
    )
    parser.add_argument(
        "--randomizer",
        choices=("generic", "eccentric", "gas_giant"),
        default="",
        help="Use the production seed randomizer instead of authored physical inputs.",
    )
    parser.add_argument(
        "--randomizer-seed",
        type=int,
        default=None,
        help="Optional reproducibility seed; a random 64-bit seed is chosen when omitted.",
    )
    parser.add_argument(
        "--region-depth",
        type=int,
        default=0,
        help="Generate nested real regional refinements after the planetary run.",
    )
    parser.add_argument("--region-center-x", type=float, default=0.5)
    parser.add_argument("--region-center-y", type=float, default=0.5)
    parser.add_argument("--finish", action="store_true")
    parser.add_argument(
        "--render",
        action="store_true",
        help="Include stage and map-layer renders (disabled by default).",
    )
    parser.add_argument(
        "--no-render",
        action="store_true",
        help="Deprecated compatibility alias; rendering is disabled by default.",
    )
    parser.add_argument("--retain", action="store_true", help="Persist one validated .i0wg run bundle.")
    parser.add_argument("--pinned", action="store_true", help="Persist a pinned benchmark .i0wg bundle.")
    parser.add_argument("--retain-debug", action="store_true", help="Include rendered diagnostics inside a retained bundle.")
    return parser


def main(argv=None):
    args = _parser().parse_args(argv)
    config = HeadlessWorldGenConfig(
        name=args.name,
        template_id=args.template,
        map_seed=args.seed,
        periapsis_au=args.periapsis_au,
        apoapsis_au=args.apoapsis_au,
        radius_earth=args.radius_earth,
        core_radius_fraction=args.core_radius_fraction,
        crust_thickness_km=args.crust_thickness_km,
        angular_velocity_deg_per_hour=args.spin_deg_per_hour,
        water_fraction=args.water,
        volatile_inventory=args.volatiles,
        tectonics_mode=args.tectonics,
        randomize_mode=args.randomizer,
        randomizer_seed=args.randomizer_seed,
        regional_refinement_depth=max(0, args.region_depth),
        regional_center_x=max(0.0, min(1.0, args.region_center_x)),
        regional_center_y=max(0.0, min(1.0, args.region_center_y)),
        finish_worldgen=args.finish,
        render_outputs=bool(args.render or args.retain_debug) and not args.no_render,
        replay_contract_path=args.replay_contract,
    )
    retention = "pinned" if args.pinned else ("retained" if args.retain or args.output else "temporary")
    result = run_isolated_headless_worldgen(
        config,
        bundle_path=Path(args.output) if args.output else None,
        retention=retention,
        include_images=bool(args.retain_debug),
        project_root=PROJECT_ROOT,
    )
    print(json.dumps(asdict(result), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
