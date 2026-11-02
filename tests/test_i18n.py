# tests/test_i18n.py — юнит-тесты задачи 02 эпика i18n
"""resolve_language (чистая таблица без Qt), tr_count (гибрид: plural_ru без
транслятора / Qt %n с переводом через мини-.qm из lrelease), install_translators
(qtbase + app, teardown-контракт).

Канон test_qa_epic.py: QT_QPA_PLATFORM=offscreen до импорта PySide6,
module-scope qapp. Один QApplication на pytest-процесс — каждый тест,
ставивший трансляторы или active_language, обязан снять их в teardown
(removeTranslator + reset_active_language), иначе транслятор (parent = app)
переживёт тест и даст чужим GUI-тестам (test_qa_epic) en-строки вместо русских.

PySide6 6.12 не экспонирует app.translators(): установка проверяется
поведенчески (translate возвращает перевод) и по результату removeTranslator
(True ⇔ транслятор был установлен).

Записи — только в tmp_path (мини-.ts/.qm); subprocess (lrelease) — аргументы
списком, без shell-строк; skipif при отсутствии бинарника.
"""

import logging
import os
import subprocess
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")  # до импорта PySide6

import pytest

from PySide6.QtCore import QCoreApplication, QTranslator
from PySide6.QtWidgets import QApplication

from dashboard.qt import i18n
from dashboard.qt.project_model import tr_count

PROJECT_ROOT = Path(__file__).resolve().parents[1]
_LRELEASE = PROJECT_ROOT / ".venv" / "bin" / "pyside6-lrelease"
_needs_lrelease = pytest.mark.skipif(
    not _LRELEASE.exists(), reason="pyside6-lrelease отсутствует в .venv/bin",
)

# Мини-.ts для round-trip теста: контекст TestContext, en numerus-формы.
# Компилируется lrelease'ом только в tmp_path (тестовая фикстура — прямой
# шаблон для en/zh-прогонов задачи 06). Формы БЕЗ %n — tr_count возвращает
# только форму существительного, число добавляет вызывающий (вердикт
# Техлида, задача 06 эпика i18n).
_MINI_TS = """<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE TS>
<TS version="2.1" language="en_US">
<context>
    <name>TestContext</name>
    <message numerus="yes">
        <source>проект</source>
        <translation>
            <numerusform>project</numerusform>
            <numerusform>projects</numerusform>
        </translation>
    </message>
    <message numerus="yes">
        <source>файл</source>
        <translation>
            <numerusform>file</numerusform>
            <numerusform>files</numerusform>
        </translation>
    </message>
</context>
</TS>
"""


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def translator_cleanup():
    """Teardown-контракт (MUST DO 4): тесты складывают в список все
    установленные трансляторы (возврат install_translators или собственные),
    фикстура снимает их и сбрасывает active_language после теста."""
    installed: list[QTranslator] = []
    yield installed
    app = QApplication.instance()
    if app is not None:
        for translator in installed:
            app.removeTranslator(translator)
    i18n.reset_active_language()


@pytest.fixture()
def en_qm(tmp_path):
    """Мини app_en.qm: .ts -> pyside6-lrelease -> .qm (tmp_path only)."""
    ts_path = tmp_path / "mini_en.ts"
    ts_path.write_text(_MINI_TS, encoding="utf-8")
    qm_path = tmp_path / "mini_en.qm"
    subprocess.run(
        [str(_LRELEASE), str(ts_path), "-qm", str(qm_path)],
        check=True, capture_output=True, text=True,
    )
    return qm_path


# --- (а) resolve_language: чистая таблица, без Qt ---

@pytest.mark.parametrize(("setting", "expected"), [("ru", "ru"), ("en", "en"), ("zh_CN", "zh_CN")])
def test_resolve_language_valid_setting_passthrough(setting, expected):
    assert i18n.resolve_language(setting, []) == expected


