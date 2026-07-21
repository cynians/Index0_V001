import pygame

class InputController:
    """
    Minimal input controller (pass-through mode).

    Responsibilities:
    * Process pygame events
    * Handle global window controls (quit, toggles)
    * Forward events to:
        - camera
        - simulation
    """

    def __init__(self, camera, simulation):

        self.camera = camera
        self.simulation = simulation

        self.running = True

        self.show_grid = True
        self.show_fps = True

    def process(self, events):
        # Wheel bursts are coalesced for every simulation. Previously this was
        # done only for the knowledge layer, leaving maps exposed to hundreds
        # of camera changes from one physical touchpad gesture.
        events = self._coalesce_mousewheel_events(events)

        for event in events:

            # --- Global controls ---
            if event.type == 256:  # pygame.QUIT
                self.running = False

            elif event.type == 768:  # pygame.KEYDOWN
                if (
                    hasattr(self.simulation, "consumes_global_keydown")
                    and self.simulation.consumes_global_keydown()
                    and hasattr(self.simulation, "handle_event")
                ):
                    self.simulation.handle_event(event)
                    continue

                if event.key == 27:  # ESC
                    pass

                elif event.key == 103:  # G
                    self.show_grid = not self.show_grid

                elif event.key == 102:  # F
                    self.show_fps = not self.show_fps

            knowledge_layer_active = getattr(self.simulation, "knowledge_layer_active", False)

            consumed_before_camera = False
            if hasattr(self.simulation, "handle_pre_camera_event"):
                consumed_before_camera = bool(self.simulation.handle_pre_camera_event(event))

            # --- Forward events ---
            if not consumed_before_camera and not (knowledge_layer_active and event.type == pygame.MOUSEWHEEL):
                self.camera.handle_event(event)

            if not consumed_before_camera and hasattr(self.simulation, "handle_event"):
                self.simulation.handle_event(event)

    def _coalesce_mousewheel_events(self, events):
        coalesced = []
        pending_wheel = None
        remaining_y_budget = 6.0
        remaining_x_budget = 6.0

        for event in events:
            if event.type == pygame.MOUSEWHEEL:
                if pending_wheel is None:
                    pending_wheel = dict(getattr(event, "dict", {}) or {})
                else:
                    pending_wheel["y"] = pending_wheel.get("y", 0) + getattr(event, "y", 0)
                    pending_wheel["x"] = pending_wheel.get("x", 0) + getattr(event, "x", 0)
                continue

            if pending_wheel is not None:
                remaining_y_budget, remaining_x_budget = self._append_bounded_wheel(
                    coalesced, pending_wheel, remaining_y_budget, remaining_x_budget,
                )
                pending_wheel = None
            coalesced.append(event)

        if pending_wheel is not None:
            self._append_bounded_wheel(
                coalesced, pending_wheel, remaining_y_budget, remaining_x_budget,
            )

        return coalesced

    @staticmethod
    def _append_bounded_wheel(output, attributes, remaining_y_budget, remaining_x_budget):
        raw_y = float(attributes.get("y", 0) or 0)
        raw_x = float(attributes.get("x", 0) or 0)
        bounded_y = max(-remaining_y_budget, min(remaining_y_budget, raw_y))
        bounded_x = max(-remaining_x_budget, min(remaining_x_budget, raw_x))
        if bounded_y or bounded_x:
            safe = dict(attributes)
            safe["y"] = bounded_y
            safe["x"] = bounded_x
            output.append(pygame.event.Event(pygame.MOUSEWHEEL, safe))
        return (
            max(0.0, remaining_y_budget - abs(bounded_y)),
            max(0.0, remaining_x_budget - abs(bounded_x)),
        )
