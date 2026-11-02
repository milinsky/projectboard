# dashboard/qt/main_window.py — MainWindow: сборка GUI и lifecycle фонового скана
"""Главное окно (задача 10): тулбар, мастер-детейл QSplitter, статусбар.

Только проводка готовых компонентов (config, storage, scan_worker,
project_model, detail_panel, zcode_opener) — логики скана/хранения/рендера
здесь нет (архитектура п. 4.1/4.5). Инварианты:
- при старте только чтение конфига и JSON-кэша: никакого скана и записи;
- фоновый код НИКОГДА не трогает виджеты — обмен только через queued-сигналы
  ScanWorker, все обращения к GUI — в слотах MainWindow (GUI-поток);
- на каждый скан — НОВЫЕ QThread + ScanWorker (moveToThread); по finished/failed:
  thread.quit() -> thread.wait() -> deleteLater обоих; двойной запуск невозможен
  по построению (во время скана кнопка — «Отмена», клик отменяет, не запускает);
- единственный вызов zcode_opener.open_in_zcode — метод _open_in_zcode:
  сигнал панели open_requested, контекстное меню и двойной клик сходятся в него.
"""

from pathlib import Path

from PySide6.QtCore import QEvent, QModelIndex, QObject, QPoint, QRect, Qt, QThread
from PySide6.QtGui import QAction, QActionGroup, QCloseEvent, QCursor, QMouseEvent, QPainter, QPalette
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTableView,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from dashboard import config, storage
from dashboard.models import ProjectEntry, ScanResult
from dashboard.qt.detail_panel import DetailPanel, NO_ZCODE_TIP
from dashboard.qt.project_model import ProjectFilterProxy, ProjectTableModel, tr_count
from dashboard.qt.scan_worker import ScanWorker
from dashboard.scanner import DEFAULT_IGNORE_NAMES, ScanOptions
from dashboard.zcode_opener import open_in_zcode, zcode_app_exists

_COLUMN_GROUP = 1  # колонка «Группа» (headerData section 1); сортировка по умолчанию


def _format_seconds(duration_ms: int) -> str:
    return f"{duration_ms / 1000:.2f}"


class _SplitCursorGuard:
    """Override-курсор «⟷» с гарантией снятия.

    На macOS (Cocoa QPA) widget-курсоры применяются ненадёжно (после
    maximize/первого интерактивного ресайза платформа перестаёт их
    отображать) — override-курсор QApplication имеет высший приоритет
    во всём приложении и применяется немедленно на любой платформе.
    """

    def __init__(self) -> None:
        self._active = False

    def apply(self, in_zone: bool) -> None:
        if in_zone and not self._active:
            QApplication.setOverrideCursor(QCursor(Qt.CursorShape.SplitHCursor))
            self._active = True
        elif not in_zone and self._active:
            QApplication.restoreOverrideCursor()
            self._active = False

    def release(self) -> None:
        self.apply(False)


class _HandleCursorFilter(QObject):
    """Override-курсор «⟷» на хендле сплиттера по Enter/Leave."""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._guard = _SplitCursorGuard()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.Type.Enter:
            self._guard.apply(True)
        elif event.type() in (QEvent.Type.Leave, QEvent.Type.Hide):
            self._guard.release()
        return False


