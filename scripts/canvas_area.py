from PySide6.QtWidgets import QWidget, QVBoxLayout

from ui.tile_widget import TileWidget


class CanvasArea(QWidget):

    def __init__(self, backend):
        super().__init__()

        self.backend = backend

        self.tiles = {}

        layout = QVBoxLayout()
        self.setLayout(layout)

        self.layout = layout

    def open_tile(self, category, entry_id):

        key = (category, entry_id)

        if key in self.tiles:
            tile = self.tiles[key]

            tile.raise_()
            tile.setFocus()

            return tile

        tile = TileWidget(self.backend, category, entry_id)

        self.tiles[key] = tile

        self.layout.addWidget(tile)

        return tile