def test_resolve_language_system_first_supported_match_wins():
    assert i18n.resolve_language("system", ["ru-RU", "en"]) == "ru"
    assert i18n.resolve_language("system", ["fr", "en-US"]) == "en"
    assert i18n.resolve_language("system", ["zh-Hans-CN", "x"]) == "zh_CN"


def test_resolve_language_fallback_to_ru():
    assert i18n.resolve_language("system", []) == "ru"
    assert i18n.resolve_language("system", ["de-DE"]) == "ru"


@pytest.mark.parametrize("setting", ["fr", ""])
def test_resolve_language_garbage_setting_uses_system_branch(setting):
    assert i18n.resolve_language(setting, ["en"]) == "en"
    assert i18n.resolve_language(setting, []) == "ru"


# --- (б) tr_count: гибрид plural_ru / Qt %n ---

def _refuse_translate(*args, **kwargs):
    raise AssertionError("translate не должен вызываться без активного перевода")


def test_tr_count_without_active_language_uses_plural_ru():
    i18n.reset_active_language()  # предусловие ветки: состояние как до install
    for n, expected in (
        (0, "файлов"), (1, "файл"), (2, "файла"), (5, "файлов"), (11, "файлов"), (21, "файл"),
    ):
        assert tr_count(_refuse_translate, "файл", "файла", "файлов", n) == expected


def test_tr_count_ru_active_language_uses_plural_ru(monkeypatch):
    monkeypatch.setattr(i18n, "active_language", lambda: "ru")
    assert tr_count(_refuse_translate, "файл", "файла", "файлов", 2) == "файла"
    assert tr_count(_refuse_translate, "проект", "проекта", "проектов", 0) == "проектов"
    assert tr_count(_refuse_translate, "проект", "проекта", "проектов", 5) == "проектов"


@_needs_lrelease
def test_tr_count_with_en_translator_returns_qt_numerus(
    qapp, en_qm, translator_cleanup, monkeypatch,
):
    translator = QTranslator(qapp)
    assert translator.load(str(en_qm))
    qapp.installTranslator(translator)
    translator_cleanup.append(translator)
    monkeypatch.setattr(i18n, "active_language", lambda: "en")

    def translate(source, disambiguation, n):
        # Контекст привязан явно: у QCoreApplication.translate сигнатура
        # (context, source, disambiguation, n), а контракт tr_count —
        # translate(one, None, n) (сигнатура self.tr). Вызов остаётся полным
        # (не алиас), контекст тестовый — lupdate tests/ не сканирует.
        return QCoreApplication.translate("TestContext", source, None, n)

    assert tr_count(translate, "проект", "проекта", "проектов", 0) == "projects"
    assert tr_count(translate, "проект", "проекта", "проектов", 1) == "project"
    assert tr_count(translate, "проект", "проекта", "проектов", 2) == "projects"
    assert tr_count(translate, "файл", "файла", "файлов", 1) == "file"
    assert tr_count(translate, "файл", "файла", "файлов", 2) == "files"


# --- (в) install_translators (нужен qapp) ---

def test_install_translators_ru_installs_nothing(qapp, translator_cleanup):
    installed = i18n.install_translators(qapp, "ru")
    translator_cleanup.extend(installed)
    assert installed == []
    assert i18n.active_language() == "ru"  # reset — в teardown фикстуры


