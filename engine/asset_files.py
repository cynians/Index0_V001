"""Where the app reads its authored assets from.

The ontology names an asset by its project-relative path
(``assets/plants/illustrations/x_pixel.png``).  While developing, that is a
loose file under the project root, which the editors and authoring tools
write.  A packed build ships one ``<category>.pak`` per folder below
``assets/`` (``world/asset_folders.py`` decides the folder) instead, built
by ``tools/pack_assets.py``: a ZIP whose entry names are
relative to the category folder (files directly in ``assets/`` go to
``common.pak``).

Which of the two is read is set once for the process, never per file:
``INDEX0_ASSET_PACKS`` names the folder of packs, and without it assets are
loose.  A packed run does not look at loose assets and a loose run does not
look at packs.  Paths outside ``assets/`` (worlds, caches, artifacts) are
plain files either way, and so are the caches the app writes inside
``assets/`` (growth snapshots, material heatmaps): their readers do not come
through here.  Writing is for loose runs only; a packed build is read-only.

Missing assets raise ``FileNotFoundError`` in both modes, so callers keep
catching ``OSError`` as they did for plain files.
"""

from __future__ import annotations

import gzip
import io
import os
import threading
import zipfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ASSET_ROOT = PROJECT_ROOT / "assets"
PACKS_ENV = "INDEX0_ASSET_PACKS"
PACK_SUFFIX = ".pak"
ROOT_CATEGORY = "common"

_lock = threading.Lock()
_packs = None
_chosen = False


class _Packs:
    """The open ``.pak`` archives of a packed run, opened on first use."""

    def __init__(self, directory):
        self.directory = Path(directory)
        if not self.directory.is_dir():
            raise FileNotFoundError(f"Asset pack folder {self.directory} does not exist")
        self._archives = {}

    def entry(self, key):
        category, _, name = key.partition("/")
        if not name:
            category, name = ROOT_CATEGORY, key
        with _lock:
            if category not in self._archives:
                path = self.directory / f"{category}{PACK_SUFFIX}"
                self._archives[category] = zipfile.ZipFile(path) if path.is_file() else None
            archive = self._archives[category]
        if archive is None:
            return None
        try:
            return archive, archive.getinfo(name)
        except KeyError:
            return None

    def close(self):
        with _lock:
            for archive in self._archives.values():
                if archive is not None:
                    archive.close()
            self._archives.clear()


def use_packs(directory):
    """Read assets from the packs in ``directory`` for the rest of the process."""
    global _packs, _chosen
    packs = _Packs(directory)
    if _packs is not None:
        _packs.close()
    _packs, _chosen = packs, True


def use_loose():
    """Read assets as loose files under ``assets/`` for the rest of the process."""
    global _packs, _chosen
    if _packs is not None:
        _packs.close()
    _packs, _chosen = None, True


def packed():
    return _current_packs() is not None


def _current_packs():
    global _packs, _chosen
    if not _chosen:
        directory = os.environ.get(PACKS_ENV, "").strip()
        if directory:
            use_packs(directory)
        else:
            _chosen = True
    return _packs


def disk_path(path):
    """``path`` as a file on disk: relative paths are relative to the project root."""
    candidate = Path(path)
    return candidate if candidate.is_absolute() else PROJECT_ROOT / candidate


def asset_key(path):
    """``path`` relative to ``assets/`` (``illustrations/x.png``), or ``None`` outside it."""
    try:
        relative = Path(os.path.normpath(disk_path(path))).relative_to(ASSET_ROOT)
    except ValueError:
        return None
    key = relative.as_posix()
    return None if key in ("", ".") else key


def _locate(path):
    """A ``Path`` to read from disk, a ``(ZipFile, ZipInfo)`` pack entry, or ``None`` when a pack lacks it."""
    packs = _current_packs()
    if packs is None:
        return disk_path(path)
    key = asset_key(path)
    if key is None:
        return disk_path(path)
    return packs.entry(key)


def _missing(path):
    return FileNotFoundError(f"{path} is not in the asset packs")


def exists(path):
    where = _locate(path)
    if isinstance(where, Path):
        return where.is_file()
    return where is not None


def revision(path):
    """What changes when the asset at ``path`` changes, or ``None`` when it is missing."""
    where = _locate(path)
    if isinstance(where, Path):
        try:
            return where.stat().st_mtime_ns
        except OSError:
            return None
    return None if where is None else where[1].CRC


def read_bytes(path):
    where = _locate(path)
    if isinstance(where, Path):
        return where.read_bytes()
    if where is None:
        raise _missing(path)
    archive, info = where
    return archive.read(info)


def read_text(path, encoding="utf-8"):
    return read_bytes(path).decode(encoding)


def open_binary(path):
    where = _locate(path)
    if isinstance(where, Path):
        return open(where, "rb")
    return io.BytesIO(read_bytes(path))


def open_gzip_text(path, encoding="utf-8"):
    """A text handle on the gzip file at ``path`` (``.json.gz`` documents)."""
    where = _locate(path)
    if isinstance(where, Path):
        return gzip.open(where, "rt", encoding=encoding)
    return gzip.open(io.BytesIO(read_bytes(path)), "rt", encoding=encoding)


def load_image(path):
    """A pygame surface of the image at ``path``, not yet converted for the display."""
    import pygame

    where = _locate(path)
    if isinstance(where, Path):
        return pygame.image.load(str(where))
    return pygame.image.load(io.BytesIO(read_bytes(path)), Path(str(path)).name)
