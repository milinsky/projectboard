# dashboard/qt/scan_worker.py — обёртка scanner.scan_root для фонового QThread
"""ScanWorker(QObject): переносимый worker скана (архитектура п. 4.5).

Только QtCore (QObject/Signal/Slot) — фоновый код НИКОГДА не трогает виджеты;
весь обмен с GUI — через три сигнала. Lifecycle QThread — в MainWindow
(задача 10): воркер не создаёт потоков и не знает о них. Логики скана нет —
только адаптация: колбэк прогресса переэммитится сигналом (троттлинг ~50 мс
уже внутри сканера), отмена — кооперативная через threading.Event.
"""

import threading

from PySide6.QtCore import QObject, Signal, Slot

from dashboard.scanner import ScanOptions, scan_root


class ScanWorker(QObject):
    progress = Signal(int, int)   # visited, found
    finished = Signal(object)     # ScanResult
    failed = Signal(str)          # фатальная ошибка (root не существует и т.п.)

    def __init__(self, options: ScanOptions, parent=None):
        super().__init__(parent)
        self._options = options
        self._cancel = threading.Event()

    @Slot()
    def start(self) -> None:
        try:
            result = scan_root(self._options, cancel=self._cancel,
                               progress=self._on_progress)
        except (FileNotFoundError, NotADirectoryError) as e:
            self.failed.emit(str(e))
        except OSError as e:            # прочие фатальные — тоже failed, не краш потока
            self.failed.emit(str(e))
        else:
            self.finished.emit(result)

    def request_cancel(self) -> None:   # вызывается GUI-потоком
        self._cancel.set()

    def _on_progress(self, visited: int, found: int) -> None:
        self.progress.emit(visited, found)
