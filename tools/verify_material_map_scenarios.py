"""Generate and verify material maps for contrasting planetary compositions.

This is an integration diagnostic rather than a second material model.  Each
scenario passes an elemental inventory through the production inference,
planetary heatmap, and regional occurrence code, then compares the results
with a compact set of scale-aware expectations.
"""

import argparse
import json
import math
import os
import sys
from pathlib import Path


os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pygame

from simulations.world_gen.material_heatmaps import (
    generate_material_heatmap_model,
    load_raster_bundle_surface,
)
from simulations.world_gen.natural_materials import derive_natural_material_model
from simulations.world_gen.regional_materials import derive_regional_material_model


SCENARIOS = (
    {
        "id": "felsic_wet_temperate",
        "name": "Felsic wet temperate world",
        "elements": {
            "O": 46.0, "Si": 29.0, "Al": 8.2, "Fe": 4.8, "Mg": 2.4,
            "Ca": 3.6, "Na": 2.8, "K": 2.5, "Ti": 0.45, "C": 0.08,
            "S": 0.05, "H": 0.12, "Cl": 0.02, "Cu": 0.02,
        },
        "tags": (
            "silicate_crust", "felsic_crust", "silica_rich_crust",
            "plate_tectonic_surface", "active_hydrology", "weathered_surface",
            "hydrated_crust", "oxidizing_surface", "carbonate_favorable",
            "co2_bearing_atmosphere",
        ),
        "climate": {
            "temperature_k": 296.0, "precipitation_mm": 2100.0,
            "runoff_mm": 850.0, "weathering": 0.82, "deposition": 0.58,
            "erosion": 0.42, "surface_age": 0.88, "ocean_fraction": 0.55,
        },
        "terrain_style": "plate_tectonic_continents",
        "expected_inventory": ("mat_granite", "mat_quartz", "mat_bauxite"),
        "expected_planetary_any": ("mat_granite", "mat_granodiorite", "mat_tonalite"),
        "expected_planetary_coverage": {
            # A felsic continental crust is a family of plutonic terranes,
            # not a requirement that one granite endmember paint the world.
            "material_ids": (
                "mat_granite", "mat_granodiorite", "mat_tonalite",
                "mat_syenite", "mat_monzonite", "mat_nepheline_syenite",
                "mat_diorite",
            ),
            "minimum_fraction": 0.3,
        },
        "expected_regional": {
            1: ("mat_quartz", "mat_alkali_feldspar", "mat_biotite"),
            2: ("mat_bauxite", "mat_cassiterite", "mat_chalcopyrite"),
        },
    },
    {
        "id": "mafic_arid_volcanic",
        "name": "Mafic arid volcanic world",
        "elements": {
            "O": 43.0, "Si": 22.0, "Al": 7.0, "Fe": 12.0, "Mg": 8.5,
            "Ca": 6.5, "Na": 1.7, "K": 0.5, "Ti": 1.4, "S": 0.65,
            "C": 0.03, "Cr": 0.08, "Cu": 0.025, "Ni": 0.03,
        },
        "tags": (
            "silicate_crust", "mafic_crust", "iron_rich_crust",
            "titanium_bearing_crust", "sulfur_bearing_crust",
            "basaltic_surface", "volcanic_surface", "active_volcanism",
            "arid_surface",
        ),
        "climate": {
            "temperature_k": 309.0, "precipitation_mm": 90.0,
            "runoff_mm": 8.0, "weathering": 0.08, "deposition": 0.22,
            "erosion": 0.34, "surface_age": 0.35, "ocean_fraction": 0.0,
        },
        "terrain_style": "volcanic_rift_resurfacing",
        "expected_inventory": ("mat_basalt", "mat_gabbro", "mat_pyrite"),
        "expected_planetary_any": ("mat_basalt", "mat_peridotite", "mat_diabase"),
        "expected_planetary_coverage": {
            "material_ids": ("mat_basalt",),
            "minimum_fraction": 0.35,
        },
        "expected_regional": {
            1: ("mat_gabbro", "mat_scoria", "mat_tephra"),
            2: ("mat_pyrite", "mat_chalcopyrite", "mat_chromite"),
        },
    },
    {
        "id": "ultramafic_wet_tropical",
        "name": "Ultramafic wet tropical world",
        "elements": {
            "O": 39.0, "Si": 18.0, "Al": 3.2, "Fe": 13.0, "Mg": 19.0,
            "Ca": 4.0, "Na": 0.8, "K": 0.25, "Ti": 0.8, "S": 0.12,
            "C": 0.04, "Cr": 0.22, "Ni": 0.18, "H": 0.12,
        },
        "tags": (
            "silicate_crust", "mafic_crust", "ultramafic_tendency",
            "iron_rich_crust", "basaltic_surface", "volcanic_surface",
            "active_hydrology", "weathered_surface", "hydrated_crust",
            "oxidizing_surface",
        ),
        "climate": {
            "temperature_k": 301.0, "precipitation_mm": 2600.0,
            "runoff_mm": 1050.0, "weathering": 0.9, "deposition": 0.46,
            "erosion": 0.3, "surface_age": 0.92, "ocean_fraction": 0.35,
        },
        "terrain_style": "old_ultramafic_highlands",
        "expected_inventory": (
            "mat_peridotite", "mat_serpentine", "mat_nickel_laterite",
        ),
        "expected_planetary_any": ("mat_peridotite", "mat_dunite", "mat_komatiite"),
        "expected_planetary_coverage": {
            "material_ids": ("mat_peridotite", "mat_dunite", "mat_komatiite"),
            "minimum_fraction": 0.35,
        },
        "expected_regional": {
            1: ("mat_serpentine", "mat_saprolite", "mat_laterite"),
            2: ("mat_nickel_laterite", "mat_chromite"),
        },
    },
    {
        "id": "carbon_rich_tectonic",
        "name": "Carbon-rich tectonic world",
        "elements": {
            "C": 16.0, "O": 34.0, "Si": 17.0, "Fe": 12.0, "Mg": 9.0,
            "Al": 4.0, "Ca": 4.0, "Na": 1.2, "K": 0.8, "S": 0.6,
            "Ti": 0.5, "Cr": 0.08, "Ni": 0.04,
        },
        "tags": (
            "silicate_crust", "carbon_bearing_crust", "mafic_crust",
            "iron_rich_crust", "plate_tectonic_surface", "volcanic_surface",
            "arid_surface",
        ),
        "climate": {
            "temperature_k": 287.0, "precipitation_mm": 180.0,
            "runoff_mm": 25.0, "weathering": 0.14, "deposition": 0.2,
            "erosion": 0.5, "surface_age": 0.7, "ocean_fraction": 0.0,
        },
        "terrain_style": "tectonic_carbon_highlands",
        "expected_inventory": ("mat_graphite", "mat_diamond", "mat_basalt"),
        "expected_planetary_any": ("mat_graphite",),
        "expected_planetary_coverage": {
            "material_ids": ("mat_graphite",),
            "minimum_fraction": 0.1,
        },
        "expected_regional": {
            1: ("mat_gabbro", "mat_slate", "mat_quartzite"),
            3: ("mat_diamond",),
        },
    },
)


