"""Pack the loose files below ``assets/`` into one ``<category>.pak`` per folder, and back.

    py -m tools.pack_assets --repository   # asset_packs/, what git commits (the pre-commit hook runs this)
    py -m tools.pack_assets --unpack       # asset_packs/ -> assets/, e.g. after a clone or pull
    py -m tools.pack_assets [--out DIR]    # every asset, for a packed build (build/asset_packs)

The loose files are the source the app and the editors work on; git ignores
them and commits the repository packs instead.  A pack is a ZIP that
``engine/asset_files.py`` can also read directly when ``INDEX0_ASSET_PACKS``
names its folder.  Entry names are relative to the category folder, and files
directly in ``assets/`` go to ``common.pak``.  PNG, JPEG and ``.gz`` entries
are already compressed and are stored as they are; everything else is
deflated (plain ZIP, so any zip tool opens a pack).  Entries are written in
name order with a fixed date, so the same files give the same pack byte for
byte and git sees a change only in the categories that changed.

Folders the app does not read as assets are left out (``SKIPPED``), and the
repository packs also leave out data that is fetched again rather than
committed (``REPOSITORY_SKIPPED``).
"""

from __future__ import annotations

import argparse
import os
import sys
import zipfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from engine.asset_files import PACK_SUFFIX, ROOT_CATEGORY  # noqa: E402

ASSET_ROOT = PROJECT_ROOT / "assets"
DEFAULT_OUT = PROJECT_ROOT / "build" / "asset_packs"
REPOSITORY_OUT = PROJECT_ROOT / "asset_packs"
STORED_SUFFIXES = {".png", ".jpg", ".jpeg", ".gz"}
DEFLATE_LEVEL = 9
FIXED_DATE = (2026, 1, 1, 0, 0, 0)

# Relative to assets/, with why each is not packed.
SKIPPED = {
    "plant_asset_specs": "plant design recipes, read by the authoring tools",
    "species_trait_specs": "plant design trait inputs, read by the authoring tools",
    "reference_credits": "reference photo credits for the design docs",
    "plants/snapshots": "baked growth stages, a cache the app rebuilds",
    "plants/diagnostics": "reports written by tools",
    "plants/telemetry": "reports written by tools",
    "maps/material_heatmaps": "rendered heatmaps, a cache the app rebuilds",
}
REPOSITORY_SKIPPED = {
    "maps/reference": "public GIS data, fetched again by tools/acquire_highest_lod_reference.py",
}
SKIPPED_NAMES = {"Thumbs.db", ".DS_Store"}


def _skipped(relative: str, skipped) -> bool:
    if any(part.startswith(".") or part in SKIPPED_NAMES or part == "__pycache__" for part in relative.split("/")):
        return True
    return any(relative == prefix or relative.startswith(prefix + "/") for prefix in skipped)


