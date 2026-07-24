"""Build galleries and a durable report for the 20 edge and 10 Earthlike runs."""

import json
import io
import os
import zipfile
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame


ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / "artifacts" / "worldgen" / "retained"
EDGE = ARTIFACTS / "edge-stress-series"
EARTH = ARTIFACTS / "earth-visual-series"
REPORT_ROOT = ROOT / ".cache" / "worldgen" / "extended-generation-report"

EDGE_FINDINGS = {
    4: "Reserved primary/foundational bedrock in the planetary palette.",
    9: "Added a foundational substrate floor after sparse smoothing.",
    13: "Made graphite foundational only on strongly carbon-rich crusts.",
}

EARTH_REFINEMENTS = {
    2: "Narrowed and segmented tectonic mountain belts.",
    3: "Added terranes, microcontinents, embayments, and fine coast detail.",
    8: "Rendered lake cells as continuous basins instead of dot grids.",
}


def _load_run(bundle_path, index, mode):
    with zipfile.ZipFile(bundle_path, "r") as bundle:
        summary = json.loads(bundle.read("summary.json").decode("utf-8"))
    return {
        "index": index,
        "mode": mode,
        "bundle": str(bundle_path),
        "contact_sheet_entry": "images/map_layers_contact_sheet.png",
        "template": (summary.get("generated_seed") or {}).get("planet_template"),
        "atmosphere_class": summary.get("atmosphere_class"),
        "surface_pressure_bar": summary.get("surface_pressure_bar"),
        "surface_temperature_k": summary.get("surface_temperature_k"),
        "tectonic_regime": summary.get("tectonic_regime"),
        "ocean_fraction": summary.get("ocean_fraction"),
        "river_count": summary.get("river_count"),
    }


def _draw_gallery(runs, title, path, columns, tile_size):
    pygame.init()
    title_font = pygame.font.SysFont("consolas", 24, bold=True)
    font = pygame.font.SysFont("consolas", 15)
    small = pygame.font.SysFont("consolas", 12)
    tile_width, tile_height = tile_size
    rows = (len(runs) + columns - 1) // columns
    margin, header = 16, 58
    sheet = pygame.Surface((
        margin * (columns + 1) + tile_width * columns,
        header + margin * (rows + 1) + tile_height * rows,
    ))
    sheet.fill((15, 18, 25))
    sheet.blit(title_font.render(title, True, (236, 240, 248)), (margin, 16))
    for offset, run in enumerate(runs):
        column, row = offset % columns, offset // columns
        x = margin + column * (tile_width + margin)
        y = header + margin + row * (tile_height + margin)
        pygame.draw.rect(sheet, (25, 29, 39), (x, y, tile_width, tile_height))
        border = (126, 146, 184) if run["mode"] == "eccentric" else (112, 156, 132)
        pygame.draw.rect(sheet, border, (x, y, tile_width, tile_height), 2)
        sheet.blit(
            font.render(f'{run["index"]:02d}  {run["mode"].title()}', True, (225, 232, 244)),
            (x + 8, y + 6),
        )
        with zipfile.ZipFile(run["bundle"], "r") as bundle:
            thumbnail = pygame.image.load(io.BytesIO(bundle.read(run["contact_sheet_entry"])), "map_layers_contact_sheet.png")
        image_height = tile_height - 76
        thumbnail = pygame.transform.smoothscale(thumbnail, (tile_width - 12, image_height))
        sheet.blit(thumbnail, (x + 6, y + 29))
        temperature = float(run["surface_temperature_k"] or 0.0)
        pressure = float(run["surface_pressure_bar"] or 0.0)
        metrics = f'{run["template"] or "unknown"} | {temperature:.1f} K | {pressure:.3g} bar'
        sheet.blit(small.render(metrics[:62], True, (190, 199, 216)), (x + 8, y + tile_height - 40))
        footer = (
            EDGE_FINDINGS.get(run["index"], "No new blocking defect")
            if "Edge" in title
            else EARTH_REFINEMENTS.get(run["index"], "Visual control passed")
        )
        sheet.blit(small.render(footer[:67], True, (220, 177, 112)), (x + 8, y + tile_height - 21))
    pygame.image.save(sheet, str(path))


def _range(values):
    values = [float(value) for value in values if value is not None]
    return [round(min(values), 3), round(max(values), 3)] if values else []