def _rows(value, width=17, height=9, latitude_delta=0.0):
    return [
        [
            round(float(value) - abs(y / max(1, height - 1) - 0.5) * 2.0 * latitude_delta, 4)
            for _x in range(width)
        ]
        for y in range(height)
    ]


def _heightmap(scenario):
    width, height = 17, 9
    ocean_fraction = scenario["climate"]["ocean_fraction"]
    rows = []
    for y in range(height):
        row = []
        for x in range(width):
            continental = (
                920.0
                + 760.0 * math.sin(x * 0.79 + y * 0.31)
                + 520.0 * math.cos(x * 0.37 - y * 0.88)
            )
            if ocean_fraction > 0.0 and (x + y * 2) % 7 < round(ocean_fraction * 4):
                continental -= 2300.0
            row.append(round(continental, 3))
        rows.append(row)
    return {
        "planet_id": scenario["id"],
        "map_seed": f"material-verification:{scenario['id']}",
        "material_distribution_seed": f"material-verification:{scenario['id']}",
        "projection": "equirectangular",
        "wrap_x": True,
        "min_elevation_m": min(min(row) for row in rows),
        "max_elevation_m": max(max(row) for row in rows),
        "sea_level_m": 0.0 if ocean_fraction > 0.0 else None,
        "region_width_m": 1_200_000.0,
        "region_height_m": 700_000.0,
        "sample_grid": {"width": width, "height": height, "rows": rows},
    }