def collect(asset_root: Path, skipped=SKIPPED) -> dict[str, list[tuple[str, Path]]]:
    """``{category: [(entry name, source file), ...]}`` in name order."""
    categories: dict[str, list[tuple[str, Path]]] = {}
    for path in sorted(asset_root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(asset_root).as_posix()
        if _skipped(relative, skipped):
            continue
        category, _, name = relative.partition("/")
        if not name:
            category, name = ROOT_CATEGORY, relative
        categories.setdefault(category, []).append((name, path))
    return categories


def write_pack(target: Path, entries: list[tuple[str, Path]]) -> bool:
    """Write the pack; ``False`` when ``target`` already held exactly these bytes and was left alone."""
    temporary = target.with_name(f".{target.name}.tmp")
    try:
        with zipfile.ZipFile(temporary, "w") as archive:
            for name, source in entries:
                info = zipfile.ZipInfo(name, date_time=FIXED_DATE)
                info.external_attr = 0o644 << 16
                if source.suffix.lower() in STORED_SUFFIXES:
                    info.compress_type = zipfile.ZIP_STORED
                    archive.writestr(info, source.read_bytes())
                else:
                    info.compress_type = zipfile.ZIP_DEFLATED
                    archive.writestr(info, source.read_bytes(), compresslevel=DEFLATE_LEVEL)
        with zipfile.ZipFile(temporary) as archive:
            broken = archive.testzip()
        if broken is not None:
            raise RuntimeError(f"{target.name}: entry {broken} does not read back")
        if target.is_file() and target.read_bytes() == temporary.read_bytes():
            return False
        os.replace(temporary, target)
        return True
    finally:
        temporary.unlink(missing_ok=True)


def build_packs(asset_root: Path = ASSET_ROOT, out: Path = DEFAULT_OUT, skipped=SKIPPED) -> list[dict]:
    out.mkdir(parents=True, exist_ok=True)
    categories = collect(asset_root, skipped)
    report = []
    for category, entries in sorted(categories.items()):
        target = out / f"{category}{PACK_SUFFIX}"
        changed = write_pack(target, entries)
        report.append(dict(
            pack=target.name,
            files=len(entries),
            source_bytes=sum(source.stat().st_size for _, source in entries),
            pack_bytes=target.stat().st_size,
            changed=changed,
        ))
    # A category that no longer has files leaves no pack behind.
    for stale in out.glob(f"*{PACK_SUFFIX}"):
        if stale.stem not in categories:
            stale.unlink()
            report.append(dict(pack=stale.name, files=0, source_bytes=0, pack_bytes=0, changed=True))
    return report


def unpack(packs: Path = REPOSITORY_OUT, asset_root: Path = ASSET_ROOT, force: bool = False) -> dict[str, list[str]]:
    """Write every pack entry to its loose file.

    A loose file that already differs from the pack is kept and listed under
    ``kept`` unless ``force``: it may be an edit that was never packed.
    """
    result = {"written": [], "unchanged": [], "kept": []}
    for pak in sorted(packs.glob(f"*{PACK_SUFFIX}")):
        folder = asset_root if pak.stem == ROOT_CATEGORY else asset_root / pak.stem
        with zipfile.ZipFile(pak) as archive:
            for info in archive.infolist():
                if info.is_dir():
                    continue
                target = folder / info.filename
                relative = target.relative_to(asset_root).as_posix()
                data = archive.read(info)
                if target.is_file():
                    if target.read_bytes() == data:
                        result["unchanged"].append(relative)
                        continue
                    if not force:
                        result["kept"].append(relative)
                        continue
                target.parent.mkdir(parents=True, exist_ok=True)
                temporary = target.with_name(f".{target.name}.tmp")
                temporary.write_bytes(data)
                os.replace(temporary, target)
                result["written"].append(relative)
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--repository", action="store_true", help="write the committed packs to asset_packs/")
    mode.add_argument("--unpack", action="store_true", help="write asset_packs/ back to the loose files in assets/")
    parser.add_argument("--out", type=Path, help="pack folder (default build/asset_packs, or asset_packs/ with --repository/--unpack)")
    parser.add_argument("--force", action="store_true", help="with --unpack: also replace loose files that differ")
    parser.add_argument("--quiet", action="store_true", help="print only what changed")
    args = parser.parse_args(argv)

    if args.unpack:
        packs = args.out or REPOSITORY_OUT
        result = unpack(packs, force=args.force)
        for relative in result["kept"]:
            print(f"kept (differs from the pack, --force replaces it): assets/{relative}")
        print(f"{len(result['written'])} files written, {len(result['unchanged'])} already up to date, "
              f"{len(result['kept'])} kept, from {packs}")
        return 0

    out = args.out or (REPOSITORY_OUT if args.repository else DEFAULT_OUT)
    skipped = {**SKIPPED, **REPOSITORY_SKIPPED} if args.repository else SKIPPED
    if not ASSET_ROOT.is_dir() or not collect(ASSET_ROOT, skipped):
        # A fresh clone or worktree has packs but no loose files: packing it would empty every pack.
        print("No loose assets in assets/: run `py -m tools.pack_assets --unpack` first. Packs left as they are.")
        return 0
    report = build_packs(out=out, skipped=skipped)
    mb = 1024 * 1024
    for row in report:
        if args.quiet and not row["changed"]:
            continue
        state = "updated" if row["changed"] else "unchanged"
        print(f"{row['pack']:<20} {row['files']:>5} files  {row['source_bytes'] / mb:7.1f} MB -> "
              f"{row['pack_bytes'] / mb:7.1f} MB  {state}")
    if not args.quiet:
        print(f"{len(report)} packs in {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
