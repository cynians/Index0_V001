from PySide6.QtWidgets import (
    QGraphicsItem,
    QDialog,
    QVBoxLayout,
    QPushButton,
    QLineEdit
)

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor


class NodeItem(QGraphicsItem):

    STRUCTURE_FIELDS = {
        "parent",
        "relationships",
        "satellites",
        "neighbours"
    }

    def __init__(self, x=0, y=0, entry_data=None, category=None, schema=None):
        super().__init__()

        self.setPos(x, y)

        self.entry_data = entry_data or {}
        self.category = category
        self.schema = schema

        self.width = 320
        self.height = 200

        self.border = 6
        self.min_w = 240
        self.min_h = 120

        self.dragging = False
        self.resizing = None
        self.drag_offset = None

        self.field_rects = []

        self.edit_mode = False
        self.edit_buffer = {}

    # -------------------------------------------------------
    # BOUNDING
    # -------------------------------------------------------

    def boundingRect(self):
        pad = self.border
        return QRectF(-pad, -pad, self.width + pad * 2, self.height + pad * 2)

    # -------------------------------------------------------
    # PAINT
    # -------------------------------------------------------

    def paint(self, painter, option, widget):

        self.field_rects = []

        margin = 12
        row_gap = 6

        font = painter.font()
        font.setPointSize(10)
        painter.setFont(font)

        metrics = painter.fontMetrics()

        label_width = 0

        for key in self.entry_data:

            if key in ["id", "name"]:
                continue

            label_width = max(label_width, metrics.horizontalAdvance(key))

        label_width += 20
        value_width = 260

        self.width = max(
            self.min_w,
            label_width + value_width + margin * 2
        )

        painter.setPen(Qt.black)
        painter.setBrush(Qt.white)
        painter.drawRect(0, 0, self.width, self.height)

        x = margin
        y = margin

        # TITLE

        title_font = painter.font()
        title_font.setPointSize(12)
        title_font.setBold(True)

        painter.setFont(title_font)

        name = self.entry_data.get("name", "")

        painter.drawText(x, y + 18, name)

        painter.setFont(font)

        painter.drawText(
            x + label_width,
            y + 18,
            f"({self.category})"
        )

        y += 32

        structure = {}
        knowledge = {}

        for k, v in self.entry_data.items():

            if k in ["id", "name"]:
                continue

            if k in self.STRUCTURE_FIELDS:
                structure[k] = v
            else:
                knowledge[k] = v

        y = self.render_section(
            painter,
            "STRUCTURE",
            structure,
            x,
            y,
            label_width,
            value_width,
            metrics,
            row_gap
        )

        y = self.render_section(
            painter,
            "KNOWLEDGE",
            knowledge,
            x,
            y,
            label_width,
            value_width,
            metrics,
            row_gap
        )

        required_height = y + margin

        if required_height != self.height:
            self.prepareGeometryChange()
            self.height = max(required_height, self.min_h)

    # -------------------------------------------------------
    # SECTION RENDERER
    # -------------------------------------------------------

    def render_section(
        self,
        painter,
        title,
        fields,
        x,
        y,
        label_width,
        value_width,
        metrics,
        gap
    ):

        if not fields:
            return y

        font = painter.font()

        section_font = painter.font()
        section_font.setBold(True)

        painter.setFont(section_font)
        painter.setPen(Qt.black)

        painter.drawText(x, y + 16, title)

        painter.setFont(font)

        y += 22

        for key, value in fields.items():

            painter.setPen(Qt.black)
            painter.drawText(x, y + 14, key)

            value_x = x + label_width

            if self.edit_mode:
                display_value = self.edit_buffer.get(key, value)
                color = QColor(20, 120, 20)
            else:
                display_value = value
                color = QColor(30, 90, 200) if isinstance(value, str) else Qt.black

            painter.setPen(color)

            measure_rect = QRectF(
                value_x,
                y,
                value_width,
                1000
            )

            text_height = metrics.boundingRect(
                measure_rect.toRect(),
                Qt.TextWordWrap,
                str(display_value)
            ).height()

            draw_rect = QRectF(
                value_x,
                y,
                value_width,
                text_height
            )

            painter.drawText(
                draw_rect,
                Qt.TextWordWrap,
                str(display_value)
            )

            rect = QRectF(
                0,
                y,
                self.width,
                max(18, text_height)
            )

            self.field_rects.append((key, rect, "inline", value))

            y += max(18, text_height) + gap

        y += 8

        return y

    # -------------------------------------------------------
    # EDIT MODE
    # -------------------------------------------------------

    def enter_edit_mode(self):

        self.edit_mode = True
        self.edit_buffer = dict(self.entry_data)
        self.update()

    def exit_edit_mode(self, save=False):

        if save:
            self.entry_data.update(self.edit_buffer)

        self.edit_mode = False
        self.update()

    def edit_field(self, field):

        dialog = QDialog()
        dialog.setWindowTitle(field)

        layout = QVBoxLayout()
        dialog.setLayout(layout)

        editor = QLineEdit()
        editor.setText(str(self.edit_buffer.get(field, "")))

        layout.addWidget(editor)

        save = QPushButton("Save")
        layout.addWidget(save)

        def apply():
            self.edit_buffer[field] = editor.text()
            dialog.accept()
            self.update()

        save.clicked.connect(apply)

        dialog.exec()

    # -------------------------------------------------------
    # MOUSE
    # -------------------------------------------------------

    def mouseDoubleClickEvent(self, event):

        if not self.edit_mode:
            self.enter_edit_mode()
        else:
            self.exit_edit_mode(save=True)

        event.accept()

    def mousePressEvent(self, event):

        pos = event.pos()
        scene = self.scene()

        if scene and hasattr(scene, "entity_selected"):
            scene.entity_selected.emit(self.entry_data)

        for key, rect, mode, value in self.field_rects:

            if rect.contains(pos):

                if self.edit_mode:
                    self.edit_field(key)

                else:

                    if isinstance(value, str) and value:

                        scene = self.scene()

                        if scene and hasattr(scene, "backend"):

                            backend = scene.backend

                            # ask backend where this entity lives
                            entity_info = backend.entity_index.get(value)

                            if entity_info:
                                category = entity_info["dataset"]

                                scene.open_tile(category, value)

                event.accept()
                return

        if pos.x() < self.border:
            self.resizing = "left"

        elif pos.x() > self.width - self.border:
            self.resizing = "right"

        elif pos.y() < self.border:
            self.resizing = "top"

        elif pos.y() > self.height - self.border:
            self.resizing = "bottom"

        else:
            self.dragging = True
            self.drag_offset = pos

        event.accept()

    def mouseMoveEvent(self, event):

        pos = event.pos()

        if self.dragging:

            new_pos = self.mapToScene(pos - self.drag_offset)
            self.setPos(new_pos)

        elif self.resizing == "right":

            self.prepareGeometryChange()
            self.width = max(self.min_w, pos.x())
            self.update()

        elif self.resizing == "bottom":

            self.prepareGeometryChange()
            self.height = max(self.min_h, pos.y())
            self.update()

        event.accept()

    def mouseReleaseEvent(self, event):

        self.dragging = False
        self.resizing = None
        event.accept()