def _environment(scenario):
    climate = scenario["climate"]
    width, height = 17, 9
    hydrology_active = "active_hydrology" in scenario["tags"]
    water_cycle = {
        "climate_grid": {
            "temperature_rows_k": _rows(
                climate["temperature_k"], width, height, latitude_delta=24.0,
            ),
            "annual_precipitation_rows_mm": _rows(
                climate["precipitation_mm"], width, height,
            ),
            "annual_runoff_rows_mm": _rows(climate["runoff_mm"], width, height),
            "seasonal_min_temperature_rows_k": _rows(
                climate["temperature_k"] - 18.0,
                width,
                height,
                latitude_delta=35.0,
            ),
        },
    }
    surface_evolution = {
        "process_grid": {
            "chemical_weathering_rows": _rows(climate["weathering"], width, height),
            "sediment_deposition_rows": _rows(climate["deposition"], width, height),
            "erosion_potential_rows": _rows(climate["erosion"], width, height),
            "relative_surface_age_rows": _rows(climate["surface_age"], width, height),
            "aeolian_transport_rows": _rows(
                0.75 if climate["precipitation_mm"] < 300.0 else 0.12,
                width,
                height,
            ),
            "glacial_erosion_rows": _rows(0.0, width, height),
        },
    }
    terrain = {
        "map_seed": f"material-verification:{scenario['id']}",
        "surface_regime": scenario["terrain_style"],
        "geologic_style": scenario["terrain_style"],
        "hydrology": {
            "cycle": "active" if hydrology_active else "none",
            "liquid_water_possible": hydrology_active,
            "target_ocean_fraction": climate["ocean_fraction"],
        },
    }
    atmosphere = {
        "estimated_surface_temperature_k": climate["temperature_k"],
        "surface_pressure_bar": 1.0 if hydrology_active else 0.08,
    }
    return terrain, atmosphere, water_cycle, surface_evolution


def _save_composite(model, output_path, artifact_root):
    bundle_path = Path(model["bundle_path"])
    if not bundle_path.is_absolute():
        bundle_path = artifact_root / bundle_path
    surface = load_raster_bundle_surface(
        bundle_path,
        model["composite_layer"]["bundle_layer_id"],
    )
    if surface is None:
        return None
    pygame.image.save(surface, str(output_path))
    return output_path


