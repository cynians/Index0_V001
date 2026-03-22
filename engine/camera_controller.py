class CameraController:
    """
    Applies per-simulation camera setup and runtime constraints.
    """

    def __init__(self, camera, screen_w, screen_h):
        self.camera = camera
        self.screen_w = screen_w
        self.screen_h = screen_h

    # --------------------------------------------------
    # INITIAL SETUP
    # --------------------------------------------------

    def setup_for_sim(self, sim):
        if sim is None:
            return

        if hasattr(sim, "get_center"):
            cx, cy = sim.get_center()
            self.camera.x = cx
            self.camera.y = cy

        preferred_zoom = getattr(sim, "preferred_zoom", None)
        if preferred_zoom is not None:
            self.camera.zoom = preferred_zoom
            return

        if hasattr(sim, "map_size"):
            zoom_x = self.screen_w / sim.map_size
            zoom_y = self.screen_h / sim.map_size
            self.camera.zoom = min(zoom_x, zoom_y) * 0.9

    # --------------------------------------------------
    # RUNTIME CONSTRAINTS
    # --------------------------------------------------

    def apply_constraints(self, sim):
        if sim is None:
            return

        min_zoom = getattr(sim, "min_zoom", None)
        max_zoom = getattr(sim, "max_zoom", None)

        if min_zoom is not None and max_zoom is not None:
            self.camera.zoom = max(
                min_zoom,
                min(max_zoom, self.camera.zoom)
            )

        if hasattr(sim, "bounds"):
            half_w = self.screen_w / (2 * self.camera.zoom)
            half_h = self.screen_h / (2 * self.camera.zoom)

            world_w = sim.bounds["max_x"] - sim.bounds["min_x"]
            world_h = sim.bounds["max_y"] - sim.bounds["min_y"]

            if half_w * 2 >= world_w:
                self.camera.x = (sim.bounds["min_x"] + sim.bounds["max_x"]) / 2
            else:
                self.camera.x = max(
                    sim.bounds["min_x"] + half_w,
                    min(sim.bounds["max_x"] - half_w, self.camera.x)
                )

            if half_h * 2 >= world_h:
                self.camera.y = (sim.bounds["min_y"] + sim.bounds["max_y"]) / 2
            else:
                self.camera.y = max(
                    sim.bounds["min_y"] + half_h,
                    min(sim.bounds["max_y"] - half_h, self.camera.y)
                )