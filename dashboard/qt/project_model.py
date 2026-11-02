# dashboard/qt/project_model.py — модель таблицы проектов и фильтр-прокси (только адаптация к GUI)
"""ProjectTableModel(QAbstractTableModel) + ProjectFilterProxy(QSortFilterProxyModel).

Инвариант (архитектура п. 4.5): отображение (форматированные строки в DisplayRole)
отделено от сортировки (сырые значения через SORT_ROLE); фильтр — кейс-инсензитивная
подстрока по name/rel_path (опционально по readme_content) через setFilterFixedString,
без пересоздания модели. Модуль не знает о QTableView (задача 10), не читает диск
и не содержит логики скана/хранения.
"""

import html
from datetime import datetime

from PySide6.QtCore import (
    QAbstractTableModel,
    QCoreApplication,
    QModelIndex,
    QSortFilterProxyModel,
    Qt,
)

from dashboard.models import ProjectEntry
from dashboard.qt import i18n

SORT_ROLE = Qt.ItemDataRole.UserRole + 1


def _size_units() -> tuple[str, ...]:
    """Единицы размера, лениво в точке вызова (format_size): translate при
    импорте модуля вычисляется до QApplication и трансляторов, поэтому
    переводимые строки живут только внутри функций (правило ленивости tr)."""
    return (
        QCoreApplication.translate("ProjectTableModel", "Б"),
        QCoreApplication.translate("ProjectTableModel", "КиБ"),
        QCoreApplication.translate("ProjectTableModel", "МиБ"),
        QCoreApplication.translate("ProjectTableModel", "ГиБ"),
        QCoreApplication.translate("ProjectTableModel", "ТиБ"),
    )


def plural_ru(count: int, one: str, few: str, many: str) -> str:
    """Русское существительное по числу: 1 файл / 3 файла / 5 файлов.

    Общий хелпер презентационного слоя (тултип таблицы, статусбар main_window).
    """
    n = abs(count) % 100
    if 11 <= n <= 14:
        return many
    n %= 10
    if n == 1:
        return one
    if 2 <= n <= 4:
        return few
    return many


def tr_count(translate, one: str, few: str, many: str, n: int) -> str:
    """Форма существительного по числу n, БЕЗ самого числа — его добавляет
    вызывающий («2 projects» = f"{n} {form}"; симметрично ru-ветке plural_ru).
    Без активного перевода (active_language None/'ru') — русское правило
    plural_ru (source-язык, контракты приёмочных тестов); с переводом en/zh —
    форма по правилам локали из app_<lang>.qm (source-ключ = one; numerus-формы
    в .ts без %n — вердикт Техлида, задача 06 эпика i18n).
    Call sites обязаны передавать translate через lambda-обёртку с прямым
    self.tr(<литерал>, None, n): lupdate извлекает source-ключ только из
    синтаксического tr-вызова (аргументы хелпера для него невидимы); литерал
    в lambda синхронен one-аргументу (инвариант Code-ревью задачи 06)."""
    if i18n.active_language() in (None, "ru"):
        return plural_ru(n, one, few, many)
    return translate(one, None, n)


def format_size(num_bytes: int) -> str:
    """Человекочитаемый размер: 512 -> "512 Б", 3*1024*1024 -> "3.0 МиБ".

    Байтовая ветка определяется ПОЗИЦИЕЙ (units[0]), не литералом «Б»:
    при активном переводе единицы переводятся («B»/…), и сравнение с
    source-литералом сломало бы целочисленный формат (точка внимания
    из отчёта задачи 03 эпика i18n). Без транслятора поведение то же.
    """
    size = float(num_bytes)
    units = _size_units()
    for unit in units:
        if size < 1024 or unit == units[-1]:
            break
        size /= 1024
    if unit == units[0]:
        return f"{int(size)} {unit}"
    return f"{size:.1f} {unit}"


