"""Compact, deterministic texture-set data used by authoring and runtime code.

The authored surface is a seamless base tile.  Character tiles are sparse
exceptions to that base and are shuffled at runtime from a seed, so a long
stem or trunk does not need a unique hand-painted image for every segment.
"""

from dataclasses import dataclass, field
import random
from typing import Any


TEXTURE_SET_VERSION = 1


def cell_key(x: int, y: int) -> str:
    return f"{int(x)},{int(y)}"


def parse_cell_key(value: Any) -> tuple[int, int] | None:
    try:
        parts = str(value).split(",")
        if len(parts) != 2:
            return None
        return int(parts[0]), int(parts[1])
    except (TypeError, ValueError):
        return None


@dataclass
class TextureVariant:
    """One authored exception tile, stored as layers instead of a flattened PNG."""

    x: int
    y: int
    layers: list[dict[str, Any]] = field(default_factory=list)

    @property
    def key(self) -> str:
        return cell_key(self.x, self.y)

    def to_dict(self) -> dict[str, Any]:
        return {"x": self.x, "y": self.y, "layers": self.layers}


@dataclass
class TextureSet:
    """A base tile plus a sparse collection of character variants."""

    width: int
    height: int
    base_layers: list[dict[str, Any]] = field(default_factory=list)
    grid_columns: int = 3
    grid_rows: int = 3
    variants: dict[str, TextureVariant] = field(default_factory=dict)
    seed: int = 17
    texture_id: str = ""

    def in_grid(self, x: int, y: int) -> bool:
        return 0 <= int(x) < self.grid_columns and 0 <= int(y) < self.grid_rows

    def add_variant(self, x: int, y: int, layers: list[dict[str, Any]]) -> TextureVariant:
        if not self.in_grid(x, y):
            raise ValueError("texture variant is outside the authoring grid")
        variant = TextureVariant(int(x), int(y), layers)
        self.variants[variant.key] = variant
        return variant

    def remove_variant(self, x: int, y: int) -> bool:
        return self.variants.pop(cell_key(x, y), None) is not None

    def variant_layers(self, x: int, y: int) -> list[dict[str, Any]] | None:
        variant = self.variants.get(cell_key(x, y))
        return variant.layers if variant else None

    def shuffled_variant_keys(self, count: int, seed: int | None = None) -> list[str]:
        """Return a deterministic order with adjacent repeats avoided when possible."""

        keys = sorted(self.variants)
        if not keys or count <= 0:
            return []
        rng = random.Random(self.seed if seed is None else int(seed))
        result: list[str] = []
        previous = None
        for _ in range(int(count)):
            choices = [key for key in keys if key != previous] or keys
            key = rng.choice(choices)
            result.append(key)
            previous = key
        return result

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": TEXTURE_SET_VERSION,
            "texture_id": self.texture_id,
            "width": int(self.width),
            "height": int(self.height),
            "grid": {"columns": int(self.grid_columns), "rows": int(self.grid_rows)},
            "seed": int(self.seed),
            "base_layers": self.base_layers,
            "variants": [variant.to_dict() for variant in self.variants.values()],
        }

    @classmethod
    def from_dict(cls, payload: Any) -> "TextureSet | None":
        if not isinstance(payload, dict):
            return None
        grid = payload.get("grid") if isinstance(payload.get("grid"), dict) else {}
        try:
            width = int(payload.get("width") or 0)
            height = int(payload.get("height") or 0)
            columns = max(1, int(grid.get("columns") or 3))
            rows = max(1, int(grid.get("rows") or 3))
            seed = int(payload.get("seed") or 17)
        except (TypeError, ValueError):
            return None
        if width <= 0 or height <= 0 or not isinstance(payload.get("base_layers"), list):
            return None
        texture = cls(
            width=width,
            height=height,
            base_layers=payload["base_layers"],
            grid_columns=columns,
            grid_rows=rows,
            seed=seed,
            texture_id=str(payload.get("texture_id") or ""),
        )
        for raw_variant in payload.get("variants") or []:
            if not isinstance(raw_variant, dict) or not isinstance(raw_variant.get("layers"), list):
                continue
            try:
                x, y = int(raw_variant.get("x")), int(raw_variant.get("y"))
            except (TypeError, ValueError):
                continue
            if texture.in_grid(x, y):
                texture.add_variant(x, y, raw_variant["layers"])
        return texture