def evaluate_scenario(scenario, artifact_root, image_size=(192, 96)):
    composition = {
        "major_elements": [
            {"symbol": symbol, "abundance_percent": abundance}
            for symbol, abundance in scenario["elements"].items()
        ],
        "trace_elements": [],
    }
    material_model = derive_natural_material_model(composition, scenario["tags"])
    heightmap = _heightmap(scenario)
    terrain, atmosphere, water_cycle, surface_evolution = _environment(scenario)
    planet = {
        "id": scenario["id"],
        "surface_evolution_model": surface_evolution,
        "climate_regulation_model": {
            "carbonate_province_favorable": (
                "carbonate_favorable" in scenario["tags"]
            ),
        },
    }
    heatmap = generate_material_heatmap_model(
        planet=planet,
        natural_material_model=material_model,
        terrain=terrain,
        heightmap=heightmap,
        atmosphere=atmosphere,
        water_cycle=water_cycle,
        output_root=artifact_root / "bundles",
        storage_root=artifact_root,
        image_size=image_size,
        max_layers=7,
    )
    inventory_ids = {
        item["material_id"] for item in material_model["likely_materials"]
    }
    planetary_ids = {
        item["material_id"] for item in heatmap.get("layers") or []
    }
    planetary_roles = {
        item.get("distribution_role") for item in heatmap.get("layers") or []
    }

    regional = {
        0: derive_regional_material_model(
            material_model,
            heightmap,
            water_cycle,
            surface_evolution,
            map_seed=f"material-verification:{scenario['id']}",
            detail_level=0,
            max_occurrences=64,
        )
    }
    parent_model = None
    for detail_level in (1, 2, 3):
        regional[detail_level] = derive_regional_material_model(
            material_model,
            heightmap,
            water_cycle,
            surface_evolution,
            map_seed=(
                f"material-verification:{scenario['id']}:level:{detail_level}"
            ),
            root_map_seed=f"material-verification:{scenario['id']}",
            detail_level=detail_level,
            max_occurrences=64,
            parent_regional_material_model=parent_model,
        )
        parent_model = regional[detail_level]

    checks = []

    def check(name, passed, expected, actual):
        checks.append({
            "name": name,
            "passed": bool(passed),
            "expected": expected,
            "actual": actual,
        })

    expected_inventory = set(scenario["expected_inventory"])
    check(
        "element inventory",
        expected_inventory <= inventory_ids,
        sorted(expected_inventory),
        sorted(expected_inventory & inventory_ids),
    )
    expected_planetary = set(scenario["expected_planetary_any"])
    check(
        "planetary substrate",
        bool(expected_planetary & planetary_ids),
        f"any of {sorted(expected_planetary)}",
        sorted(planetary_ids),
    )
    coverage_expectation = scenario["expected_planetary_coverage"]
    coverage_ids = set(coverage_expectation["material_ids"])
    actual_coverage = round(sum(
        float(item.get("coverage_fraction", 0.0) or 0.0)
        for item in heatmap.get("layers") or []
        if item["material_id"] in coverage_ids
    ), 4)
    check(
        "planetary composition coverage",
        actual_coverage >= coverage_expectation["minimum_fraction"],
        {
            "material_ids": sorted(coverage_ids),
            "minimum_fraction": coverage_expectation["minimum_fraction"],
        },
        actual_coverage,
    )
    check(
        "planetary scale roles",
        planetary_roles <= {"bedrock", "surface_cover"},
        ["bedrock", "surface_cover"],
        sorted(role for role in planetary_roles if role),
    )
    check(
        "planetary map excludes deferred materials",
        not any(
            int(item.get("minimum_map_detail_level", 0) or 0) > 0
            and item["material_id"] in planetary_ids
            for item in material_model["likely_materials"]
        ),
        "no detail level > 0 material",
        sorted(planetary_ids),
    )
    check(
        "detail 0 defers occurrences",
        regional[0].get("occurrence_count", 0) == 0
        and not regional[0].get("occurrences"),
        0,
        regional[0].get("occurrence_count", 0),
    )
    for detail_level, expected_any in scenario["expected_regional"].items():
        actual_occurrences = regional[detail_level].get("occurrences") or []
        actual_ids = {
            item["material_id"]
            for item in actual_occurrences
        }
        matching_occurrences = [
            item for item in actual_occurrences
            if item["material_id"] in set(expected_any)
        ]
        check(
            f"detail {detail_level} occurrence",
            bool(matching_occurrences),
            f"any of {sorted(expected_any)}",
            sorted(actual_ids),
        )
        if detail_level >= 2:
            maximum_radius_m = 4_000.0 if detail_level == 2 else 1_500.0
            check(
                f"detail {detail_level} deposit scale",
                bool(matching_occurrences)
                and all(
                    item["occurrence_role"] == "ore_or_mineral_prospect"
                    and item["estimated_radius_m"] <= maximum_radius_m
                    for item in matching_occurrences
                ),
                {
                    "role": "ore_or_mineral_prospect",
                    "maximum_radius_m": maximum_radius_m,
                },
                [
                    {
                        "material_id": item["material_id"],
                        "role": item["occurrence_role"],
                        "radius_m": item["estimated_radius_m"],
                    }
                    for item in matching_occurrences
                ],
            )

    image_path = artifact_root / f"{scenario['id']}_planetary.png"
    saved_image = _save_composite(heatmap, image_path, artifact_root)
    return {
        "id": scenario["id"],
        "name": scenario["name"],
        "passed": all(item["passed"] for item in checks),
        "checks": checks,
        "element_profile": material_model["element_profile"],
        "inventory_count": len(inventory_ids),
        "planetary_layers": heatmap.get("layers") or [],
        "planetary_image": (
            image_path.relative_to(artifact_root).as_posix()
            if saved_image is not None
            else None
        ),
        "regional_scales": {
            str(level): {
                "eligible_candidate_count": model.get("eligible_candidate_count", 0),
                "occurrence_count": model.get("occurrence_count", 0),
                "occurrences": [
                    {
                        "material_id": item["material_id"],
                        "role": item["occurrence_role"],
                        "radius_m": item["estimated_radius_m"],
                        "suitability": item["suitability"],
                    }
                    for item in model.get("occurrences") or []
                ],
            }
            for level, model in regional.items()
        },
    }


