from __future__ import annotations

import argparse
import base64
import io
import json
from pathlib import Path

from PIL import Image


def _data_uri(path: Path) -> str:
    with Image.open(path) as source:
        image = source.convert("RGB")
        image.thumbnail((900, 720), Image.Resampling.LANCZOS)
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=76, optimize=True, progressive=True)
    return "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


def build(template_path: Path, report_path: Path, generated_dir: Path, output_path: Path) -> None:
    report = json.loads(report_path.read_text(encoding="utf-8"))
    generated_report = json.loads(
        (generated_dir.parent / "benchmark_report.json").read_text(encoding="utf-8")
    )
    generated_by_level = {int(item["level"]): item for item in generated_report["branches"]["cliff"]}
    structures = {
        6: (
            "many closed shoreline loops and isolated speckles",
            "one connected sea; dominant cliff/bench edge",
        ),
        7: (
            "fragmentation increases and diagonal seabed banding persists",
            "one connected land mass against one connected sea",
        ),
    }
    payload = []
    for level, key, generated_name in (
        (6, "l6", "level_6_plot.png"),
        (7, "l7", "level_7_survey.png"),
    ):
        generated = generated_by_level[level]
        reference = report[key]
        metrics = reference["metrics"]
        generated_structure, reference_structure = structures[level]
        payload.append(
            {
                "level": level,
                "footprint": int(metrics["footprint_m"]),
                "generatedImage": _data_uri(generated_dir / generated_name),
                "referenceImage": _data_uri(Path(reference["image"])),
                "generatedSpacing": f'{generated["sample_spacing_x_m"] * 100:.1f} cm',
                "generatedRelief": f'{generated["elevation_range_m"]:.1f}',
                "referenceRelief": f'{metrics["elevation_p95_m_lmsl"] - metrics["elevation_p05_m_lmsl"]:.2f}',
                "generatedSegments": int(generated["segment_count"]),
                "referenceTopology": (
                    f'{metrics["water_components"]} water / {metrics["land_components"]} land connected components'
                ),
                "generatedStructure": generated_structure,
                "referenceStructure": reference_structure,
                "limit": (
                    "The 1 m reference validates landform organization, not the generated centimetre-scale microtexture. "
                    "Segment and component counts are different statistics and are not a ratio."
                ),
            }
        )
    fragment = template_path.read_text(encoding="utf-8").replace(
        "__PAYLOAD__", json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(fragment, encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("template", type=Path)
    parser.add_argument("report", type=Path)
    parser.add_argument("generated_dir", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    build(args.template.resolve(), args.report.resolve(), args.generated_dir.resolve(), args.output.resolve())
