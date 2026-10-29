from __future__ import annotations

import argparse
import base64
import io
import json
from pathlib import Path

from PIL import Image


LEVEL_NOTES = {
    0: "The magenta box is the exact L1 footprint generated from this planetary map.",
    1: "The rocky-cliff morphology and coastal-system identity remain aligned at macroregional scale.",
    2: "The marked L3 selection stays on the same coast without crossing a local-map seam.",
    3: "Emergent marine terrace is a compatible local facies within the inherited rocky-cliff system.",
    4: "Site-scale cliff toes, notches, platforms, and cross sections become available.",
    5: "Parcel-scale profiles remain physically bounded and introduce cusps, talus aprons, and swash bars.",
    6: "Plot relief is 6.0 m across 30 m; the outlined rectangle is the final 10 m Survey footprint.",
    7: "Survey relief is 1.5 m across 10 m; the false edge-wrapping zigzag and most coastal speckle are gone.",
}


def _data_uri(path: Path) -> str:
    with Image.open(path) as source:
        image = source.convert("RGB")
        image.thumbnail((720, 500), Image.Resampling.LANCZOS)
        buffer = io.BytesIO()
        image.save(buffer, "JPEG", quality=70, optimize=True, progressive=True)
    return "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


def build(report_path: Path, output_path: Path) -> None:
    report = json.loads(report_path.read_text(encoding="utf-8"))
    records: dict[int, dict[str, object]] = {}
    branch_names = list(report.get("branches") or {})
    for branch_name in branch_names:
        for record in report["branches"][branch_name]:
            level = int(record["level"])
            entry = records.setdefault(level, {"level": level, "label": record["label"]})
            entry[branch_name] = {
                "image": _data_uri(Path(record["image"])),
                "assemblage": record["tracked_assemblage"],
                "footprint": record["footprint_width_m"],
                "relief": record["elevation_range_m"],
                "ratio": record["relief_to_footprint_ratio"],
                "segments": record["segment_count"],
                "seconds": record["generation_seconds"],
            }
            records[level]["note"] = LEVEL_NOTES[level]

    payload = json.dumps({
        "branches": branch_names,
        "levels": [records[level] for level in sorted(records)],
    }, separators=(",", ":"))
    fragment = r'''<section class="coastal-benchmark" aria-label="Coastal scale benchmark">
  <style>
    .coastal-benchmark{font-size:var(--font-size-base);color:var(--foreground);padding:14px;box-sizing:border-box}
    .coastal-benchmark *{box-sizing:border-box}.coastal-benchmark .sub{color:var(--muted-foreground);margin:3px 0 12px}
    .coastal-benchmark .viz-controls{margin-bottom:12px}.coastal-benchmark .cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,520px),1fr));gap:12px}
    .coastal-benchmark img{display:block;width:100%;aspect-ratio:3/2;object-fit:cover;background:var(--muted)}.coastal-benchmark .meta{padding:9px}.coastal-benchmark h3{margin:0 0 5px}.coastal-benchmark dl{display:grid;grid-template-columns:auto 1fr;gap:2px 8px;margin:0}.coastal-benchmark dt{color:var(--muted-foreground)}.coastal-benchmark dd{margin:0;font-variant-numeric:tabular-nums}
    .coastal-benchmark .finding{margin-top:12px}
    @media(max-width:700px){.coastal-benchmark .cards{grid-template-columns:1fr}}
  </style>
  <p class="sub" id="scaleTitle"></p>
  <div class="viz-controls" id="scaleControls" aria-label="Scale selection"></div>
  <div class="cards" id="coastCards"></div>
  <div class="card finding" id="finding"></div>
  <script>
    (()=>{const payload=__PAYLOAD__,data=payload.levels,controls=document.getElementById('scaleControls'),cards=document.getElementById('coastCards'),title=document.getElementById('scaleTitle'),finding=document.getElementById('finding');
      const dist=m=>m>=1e6?(m/1e6).toFixed(m%1e6?1:0)+' Mm':m>=1e3?(m/1e3).toFixed(m%1e3?1:0)+' km':m+' m';
      const branch=(name,d)=>`<article class="card"><img src="${d.image}" alt="Generated ${name} coast at selected scale"><div class="meta"><h3>${name}</h3><dl><dt>Class</dt><dd>${d.assemblage.replaceAll('_',' ')}</dd><dt>Footprint</dt><dd>${dist(d.footprint)}</dd><dt>Elevation range</dt><dd>${d.relief.toFixed(1)} m (${d.ratio.toFixed(3)}× width)</dd><dt>Coast segments</dt><dd>${d.segments.toLocaleString()}</dd><dt>Generation</dt><dd>${d.seconds.toFixed(1)} s</dd></dl></div></article>`;
      const labels={depositional:'Depositional / delta end member',cliff:'Rocky-cliff coastal system'};
      const show=i=>{const d=data[i];[...controls.children].forEach((b,j)=>b.setAttribute('aria-pressed',i===j?'true':'false'));title.textContent=`L${d.level} ${d.label}`;cards.innerHTML=payload.branches.map(name=>branch(labels[name]||name,d[name])).join('');finding.textContent=d.note};
      data.forEach((d,i)=>{const b=document.createElement('button');b.className='btn';b.type='button';b.textContent=`L${d.level} ${d.label}`;b.onclick=()=>show(i);controls.appendChild(b)});show(0);
    })();
  </script>
</section>'''.replace("__PAYLOAD__", payload)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(fragment, encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("report", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    build(args.report.resolve(), args.output.resolve())
