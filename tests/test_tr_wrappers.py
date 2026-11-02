# tests/test_tr_wrappers.py — ленивые tr-обёртки модели/панели (эпик i18n, задача 03)
"""Тесты задачи 03: переводимые строки project_model/detail_panel/mdrender
ленивы (self.tr/translate в точках показа, ни одной на уровне модуля), а без
установленного транслятора tr возвращает русский source — видимое поведение
побайтно совпадает с до-i18n каноном.

Трансляторы в этой задаче НЕ устанавливаются (en/zh-прогоны — задача 06):
все проверки идут на source-возврате. Канон test_qa_epic.py:
QT_QPA_PLATFORM=offscreen до импорта PySide6, module-scope QApplication.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")  # до импорта PySide6

import pytest

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from dashboard.mdrender import render_readme
from dashboard.models import ProjectEntry
from dashboard.qt.detail_panel import NO_ZCODE_TIP, DetailPanel
from dashboard.qt.project_model import ProjectTableModel, format_size


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def make_entry(**overrides) -> ProjectEntry:
    values = dict(
        name="alpha", path="/scan/root/alpha", rel_path="alpha", group="alpha",
        readme_path="/scan/root/alpha/README.md", mtime=1795000000.0,
        dir_size_bytes=10, file_count=1, readme_size_bytes=10,
        readme_truncated=False, readme_content="# Alpha\n", readme_error=None,
    )
    values.update(overrides)
    return ProjectEntry(**values)


# --- (а) headerData/columnCount: русские заголовки без транслятора, 5 колонок ---

def test_header_data_returns_source_titles_without_translator(qapp):
    model = ProjectTableModel()
    expected = ["Имя", "Группа", "Путь (rel)", "Изменён", "Размер"]
    for section, title in enumerate(expected):
        assert model.headerData(
            section, Qt.Orientation.Horizontal, Qt.ItemDataRole.DisplayRole,
        ) == title


def test_column_count_contract(qapp):
    assert ProjectTableModel().columnCount() == 5


# --- (б) format_size: единицы из translate без транслятора = source ---

def test_format_size_units_source_without_translator(qapp):
    assert format_size(512) == "512 Б"
    assert format_size(3 * 1024 * 1024) == "3.0 МиБ"
    assert format_size(5 * 1024 ** 3) == "5.0 ГиБ"


# --- (в) render_readme: метка усечения приходит параметром, дефолт — русская ---

def test_render_readme_custom_truncation_label_in_html():
    content = "# head\n" + "a" * 3000
    result = render_readme(make_entry(readme_content=content),
                           max_chars=1000, truncation_label="TRUNC-LABEL")
    assert result.html is not None
    assert "<blockquote>TRUNC-LABEL</blockquote>" in result.html
    assert result.notice is None


def test_render_readme_default_truncation_label_is_russian_source():
    content = "# head\n" + "a" * 3000
    result = render_readme(make_entry(readme_content=content), max_chars=1000)
    assert result.html is not None
    assert "<blockquote>README усечён для отображения</blockquote>" in result.html


# --- (г) notice-ветку панели строит панель по признакам entry (порядок == render_readme) ---

def test_panel_shows_error_notice_from_entry_attributes(qapp):
    panel = DetailPanel(max_render_chars=1000)
    panel.show_entry(make_entry(readme_content="", readme_error="boom"))
    assert panel._browser.toPlainText() == "README нечитаем: boom"


def test_panel_shows_empty_notice_from_entry_attributes(qapp):
    panel = DetailPanel(max_render_chars=1000)
    panel.show_entry(make_entry(readme_content=""))
    assert panel._browser.toPlainText() == "README пуст"


def test_panel_error_branch_wins_over_content(qapp):
    """Порядок ветвления панели совпадает с render_readme: ошибка раньше пустоты."""
    panel = DetailPanel(max_render_chars=1000)
    panel.show_entry(make_entry(readme_content="# непустой", readme_error="boom"))
    assert panel._browser.toPlainText() == "README нечитаем: boom"


# --- (д) NO_ZCODE_TIP — функция, source без транслятора ---

def test_no_zcode_tip_is_callable_returns_source(qapp):
    assert callable(NO_ZCODE_TIP)
    assert NO_ZCODE_TIP() == "ZCode.app не найден"
