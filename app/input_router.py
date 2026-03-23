import pygame


class InputRouter:
    """
    Routes simulation-specific pointer and view-reset input.

    Responsibilities:
    * reset the active simulation camera on middle click
    * forward pointer motion to the active simulation
    * forward left-click pointer events to the active simulation
    """

    def __init__(self, app):
        self.app = app

    def handle_middle_click_reset(self, event, active_sim):
        """
        Reset camera view for the active simulation on middle click.
        """
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 2:
            if active_sim is not None:
                self.app.camera_controller.setup_for_sim(active_sim)
            return True

        return False

    def handle_pointer_input(self, event, active_sim):
        """
        Forward pointer motion and left-click events to the active simulation.
        """
        if active_sim and hasattr(active_sim, "handle_pointer_motion"):
            if event.type == pygame.MOUSEMOTION:
                active_sim.handle_pointer_motion(
                    event=event,
                    camera=self.app.camera,
                    screen_pos=event.pos
                )

        if active_sim and hasattr(active_sim, "handle_pointer_event"):
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                active_sim.handle_pointer_event(
                    event=event,
                    camera=self.app.camera,
                    screen_pos=event.pos
                )