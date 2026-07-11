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
        if getattr(self.simulation, "knowledge_layer_active", False):
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

        for event in events:
            if event.type == pygame.MOUSEWHEEL:
                if pending_wheel is None:
                    pending_wheel = event
                else:
                    pending_wheel.y = getattr(pending_wheel, "y", 0) + getattr(event, "y", 0)
                    pending_wheel.x = getattr(pending_wheel, "x", 0) + getattr(event, "x", 0)
                continue

            if pending_wheel is not None:
                coalesced.append(pending_wheel)
                pending_wheel = None
            coalesced.append(event)

        if pending_wheel is not None:
            coalesced.append(pending_wheel)

        return coalesced
