"""Regression-sample tool for SpeciesSim/renderer mechanics changes.

Before starting any new plant development pass, run ``select`` once to pick
a fixed number of random leaf (terminal) descendants of Plantae and Fungi from the
live ontology and show each at a representative mature stage. The choice
is written to a manifest (species id, fixed age, per-individual
render seed) so the exact same individuals can be regenerated later. Render
``before`` from that manifest, make the mechanics change under test, render
``after`` from the same manifest, then ``compare`` to see whether anything
moved that the fixed species/age/seed should have held constant.

    py -m tools.plant_mechanics_regression_sample select
    py -m tools.plant_mechanics_regression_sample render --status before
    ... change SpeciesSim/SpeciesRenderer growth or rendering mechanics ...
    py -m tools.plant_mechanics_regression_sample render --status after
    py -m tools.plant_mechanics_regression_sample compare

If a sampled leaf has no authored plant or fungal trait fields (a bare stub),
``select`` reports it under ``NEEDS_AUTHORING`` instead of silently treating
its generic-fallback render as a meaningful baseline. Per
``docs/Plant_Design_Process.md``, ask the user whether to author it now
before relying on it for a comparison.
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path
from types import SimpleNamespace

import pygame

from simulations.species.plant_assets import PlantBlueprint
from simulations.species.species_renderer import (
    DiagnosticCamera,
    IsometricDiagnosticCamera,
    SpeciesRenderer,
    diagnostic_cell_bounds,
)
from simulations.species.species_simulation import SpeciesSimulation
from simulations.species.preview_timing import mature_preview_age
from world.persistent_ontology_store import PersistentOntologyStore
from world.plant_catalogue import PlantCatalogue
from world.plant_traits import PLANT_TRAIT_FIELDS
from world.fungal_traits import FUNGAL_TRAIT_SCHEMA_FIELDS
from world.species_inheritance import is_authored_field
from world.world_model import WorldModel


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = Path("artifacts/plant_mechanics_regression")
SAMPLE_COUNT = 3
LOD = 2


def _load_live_entities() -> dict:
    datasets = PersistentOntologyStore(ROOT / "ontology" / "index0.owl").load_datasets()
    return {
        row["id"]: row
        for rows in datasets.values()
        if isinstance(rows, list)
        for row in rows
        if isinstance(row, dict) and row.get("id")
    }


def _authored_field_count(raw_entity: dict) -> int:
    fields = set(PLANT_TRAIT_FIELDS) | set(FUNGAL_TRAIT_SCHEMA_FIELDS)
    return sum(1 for key in fields if is_authored_field(raw_entity, key))


def select_sample(seed: int | None, count: int = SAMPLE_COUNT, scope: str = "all",
                  excluded_species_ids=()) -> dict:
    entities = _load_live_entities()
    if scope not in {"all", "plants", "fungi"}:
        raise ValueError("Sample scope must be all, plants or fungi")
    plants = PlantCatalogue.build(entities).leaf_species_ids
    fungi = PlantCatalogue.build(entities, root_id="cladis_fungi").leaf_species_ids
    leaves = sorted(plants | fungi if scope == "all" else plants if scope == "plants" else fungi)
    excluded = sorted(set(excluded_species_ids or ()) & set(entities))
    leaves = [species_id for species_id in leaves if species_id not in excluded]
    if len(leaves) < count:
        raise RuntimeError(f"Only {len(leaves)} terminal species exist in scope {scope}; need {count}.")

    selection_seed = seed if seed is not None else random.SystemRandom().randrange(2**31)
    rng = random.Random(selection_seed)
    chosen = rng.sample(leaves, count)

    world = WorldModel()
    entries = []
    for species_id in chosen:
        raw = world.loader.get(species_id) or entities.get(species_id, {})
        resolved = world.resolved_species_entity(species_id) or raw
        blueprint = PlantBlueprint.from_species_entity(resolved, species_id)
        authored_count = _authored_field_count(raw)
        render_seed = rng.randrange(2**31)
        sim = SpeciesSimulation(species_entity=resolved, species_id=species_id, seed=render_seed)
        age = mature_preview_age(sim)
        entries.append(
            {
                "species_id": species_id,
                "display_name": blueprint.display_name,
                "maturity_fraction": 1.0,
                "age_days": age,
                "preview_stage": "representative_mature",
                "render_seed": render_seed,
                "authored_field_count": authored_count,
                "needs_authoring": authored_count == 0,
                "kingdom": "Fungi" if species_id in fungi else "Plantae",
            }
        )

    return {
        "kind": "plant_mechanics_regression_sample",
        "selection_seed": selection_seed,
        "sample_count": count,
        "scope": scope,
        "preview_policy": "mature_leafy_or_flowering",
        **({"excluded_species_ids": excluded} if excluded else {}),
        "scope_roots": (["cladis_plants_plantae", "cladis_fungi"] if scope == "all" else
                        ["cladis_plants_plantae"] if scope == "plants" else ["cladis_fungi"]),
        "display_title": "Plant and fungi candidates" if scope == "all" else f"{scope.capitalize()} candidates",
        "entries": entries,
    }


def write_manifest(manifest: dict, manifest_path: Path) -> Path:
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest_path


def load_manifest(manifest_path: Path) -> dict:
    if not manifest_path.exists():
        raise RuntimeError(f"No manifest at {manifest_path}. Run `select` first to pick a sample.")
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def case_state_label(state: dict) -> str:
    """Explain seasonal organ loss without changing the sampled individual."""
    parts = [str(state.get("phase", "unknown")).replace("_", " ")]
    if "leaf_factor" in state:
        leaf = state["leaf_factor"]
        parts.append("leafless model season" if leaf == 0 else
                     "full foliage" if leaf == 1 else f"foliage {leaf:.0%}")
    elif state.get("seasonal_stage"):
        parts.append(str(state["seasonal_stage"]).replace("_", " "))
    parts.append("independent scale")
    return " | ".join(parts)


def _draw_case(renderer: SpeciesRenderer, sim: SpeciesSimulation, entry: dict, size: tuple) -> tuple:
    width, height = size
    surface = pygame.Surface(size)
    surface.fill((13, 18, 17))
    title_font = pygame.font.SysFont("consolas", 18)
    font = pygame.font.SysFont("consolas", 12)

    counts = {
        kind: sum(1 for placement in sim.render_snapshot.placements if placement[0] == kind)
        for kind in ("leaf", "flower", "fruit", "stem_section", "branch_section", "root_section")
    }
    if sim.blueprint.growth.get("fungal_grammar_version"):
        counts.update({kind: sum(p[0] == kind for p in sim.render_snapshot.placements)
                       for kind in ("mycelium", "fruiting_body")})
    elif sim.blueprint.growth.get("surface_growth_profile"):
        counts.update({kind: sum(p[0] == kind for p in sim.render_snapshot.placements)
                       for kind in ("thallus", "apothecium")})
    surface.blit(title_font.render(sim.blueprint.display_name, True, (232, 238, 233)), (12, 10))
    surface.blit(
        font.render(
            f"seed {entry['render_seed']} | maturity {entry['maturity_fraction']:.2f} | model day {sim.age_days:.1f}",
            True,
            (182, 193, 151),
        ),
        (12, 32),
    )

    surface.blit(font.render(case_state_label(sim.life_state()), True, (211, 199, 154)), (12, 50))
    body_top = 72
    body_height = height - body_top - 26
    body_width = width - 16
    body = pygame.Surface((body_width, body_height))
    surface_body = bool(sim.blueprint.growth.get("surface_growth_profile"))
    camera = (IsometricDiagnosticCamera(body_width, body_height, sim.render_snapshot.bounds_m)
              if surface_body else DiagnosticCamera(body_width, body_height,
                                                    diagnostic_cell_bounds(sim.render_snapshot)))
    renderer._draw_individual(
        body,
        sim,
        camera=camera,
        show_height_reference=False,
        draw_ground_line=not surface_body,
        cache=False,
    )
    surface.blit(body, (8, body_top))
    if sim.blueprint.growth.get("fungal_grammar_version"):
        bodies = sim.render_snapshot.stats.get("fungal_bodies", [])
        widths = [b["cap_width_m"]*100 for b in bodies]
        caption = (f"Caps {min(widths):.1f}-{max(widths):.1f} cm" if widths else "No visible shelves in this phase")
        supports = sim.render_snapshot.stats.get("fungal_substrates", [])
        if any(w.get("id") == "wood_test_asset" for w in supports):
            caption += " | standard oak bark, trunk diameter 32 cm"
        surface.blit(font.render(caption, True, (211, 199, 154)), (12, body_top+8))
    if (entry.get("kingdom") == "Fungi" and not sim.blueprint.growth.get("fungal_grammar_version")
            and not sim.blueprint.growth.get("surface_growth_profile")):
        surface.blit(font.render("UNCONFIGURED FUNGUS | generic plant fallback", True, (236, 196, 128)),
                     (12, body_top + 8))
    elif entry.get("needs_authoring"):
        surface.blit(font.render("NEEDS AUTHORING | generic fallback", True, (236, 196, 128)),
                     (12, body_top + 8))
    pygame.draw.rect(surface, (76, 99, 86), (8, body_top, body_width, body_height), 1)
    footer = "  ".join(f"{kind} {value}" for kind, value in counts.items() if value) or "no placements"
    surface.blit(font.render(footer, True, (185, 197, 188)), (12, height - 20))

    record = {
        "species_id": sim.species_id,
        "display_name": sim.blueprint.display_name,
        "maturity_fraction": entry["maturity_fraction"],
        "render_seed": entry["render_seed"],
        "age_days": round(float(sim.age_days), 4),
        "life_state": sim.life_state(),
        "blueprint_fingerprint": sim.blueprint.fingerprint(),
        "counts": counts,
        "placement_count": len(sim.render_snapshot.placements),
        "bounds_m": [round(float(value), 6) for value in sim.render_snapshot.bounds_m],
    }
    return surface, record


def render_sample(manifest: dict, output_dir: Path, status: str) -> tuple:
    world = WorldModel()
    status_dir = output_dir / status
    status_dir.mkdir(parents=True, exist_ok=True)

    pygame.init()
    pygame.font.init()
    pygame.display.set_mode((1, 1))
    renderer = SpeciesRenderer(SimpleNamespace(camera=None))
    panel_size = (520, 460)
    entries = manifest["entries"]
    sheet = pygame.Surface((panel_size[0] * len(entries), panel_size[1] + 40))
    sheet.fill((8, 12, 11))
    title_font = pygame.font.SysFont("consolas", 20)
    sheet.blit(
        title_font.render(f"{manifest.get('display_title_after') if status == 'after' and manifest.get('display_title_after') else manifest.get('display_title', 'Plant mechanics regression sample')} — {status.upper()}", True, (234, 238, 222)),
        (14, 10),
    )

    records = []
    for index, entry in enumerate(entries):
        species_id = entry["species_id"]
        sim = SpeciesSimulation(world_model=world, species_id=species_id, seed=entry["render_seed"])
        sim.set_lod(LOD)
        # Age is frozen at selection, so later trait/mechanics changes cannot
        # silently move a new sample to a different season. Historical samples
        # retain their recorded fractional age until explicitly re-presented.
        sim.set_age(entry.get("age_days", sim.mature_age_days * entry["maturity_fraction"]))
        # Authoring flags in the manifest describe selection time. Refresh the
        # displayed flag so an authored AFTER plant is not called a fallback.
        authored_count = _authored_field_count(world.loader.get(species_id) or {})
        display_entry = {**entry, "needs_authoring": authored_count == 0}
        panel, record = _draw_case(renderer, sim, display_entry, panel_size)
        record["authored_field_count"] = authored_count
        records.append(record)
        pygame.image.save(panel, status_dir / f"{species_id}.png")
        sheet.blit(panel, (index * panel_size[0], 40))

    sheet_path = output_dir / f"{status}_contact_sheet.png"
    pygame.image.save(sheet, sheet_path)
    report_path = output_dir / f"{status}_metrics.json"
    report_path.write_text(
        json.dumps(
            {"status": status, "selection_seed": manifest["selection_seed"], "cases": records},
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    pygame.quit()
    return sheet_path, report_path


def compare(output_dir: Path) -> dict:
    before_path = output_dir / "before_metrics.json"
    after_path = output_dir / "after_metrics.json"
    if not before_path.exists() or not after_path.exists():
        raise RuntimeError("Render both --status before and --status after before comparing.")
    before = {case["species_id"]: case for case in json.loads(before_path.read_text(encoding="utf-8"))["cases"]}
    after = {case["species_id"]: case for case in json.loads(after_path.read_text(encoding="utf-8"))["cases"]}

    tracked_keys = ("age_days", "maturity_fraction", "counts", "placement_count", "bounds_m",
                    "blueprint_fingerprint", "life_state")
    species_report = {}
    any_changed = False
    for species_id, before_case in before.items():
        after_case = after.get(species_id)
        if after_case is None:
            species_report[species_id] = {"status": "MISSING_AFTER"}
            any_changed = True
            continue
        changed = {
            key: {"before": before_case[key], "after": after_case[key]}
            for key in tracked_keys
            if before_case[key] != after_case[key]
        }
        species_report[species_id] = {
            "status": "CHANGED" if changed else "UNCHANGED",
            "changed_fields": changed,
        }
        any_changed = any_changed or bool(changed)

    comparison_dir = output_dir / "comparison"
    comparison_dir.mkdir(parents=True, exist_ok=True)
    pygame.init()
    pygame.display.set_mode((1, 1))
    for species_id in before:
        before_img_path = output_dir / "before" / f"{species_id}.png"
        after_img_path = output_dir / "after" / f"{species_id}.png"
        if not (before_img_path.exists() and after_img_path.exists()):
            continue
        before_img = pygame.image.load(before_img_path)
        after_img = pygame.image.load(after_img_path)
        gap = 12
        combined = pygame.Surface(
            (before_img.get_width() + after_img.get_width() + gap, max(before_img.get_height(), after_img.get_height()))
        )
        combined.fill((5, 8, 7))
        combined.blit(before_img, (0, 0))
        combined.blit(after_img, (before_img.get_width() + gap, 0))
        pygame.image.save(combined, comparison_dir / f"{species_id}.png")
    pygame.quit()

    report_path = comparison_dir / "report.json"
    report_path.write_text(
        json.dumps({"any_changed": any_changed, "species": species_report}, indent=2) + "\n",
        encoding="utf-8",
    )
    return {"any_changed": any_changed, "report_path": str(report_path.resolve()), "species": species_report}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--manifest", type=Path, default=None)
    subparsers = parser.add_subparsers(dest="command", required=True)

    select_parser = subparsers.add_parser("select", help="Pick random terminal plant/fungal species.")
    select_parser.add_argument("--seed", type=int, default=None, help="Selection RNG seed; omit for a fresh random draw.")
    select_parser.add_argument("--count", type=int, default=SAMPLE_COUNT)
    select_parser.add_argument("--scope", choices=("all", "plants", "fungi"), default="all")
    select_parser.add_argument("--exclude", action="append", default=[], metavar="SPECIES_ID",
                               help="Leave a completed species out of this draw; repeat for multiple IDs.")

    render_parser = subparsers.add_parser("render", help="Render the current manifest at the given status.")
    render_parser.add_argument("--status", choices=("before", "after"), required=True)

    subparsers.add_parser("compare", help="Diff the before/after metrics and images for the current manifest.")

    args = parser.parse_args()
    manifest_path = args.manifest or (args.output_dir / "sample.json")

    if args.command == "select":
        manifest = select_sample(args.seed, args.count, args.scope, args.exclude)
        write_manifest(manifest, manifest_path)
        print(json.dumps(manifest, indent=2))
        stub_species = [entry["species_id"] for entry in manifest["entries"] if entry["needs_authoring"]]
        if stub_species:
            print(
                "\nNEEDS_AUTHORING: "
                + ", ".join(stub_species)
                + " — no plant or fungal simulation traits are authored on this species yet."
                " Ask the user whether to run a Plant_Design_Process pass on it now,"
                " since its render is presently just the generic fallback shape."
            )
    elif args.command == "render":
        manifest = load_manifest(manifest_path)
        sheet_path, report_path = render_sample(manifest, args.output_dir, args.status)
        print(json.dumps({"sheet": str(sheet_path.resolve()), "report": str(report_path.resolve())}, indent=2))
    elif args.command == "compare":
        result = compare(args.output_dir)
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
