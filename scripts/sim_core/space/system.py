class CelestialSystem:
    """
    Container for space objects and their associated data (e.g. map layers).

    Current responsibilities:
    - Store objects in hierarchical order (parent before child)
    - Update all objects per simulation step
    - Provide iterable access for rendering

    Future:
    - Dependency graph (automatic ordering)
    - Multi-system support (star systems)
    """

    def __init__(self):
        self.entries = []

    # --------------------------------------------------
    # Add object
    # --------------------------------------------------

    def add(self, obj, name=None, layers=None):
        """
        Add a space object to the system.

        Parameters
        ----------
        obj : SpaceObject
        name : str | None
        layers : MapLayerStack | None
        """
        self.entries.append({
            "name": name or obj.name,
            "object": obj,
            "layers": layers
        })

    # --------------------------------------------------
    # Update
    # --------------------------------------------------

    def update(self, dt):
        """
        Update all objects.

        IMPORTANT:
        Order matters (parents must be added before children).
        """
        for entry in self.entries:
            entry["object"].update(dt)

    # --------------------------------------------------
    # Access
    # --------------------------------------------------

    def get_entries(self):
        return self.entries