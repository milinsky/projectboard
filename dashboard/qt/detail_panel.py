# dashboard/qt/detail_panel.py — только Qt, без логики скана/хранения
"""DetailPanel: правая половина мастер-детейл (задача 09).

Метаданные выбранного проекта (имя, полный путь с копированием, дата, размер,
флаг «README усечён»), кнопка «Открыть в ZCode» и README в QTextBrowser.

Инварианты (архитектура п. 4.5/4.6/10, декомпозиция риски №2/№3):
- панель НИКОГДА не запускает ZCode и не показывает QMessageBox об ошибке
  запуска — только эмитит open_requested(path); владелец действия и
  обработки ошибок — MainWindow (задача 10);
- внешние ссылки открываются только по явному клику с подтверждением:
  setOpenExternalLinks(False), anchorClicked -> allowlist схем (только http/https)
  -> QMessageBox.question; прочие схемы (file:, qrc:, кастомные, без схемы)
  отвергаются БЕЗ вызова QDesktopServices.openUrl;
- панель не делает ввода-вывода: контент README уже в ProjectEntry;
- HTML-кэш по rel_path очищается только явным invalidate_cache(), который
  зовёт MainWindow после каждого нового скана.
"""

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from dashboard import mdrender
from dashboard.models import ProjectEntry
from dashboard.qt.project_model import format_datetime, format_size
from dashboard.zcode_opener import zcode_app_exists

_PLACEHOLDER = "Нажмите „Индексировать“"
NO_ZCODE_TIP = "ZCode.app не найден"  # публичное имя: импортируется в main_window
_TRUNCATED_TEXT = "README усечён"
_ALLOWED_SCHEMES = ("http", "https")
_REJECT_TITLE = "Ссылка не открывается"


def _format_mtime(mtime: float) -> str:
    """«—» для отсутствующего mtime (<=0, в т.ч. дефолт битого кэша); остальное —
    единый форматтер project_model.format_datetime (Code-ревью MINOR: форматы
    панели и таблицы не должны расходиться)."""
    if mtime <= 0:
        return "—"
    return format_datetime(mtime)


class DetailPanel(QWidget):
    """Панель деталей. Единственный исходящий сигнал — open_requested(str)."""

    # путь проекта; запуск ZCode и QMessageBox об ошибке — владелец MainWindow (задача 10)
    open_requested = Signal(str)

    def __init__(self, max_render_chars: int, parent=None) -> None:
        super().__init__(parent)
        self._max_chars = max_render_chars
        self._entry: ProjectEntry | None = None
        self._cache: dict[str, str] = {}          # rel_path -> html

        self._name_label = QLabel()
        # имя/путь — недоверенные данные из README/ФС: только plain text
        self._name_label.setTextFormat(Qt.TextFormat.PlainText)
        self._name_label.setStyleSheet("font-size: 16px; font-weight: bold;")
        self._name_label.setWordWrap(True)

        self._path_label = QLabel()
        self._path_label.setTextFormat(Qt.TextFormat.PlainText)
        self._path_label.setWordWrap(True)
        self._copy_button = QPushButton("Скопировать путь")
        self._copy_button.clicked.connect(self._copy_path)

        self._mtime_label = QLabel()
        self._size_label = QLabel()
        self._truncated_label = QLabel(_TRUNCATED_TEXT)
        self._truncated_label.setVisible(False)

        self._open_button = QPushButton("Открыть в ZCode")
        self._open_button.clicked.connect(self._emit_open_requested)

        self._browser = QTextBrowser()
        self._browser.setOpenExternalLinks(False)
        # только anchorClicked, без внутренней навигации браузера по ссылкам
        self._browser.setOpenLinks(False)
        self._browser.document().setDefaultStyleSheet(mdrender.STYLESHEET)
        self._browser.anchorClicked.connect(self._confirm_and_open)

        path_row = QHBoxLayout()
        path_row.addWidget(self._path_label, stretch=1)
        path_row.addWidget(self._copy_button)

        layout = QVBoxLayout(self)
        layout.addWidget(self._name_label)
        layout.addLayout(path_row)
        layout.addWidget(self._mtime_label)
        layout.addWidget(self._size_label)
        layout.addWidget(self._truncated_label)
        layout.addWidget(self._open_button)
        layout.addWidget(self._browser, stretch=1)

        self.show_entry(None)

    def show_entry(self, entry: ProjectEntry | None) -> None:
        """Показать проект или пустое состояние (None). Панель не читает диск."""
        self._entry = entry
        if entry is None:
            self._name_label.setText("")
            self._path_label.setText("")
            self._mtime_label.setText("")
            self._size_label.setText("")
            self._truncated_label.setVisible(False)
            self._copy_button.setEnabled(False)
            self._browser.setPlainText(_PLACEHOLDER)
        else:
            self._name_label.setText(entry.name)
            self._path_label.setText(entry.path)
            self._mtime_label.setText(f"Изменён: {_format_mtime(entry.mtime)}")
            self._size_label.setText(f"Размер: {format_size(entry.dir_size_bytes)}")
            self._truncated_label.setVisible(entry.readme_truncated)
            self._copy_button.setEnabled(True)
            if entry.readme_error or entry.readme_content == "":
                # notice-ветка render_readme (html=None): сообщение вместо рендера
                rendered = mdrender.render_readme(entry, self._max_chars)
                self._browser.setPlainText(rendered.notice or "")
            else:
                # кэш до вызова render_readme: попадание не перерендеривает markdown
                html = self._cache.get(entry.rel_path)
                if html is None:
                    rendered = mdrender.render_readme(entry, self._max_chars)
                    html = rendered.html or ""
                    self._cache[entry.rel_path] = html
                self._browser.setHtml(html)
        self._update_open_button()

    def invalidate_cache(self) -> None:
        """Очистка HTML-кэша; вызывает MainWindow после каждого нового скана."""
        self._cache.clear()

    def _update_open_button(self) -> None:
        # Деградация §3: без ZCode.app кнопка дизейблится с тултипом,
        # но остаётся видимой (не скрывается). Без выбора нечего открывать.
        if self._entry is None:
            self._open_button.setEnabled(False)
            self._open_button.setToolTip("")
            return
        exists = zcode_app_exists()
        self._open_button.setEnabled(exists)
        self._open_button.setToolTip("" if exists else NO_ZCODE_TIP)

    def _copy_path(self) -> None:
        if self._entry is not None:
            QApplication.clipboard().setText(self._entry.path)

    def _emit_open_requested(self) -> None:
        if self._entry is not None:
            self.open_requested.emit(self._entry.path)

    def _confirm_and_open(self, url: QUrl) -> None:
        # Allowlist схем (Security-ревью, HIGH): URL из недоверенного README
        # открываем ТОЛЬКО для http/https; file:/qrc:/кастомные/без схемы —
        # отказ БЕЗ вызова QDesktopServices.openUrl.
        scheme = url.scheme().lower()
        if scheme not in _ALLOWED_SCHEMES:
            QMessageBox.information(
                self,
                _REJECT_TITLE,
                f"Локальные и нестандартные ссылки не открываются: {url.toString()}",
            )
            return
        answer = QMessageBox.question(
            self,
            "Открыть ссылку",
            f"Открыть ссылку в браузере?\n{url.toString()}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            QDesktopServices.openUrl(url)