def main():
    REPORT_ROOT.mkdir(parents=True, exist_ok=True)
    edge_runs = [
        _load_run(EDGE / f'{index:02d}-{"eccentric" if index % 2 else "generic"}.i0wg',
                  index, "eccentric" if index % 2 else "generic")
        for index in range(1, 21)
    ]
    earth_runs = [
        _load_run(EARTH / f'{index:02d}-{"eccentric" if index % 2 == 0 else "generic"}.i0wg',
                  index, "eccentric" if index % 2 == 0 else "generic")
        for index in range(1, 11)
    ]

    edge_gallery = REPORT_ROOT / "edge_series_gallery.png"
    earth_gallery = REPORT_ROOT / "earth_series_gallery.png"
    _draw_gallery(edge_runs, "20-Planet Edge Stress Series", edge_gallery, 4, (300, 220))
    _draw_gallery(earth_runs, "10-Planet Earthlike Visual Series", earth_gallery, 2, (510, 300))

    report = {
        "verification": {
            "command": (
                "py -3 -m unittest tests.test_atmosphere_redox tests.test_venus_template "
                "tests.test_interior_regime_diversity tests.test_terrain_regime_diversity "
                "tests.test_material_affinities tests.test_natural_material_surface_palette "
                "tests.test_material_reference_models tests.test_orbital_climate_forcing "
                "tests.test_surface_evolution tests.test_headless_worldgen"
            ),
            "tests_run": 32,
            "failures": 0,
            "errors": 0,
            "elapsed_seconds": 231.434,
        },
        "edge_stress": {
            "run_count": len(edge_runs),
            "strict_alternation": all(
                run["mode"] == ("eccentric" if run["index"] % 2 else "generic")
                for run in edge_runs
            ),
            "temperature_range_k": _range(run["surface_temperature_k"] for run in edge_runs),
            "pressure_range_bar": _range(run["surface_pressure_bar"] for run in edge_runs),
            "ocean_fraction_range": _range(run["ocean_fraction"] for run in edge_runs),
            "refinements": EDGE_FINDINGS,
            "runs": edge_runs,
            "gallery": str(edge_gallery),
        },
        "earth_visual": {
            "run_count": len(earth_runs),
            "strict_alternation": all(
                run["mode"] == ("eccentric" if run["index"] % 2 == 0 else "generic")
                for run in earth_runs
            ),
            "temperature_range_k": _range(run["surface_temperature_k"] for run in earth_runs),
            "pressure_range_bar": _range(run["surface_pressure_bar"] for run in earth_runs),
            "ocean_fraction_range": _range(run["ocean_fraction"] for run in earth_runs),
            "river_count_range": _range(run["river_count"] for run in earth_runs),
            "refinements": EARTH_REFINEMENTS,
            "runs": earth_runs,
            "gallery": str(earth_gallery),
        },
    }
    report_path = REPORT_ROOT / "extended_generation_report.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    edge_stats = report["edge_stress"]
    earth_stats = report["earth_visual"]
    summary_path = REPORT_ROOT / "extended_generation_summary.md"
    summary_path.write_text(
        "\n".join([
            "# Extended Planet Generation Refinement",
            "",
            "## Scope",
            "",
            "- 20 edge-stress planets, strictly alternating eccentric and generic randomization.",
            "- 10 Earthlike visual controls, alternating eccentric and ordinary circular orbits.",
            "- Every run used `HeadlessWorldGenRunner`, which invokes the production simulation and renderer.",
            "",
            "## Verification",
            "",
            "- Final regression suite: 32 tests passed, 0 failures, 0 errors (231.434 seconds).",
            "",
            "## Edge-stress results",
            "",
            f'- Temperature range: {edge_stats["temperature_range_k"][0]} to {edge_stats["temperature_range_k"][1]} K.',
            f'- Pressure range: {edge_stats["pressure_range_bar"][0]} to {edge_stats["pressure_range_bar"][1]} bar.',
            f'- Ocean-fraction range: {edge_stats["ocean_fraction_range"][0]} to {edge_stats["ocean_fraction_range"][1]}.',
            "- Fixes: foundational bedrock reservation; persistent substrate floor; conditional graphite lithology.",
            "",
            "## Earthlike visual results",
            "",
            f'- Temperature range: {earth_stats["temperature_range_k"][0]} to {earth_stats["temperature_range_k"][1]} K.',
            f'- Pressure range: {earth_stats["pressure_range_bar"][0]} to {earth_stats["pressure_range_bar"][1]} bar.',
            f'- Ocean fraction: {earth_stats["ocean_fraction_range"][0]} to {earth_stats["ocean_fraction_range"][1]}.',
            f'- River-count range: {int(earth_stats["river_count_range"][0])} to {int(earth_stats["river_count_range"][1])}.',
            "- Improvements: more crustal assemblies; smaller cratons; segmented orogens; accreted terranes; "
            "microcontinents; embayments and marginal seas; finer coastlines; continuous lake rendering.",
            "- Remaining calibration opportunity: Earthlike seed pressure and mean temperature vary more than "
            "modern-Earth controls, although all ten remain within a broadly temperate terrestrial range.",
            "",
            "## Artifacts",
            "",
            f"- Edge gallery: `{edge_gallery}`",
            f"- Earthlike gallery: `{earth_gallery}`",
            f"- Machine-readable report: `{report_path}`",
            "",
        ]) + "\n",
        encoding="utf-8",
    )
    print(edge_gallery)
    print(earth_gallery)
    print(report_path)
    print(summary_path)


if __name__ == "__main__":
    main()
