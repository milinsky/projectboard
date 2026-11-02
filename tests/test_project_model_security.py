# tests/test_project_model_security.py — security-доработка задачи 09 в project_model
"""Анти-тесты Security-ревью: экстремальные mtime не роняют форматирование,
тултип не интерпретирует недоверенные пути как rich text. Дополнено тестами
форматтеров и склонения (Code-ревью MINOR/NIT)."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")  # до импорта PySide6

import re

import pytest

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from dashboard.models import ProjectEntry
from dashboard.qt.project_model import ProjectTableModel, format_datetime, format_size, plural_ru


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def test_format_datetime_extreme_mtime_returns_fallback():
    """mtime 1e18 (недоверенные данные) не бросает — фолбэк «—»."""
    assert format_datetime(1e18) == "—"


def test_format_datetime_nan_returns_fallback():
    assert format_datetime(float("nan")) == "—"


def test_format_datetime_normal_value_unchanged():
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}", format_datetime(1735689600.0))


def test_format_datetime_zero_mtime_returns_fallback():
    """mtime=0 (дефолт битого кэша) — не «1970», а «—» (Code-ревью MINOR)."""
    assert format_datetime(0) == "—"


# --- Форматтеры на нормальных значениях (Code-ревью: обязательные тесты) ---

def test_format_size_normal_values():
    assert format_size(512) == "512 Б"
    assert format_size(3 * 1024 * 1024) == "3.0 МиБ"
    assert format_size(0) == "0 Б"


def test_format_size_kib_and_gib():
    assert format_size(1536) == "1.5 КиБ"
    assert format_size(5 * 1024 ** 3) == "5.0 ГиБ"


def test_tooltip_escapes_html_like_path(qapp):
    """Путь с HTML-подобными символами не рендерится тултипом как разметка."""
    model = ProjectTableModel()
    model.set_projects([ProjectEntry(
        name="<b>proj</b>",
        path="/tmp/<b>dir</b>&co",
        rel_path="<b>proj</b>",
        file_count=3,
    )])
    tip = model.data(model.index(0, 0), Qt.ItemDataRole.ToolTipRole)
    assert isinstance(tip, str)
    # данные экранированы: сырых тегов из пути в строке нет
    assert "<b>dir</b>" not in tip
    assert "&lt;b&gt;dir&lt;/b&gt;" in tip
    # принудительный rich text — чтобы escape отобразился как текст, а не литерал
    assert tip.startswith("<span")
    assert "3 файла" in tip  # склонение (Code-ревью NIT: не «3 файлов»)


def test_tooltip_file_count_pluralization(qapp):
    """Склонение счётчика файлов: 1 файл / 3 файла / 5 файлов / 11 файлов."""
    cases = {1: "1 файл", 2: "2 файла", 5: "5 файлов", 11: "11 файлов", 21: "21 файл"}
    for file_count, expected in cases.items():
        model = ProjectTableModel()
        model.set_projects([ProjectEntry(name="p", path="/tmp/p", rel_path="p",
                                         file_count=file_count)])
        tip = model.data(model.index(0, 0), Qt.ItemDataRole.ToolTipRole)
        assert expected in tip


def test_plural_ru_forms():
    assert plural_ru(1, "файл", "файла", "файлов") == "файл"
    assert plural_ru(3, "файл", "файла", "файлов") == "файла"
    assert plural_ru(5, "файл", "файла", "файлов") == "файлов"
    assert plural_ru(11, "файл", "файла", "файлов") == "файлов"
    assert plural_ru(21, "проект", "проекта", "проектов") == "проект"
