from PySide6.QtWidgets import QGraphicsPathItem, QGraphicsSimpleTextItem
from PySide6.QtGui import QPen, QColor, QPainterPath
from PySide6.QtCore import Qt, QPointF
import math


class EdgeItem(QGraphicsPathItem):

    def __init__(self, source_node, target_node, relation_type):
        super().__init__()

        self.source_node = source_node
        self.target_node = target_node
        self.relation_type = relation_type

        pen = QPen(QColor(120, 120, 120), 2)
        self.setPen(pen)

        # render behind nodes
        self.setZValue(-1)

        # label
        self.label = QGraphicsSimpleTextItem(relation_type)
        self.label.setBrush(QColor(80, 80, 80))
        self.label.setZValue(-1)

        self.update_position()

    def update_position(self):

        source_pos = self.source_node.scenePos()
        target_pos = self.target_node.scenePos()

        sx = source_pos.x() + self.source_node.width / 2
        sy = source_pos.y() + self.source_node.height / 2

        tx = target_pos.x() + self.target_node.width / 2
        ty = target_pos.y() + self.target_node.height / 2

        start = QPointF(sx, sy)
        end = QPointF(tx, ty)

        # midpoint
        mx = (sx + tx) / 2
        my = (sy + ty) / 2

        dx = tx - sx
        dy = ty - sy

        length = math.hypot(dx, dy)
        if length == 0:
            length = 1

        # perpendicular vector
        px = -dy / length
        py = dx / length

        curvature = 60

        cx = mx + px * curvature
        cy = my + py * curvature

        control = QPointF(cx, cy)

        path = QPainterPath(start)
        path.quadTo(control, end)

        self.setPath(path)

        # label near curve midpoint
        label_x = (sx + 2 * cx + tx) / 4
        label_y = (sy + 2 * cy + ty) / 4

        self.label.setPos(label_x, label_y)