def _markdown_report(results):
    lines = [
        "# Material map scale verification",
        "",
        "The comparison uses the production elemental inference, planetary heatmap,",
        "and regional occurrence generators. Expectations are intentionally about",
        "material families and scale roles, not exact pixel placement.",
        "",
        "| Scenario | Inventory | Planetary layers | L1/L2/L3 occurrences | Result |",
        "|---|---:|---|---:|---|",
    ]
    for result in results:
        layers = ", ".join(
            (
                f"{item['material_id'].removeprefix('mat_')} "
                f"({float(item.get('coverage_fraction', 0.0)):.1%})"
            )
            for item in result["planetary_layers"]
        ) or "none"
        counts = "/".join(
            str(result["regional_scales"][str(level)]["occurrence_count"])
            for level in (1, 2, 3)
        )
        lines.append(
            f"| {result['name']} | {result['inventory_count']} | {layers} | "
            f"{counts} | {'PASS' if result['passed'] else 'FAIL'} |"
        )
    lines.extend(["", "## Checks", ""])
    for result in results:
        lines.append(f"### {result['name']}")
        lines.append("")
        if result["planetary_image"]:
            lines.append(f"![{result['name']}]({result['planetary_image']})")
            lines.append("")
        for item in result["checks"]:
            marker = "PASS" if item["passed"] else "FAIL"
            lines.append(
                f"- **{marker} - {item['name']}**: expected "
                f"`{item['expected']}`; actual `{item['actual']}`"
            )
        lines.append("")
    return "\n".join(lines)


def run_verification(output_dir):
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    results = [
        evaluate_scenario(scenario, output_dir)
        for scenario in SCENARIOS
    ]
    summary = {
        "passed": all(result["passed"] for result in results),
        "scenario_count": len(results),
        "passed_scenario_count": sum(result["passed"] for result in results),
        "results": results,
    }
    (output_dir / "material_map_verification.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    (output_dir / "material_map_verification.md").write_text(
        _markdown_report(results),
        encoding="utf-8",
    )
    return summary


def main():
    parser = argparse.ArgumentParser(
        description="Verify material-map behavior across composition and scale.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=PROJECT_ROOT / "artifacts" / "material_map_verification",
    )
    args = parser.parse_args()
    summary = run_verification(args.output_dir)
    print(
        f"{summary['passed_scenario_count']}/{summary['scenario_count']} "
        f"material scenarios passed; report: "
        f"{args.output_dir.resolve() / 'material_map_verification.md'}"
    )
    return 0 if summary["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
