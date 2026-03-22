import random


class MapLayerStack:
    """
    Simple layered representation of a planetary surface.

    Each layer is a dict:
    {
        "name": str,
        "color": (r, g, b),
        "x": float,
        "y": float,
        "size": float
    }
    """

    def __init__(self, size, seed=None):

        self.size = size
        self.seed = seed

        # --------------------------------------------------
        # IMPORTANT: start empty (no placeholder layers)
        # --------------------------------------------------

        self.layers = []

    # --------------------------------------------------

    def get_layers(self):
        return self.layers

    # --------------------------------------------------
    # NEW: required for MapSimulation integration
    # --------------------------------------------------

    def add_layer(self, layer):
        self.layers.append(layer)

    def clear(self):
        self.layers.clear()

    # --------------------------------------------------
    # (kept for optional future debugging, but unused)
    # --------------------------------------------------

    def _generate_placeholder_layers(self):

        if self.seed is not None:
            random.seed(self.seed)

        layers = []

        base_colors = [
            (30, 60, 120),
            (40, 100, 60),
            (120, 100, 40),
            (100, 40, 40),
            (80, 80, 80),
        ]

        for i in range(5):

            size = self.size * (0.5 - i * 0.08)

            layers.append({
                "name": f"Layer {i}",
                "color": base_colors[i % len(base_colors)],
                "x": random.uniform(-self.size * 0.1, self.size * 0.1),
                "y": random.uniform(-self.size * 0.1, self.size * 0.1),
                "size": size
            })

        return layers