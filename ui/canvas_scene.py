import logging
from pathlib import Path

from PySide6.QtWidgets import QGraphicsScene
from PySide6.QtCore import Qt, QRectF, Signal
from PySide6.QtGui import QBrush, QColor, QPen

from ui.node_item import NodeItem
from ui.edge_item import EdgeItem


LOG_PATH = Path(__file__).resolve().parents[1] / "index0_debug.log"


def _ensure_logging():
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


_ensure_logging()
logger = logging.getLogger(__name__)


class CanvasScene(QGraphicsScene):

    entity_selected = Signal(dict)

    def __init__(self, world):
        super().__init__()

        # expose world to canvas tools
        self.world = world
        self.backend = world

        logger.debug("CanvasScene backend attached")

        self.current_year = 2022

        self.nodes = {}
        self.edges = []
        self.spawn_offset = 0

        self.setSceneRect(QRectF(-2000, -2000, 4000, 4000))

        logger.debug("CanvasScene.__init__ start")
        logger.debug("Backend type: %s", type(self.backend).__name__)

        self._log_backend_summary()

        import random

        entities = list(self.world.loader.entities.keys())

        random.shuffle(entities)

        for entity_id in entities[:3]:

            entry = self.world.loader.get(entity_id)
            dataset = entry.get("_dataset")

            self.open_tile(dataset, entity_id)

            if entity_id in self.nodes:
                node = self.nodes[entity_id]
                node.setPos(
                    random.randint(-300, 300),
                    random.randint(-200, 200)
                )

    def _log_backend_summary(self):
        try:
            if hasattr(self.backend, "loader"):
                datasets = getattr(self.backend.loader, "datasets", {})
                entities = getattr(self.backend.loader, "entities", {})
                logger.debug("Datasets loaded: %s", list(datasets.keys()))
                logger.debug("Entity count: %s", len(entities))
            else:
                logger.debug("Backend has no loader attribute")
        except Exception:
            logger.exception("Failed backend summary")

    def drawBackground(self, painter, rect):
        painter.fillRect(rect, QBrush(QColor(250, 250, 250)))

        grid_pen = QPen(QColor(232, 232, 232))
        painter.setPen(grid_pen)

        grid_size = 100

        left = int(rect.left()) - (int(rect.left()) % grid_size)
        top = int(rect.top()) - (int(rect.top()) % grid_size)

        x = left
        while x < rect.right():
            painter.drawLine(x, rect.top(), x, rect.bottom())
            x += grid_size

        y = top
        while y < rect.bottom():
            painter.drawLine(rect.left(), y, rect.right(), y)
            y += grid_size

    def get_available_entity_ids(self):
        if hasattr(self.backend, "loader") and hasattr(self.backend.loader, "entities"):
            return list(self.backend.loader.entities.keys())

        return []

    def open_tile(self, category, entry_id):
        logger.debug("open_tile called | category=%s | entry_id=%s", category, entry_id)

        key = (category, entry_id)

        if key in self.nodes:
            node = self.nodes[key]
            node.setZValue(node.zValue() + 1)
            logger.debug("Node already exists, reusing | key=%s", key)

            views = self.views()
            if views:
                views[0].centerOn(node)
                logger.debug("Centered existing node in view")

            return node

        try:
            if hasattr(self.backend, "get_entity"):
                entry = self.backend.get_entity(entry_id)
            else:
                entry = None

            if not entry:
                logger.warning("No entry found for entry_id=%s", entry_id)
                return None

            node = NodeItem(
                self.spawn_offset,
                self.spawn_offset,
                entry_data=entry,
                category=category,
                schema=None
            )

            self.addItem(node)
            self.nodes[key] = node
            self.spawn_offset += 40

            logger.debug(
                "Node created | id=%s | name=%s | pos=(%s,%s)",
                entry.get("id"),
                entry.get("name"),
                node.pos().x(),
                node.pos().y()
            )

            views = self.views()
            if views:
                views[0].update_zoom_limits()
                logger.debug("View zoom limits updated")

            return node

        except Exception:
            logger.exception("open_tile failed | category=%s | entry_id=%s", category, entry_id)
            return None

    def open_first_entity(self):
        logger.debug("open_first_entity called")

        entity_ids = self.get_available_entity_ids()

        if not entity_ids:
            logger.warning("No entities available")
            return None

        first_id = entity_ids[0]

        try:
            entry = self.backend.get_entity(first_id)
            category = entry.get("_dataset", "unknown") if entry else "unknown"
            logger.debug("Opening first entity | id=%s | category=%s", first_id, category)
            return self.open_tile(category, first_id)
        except Exception:
            logger.exception("open_first_entity failed")
            return None

    def mouseDoubleClickEvent(self, event):
        logger.debug(
            "Scene double click | x=%.2f | y=%.2f",
            event.scenePos().x(),
            event.scenePos().y()
        )

        available = self.get_available_entity_ids()

        if available:
            first_id = available[0]
            try:
                entry = self.backend.get_entity(first_id)
                category = entry.get("_dataset", "unknown") if entry else "unknown"
                self.open_tile(category, first_id)
            except Exception:
                logger.exception("Double click open failed")
        else:
            logger.warning("Double click ignored, no entities loaded")

        event.accept()