@_needs_lrelease
def test_install_translators_en_installs_qtbase_then_app(
    qapp, en_qm, translator_cleanup, monkeypatch, tmp_path,
):
    app_dir = tmp_path / "translations"
    app_dir.mkdir()
    (app_dir / "app_en.qm").write_bytes(en_qm.read_bytes())
    monkeypatch.setattr(i18n, "_APP_TRANSLATIONS_DIR", app_dir)

    installed = i18n.install_translators(qapp, "en")
    translator_cleanup.extend(installed)

    assert len(installed) == 2
    # QTranslator.translate не подставляет %n (сырая форма), поэтому
    # поведенческие проверки — только через QCoreApplication.translate.
    # Форма без числа: число добавляет вызывающий (вердикт Техлида, задача 06).
    assert QCoreApplication.translate("TestContext", "файл", None, 2) == "files"
    # Порядок qtbase -> app: снятие второго (app — содержит наши строки)
    # возвращает source, значит первый — qtbase; последний установленный
    # ищется первым, наши строки приоритетнее системных.
    assert qapp.removeTranslator(installed[1])  # True ⇔ был установлен
    assert QCoreApplication.translate("TestContext", "проект", None, 2) == "проект"
    assert qapp.removeTranslator(installed[0])  # qtbase тоже был установлен
    assert i18n.active_language() == "en"


@_needs_lrelease
def test_install_translators_en_missing_app_qm_warns_not_raises(
    qapp, translator_cleanup, monkeypatch, tmp_path, caplog,
):
    empty_dir = tmp_path / "translations"
    empty_dir.mkdir()
    monkeypatch.setattr(i18n, "_APP_TRANSLATIONS_DIR", empty_dir)

    with caplog.at_level(logging.WARNING):
        installed = i18n.install_translators(qapp, "en")
    translator_cleanup.extend(installed)

    assert len(installed) == 1  # только qtbase_en.qm; app_en.qm отсутствует
    assert qapp.removeTranslator(installed[0])
    assert i18n.active_language() == "en"
    assert any("app_en.qm" in record.getMessage() for record in caplog.records)


@_needs_lrelease
def test_install_translators_en_missing_app_qm_plural_degrades_to_source_singular(
    qapp, translator_cleanup, monkeypatch, tmp_path,
):
    """Фиксирует ФАКТИЧЕСКОЕ поведение деградации (Code-ревью MINOR-2):
    active=en и пустой app-каталог -> обычные строки остаются русскими
    source, но tr_count идёт в Qt-numerus БЕЗ перевода и возвращает
    singular-source на любой n («2 проект» — несогласованная форма: не
    русская plural-форма «проекта» и не en-форма «projects»). Контракт
    active_language сознательно не меняется (решение Техлида); тест
    документирует реальность, а не желаемое."""
    empty_dir = tmp_path / "translations"
    empty_dir.mkdir()
    monkeypatch.setattr(i18n, "_APP_TRANSLATIONS_DIR", empty_dir)

    installed = i18n.install_translators(qapp, "en")
    translator_cleanup.extend(installed)

    assert i18n.active_language() == "en"
    noun = tr_count(
        lambda _s, _d, n: QCoreApplication.translate("TestContext", "проект", None, n),
        "проект", "проекта", "проектов", 2,
    )
    assert noun == "проект"


@_needs_lrelease
def test_install_translators_missing_qtbase_warns_and_skips(
    qapp, en_qm, translator_cleanup, monkeypatch, tmp_path, caplog,
):
    empty_qt_dir = tmp_path / "qt_translations"
    empty_qt_dir.mkdir()
    app_dir = tmp_path / "translations"
    app_dir.mkdir()
    (app_dir / "app_en.qm").write_bytes(en_qm.read_bytes())
    monkeypatch.setattr(i18n, "_QT_TRANSLATIONS_DIR", empty_qt_dir)
    monkeypatch.setattr(i18n, "_APP_TRANSLATIONS_DIR", app_dir)

    with caplog.at_level(logging.WARNING):
        installed = i18n.install_translators(qapp, "en")
    translator_cleanup.extend(installed)

    assert len(installed) == 1  # qtbase не добавлен в результат
    assert QCoreApplication.translate("TestContext", "проект", None, 2) == "projects"
    assert qapp.removeTranslator(installed[0])  # True ⇔ app-транслятор установлен
    assert i18n.active_language() == "en"
    assert any("qtbase_en.qm" in record.getMessage() for record in caplog.records)
