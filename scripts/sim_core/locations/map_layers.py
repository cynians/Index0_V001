import random


class MapLayerStack:
    """
    Unified interface for spatial layers.

    CURRENT:
    - Uses procedural square layers (placeholder)

    FUTURE:
    - Will connect planetary / regional / local maps
    - Will support zoom-dependent rendering
    """

    def __init__(self, size, seed=None):

        self.size = size
        self.seed = seed

        self.layers = self._generate_placeholder_layers()

    # --------------------------------------------------
    # PUBLIC API
    # --------------------------------------------------

    def get_layers(self):
        return self.layers

    # --------------------------------------------------
    # PLACEHOLDER GENERATOR (current behavior)
    # --------------------------------------------------

    def _generate_placeholder_layers(self):

        if self.seed is not None:
            random.seed(self.seed)

        layers = []

        structure = [
            ("planet", 1.0),
            ("continent", 0.30),
            ("region", 0.075),
            ("city", 0.02),
            ("production_site", 0.004),
            ("building", 0.0006)
        ]

        shades = [
            (60, 60, 60),
            (75, 75, 75),
            (90, 90, 90),
            (110, 110, 110),
            (130, 130, 130),
            (160, 160, 160)
        ]

        parent_x = -self.size / 2
        parent_y = -self.size / 2
        parent_size = self.size

        for i, (name, rel) in enumerate(structure):

            size = parent_size * rel

            if i == 0:
                x = parent_x
                y = parent_y
            else:
                margin = parent_size - size
                x = parent_x + random.uniform(0, margin)
                y = parent_y + random.uniform(0, margin)

            layers.append({
                "name": name,
                "x": x,
                "y": y,
                "size": size,
                "color": shades[i]
            })

            parent_x = x
            parent_y = y
            parent_size = size

        return layers