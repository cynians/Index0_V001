"""Run a fast, representative world-generation detail-chain scenario.

The scenario uses the production generic planet randomizer and production
regional refinement route. It keeps the randomized planet Earth-like enough
for terrain, climate, hydrology, coast, and material layers to participate,
then simulates the map UI zooming into one deterministic 100 km x 100 km
geographic window and pressing Regenerate Region.
"""

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from simulations.world_gen.headless_runner import (
    HeadlessWorldGenConfig,
    run_isolated_headless_worldgen,
)


DEFAULT_RANDOMIZER_SEED = 20260826


def _parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--randomizer-seed",
        type=int,
        default=DEFAULT_RANDOMIZER_SEED,
        help="Seed for the generic physical randomizer and default random center.",
    )
    parser.add_argument(
        "--depth",
        type=int,
        default=7,
        help="Number of nested detail levels to generate (0-7; default: 7).",
    )
    parser.add_argument(
        "--width-km", type=float, default=None,
        help="Override the first refinement width; otherwise use --lod-footprints-km.",
    )
    parser.add_argument(
        "--height-km", type=float, default=None,
        help="Override the first refinement height; otherwise use --lod-footprints-km.",
    )
    parser.add_argument(
        "--lod-footprints-km",
        default="1000,100,25,6.25,1.56,0.39,0.10",
        help="Per-level square footprints in km (LOD1..LOD7); default includes a 100 km LOD2.",
    )
    parser.add_argument(
        "--scientific-samples",
        default="513x257",
        help="Fast diagnostic LOD0 support; use at least 1025x513 for canonical acceptance (default: 513x257).",
    )
    parser.add_argument(
        "--regional-samples",
        default="257x257",
        help="Scientific sample grid for the requested regional tile (default: 257x257).",
    )
    parser.add_argument(
        "--feedback-iterations",
        type=int,
        default=1,
        help="Bounded climate/landscape feedback passes for this scenario (default: 1).",
    )
    parser.add_argument("--center-lat", type=float, default=None)
    parser.add_argument("--center-lon", type=float, default=None)
    parser.add_argument(
        "--output",
        default="",
        help="Optional .i0wg output path. Without it, the normal retained-bundle location is used.",
    )
    parser.add_argument(
        "--render",
        dest="render",
        action="store_true",
        default=True,
        help="Include diagnostic images in the retained bundle (default).",
    )
    parser.add_argument(
        "--no-render",
        dest="render",
        action="store_false",
        help="Skip image generation when only numeric diagnostics are needed.",
    )
    return parser


def main(argv=None):
    args = _parser().parse_args(argv)
    seed = int(args.randomizer_seed)
    try:
        footprints = tuple(
            max(0.01, float(item.strip()))
            for item in str(args.lod_footprints_km).split(",")
            if item.strip()
        )
    except (TypeError, ValueError):
        raise SystemExit("--lod-footprints-km must be a comma-separated list of positive km values")
    if not footprints:
        raise SystemExit("--lod-footprints-km must contain at least one footprint")
    first_width_km = float(args.width_km) if args.width_km is not None else footprints[0]
    first_height_km = float(args.height_km) if args.height_km is not None else footprints[0]
    try:
        sample_width, sample_height = (
            int(part) for part in str(args.scientific_samples).lower().split("x", 1)
        )
        regional_width, regional_height = (
            int(part) for part in str(args.regional_samples).lower().split("x", 1)
        )
    except (TypeError, ValueError):
        raise SystemExit("sample grids must use WIDTHxHEIGHT, for example 513x257")
    if (
        sample_width < 3 or sample_height < 3
        or sample_width % 2 != 1 or sample_height % 2 != 1
        or regional_width < 3 or regional_height < 3
        or regional_width % 2 != 1 or regional_height % 2 != 1
    ):
        raise SystemExit("sample grids must contain odd dimensions >= 3")
    config = HeadlessWorldGenConfig(
        name="Representative 100 km LOD Test",
        template_id="silicate_terrestrial",
        map_seed=f"representative-generic-{seed}",
        randomize_mode="generic",
        randomizer_seed=seed,
        force_plate_tectonics=True,
        earthlike_constraints=True,
        regional_refinement_depth=max(0, min(7, int(args.depth))),
        regional_target_mode="mountain",
        regional_width_km=max(0.01, first_width_km),
        regional_height_km=max(0.01, first_height_km),
        regional_center_seed=seed,
        regional_center_latitude=args.center_lat,
        regional_center_longitude=args.center_lon,
        regional_footprint_schedule_km=footprints,
        render_outputs=bool(args.render),
        scientific_sample_dimensions=(sample_width, sample_height),
        regional_sample_dimensions=(regional_width, regional_height),
        worldgen_feedback_iterations=max(1, min(2, int(args.feedback_iterations))),
    )
    result = run_isolated_headless_worldgen(
        config,
        bundle_path=Path(args.output) if args.output else None,
        retention="retained",
        include_images=bool(args.render),
        project_root=PROJECT_ROOT,
    )
    summary = result.summary
    print(json.dumps({
        "bundle_path": result.bundle_path,
        "planet_id": result.planet_id,
        "randomizer_seed": seed,
        "tectonic_regime": summary.get("tectonic_regime"),
        "generated_seed": summary.get("generated_seed"),
        "representative_region": summary.get("representative_region"),
        "regional_selection_diagnostics": summary.get("regional_selection_diagnostics"),
        "regional_refinement_manifest": summary.get("regional_refinement_manifest"),
        "render_diagnostics": summary.get("render_diagnostics"),
        "stage_history": summary.get("stage_history"),
    }, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
