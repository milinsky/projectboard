# main.py — точка входа: QApplication + MainWindow.show(); никакой индексации при старте
"""Точка входа приложения (задача 10): только QApplication, показ MainWindow
и event loop. Стартовая загрузка (конфиг + JSON-кэш, без скана и записи) —
внутри MainWindow; индексация — только по кнопке «Индексировать»."""
import sys

from PySide6.QtWidgets import QApplication

from dashboard.qt.main_window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