def format_datetime(mtime: float) -> str:
    """mtime (epoch) -> "YYYY-MM-DD HH:MM" (локальное время); «—» вне диапазона
    и для отсутствующего mtime (<=0, дефолт битого кэша) — не «1970»
    (Code-ревью MINOR: форматтеры панели и таблицы едины)."""
    if mtime <= 0:
        return "—"
    try:
        return datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M")
    except (ValueError, OSError, OverflowError):
        # недоверенный mtime из данных (экстремальный/NaN) не должен ронять UI
        return "—"


class ProjectTableModel(QAbstractTableModel):
    """Плоская модель таблицы поверх готового списка ProjectEntry (без диска)."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._projects: list[ProjectEntry] = []

    def set_projects(self, projects: list[ProjectEntry]) -> None:
        """Замена всего списка через reset модели (пустой список валиден)."""
        self.beginResetModel()
        self._projects = list(projects)
        self.endResetModel()

    def entry_at(self, row: int) -> ProjectEntry:
        """ProjectEntry по SOURCE-строке (прокси-строку в source отображает задача 10)."""
        return self._projects[row]

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._projects)

    def columnCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else 5

    def headerData(self, section: int, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            if section == 0:
                return self.tr("Имя")
            if section == 1:
                return self.tr("Группа")
            if section == 2:
                return self.tr("Путь (rel)")
            if section == 3:
                return self.tr("Изменён")
            return self.tr("Размер")
        return None

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not (0 <= index.row() < len(self._projects)):
            return None
        entry = self._projects[index.row()]
        column = index.column()
        if role == Qt.ItemDataRole.DisplayRole:
            return self._display_value(entry, column)
        if role == SORT_ROLE:
            # Сортировка только по сырым значениям: НЕ по форматированным строкам
            # ("512 Б" vs "3.0 МиБ" сравниваются строками неверно).
            if column == 3:
                return entry.mtime          # float
            if column == 4:
                return entry.dir_size_bytes  # int
            return self._display_value(entry, column)  # str: Имя/Группа/Путь (rel)
        if role == Qt.ItemDataRole.ToolTipRole:
            # QToolTip рендерит строки, похожие на HTML, как rich text: экранируем
            # недоверенные данные и принудительно задаём rich text, чтобы escape
            # гарантированно отобразился как текст (Security-ревью, INFO).
            # Порядок сохранён: escape — только к недоверенному пути, ДО склейки;
            # склонение лениво через tr_count (перевод получен до склейки).
            esc_path = html.escape(entry.path)
            noun = tr_count(lambda _s, _d, n: self.tr("файл", None, n), "файл", "файла", "файлов", entry.file_count)
            return f"<span style='white-space:pre'>{esc_path}\n{entry.file_count} {noun}</span>"
        return None

    @staticmethod
    def _display_value(entry: ProjectEntry, column: int) -> str:
        if column == 0:
            return entry.name
        if column == 1:
            return entry.group
        if column == 2:
            return entry.rel_path
        if column == 3:
            return format_datetime(entry.mtime)
        return format_size(entry.dir_size_bytes)


class ProjectFilterProxy(QSortFilterProxyModel):
    """Кейс-инсензитивный фильтр-подстрока по name/rel_path (+ readme_content по флагу).

    Источник — ProjectTableModel (обращается к его entry_at). Сортирует по SORT_ROLE,
    чтобы даты/размеры никогда не сравнивались как форматированные строки.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFilterCaseSensitivity(Qt.CaseInsensitive)
        self.setSortRole(SORT_ROLE)
        self._search_in_readme = False

    def set_search_in_readme(self, enabled: bool) -> None:
        """Включить/выключить поиск по readme_content (переприменить фильтр без reset модели)."""
        enabled = bool(enabled)
        if enabled != self._search_in_readme:
            self._search_in_readme = enabled
            self.invalidateFilter()

    def filterAcceptsRow(self, source_row: int, source_parent) -> bool:
        if source_parent.isValid():
            return False
        rx = self.filterRegularExpression()
        if not rx.pattern():
            return True
        entry = self.sourceModel().entry_at(source_row)
        if rx.match(entry.name).hasMatch() or rx.match(entry.rel_path).hasMatch():
            return True
        return self._search_in_readme and rx.match(entry.readme_content).hasMatch()
