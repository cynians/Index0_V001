"""Review every live authored Plantae species through BioSim's sprite consumer.

The same mature body, seed and season are used at every pixel cap. Isometric
ground tiles are inspection beds, independently scaled, not an ecology run.
"""
from __future__ import annotations

import argparse
import html
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pygame
from simulations.biosphere.biosphere_renderer import BiosphereBuilderRenderer
from simulations.biosphere.plant_pictures import grow_specimen
from world.plant_traits import PLANT_TRAIT_FIELDS
from world.world_model import WorldModel

CAPS = (84, 165, 220)
BG = (19, 25, 23)


def authored_species(world):
    # Authorship is checked on raw rows; inheritance and defaults do not count.
    return [sid for sid in sorted(world.plant_catalogue.species_ids)
            if any((world.get_entity(sid) or {}).get(f) is not None for f in PLANT_TRAIT_FIELDS)]


def bed(surface, foot, width=170):
    x, y = foot
    points = [(x-width//2, y), (x, y-width//4), (x+width//2, y), (x, y+width//4)]
    pygame.draw.polygon(surface, (52, 62, 43), points)
    pygame.draw.lines(surface, (93, 105, 72), True, points, 1)
    pygame.draw.ellipse(surface, (35, 43, 32), (x-width*.27, y-7, width*.54, 15))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "artifacts/authored_plant_caps")
    parser.add_argument("--species", nargs="*", help="Optional subset for refinement checks")
    args = parser.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    pygame.init()
    pygame.display.set_mode((1, 1))
    world = WorldModel()
    ids = authored_species(world)
    if args.species:
        unknown = set(args.species) - set(ids)
        if unknown:
            raise ValueError(f"Not live authored Plantae species: {sorted(unknown)}")
        ids = [sid for sid in ids if sid in args.species]
    renderer = BiosphereBuilderRenderer(SimpleNamespace())
    font = pygame.font.SysFont("segoeui", 20)
    small = pygame.font.SysFont("segoeui", 15)
    records, cards, thumbs = [], [], []
    for index, sid in enumerate(ids):
        raw = world.get_entity(sid)
        support = ({"climbing_supports": [{"id": "inspection_pole", "kind": "pole",
            "center_m": [.35, 0.], "radius_m": .05, "height_m": 6., "crown_radius_m": 0.}]}
            if raw.get("plant_growth_behaviour") == "climbing_support_dependent" else None)
        body = grow_specimen(world, sid, 303, 1., environment=support)
        instance = {"species_id": sid, "representative_id": sid, "abundance": 1.,
                    "visual_scale": 1., "variant": 0, "growth_form": body.blueprint.growth.get("form", raw.get("plant_growth_form"))}
        scene = SimpleNamespace(world_model=world, world_units_to_meters=1.,
            get_representative_species_simulation=lambda _id: body)
        label = body.blueprint.display_name
        renderer._frame_surfaces.clear()
        sprites = [renderer._sprite_surface(scene, instance,
                   SimpleNamespace(zoom=400., sprite_height_cap=cap, true_scale=False)) for cap in CAPS]
        widths = [max(240, art.get_width()+50) for art, _anchor in sprites]
        card = pygame.Surface((sum(widths), 360)); card.fill(BG)
        card.blit(font.render(label, True, (225, 234, 214)), (16, 8))
        card.blit(small.render(f"{sid} | {instance['growth_form']} | seed 303", True, (155, 177, 159)), (16, 38))
        samples = []
        left = 0
        for cap, width, (art, anchor) in zip(CAPS, widths, sprites):
            # Centre the painted extent, not the root: spreading crowns can be asymmetric.
            x = left + width//2 - art.get_width()/2 + anchor[0]
            bed(card, (x, 300), 190 if cap == 84 else 245)
            card.blit(art, (round(x-anchor[0]), round(300-anchor[1])))
            card.blit(small.render(f"{cap} px cap | {art.get_width()} x {art.get_height()} px", True,
                                  (189, 206, 180)), (left+20, 336))
            left += width
            file = f"{sid}_{cap}.png"
            pygame.image.save(art, str(args.out / file))
            samples.append({"cap_px": cap, "file": file, "size_px": list(art.get_size()),
                            "ground_anchor_px": list(anchor)})
            if cap == 84:
                thumb = pygame.Surface((200, 170)); thumb.fill(BG)
                bed(thumb, (100, 112), 170)
                factor = min(1., 180 / art.get_width(), 90 / art.get_height())
                display = pygame.transform.scale(art, (max(1,round(art.get_width()*factor)), max(1,round(art.get_height()*factor))))
                thumb.blit(display, (round(100-display.get_width()/2), round(112-anchor[1]*factor)))
                short = label.split(" - ")[0].strip()
                while small.size(short)[0] > 190: short = short[:-1]
                thumb.blit(small.render(short, True, (222, 232, 211)), (5, 145))
                thumbs.append(thumb)
        file = f"{sid}_comparison.png"
        pygame.image.save(card, str(args.out / file)); cards.append(card)
        refs = {f: raw[f] for f in raw if f.startswith("plant_") and f.endswith("_module_ref")}
        records.append({"id": sid, "label": label, "growth_form": instance["growth_form"],
            "authored_fields": sorted(f for f in PLANT_TRAIT_FIELDS if raw.get(f) is not None),
            "asset_refs": refs, "blueprint_fingerprint": body.blueprint.fingerprint(),
            "age_model_days": body.age_days, "age_real_days": body.real_age_days,
            "ecology": body.get_ecological_outcome(), "samples": samples, "comparison": file})
        print(f"{index+1}/{len(ids)} {sid}", flush=True)
    overview = pygame.Surface((1600, 90 + 170*((len(thumbs)+7)//8))); overview.fill(BG)
    overview.blit(font.render(f"{len(ids)} AUTHORED PLANTS / BIOSIM / 84 PX", True, (230, 239, 219)), (20, 14))
    overview.blit(small.render("Production renderer preview | mature specimens | seed 303 | wide thumbnails fitted; comparisons show native pixels", True,
                              (172, 196, 176)), (20, 50))
    for i, thumb in enumerate(thumbs): overview.blit(thumb, ((i%8)*200, 90+(i//8)*170))
    pygame.image.save(overview, str(args.out / "overview.png"))
    pages = []
    for start in range(0, len(cards), 8):
        page_width = max(card.get_width() for card in cards[start:start+8])
        page = pygame.Surface((page_width, 70+360*len(cards[start:start+8]))); page.fill(BG)
        page.blit(font.render(f"BIO SIM CAP REVIEW / {start+1}-{min(len(ids),start+8)} of {len(ids)} / 84, 165, 220 px",
                               True, (225, 234, 214)), (20, 20))
        for i, card in enumerate(cards[start:start+8]): page.blit(card, (0, 70+i*360))
        file = f"page_{start//8+1:02d}.png"; pages.append(file)
        pygame.image.save(page, str(args.out/file))
    (args.out/"review.json").write_text(json.dumps({"source": "live persistent ontology decoded by WorldModel",
        "selection": "Plantae ancestry AND at least one raw authored plant trait", "seed": 303,
        "caps_px": CAPS, "scale": "Independent specimen display scales; native output pixels",
        "pages": pages, "species": records}, indent=2, default=str), encoding="utf-8")
    entries = []
    for r in records:
        links = " ".join(f'<a href="{html.escape(Path(os.path.relpath(ROOT / ref, args.out)).as_posix())}">{html.escape(field.removeprefix("plant_").removesuffix("_module_ref"))}</a>'
                         for field, ref in r["asset_refs"].items())
        entries.append(f'<article data-search="{html.escape(r["id"]+" "+r["label"]+" "+r["growth_form"])}">'
            f'<a href="{r["comparison"]}" target="_blank"><img src="{r["comparison"]}" alt="{html.escape(r["label"])}: pixel cap comparison"></a>'
            f'<p>{len(r["authored_fields"])} authored fields · Saved organ assets: {links or "procedural modules"}</p></article>')
    (args.out/"index.html").write_text('''<!doctype html><html><meta charset="utf-8"><title>BioSim plant asset review</title>
<style>body{background:#131917;color:#dfead8;font:16px system-ui;margin:24px}header{position:sticky;top:0;background:#131917;padding:12px;z-index:1}input{padding:12px;width:360px;background:#27332b;color:white;border:1px solid #6a8168}main{display:grid;grid-template-columns:repeat(auto-fit,minmax(600px,1fr));gap:20px}article{border:1px solid #354539;border-radius:8px;overflow:hidden}img{width:100%;image-rendering:pixelated}p{padding:0 16px}a{color:#aad49a}</style>
<header><h1>BioSim · authored plant assets</h1><p>84 / 165 / 220 pixel caps · production renderer preview · same mature specimen and seed at every cap.</p><p>Each bed uses its own display scale. Click a comparison for native pixels. Organ links open the saved source assets.</p><p>Shared garden: <a href="../garden/garden_overview_cap_084.png">84 px</a> · <a href="../garden/garden_overview_cap_165.png">165 px</a> · <a href="../garden/garden_overview_cap_220.png">220 px</a></p><input placeholder="Find a plant or growth form" oninput="document.querySelectorAll('article').forEach(a=>a.hidden=!a.dataset.search.toLowerCase().includes(this.value.toLowerCase()))"></header><main>'''
        + "\n".join(entries) + "</main></html>", encoding="utf-8")
    pygame.quit()
    print(str((args.out/"index.html").resolve()), flush=True)


if __name__ == "__main__": main()
