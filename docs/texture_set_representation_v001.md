# Texture set representation v001

Pixel Studio's `texture` mode authors a small seamless base tile and a sparse set of character exceptions. The editor displays the base in a 3×3 neighborhood; the center cell is the base and clicking a surrounding cell activates a copy that can be painted independently.

The saved document keeps the editable layer structure for the base and each activated cell. It does not save repeated copies. The illustration keeps the texture mode, grid size, seed, exception count, and runtime policy as metadata; the canonical PNG is the base tile.

Runtime consumers should treat the base as the default and select exception tiles with a deterministic seed. The initial policy is shuffled selection with adjacent repeats avoided when there is more than one exception. Stem and bark renderers can later map the texture's local coordinates onto curved segment axes without changing the authored asset format.
