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

        for event in events:

            # --- Global controls ---
            if event.type == 256:  # pygame.QUIT
                self.running = False

            elif event.type == 768:  # pygame.KEYDOWN

                if event.key == 27:  # ESC
                    self.running = False

                elif event.key == 103:  # G
                    self.show_grid = not self.show_grid

                elif event.key == 102:  # F
                    self.show_fps = not self.show_fps

            knowledge_layer_active = getattr(self.simulation, "knowledge_layer_active", False)

            # --- Forward events ---
            if not (knowledge_layer_active and event.type == pygame.MOUSEWHEEL):
                self.camera.handle_event(event)

            if hasattr(self.simulation, "handle_event"):
                self.simulation.handle_event(event)