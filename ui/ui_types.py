class UIButton:
    """
    Minimal screen-space button description.
    """

    def __init__(self, button_id, label, rect, visible=True, enabled=True):
        self.id = button_id
        self.label = label
        self.rect = rect
        self.visible = visible
        self.enabled = enabled