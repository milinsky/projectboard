# main.py — точка входа: монтаж трансляторов + MainWindow.show(); никакой индексации при старте
"""Точка входа приложения (задача 10 + эпик i18n): QApplication, установка
трансляторов по языку из конфига, показ MainWindow и event loop. Стартовая
загрузка (конфиг + JSON-кэш, без скана и записи) — внутри MainWindow;
индексация — только по кнопке «Индексировать»."""
import sys

from PySide6.QtCore import QLocale
from PySide6.QtWidgets import QApplication

from dashboard import config
from dashboard.qt import i18n
from dashboard.qt.main_window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    cfg = config.load_config(config.CONFIG_PATH)          # чтение №1: язык нужен до MainWindow
    language = i18n.resolve_language(cfg.language, QLocale.system().uiLanguages())
    # GC PySide6: без живых ссылок QTranslator удаляется — перевод исчезает.
    # Локальная переменная живёт всё app.exec() (main() не завершена).
    translators = i18n.install_translators(app, language)  # noqa: F841 — держим ссылки
    window = MainWindow()                                  # конфиг читает и сам (чтение №2)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
