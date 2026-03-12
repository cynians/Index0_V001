import sys

from PySide6.QtWidgets import QApplication

from editor_backend import EditorBackend
from ui_main_window import MainWindow


def main():

    app = QApplication(sys.argv)

    backend = EditorBackend()
    backend.load_entries()

    window = MainWindow(backend)
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()