from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QLabel,
    QTabWidget,
    QLineEdit,
    QTextEdit,
    QPushButton,
    QFormLayout
)


class AssetEditorPanel(QWidget):

    def __init__(self, world):
        super().__init__()

        self.world = world
        self.current_entity = None

        layout = QVBoxLayout(self)

        title = QLabel("Asset Editor")
        layout.addWidget(title)

        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)

        # --- GENERAL TAB ---
        self.general_tab = QWidget()
        self.tabs.addTab(self.general_tab, "General")

        form = QFormLayout(self.general_tab)

        self.name_field = QLineEdit()
        self.description_field = QTextEdit()

        form.addRow("Name", self.name_field)
        form.addRow("Description", self.description_field)

        # --- SAVE BUTTON ---
        self.save_button = QPushButton("Save")
        self.save_button.clicked.connect(self.save_entity)

        layout.addWidget(self.save_button)

    # --------------------------------------------------

    def load_entity(self, entity):

        self.current_entity = entity

        if not entity:
            self.name_field.setText("")
            self.description_field.setText("")
            return

        self.name_field.setText(entity.get("name", ""))
        self.description_field.setText(entity.get("description", ""))

    # --------------------------------------------------

    def save_entity(self):

        if not self.current_entity:
            return

        self.current_entity["name"] = self.name_field.text()
        self.current_entity["description"] = self.description_field.toPlainText()