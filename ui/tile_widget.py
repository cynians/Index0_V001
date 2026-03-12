from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QTextEdit
from PySide6.QtGui import QFont
from PySide6.QtCore import Qt


class TileWidget(QWidget):

    def __init__(self, entity):
        super().__init__()

        self.entity = entity

        layout = QVBoxLayout(self)

        # -------------------------
        # Title
        # -------------------------

        title = entity.get("name", "Unnamed")

        title_label = QLabel(title)

        title_font = QFont()
        title_font.setPointSize(12)
        title_font.setBold(True)

        title_label.setFont(title_font)

        layout.addWidget(title_label)

        # -------------------------
        # Dataset
        # -------------------------

        dataset = entity.get("_dataset", "")

        if dataset:
            dataset_label = QLabel(f"({dataset})")
            layout.addWidget(dataset_label)

        # -------------------------
        # Raw data display
        # -------------------------

        text = QTextEdit()
        text.setReadOnly(True)

        lines = []

        for key, value in entity.items():

            if key == "name":
                continue

            lines.append(f"{key}: {value}")

        text.setPlainText("\n".join(lines))

        layout.addWidget(text)