class _ResizeCursorHeader(QHeaderView):
    """QHeaderView: курсор «⟷» в зоне ±_MARGIN px от границ колонок и
    видимая линия на каждой границе.

    Подкласс (не eventFilter): mouseMoveEvent выполняется ПОСЛЕ внутренней
    логики QHeaderView, которая сбрасывает viewport-курсор в Arrow вне своей
    зоны ~2 px. Widget-курсор остаётся как дублирующий, а реально видимый —
    override-курсор через _SplitCursorGuard (см. класс). paintSection рисует
    тонкую линию у правого края каждой секции, кроме последней видимой:
    зону захвата видно глазами, не только курсором.
    """

    _MARGIN = 5

    def __init__(self, orientation: Qt.Orientation, parent: QWidget | None = None) -> None:
        super().__init__(orientation, parent)
        self.setMouseTracking(True)
        self._guard = _SplitCursorGuard()

    def _near_edge(self, pos_x: int) -> bool:
        # ВСЕ видимые секции, включая последнюю: без растяжки её правый край —
        # полноценная граница.
        return any(
            abs(self.sectionViewportPosition(section)
                + self.sectionSize(section) - pos_x) <= self._MARGIN
            for section in range(self.count())
            if not self.isSectionHidden(section)
        )

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        super().mouseMoveEvent(event)
        in_zone = self._near_edge(event.position().toPoint().x())
        self.viewport().setCursor(
            Qt.CursorShape.SplitHCursor if in_zone else Qt.CursorShape.ArrowCursor
        )
        self._guard.apply(in_zone)

    def leaveEvent(self, event: QEvent) -> None:
        super().leaveEvent(event)
        self.viewport().setCursor(Qt.CursorShape.ArrowCursor)
        self._guard.release()

    def hideEvent(self, event: QEvent) -> None:
        super().hideEvent(event)
        self._guard.release()

    def paintSection(self, painter: QPainter, rect: QRect, logical_index: int) -> None:
        super().paintSection(painter, rect, logical_index)
        if not self.isSectionHidden(logical_index) and rect.width() > 0:
            # Заметная линия на правом крае КАЖДОЙ секции (без растяжки это
            # всегда настоящая граница): Text-цвет с прозрачностью — виден
            # и в светлой, и в тёмной теме.
            color = self.palette().color(QPalette.ColorRole.Text)
            color.setAlpha(70)
            painter.fillRect(rect.right(), rect.top(), 1, rect.height(), color)


