from ui.canvas_scene import CanvasScene
from ui.canvas_view import CanvasView
from ui.timeline_widget import TimelineWidget

from PySide6.QtWidgets import (
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QTextEdit,
    QLabel,
    QTreeWidget,
    QTreeWidgetItem,
    QSplitter,
    QPushButton,
    QInputDialog
)

from PySide6.QtCore import Qt


class MainWindow(QMainWindow):

    def __init__(self, backend):
        super().__init__()

        self.backend = backend

        self.setWindowTitle("World Index Entry Editor")
        self.resize(1200, 700)

        self._build_ui()
        self.populate_tree()

    def _build_ui(self):

        main_widget = QWidget()
        self.setCentralWidget(main_widget)

        layout = QVBoxLayout()
        main_widget.setLayout(layout)

        toolbar = QHBoxLayout()

        self.add_button = QPushButton("Add Entry")
        self.add_button.clicked.connect(self.add_entry)

        toolbar.addWidget(self.add_button)
        toolbar.addStretch()

        layout.addLayout(toolbar)

        # Timeline widget
        self.timeline = TimelineWidget()
        layout.addWidget(self.timeline)

        splitter = QSplitter(Qt.Horizontal)

        self.entry_tree = QTreeWidget()
        self.entry_tree.setHeaderLabel("Entries")
        self.entry_tree.itemClicked.connect(self.display_entry)

        splitter.addWidget(self.entry_tree)

        self.canvas_scene = CanvasScene(self.backend)
        self.canvas = CanvasView(self.canvas_scene)
        splitter.addWidget(self.canvas)

        right_panel = QWidget()
        right_layout = QVBoxLayout()

        right_panel.setLayout(right_layout)

        right_layout.addWidget(QLabel("Entry Explorer (future)"))

        self.explorer_view = QTextEdit()
        self.explorer_view.setReadOnly(True)

        right_layout.addWidget(self.explorer_view)

        splitter.addWidget(right_panel)

        splitter.setSizes([300, 600, 300])

        layout.addWidget(splitter)

    def populate_tree(self):

        self.entry_tree.clear()

        for category in self.backend.get_categories():

            entries = self.backend.get_entries(category)

            category_item = QTreeWidgetItem([category])
            self.entry_tree.addTopLevelItem(category_item)

            for entry_id, entry in entries.items():

                name = entry.get("name", entry_id)

                item = QTreeWidgetItem([name])
                item.setData(0, Qt.UserRole, (category, entry_id))

                category_item.addChild(item)

    def display_entry(self, item, column):

        data = item.data(0, Qt.UserRole)

        if not data:
            return

        category, entry_id = data

        entry = self.backend.get_entry(category, entry_id)

        self.canvas_scene.open_tile(category, entry_id)

    def add_entry(self):

        categories = self.backend.get_categories()

        category, ok = QInputDialog.getItem(
            self,
            "Select Category",
            "Entry Type:",
            categories,
            0,
            False
        )

        if not ok:
            return

        entry_id, ok = QInputDialog.getText(
            self,
            "Entry ID",
            "Enter new entry ID:"
        )

        if not ok or not entry_id:
            return

        self.backend.add_entry(category, entry_id)

        self.populate_tree()
