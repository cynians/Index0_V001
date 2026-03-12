from PySide6.QtWidgets import (
    QGraphicsRectItem,
    QGraphicsItem,
    QGraphicsProxyWidget,
    QWidget,
    QVBoxLayout,
    QLabel,
    QLineEdit,
    QGridLayout,
    QFrame,
    QStackedLayout
)

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPen, QBrush, QFont
from PySide6.QtGui import QTextOption
from PySide6.QtWidgets import QPushButton, QHBoxLayout



DATASET_COLORS = {
    "events": "#f39c12",
    "factions": "#3498db",
    "people": "#27ae60",
    "technology": "#9b59b6",
    "location": "#16a085",
    "institutions": "#e74c3c",
    "production": "#8e6e53"
}


NODE_Z_COUNTER = 0

from PySide6.QtWidgets import QTextEdit


class FieldWidget(QWidget):

    def __init__(self, value):
        super().__init__()

        self.layout = QStackedLayout()

        # display label
        self.label = QLabel(str(value))
        self.label.setWordWrap(True)
        self.label.setTextInteractionFlags(Qt.TextSelectableByMouse)

        # edit widget
        self.edit = QTextEdit(str(value))
        self.edit.setAcceptRichText(False)
        self.edit.setWordWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)
        self.edit.setMaximumHeight(120)

        self.layout.addWidget(self.label)
        self.layout.addWidget(self.edit)

        self.setLayout(self.layout)

    def set_edit_mode(self, enabled):

        if enabled:
            self.layout.setCurrentIndex(1)

        else:
            text = self.edit.toPlainText()
            self.label.setText(text)
            self.layout.setCurrentIndex(0)

    def get_value(self):
        return self.edit.toPlainText()

class HeaderLabel(QLabel):

    def __init__(self, text, double_click_callback):
        super().__init__(text)
        self._double_click_callback = double_click_callback

    def mouseDoubleClickEvent(self, event):
        if self._double_click_callback:
            self._double_click_callback(event)
        else:
            super().mouseDoubleClickEvent(event)

class NodeWidget(QWidget):

    STRUCTURE_FIELDS = {
        "parent",
        "relationships",
        "satellites",
        "neighbours"
    }

    def __init__(self, entry_data, schema, category):
        super().__init__()

        self.entry_data = entry_data or {}
        self.schema = schema or {}
        self.category = category or "unknown"

        self.edit_mode = False

        root = QVBoxLayout()
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ----------------
        # HEADER
        # ----------------

        name = self.entry_data.get("name", "")
        dataset = str(self.category).upper()

        font = QFont()
        font.setPointSize(11)
        font.setBold(True)

        color = DATASET_COLORS.get(self.category, "#888")

        header_container = QWidget()
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(6, 2, 6, 2)

        self.header = HeaderLabel(
            f"{dataset}  —  {name}",
            self._header_double_click
        )

        self.header.setFont(font)

        self.done_button = QPushButton("✓")
        self.done_button.setFixedWidth(26)
        self.done_button.setVisible(False)
        self.done_button.clicked.connect(self._finish_edit)

        header_layout.addWidget(self.header)
        header_layout.addStretch()
        header_layout.addWidget(self.done_button)

        header_container.setLayout(header_layout)

        header_container.setStyleSheet(
            f"""
            background-color: {color};
            color: white;
            """
        )

        root.addWidget(header_container)

        # ----------------
        # CONTENT AREA
        # ----------------

        content = QWidget()
        content_layout = QVBoxLayout()
        content_layout.setContentsMargins(6, 6, 6, 6)
        content_layout.setSpacing(6)

        self.fields = {}

        # ----------------
        # SCHEMA BLOCKS
        # ----------------

        if isinstance(self.schema, dict):

            for block_name, block_fields in self.schema.items():

                block = self._create_block(
                    block_name,
                    block_fields
                )

                content_layout.addWidget(block)

        # ----------------
        # EXTRA FIELDS
        # ----------------

        extras = []

        for key in self.entry_data.keys():

            if key == "name":
                continue

            if key in self.STRUCTURE_FIELDS:
                continue

            found = False

            for block_fields in self.schema.values():
                if key in block_fields:
                    found = True

            if not found:
                extras.append(key)

        if extras:

            block = self._create_block("extra", extras)

            content_layout.addWidget(block)

        content.setLayout(content_layout)

        root.addWidget(content)

        self.setLayout(root)



    # ----------------
    # BLOCK CREATION
    # ----------------

    def _create_block(self, block_name, fields):

        block_widget = QWidget()
        layout = QVBoxLayout()

        title = QLabel(block_name.upper())
        title.setStyleSheet(
            """
            font-weight: bold;
            color: #444;
            padding-top: 4px;
            """
        )

        layout.addWidget(title)

        grid = QGridLayout()
        grid.setColumnStretch(1, 1)

        row = 0

        for key in fields:

            if key == "name":
                continue

            value = self.entry_data.get(key, "")

            label = QLabel(key)
            label.setWordWrap(True)
            label.setStyleSheet("color:#666")

            field = FieldWidget(value)

            grid.addWidget(label, row, 0)
            grid.addWidget(field, row, 1)

            self.fields[key] = field

            row += 1

        layout.addLayout(grid)

        divider = QFrame()
        divider.setFrameShape(QFrame.HLine)

        layout.addWidget(divider)

        block_widget.setLayout(layout)

        return block_widget

    def _header_double_click(self, event):

        self.set_edit_mode(True)

        event.accept()

    # ----------------
    # EDIT MODE
    # ----------------

    def set_edit_mode(self, enabled):

        self.edit_mode = enabled

        for field in self.fields.values():
            field.set_edit_mode(enabled)

class NodeItem(QGraphicsRectItem):

    def __init__(self, x=0, y=0, entry_data=None, category=None, schema=None):
        super().__init__()

        self.entry_data = entry_data or {}
        self.category = category
        self.schema = schema

        self.setRect(0, 0, 320, 200)
        self.setPos(x, y)

        pen = QPen(QColor(120, 120, 120))
        pen.setWidth(1)

        self.setPen(pen)
        self.setBrush(QBrush(QColor(255, 255, 255)))

        self.setFlag(QGraphicsItem.ItemIsMovable)
        self.setFlag(QGraphicsItem.ItemIsSelectable)
        self.setFlag(QGraphicsItem.ItemSendsGeometryChanges)
        self.setFlag(QGraphicsItem.ItemIsFocusable)

        self.widget = NodeWidget(self.entry_data, self.schema, self.category)

        self.proxy = QGraphicsProxyWidget(self)
        self.proxy.setWidget(self.widget)
        self.proxy.setPos(4, 4)

        self.adjust_size()

    def adjust_size(self):

        self.widget.adjustSize()

        w = max(self.widget.width() + 8, 240)
        h = max(self.widget.height() + 8, 120)

        self.setRect(0, 0, w, h)

    def mouseDoubleClickEvent(self, event):

        self.widget.set_edit_mode(True)

        event.accept()

    def mousePressEvent(self, event):
        global NODE_Z_COUNTER

        NODE_Z_COUNTER += 1
        self.setZValue(NODE_Z_COUNTER)

        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):

        self.adjust_size()

        super().mouseReleaseEvent(event)