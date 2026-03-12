import logging

from PySide6.QtWidgets import QGraphicsView, QPinchGesture, QInputDialog
from PySide6.QtCore import Qt, QEvent
from PySide6.QtGui import QNativeGestureEvent


logger = logging.getLogger(__name__)


class CanvasView(QGraphicsView):

    def __init__(self, scene):
        super().__init__(scene)

        self.setViewportUpdateMode(QGraphicsView.FullViewportUpdate)
        self.setCacheMode(QGraphicsView.CacheNone)

        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorUnderMouse)

        self.setDragMode(QGraphicsView.ScrollHandDrag)

        self.setFocusPolicy(Qt.StrongFocus)

        self.zoom = 1.0
        self.min_zoom = 0.35
        self.max_zoom = 2.25

        self.viewport().grabGesture(Qt.PinchGesture)

        logger.debug("CanvasView.__init__ | scene=%s", type(scene).__name__)

    def showEvent(self, event):
        super().showEvent(event)
        logger.debug("CanvasView.showEvent")

    def mousePressEvent(self, event):
        logger.debug(
            "CanvasView.mousePressEvent | button=%s | x=%.2f | y=%.2f",
            event.button(),
            event.position().x(),
            event.position().y()
        )
        self.setFocus()
        super().mousePressEvent(event)

    # --------------------------------------------------
    # ENTITY SPAWN PICKER
    # --------------------------------------------------

    def open_entity_picker(self):

        logger.debug("CanvasView.open_entity_picker called")

        scene = self.scene()

        logger.debug("Scene type: %s", type(scene).__name__)
        logger.debug("Scene attributes: %s", dir(scene))

        if not hasattr(scene, "world"):
            logger.warning("Scene has no world reference")
            return

        world = scene.world
        loader = world.loader

        ids = list(loader.entities.keys())

        logger.debug("Entity picker candidate count=%s", len(ids))

        if not ids:
            logger.warning("Entity picker aborted, no entities")
            return

        item, ok = QInputDialog.getItem(
            self,
            "Spawn Entity",
            "Select entity:",
            ids,
            0,
            False
        )

        logger.debug("Entity picker result | ok=%s | item=%s", ok, item)

        if not ok or not item:
            return

        entry = loader.get(item)

        if not entry:
            logger.warning("Entity not found in loader: %s", item)
            return

        dataset = entry.get("_dataset", "unknown")

        logger.debug("Spawning entity | id=%s | dataset=%s", item, dataset)

        scene.open_tile(dataset, item)

    # --------------------------------------------------
    # ZOOM
    # --------------------------------------------------

    def apply_zoom_factor(self, factor):
        logger.debug("CanvasView.apply_zoom_factor | factor=%s", factor)

        if factor <= 0:
            logger.warning("Rejected zoom factor <= 0")
            return

        new_zoom = self.zoom * factor

        if new_zoom < self.min_zoom:
            factor = self.min_zoom / self.zoom
            new_zoom = self.min_zoom

        elif new_zoom > self.max_zoom:
            factor = self.max_zoom / self.zoom
            new_zoom = self.max_zoom

        self.zoom = new_zoom
        self.scale(factor, factor)

        logger.debug("Canvas zoom updated | zoom=%s", self.zoom)

    def wheelEvent(self, event):
        logger.debug("CanvasView.wheelEvent | delta=%s", event.angleDelta().y())

        zoom_factor = 1.03

        if event.angleDelta().y() > 0:
            self.apply_zoom_factor(zoom_factor)
        else:
            self.apply_zoom_factor(1 / zoom_factor)

    # --------------------------------------------------
    # GESTURES
    # --------------------------------------------------

    def event(self, event):

        if event.type() == QEvent.Gesture:
            gesture = event.gesture(Qt.PinchGesture)

            if isinstance(gesture, QPinchGesture):
                factor = gesture.scaleFactor() / gesture.lastScaleFactor()
                logger.debug("CanvasView.pinchGesture | factor=%s", factor)
                self.apply_zoom_factor(factor)
                return True

        if event.type() == QEvent.NativeGesture:
            gesture = event

            if isinstance(gesture, QNativeGestureEvent):
                if gesture.gestureType() == Qt.ZoomNativeGesture:
                    factor = 1.0 + gesture.value()
                    logger.debug("CanvasView.nativeZoomGesture | factor=%s", factor)
                    self.apply_zoom_factor(factor)
                    return True

        return super().event(event)

    # --------------------------------------------------
    # HELPERS
    # --------------------------------------------------

    def fit_to_nodes(self):
        scene = self.scene()

        if not scene:
            logger.warning("fit_to_nodes aborted, no scene")
            return

        items = scene.items()

        if not items:
            logger.warning("fit_to_nodes aborted, no items")
            return

        rect = scene.itemsBoundingRect()

        if rect.isNull():
            logger.warning("fit_to_nodes aborted, null rect")
            return

        padding = 120
        padded = rect.adjusted(-padding, -padding, padding, padding)

        self.fitInView(padded, Qt.KeepAspectRatio)
        self.zoom = 1.0

        logger.debug("fit_to_nodes complete")