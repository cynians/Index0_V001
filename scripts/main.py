import sys
import logging
from pathlib import Path

from PySide6.QtWidgets import QApplication, QMainWindow, QWidget, QVBoxLayout, QSplitter
from PySide6.QtCore import Qt
from PySide6.QtGui import QShortcut, QKeySequence


from tools.world_model import WorldModel


from ui.canvas_view import CanvasView
from ui.timeline_widget import TimelineWidget
from ui.debug_panel import DebugPanel
from ui.canvas_scene import CanvasScene


LOG_PATH = Path(__file__).resolve().parents[1] / "index0_debug.log"



def ensure_logging():
    root = logging.getLogger()

    if root.handlers:
        return

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    )

    file_handler = logging.FileHandler(LOG_PATH, encoding="utf-8")
    file_handler.setFormatter(formatter)

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)

    root.setLevel(logging.DEBUG)
    root.addHandler(file_handler)
    root.addHandler(stream_handler)


ensure_logging()
logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):

    def __init__(self):
        super().__init__()

        logger.debug("MainWindow.__init__ start")

        self.setWindowTitle("Index_0 World Explorer")
        self.resize(1400, 900)

        # ----------------------------------
        # WORLD MODEL
        # ----------------------------------

        self.world = WorldModel()
        logger.debug("WorldModel initialized")

        # ----------------------------------
        # UI COMPONENTS
        # ----------------------------------

        scene = CanvasScene(self.world)

        self.canvas = CanvasView(scene)
        self.canvas.setScene(scene)

        self.timeline = TimelineWidget(self.world)

        self.debug_panel = DebugPanel(self.world)
        self.debug_panel.hide()

        from PySide6.QtWidgets import QDockWidget





        self.timeline.event_clicked.connect(self.open_event)

        # ----------------------------------
        # LAYOUT
        # ----------------------------------

        container = QWidget()
        layout = QVBoxLayout(container)

        splitter = QSplitter(Qt.Vertical)
        splitter.addWidget(self.canvas)
        splitter.addWidget(self.timeline)
        splitter.setSizes([800, 120])

        layout.addWidget(splitter)

        self.setCentralWidget(container)

        # ----------------------------------
        # GLOBAL SHORTCUTS
        # ----------------------------------

        self.spawn_shortcut = QShortcut(QKeySequence("Ctrl+Space"), self)
        self.spawn_shortcut.activated.connect(self.handle_spawn_shortcut)

        self.debug_shortcut = QShortcut(QKeySequence("F9"), self)
        self.debug_shortcut.activated.connect(self.toggle_debug_panel)

        self.fit_shortcut = QShortcut(QKeySequence("F"), self)
        self.fit_shortcut.activated.connect(self.handle_fit_shortcut)

        logger.debug("Global shortcuts registered | Ctrl+Space, F9, F")

    # --------------------------------------------------
    # GLOBAL SHORTCUT HANDLERS
    # --------------------------------------------------

    def handle_spawn_shortcut(self):
        logger.debug("Shortcut activated | Ctrl+Space")
        self.canvas.open_entity_picker()

    def toggle_debug_panel(self):
        logger.debug("Shortcut activated | F9")

        if self.debug_panel.isVisible():
            self.debug_panel.hide()
            logger.debug("Debug panel hidden")
        else:
            self.debug_panel.refresh()
            self.debug_panel.show()
            logger.debug("Debug panel shown")

    def handle_fit_shortcut(self):
        logger.debug("Shortcut activated | F")
        self.canvas.fit_to_nodes()

    # --------------------------------------------------
    # INPUT LOGGING
    # --------------------------------------------------

    def keyPressEvent(self, event):

        logger.debug(
            "MainWindow.keyPressEvent | key=%s | modifiers=%s",
            event.key(),
            event.modifiers()
        )

        super().keyPressEvent(event)

    # --------------------------------------------------
    # EVENT HANDLERS
    # --------------------------------------------------

    def open_event(self, event_id):
        logger.debug("Timeline event clicked | event_id=%s", event_id)

        try:
            if hasattr(self.canvas.scene(), "open_tile"):
                entry = self.world.get_entity(event_id)

                if entry:
                    dataset = entry.get("_dataset", "unknown")
                    self.canvas.scene().open_tile(dataset, event_id)
                else:
                    logger.warning("Timeline clicked entity not found: %s", event_id)

        except Exception:
            logger.exception("Failed to open event from timeline")


def main():
    app = QApplication(sys.argv)

    window = MainWindow()
    window.show()

    logger.debug("Application started")
    sys.exit(app.exec())


if __name__ == "__main__":
    main()