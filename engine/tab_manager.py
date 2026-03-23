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

    def find_tab_index_by_key(self, tab_key):
        if tab_key is None:
            return None

        for i, tab in enumerate(self.tabs):
            if getattr(tab, "tab_key", None) == tab_key:
                return i

        return None

    # --------------------------------------------------

    def activate_tab(self, index):
        if index is None:
            return False

        if index < 0 or index >= len(self.tabs):
            return False

        self.active_index = index
        return True

    # --------------------------------------------------

    def activate_tab_by_key(self, tab_key):
        index = self.find_tab_index_by_key(tab_key)
        if index is None:
            return False

        self.active_index = index
        return True

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