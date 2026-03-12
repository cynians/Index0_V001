from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel
from PySide6.QtCore import Qt


class DebugPanel(QWidget):

    def __init__(self, world):
        super().__init__()

        self.world = world

        self.setWindowTitle("Index0 Debug Inspector")
        self.setWindowFlag(Qt.WindowStaysOnTopHint)

        layout = QVBoxLayout()
        self.setLayout(layout)

        self.datasets = QLabel()
        self.entities = QLabel()
        self.events = QLabel()
        self.relationships = QLabel()

        layout.addWidget(self.datasets)
        layout.addWidget(self.entities)
        layout.addWidget(self.events)
        layout.addWidget(self.relationships)

        self.refresh()

    def refresh(self):

        loader = self.world.loader
        graph = self.world.graph

        dataset_names = list(loader.datasets.keys())
        entity_count = len(loader.entities)

        event_count = len(loader.get_dataset("events"))

        edge_count = sum(len(v) for v in graph.edges.values())

        self.datasets.setText(f"Datasets: {dataset_names}")
        self.entities.setText(f"Entities: {entity_count}")
        self.events.setText(f"Events: {event_count}")
        self.relationships.setText(f"Relationships: {edge_count}")