class MainWindow(QMainWindow):
    """Композиция окна; владелец lifecycle скана и действия «Открыть в ZCode»."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Projectboard")
        self.resize(1100, 700)

        # Старт: только конфиг + JSON-кэш. Никакого скана и записи на диск.
        self._cfg = config.load_config(config.CONFIG_PATH)
        self._last_result: ScanResult | None = None
        self._scan_thread: QThread | None = None
        self._worker: ScanWorker | None = None

        self._model = ProjectTableModel(self)
        self._proxy = ProjectFilterProxy(self)
        self._proxy.setSourceModel(self._model)
        self._panel = DetailPanel(
            max_render_chars=self._cfg.max_readme_render_chars, parent=self
        )
        # BUG-001 (QA): проводка сигнала панели — без неё кнопка «Открыть в ZCode»
        # в панели эмитит open_requested в пустоту; обработчик — единый _open_in_zcode.
        self._panel.open_requested.connect(self._open_in_zcode)

        self._build_toolbar()
        self._build_language_menu()
        self._build_central()
        self._build_statusbar()
        self._load_cached_index()

    # ---------- композиция ----------

    def _build_toolbar(self) -> None:
        toolbar = QToolBar(self.tr("Главная"), self)
        toolbar.setMovable(False)
        toolbar.setFloatable(False)
        self.addToolBar(toolbar)

        self._index_action = QAction(self.tr("Индексировать"), self)
        self._index_action.triggered.connect(self._on_index_clicked)
        toolbar.addAction(self._index_action)

        self._root_edit = QLineEdit(self._cfg.root, self)
        self._root_edit.setReadOnly(True)
        self._root_edit.setMinimumWidth(260)
        self._root_edit.setToolTip(self.tr("Корень сканирования"))
        toolbar.addWidget(self._root_edit)

        browse_button = QPushButton(self.tr("Обзор…"), self)
        browse_button.clicked.connect(self._on_browse_clicked)
        toolbar.addWidget(browse_button)

        self._search_edit = QLineEdit(self)
        self._search_edit.setPlaceholderText(self.tr("Поиск по имени и пути…"))
        self._search_edit.setClearButtonEnabled(True)
        self._search_edit.setMinimumWidth(220)
        self._search_edit.textChanged.connect(self._proxy.setFilterFixedString)
        toolbar.addWidget(self._search_edit)

        readme_check = QCheckBox(self.tr("Искать в README"), self)
        readme_check.toggled.connect(self._proxy.set_search_in_readme)
        toolbar.addWidget(readme_check)

    def _build_central(self) -> None:
        self._table = QTableView(self)
        self._table.setModel(self._proxy)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.verticalHeader().setVisible(False)
        # Свой header: курсор «⟷» в зоне ±5 px у границ колонок (см. класс).
        self._table.setHorizontalHeader(_ResizeCursorHeader(Qt.Orientation.Horizontal, self._table))
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setMinimumSectionSize(48)
        # БЕЗ растяжки последней колонки: растянутая колонка создаёт широкую
        # «мёртвую» зону без границы (диагностика 2026-11-02: пользователь
        # наводил курсор в ~170 px правее реальной границы, внутри пустой
        # растянутой «Размер»). Теперь у каждой колонки настоящий правый край.
        header.setStretchLastSection(False)
        # Начальные ширины секций: явные границы, которые видно и за которые
        # удобно тянуть (мас-style рисует зону захвата только у границы секции).
        for column, width in enumerate((220, 110, 260, 130, 90)):
            self._table.setColumnWidth(column, width)
        # Сортировка по умолчанию (Группа, Имя): proxy-сортировка стабильна,
        # поэтому внутри группы сохраняется исходный порядок (group, name).
        header.setSortIndicator(_COLUMN_GROUP, Qt.SortOrder.AscendingOrder)
        self._table.setSortingEnabled(True)

        self._table.selectionModel().selectionChanged.connect(self._on_selection_changed)
        self._table.doubleClicked.connect(self._on_double_clicked)
        self._table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._table.customContextMenuRequested.connect(self._show_context_menu)

        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        splitter.addWidget(self._table)
        splitter.addWidget(self._panel)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        splitter.setChildrenCollapsible(False)
        # Дефолтный хендл mac-стиля почти невидим и не «ловится» мышью;
        # явная ширина даёт комфортную зону захвата вертикальной грани,
        # курсор SplitHCursor — widget-курсор + override (Enter/Leave).
        splitter.setHandleWidth(8)
        handle = splitter.handle(1)
        handle.setCursor(Qt.CursorShape.SplitHCursor)
        self._handle_cursor_filter = _HandleCursorFilter(self)
        handle.installEventFilter(self._handle_cursor_filter)
        self.setCentralWidget(splitter)

    def _build_statusbar(self) -> None:
        self._status_label = QLabel(self)
        self.statusBar().addWidget(self._status_label, 1)

        self._errors_button = QPushButton(self)
        self._errors_button.setFlat(True)
        self._errors_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._errors_button.setToolTip(self.tr("Показать список ошибок скана"))
        self._errors_button.clicked.connect(self._show_errors_dialog)
        self._errors_button.setVisible(False)
        self.statusBar().addPermanentWidget(self._errors_button)

    # ---------- меню «Язык»: первый menu bar приложения ----------

    def _build_language_menu(self) -> None:
        # Стандартные пункты app-menu (About/Hide/Quit) создаёт платформа —
        # своих QAction с AboutRole/QuitRole не добавляем (архитектура п. 4.7).
        menu = self.menuBar().addMenu(self.tr("Язык"))
        group = QActionGroup(self)
        group.setExclusive(True)
        # «Системный» переводится как обычная строка; самоназвания языков —
        # литералы БЕЗ tr (бриф §9: Русский / English / 简体中文 выглядят
        # одинаково на любом языке; «Русский» — в allowlist гейта кириллицы).
        for value, label in (
            ("system", self.tr("Системный")),
            ("ru", "Русский"),
            ("en", "English"),
            ("zh_CN", "简体中文"),
        ):
            action = QAction(label, self)
            action.setCheckable(True)
            action.setData(value)
            group.addAction(action)
            menu.addAction(action)
            # value — аргументом по умолчанию: без него lambda из цикла
            # захватывает последний пункт (подводный камень задачи).
            action.triggered.connect(
                lambda checked=False, v=value: self._set_language(v)
            )
            if value == self._cfg.language:
                action.setChecked(True)

    def _set_language(self, value: str) -> None:
        # Запись конфига ТОЛЬКО здесь, по действию пользователя (инвариант
        # gui.md №5: при старте — только чтение); неизменённое значение —
        # ни записи, ни диалога.
        if value == self._cfg.language:
            return
        self._cfg.language = value
        self._cfg.save(config.CONFIG_PATH)
        # Язык процесса меняется только рестартом (монтаж — в main.py),
        # живое переключение вне скоупа (бриф §5).
        QMessageBox.information(self, self.tr("Язык"),
                                self.tr("Язык применится после перезапуска"))

    # ---------- старт ----------

    def _load_cached_index(self) -> None:
        result = storage.load_index(config.INDEX_PATH)
        if result is not None:
            self._last_result = result
            self._model.set_projects(result.projects)
            self._panel.show_entry(None)  # выделения ещё нет — плейсхолдер
        self._refresh_status()
        self._update_errors_button()

    def _refresh_status(self) -> None:
        if self._last_result is None:
            self._status_label.setText(self.tr("Нет данных — нажмите «Индексировать»"))
            return
        count = len(self._last_result.projects)
        # lambda-обёртка обязательна: lupdate извлекает source-ключ только из
        # синтаксического tr-вызова (аргументы tr_count для него невидимы).
        # Инвариант Code-ревью: литерал в lambda синхронен one-аргументу.
        noun = tr_count(lambda _s, _d, n: self.tr("проект", None, n), "проект", "проекта", "проектов", count)
        text = self.tr("%1 %2, скан %3 с").replace("%1", str(count)).replace("%2", noun).replace(
            "%3", _format_seconds(self._last_result.duration_ms))
        if self._last_result.root != self._cfg.root:
            text += self.tr(" — индекс построен для другого корня")
        self._status_label.setText(text)

    def _update_errors_button(self) -> None:
        count = len(self._last_result.errors) if self._last_result is not None else 0
        if count == 0:
            self._errors_button.setVisible(False)
            return
        noun = tr_count(lambda _s, _d, n: self.tr("ошибка", None, n), "ошибка", "ошибки", "ошибок", count)
        self._errors_button.setText(self.tr("%1 %2").replace("%1", str(count)).replace("%2", noun))
        self._errors_button.setVisible(True)

    # ---------- скан: lifecycle (архитектура п. 4.5) ----------

    def _on_index_clicked(self) -> None:
        if self._scan_thread is not None:
            # Кнопка сейчас — «Отмена»: второй запуск невозможен по построению.
            if self._worker is not None:
                self._worker.request_cancel()
            return

        root = Path(self._cfg.root)
        if not root.is_dir():
            QMessageBox.warning(
                self,
                self.tr("Индексировать"),
                self.tr("Корень сканирования не существует или не каталог:\n%1").replace(
                    "%1", self._cfg.root),
            )
            return

        options = ScanOptions(
            root=root,
            max_depth=self._cfg.max_depth,
            ignore_names=frozenset(DEFAULT_IGNORE_NAMES | set(self._cfg.extra_ignore_names)),
            max_readme_store_bytes=self._cfg.max_readme_store_bytes,
        )

        thread = QThread(self)
        worker = ScanWorker(options)  # без parent — иначе moveToThread невозможен
        worker.moveToThread(thread)
        thread.started.connect(worker.start)
        worker.progress.connect(self._on_scan_progress)
        worker.finished.connect(self._on_scan_finished)
        worker.failed.connect(self._on_scan_failed)

        self._scan_thread = thread
        self._worker = worker
        self._index_action.setText(self.tr("Отмена"))
        self._status_label.setText(
            self.tr("Просканировано %1, найдено %2…").replace("%1", "0").replace("%2", "0")
        )
        thread.start()

    def _on_scan_progress(self, visited: int, found: int) -> None:
        # GUI-поток (queued-сигнал): только текст статусбара, без накопления строк.
        self._status_label.setText(
            self.tr("Просканировано %1, найдено %2…")
            .replace("%1", str(visited)).replace("%2", str(found))
        )

    def _on_scan_finished(self, result: ScanResult) -> None:
        # GUI-поток (queued-сигнал). Отменённый скан (cancelled=True, частичный
        # результат) проходит этот же штатный путь сохранения — это не failed.
        try:
            storage.save_index(result, config.INDEX_PATH)
        except (OSError, ValueError) as exc:
            # ValueError — суррогатные пути из save_index (симметрично storage/config)
            QMessageBox.critical(
                self, self.tr("Сохранение индекса"),
                self.tr("Не удалось сохранить индекс: %1").replace("%1", str(exc)),
            )
        self._last_result = result
        self._model.set_projects(result.projects)
        self._panel.invalidate_cache()
        self._panel.show_entry(None)  # reset модели снял выделение
        self._refresh_status()
        self._update_errors_button()
        self._finish_scan_lifecycle()

    def _on_scan_failed(self, code: str, detail: str) -> None:
        # Старый индекс остаётся в таблице (архитектура п. 9); индекс НЕ сохраняем.
        # Переводим КОД ошибки (строковый контракт scan_worker ↔ main_window:
        # "root_missing" | "root_not_dir" | "oserror"), detail — недоверенный.
        self._finish_scan_lifecycle()                 # порядок: lifecycle -> dialog -> refresh
        if code == "root_missing":
            QMessageBox.critical(self, self.tr("Ошибка индексации"),
                                 self.tr("Корень сканирования не существует:\n%1").replace(
                                     "%1", detail))
        elif code == "root_not_dir":
            QMessageBox.critical(self, self.tr("Ошибка индексации"),
                                 self.tr("Корень сканирования не каталог:\n%1").replace(
                                     "%1", detail))
        else:                                         # "oserror": detail — техническая строка
            QMessageBox.critical(self, self.tr("Ошибка индексации"), detail)
        self._refresh_status()

    def _finish_scan_lifecycle(self) -> None:
        """Обязательный порядок: quit() -> wait() -> deleteLater обоих."""
        self._index_action.setText(self.tr("Индексировать"))
        thread, worker = self._scan_thread, self._worker
        self._scan_thread = None
        self._worker = None
        if thread is None:
            return
        thread.quit()
        thread.wait()
        if worker is not None:
            worker.deleteLater()  # воркер не удаляется раньше завершения потока
        thread.deleteLater()

    # ---------- корень сканирования ----------

    def _on_browse_clicked(self) -> None:
        chosen = QFileDialog.getExistingDirectory(
            self, self.tr("Выберите корень сканирования"), self._cfg.root
        )
        if not chosen:
            return
        self._cfg.root = chosen
        self._root_edit.setText(chosen)
        self._cfg.save(config.CONFIG_PATH)
        # Индекс НЕ перечитываем (декомпозиция, риск №4): только пометка в
        # статусбаре; новые данные появятся после «Индексировать».
        self._refresh_status()

    # ---------- выбор строки / открытие в ZCode ----------

    def _entry_at_proxy(self, proxy_index: QModelIndex) -> ProjectEntry | None:
        source_index = self._proxy.mapToSource(proxy_index)
        if not source_index.isValid():
            return None
        return self._model.entry_at(source_index.row())

    def _on_selection_changed(self) -> None:
        rows = self._table.selectionModel().selectedRows()
        entry = self._entry_at_proxy(rows[0]) if rows else None
        self._panel.show_entry(entry)

    def _on_double_clicked(self, index: QModelIndex) -> None:
        if not index.isValid():
            return
        entry = self._entry_at_proxy(index)
        if entry is not None:
            self._open_in_zcode(entry.path)

    def _show_context_menu(self, pos: QPoint) -> None:
        index = self._table.indexAt(pos)
        if not index.isValid():
            return
        menu = QMenu(self._table)
        open_action = menu.addAction(self.tr("Открыть в ZCode"))
        if not zcode_app_exists():
            # Деградация, а не исчезновение (архитектура п. 9, Code-ревью NIT):
            # пункт остаётся видимым, но задизейблен с причиной.
            open_action.setEnabled(False)
            open_action.setToolTip(NO_ZCODE_TIP())
        menu.setToolTipsVisible(True)
        if menu.exec(self._table.viewport().mapToGlobal(pos)) is open_action:
            entry = self._entry_at_proxy(index)
            if entry is not None:
                self._open_in_zcode(entry.path)

    def _open_in_zcode(self, path: str) -> None:
        # ЕДИНСТВЕННОЕ место вызова zcode_opener.open_in_zcode (декомпозиция,
        # риск №2): панель, контекстное меню и двойной клик сходятся сюда.
        # Переводим КОД ошибки (OpenResult.error_code: "not_absolute" |
        # "dir_not_found" | "timeout" | "open_missing" | "open_failed");
        # недоверенные строки (path, stderr) — только %1-подстановка.
        result = open_in_zcode(path)
        if not result.ok:
            if result.error_code == "not_absolute":
                QMessageBox.warning(self, self.tr("Открыть в ZCode"),
                                    self.tr("Ожидается абсолютный путь: %1").replace(
                                        "%1", path))
            elif result.error_code == "dir_not_found":
                QMessageBox.warning(self, self.tr("Открыть в ZCode"),
                                    self.tr("Каталог не найден: %1").replace("%1", path))
            elif result.error_code == "timeout":
                QMessageBox.warning(self, self.tr("Открыть в ZCode"),
                                    self.tr("Превышено время ожидания (10 с)"))
            elif result.error_code == "open_missing":
                QMessageBox.warning(self, self.tr("Открыть в ZCode"),
                                    self.tr("Утилита open не найдена"))
            elif result.error_code == "open_failed":
                QMessageBox.warning(self, self.tr("Открыть в ZCode"),
                                    self.tr("Не удалось открыть: %1").replace(
                                        "%1", result.error_message or ""))
            elif result.error_message:
                QMessageBox.warning(self, self.tr("Открыть в ZCode"), result.error_message)
            else:
                QMessageBox.warning(self, self.tr("Открыть в ZCode"),
                                    self.tr("не удалось открыть каталог"))

    # ---------- ошибки скана ----------

    def _show_errors_dialog(self) -> None:
        if self._last_result is None:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle(self.tr("Ошибки скана"))
        dialog.resize(640, 360)
        layout = QVBoxLayout(dialog)
        details = QPlainTextEdit(dialog)
        details.setReadOnly(True)
        details.setPlainText(
            "\n".join(
                f"{error.path} — {error.reason}" for error in self._last_result.errors
            )
            or self.tr("Нет ошибок")
        )
        layout.addWidget(details)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, parent=dialog)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.exec()

    # ---------- закрытие ----------

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._scan_thread is not None:
            # Отмена + ограниченное ожидание, затем закрытие (архитектура п. 9).
            if self._worker is not None:
                self._worker.request_cancel()
            self._scan_thread.quit()
            if not self._scan_thread.wait(2000):
                # Code-ревью MAJOR: замер дерева теперь прерывается по cancel
                # (scanner._measure_tree), поэтому завершение быстрое; цикл —
                # страховка: закрываемся только после фактического завершения
                # потока (иначе «QThread: Destroyed while thread is still running»).
                while not self._scan_thread.wait(1000):
                    pass
        event.accept()
