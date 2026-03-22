class TabManager:
    """
    Manages multiple simulation tabs.
    """

    def __init__(self):

        self.tabs = []
        self.active_index = 0

    # --------------------------------------------------

    def add_tab(self, tab):

        self.tabs.append(tab)

    # --------------------------------------------------

    def get_active(self):

        if not self.tabs:
            return None

        return self.tabs[self.active_index]

    # --------------------------------------------------

    def switch_next(self):

        if not self.tabs:
            return

        self.active_index = (self.active_index + 1) % len(self.tabs)

    # --------------------------------------------------

    def update(self, dt):

        for i, tab in enumerate(self.tabs):

            if i == self.active_index:
                tab.sim_instance.active = True
                tab.update(dt)
            else:
                tab.sim_instance.active = False

    # --------------------------------------------------

    def draw(self):

        active = self.get_active()
        if active:
            active.draw()

    # --------------------------------------------------

    def handle_event(self, event):

        active = self.get_active()
        if active:
            active.handle_event(event)