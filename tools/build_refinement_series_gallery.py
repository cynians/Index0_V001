"""Build a compact visual and machine-readable report for the 15-run series."""

import json
import os
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame


ROOT = Path(__file__).resolve().parents[1]
SERIES = ROOT / "artifacts" / "headless_worldgen" / "refinement-series"

ISSUES = {
    1: "High-CO2 greenhouse response was too weak",
    2: "Airless worlds still received rainfall and alluvium",
    3: "Fresh pyroclastics appeared without active volcanism",
    4: "Material coverage fractions overlapped",
    5: "Zero-dominance materials consumed global slots",
    6: "Obsidian became a planetary-scale surface",
    7: "Headless route could not finish gas giants",
    8: "Volcanic activity allowed zero resurfacing",
    9: "Massive explicit rocky worlds became ice giants",
    10: "Desiccated worlds gained excessive oceans and rivers",
    11: "Evaporites required chemistry but no aqueous history",
    12: "Airless templates could gain substantial CO2 atmospheres",
    13: "Limited hydrology generated too many rivers",
    14: "Surface palette could omit broad bedrock",
    15: "CO2 greenhouse forcing had a hard pressure cutoff",
}


def _series_directory(index):
    mode = "eccentric" if index % 2 else "generic"
    return SERIES / f"{index:02d}-{mode}", mode


def main():
    pygame.init()
    font = pygame.font.SysFont("consolas", 16)
    small = pygame.font.SysFont("consolas", 13)
    title_font = pygame.font.SysFont("consolas", 24, bold=True)
    tile_width, tile_height = 350, 250
    columns, rows = 3, 5
    margin, title_height = 18, 58
    sheet = pygame.Surface(
        (
            margin * (columns + 1) + tile_width * columns,
            title_height + margin * (rows + 1) + tile_height * rows,
        )
    )
    sheet.fill((15, 18, 25))
    sheet.blit(
        title_font.render(
            "15-Planet Generation / Refinement Series",
            True,
            (236, 240, 248),
        ),
        (margin, 16),
    )

    report = []
    for index in range(1, 16):
        directory, mode = _series_directory(index)
        summary = json.loads((directory / "summary.json").read_text(encoding="utf-8"))
        contact_path = directory / "images" / "map_layers_contact_sheet.png"
        thumbnail = pygame.image.load(str(contact_path))
        image_height = 164
        thumbnail = pygame.transform.smoothscale(
            thumbnail,
            (tile_width - 12, image_height),
        )

        column = (index - 1) % columns
        row = (index - 1) // columns
        x = margin + column * (tile_width + margin)
        y = title_height + margin + row * (tile_height + margin)
        tile = pygame.Rect(x, y, tile_width, tile_height)
        pygame.draw.rect(sheet, (25, 29, 39), tile)
        pygame.draw.rect(
            sheet,
            (126, 146, 184) if mode == "eccentric" else (112, 156, 132),
            tile,
            2,
        )
        sheet.blit(
            font.render(
                f"{index:02d}  {mode.title()}",
                True,
                (225, 232, 244),
            ),
            (x + 8, y + 6),
        )
        sheet.blit(thumbnail, (x + 6, y + 30))

        temperature = summary.get("surface_temperature_k")
        pressure = summary.get("surface_pressure_bar")
        template = (summary.get("generated_seed") or {}).get("planet_template")
        metrics = (
            f"{template or 'unknown'} | "
            f"{float(temperature or 0.0):.1f} K | "
            f"{float(pressure or 0.0):.3g} bar"
        )
        sheet.blit(
            small.render(metrics[:52], True, (190, 199, 216)),
            (x + 8, y + 199),
        )
        sheet.blit(
            small.render(ISSUES[index][:52], True, (220, 177, 112)),
            (x + 8, y + 220),
        )

        report.append(
            {
                "index": index,
                "mode": mode,
                "directory": str(directory),
                "template": template,
                "atmosphere_class": summary.get("atmosphere_class"),
                "surface_pressure_bar": pressure,
                "surface_temperature_k": temperature,
                "tectonic_regime": summary.get("tectonic_regime"),
                "ocean_fraction": summary.get("ocean_fraction"),
                "river_count": summary.get("river_count"),
                "issue_found": ISSUES[index],
                "contact_sheet": str(contact_path),
            }
        )

    gallery_path = SERIES / "series_gallery.png"
    pygame.image.save(sheet, str(gallery_path))
    report_path = SERIES / "series_report.json"
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(gallery_path)
    print(report_path)


if __name__ == "__main__":
    main()
