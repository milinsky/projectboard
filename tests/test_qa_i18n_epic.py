# tests/test_qa_i18n_epic.py — QA-тесты эпика i18n (этап QA, 2026-11-02)
"""Независимые QA-проверки критериев приёмки брифа i18n §8, дополняющие
тесты задач 01–07: (1) плюрал-формы n=0/1/2/5/21 во всех трёх локалях на
РЕАЛЬНЫХ translations/app_*.qm (не мини-фикстурах) — критерий 4; (2) полный
рестарт-цикл «язык читается из config.json -> resolve -> install ->
MainWindow» для ru/en/zh_CN — критерии 3–5 (перезапуск моделируется, как
предписывает архитектура п. 13 «QA»); (3) битый app_<lang>.qm — warning и
русский source, не крах — критерий 5 брифа + архитектура п. 9.

Канон test_qa_epic.py: QT_QPA_PLATFORM=offscreen до импорта PySide6,
module-scope qapp, изолированные пути в tmp_path, запрет скана/записи при
старте, monkeypatch модальных диалогов. Один QApplication на pytest-процесс:
каждый тест, ставивший трансляторы, снимает их в teardown вместе с
reset_active_language (teardown-контракт архитектуры п. 9).
"""

import json
import logging
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")  # до импорта PySide6

import pytest

from PySide6.QtCore import QCoreApplication, Qt
from PySide6.QtWidgets import QApplication

import dashboard.config as config_module
import dashboard.qt.scan_worker as worker_module
import dashboard.storage as storage_module
from dashboard.config import load_config
from dashboard.models import ProjectEntry, ScanError, ScanResult
from dashboard.qt import i18n
from dashboard.qt.main_window import MainWindow
from dashboard.qt.project_model import tr_count
from dashboard.storage import save_index

PROJECT_ROOT = Path(__file__).resolve().parents[1]
_APP_QM_EXISTS = (
    (PROJECT_ROOT / "translations" / "app_en.qm").exists()
    and (PROJECT_ROOT / "translations" / "app_zh_CN.qm").exists()
)


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def isolated_paths(tmp_path, monkeypatch):
    """data/-пути MainWindow направляются в tmp_path; реальный data/ не тронут."""
    cfg_path = tmp_path / "config.json"
    idx_path = tmp_path / "index.json"
    monkeypatch.setattr(config_module, "CONFIG_PATH", cfg_path)
    monkeypatch.setattr(config_module, "INDEX_PATH", idx_path)
    return cfg_path, idx_path


@pytest.fixture()
def forbid_scan_and_writes(monkeypatch):
    def _fail(*args, **kwargs):
        raise AssertionError("при старте приложения недопустимы скан или запись")
    monkeypatch.setattr(worker_module, "scan_root", _fail)
    monkeypatch.setattr(storage_module, "save_index", _fail)


@pytest.fixture()
def translators_down(qapp):
    """Teardown-контракт: все установленные тестом трансляторы снимаются,
    active_language сбрасывается (иначе утечка уронит test_qa_epic)."""
    installed: list = []
    yield installed
    for translator in installed:
        qapp.removeTranslator(translator)
    i18n.reset_active_language()


def _mk_entry(name: str) -> ProjectEntry:
    return ProjectEntry(
        name=name, path=f"/scan/root/{name}", rel_path=name, group=name,
        readme_path=f"/scan/root/{name}/README.md", mtime=0.0,
        dir_size_bytes=512, file_count=1, readme_size_bytes=4,
        readme_truncated=False, readme_content="# T\n", readme_error=None,
    )


def _seed_two_projects_two_errors(cfg_path, idx_path):
    """Кэш на 2 проекта / 2 ошибки / duration 42 мс — как в каноне задачи 06."""
    cfg_path.write_text(json.dumps({"root": "/scan/root"}), encoding="utf-8")
    save_index(
        ScanResult(
            root="/scan/root", duration_ms=42,
            projects=[_mk_entry("alpha"), _mk_entry("beta")],
            errors=[ScanError(path="/scan/root/alpha/x", reason="boom"),
                    ScanError(path="/scan/root/beta/y", reason="meh")],
        ),
        idx_path,
    )


# --- TC-101: плюрал-формы n=0/1/2/5/21 во всех трёх локалях (критерий 4) ---

_PLURAL_N = (0, 1, 2, 5, 21)
# русские формы (ветка plural_ru без активного перевода; 21 — «1 файл»-класс)
_RU_EXPECTED = {
    "проект": {0: "проектов", 1: "проект", 2: "проекта", 5: "проектов", 21: "проект"},
    "ошибка": {0: "ошибок", 1: "ошибка", 2: "ошибки", 5: "ошибок", 21: "ошибка"},
    "файл": {0: "файлов", 1: "файл", 2: "файла", 5: "файлов", 21: "файл"},
}
# en: 2 формы (1 -> singular, прочее -> plural); zh: 1 форма на любой n
_EN_EXPECTED = {
    "проект": ("project", "projects"),
    "ошибка": ("error", "errors"),
    "файл": ("file", "files"),
}
_ZH_EXPECTED = {"проект": "个项目", "ошибка": "个错误", "файл": "个文件"}
_PLURAL_CONTEXT = {"проект": "MainWindow", "ошибка": "MainWindow", "файл": "ProjectTableModel"}
_PLURAL_RU_FORMS = {
    "проект": ("проекта", "проектов"),
    "ошибка": ("ошибки", "ошибок"),
    "файл": ("файла", "файлов"),
}


def test_plural_forms_all_three_locales_real_qm(qapp, translators_down):
    """Критерий 4 брифа: «плюрал N проектов корректен во всех трёх локалях
    (%n-механизм, ru 3 / en 2 / zh 1)» — на реальных каталогах translations/,
    для всех трёх существительных эпика и n=0/1/2/5/21 (en/zh) и ru-ветки."""
    installed = i18n.install_translators(qapp, "en")
    translators_down.extend(installed)
    assert i18n.active_language() == "en"
    for one, (few, many) in _PLURAL_RU_FORMS.items():
        context = _PLURAL_CONTEXT[one]
        singular, plural = _EN_EXPECTED[one]
        for n in _PLURAL_N:
            form = tr_count(
                lambda _s, _d, k, _c=context, _o=one: QCoreApplication.translate(
                    _c, _o, None, k),
                one, few, many, n,
            )
            expected = singular if n == 1 else plural
            assert form == expected, f"en {one!r} n={n}: {form!r} != {expected!r}"

    for translator in installed:
        qapp.removeTranslator(translator)
    translators_down.clear()

    installed = i18n.install_translators(qapp, "zh_CN")
    translators_down.extend(installed)
    assert i18n.active_language() == "zh_CN"
    for one, (few, many) in _PLURAL_RU_FORMS.items():
        context = _PLURAL_CONTEXT[one]
        for n in _PLURAL_N:
            form = tr_count(
                lambda _s, _d, k, _c=context, _o=one: QCoreApplication.translate(
                    _c, _o, None, k),
                one, few, many, n,
            )
            assert form == _ZH_EXPECTED[one], f"zh {one!r} n={n}: {form!r}"

    for translator in installed:
        qapp.removeTranslator(translator)
    translators_down.clear()
    i18n.reset_active_language()

    # ru (source): без активного перевода — русское правило на всей таблице
    for one, (few, many) in _PLURAL_RU_FORMS.items():
        for n in _PLURAL_N:
            assert tr_count(QCoreApplication.translate, one, few, many, n) \
                == _RU_EXPECTED[one][n]


# --- TC-102/103/104: рестарт-цикл «язык из config.json» (критерии 3, 4, 5) ---

def _restart_cycle(qapp, isolated_paths, monkeypatch, forbid_scan_and_writes,
                   translators_down, language, ui_languages=()):
    """Моделирует перезапуск после выбора языка в меню: main() читает НОВЫЙ
    config.json (записанный _set_language), резолвит язык, ставит трансляторы,
    строит MainWindow. Возвращает окно; снятие трансляторов — teardown."""
    cfg_path, idx_path = isolated_paths
    _seed_two_projects_two_errors(cfg_path, idx_path)
    # язык пишем ПОСЛЕ сида кэша (сид перезаписывает config.json целиком)
    cfg_path.write_text(
        json.dumps({"root": "/scan/root", "language": language}), encoding="utf-8",
    )

    cfg = load_config(config_module.CONFIG_PATH)
    assert cfg.language == language, "клик меню должен персистить выбор в config.json"
    resolved = i18n.resolve_language(cfg.language, list(ui_languages))
    translators_down.extend(i18n.install_translators(qapp, resolved))
    return MainWindow(), resolved


@pytest.mark.skipif(not _APP_QM_EXISTS, reason="translations/app_*.qm отсутствуют")
def test_restart_cycle_en_from_config(qapp, isolated_paths, monkeypatch,
                                      forbid_scan_and_writes, translators_down):
    window, resolved = _restart_cycle(qapp, isolated_paths, monkeypatch,
                                      forbid_scan_and_writes, translators_down, "en")
    assert resolved == "en"
    assert i18n.active_language() == "en"
    # поверхности критерия 3: тулбар, заголовки колонок, статусбар, меню, кнопка ошибок
    assert window._index_action.text() == "Index"
    assert window.menuBar().actions()[0].text() == "Language"
    assert window._model.headerData(0, Qt.Orientation.Horizontal) == "Name"
    assert window._status_label.text().startswith("2 projects, scan ")
    assert window._errors_button.text() == "2 errors"
    # checked-пункт меню соответствует языку, выбранному перед «перезапуском»
    checked = [a for a in window.menuBar().actions()[0].menu().actions() if a.isChecked()]
    assert len(checked) == 1 and checked[0].data() == "en"
    window.close()


@pytest.mark.skipif(not _APP_QM_EXISTS, reason="translations/app_*.qm отсутствуют")
def test_restart_cycle_zh_from_config(qapp, isolated_paths, monkeypatch,
                                      forbid_scan_and_writes, translators_down):
    window, resolved = _restart_cycle(qapp, isolated_paths, monkeypatch,
                                      forbid_scan_and_writes, translators_down, "zh_CN")
    assert resolved == "zh_CN"
    assert i18n.active_language() == "zh_CN"
    # qtbase_zh_CN.qm реально загружен и непуст: стандартные строки Qt получают
    # перевод (критерий 4 «те же поверхности», основа для стандартных кнопок)
    installed = translators_down
    assert len(installed) == 2, "qtbase + app, оба установлены"
    assert not installed[0].isEmpty(), "qtbase_zh_CN.qm не должен быть пустым"
    assert window._index_action.text() == "索引"
    assert window.menuBar().actions()[0].text() == "语言"
    assert window._status_label.text().startswith("2 个项目，扫描 ")
    assert window._errors_button.text() == "2 个错误"
    checked = [a for a in window.menuBar().actions()[0].menu().actions() if a.isChecked()]
    assert len(checked) == 1 and checked[0].data() == "zh_CN"
    window.close()


def test_restart_cycle_ru_from_config(qapp, isolated_paths, monkeypatch,
                                      forbid_scan_and_writes, translators_down):
    """ru — source-язык: install ничего не грузит, UI побайтно русский
    (критерий 2) даже когда language=ru записан в конфиг явно."""
    window, resolved = _restart_cycle(qapp, isolated_paths, monkeypatch,
                                      forbid_scan_and_writes, translators_down, "ru")
    assert resolved == "ru"
    assert translators_down == [] and i18n.active_language() == "ru"
    assert window._index_action.text() == "Индексировать"
    assert window._status_label.text().startswith("2 проекта, скан ")
    assert window._errors_button.text() == "2 ошибки"
    window.close()


def test_restart_cycle_system_unsupported_locale_falls_back_to_ru(
    qapp, isolated_paths, monkeypatch, forbid_scan_and_writes, translators_down,
):
    """language="system" + системная локаль вне ru/en/zh -> русский (ответ
    пользователя из брифа §10 п.1; критерий 2)."""
    window, resolved = _restart_cycle(
        qapp, isolated_paths, monkeypatch, forbid_scan_and_writes,
        translators_down, "system", ui_languages=("de-DE", "fr"),
    )
    assert resolved == "ru"
    assert window._index_action.text() == "Индексировать"
    window.close()


# --- TC-105: битый app_<lang>.qm — деградация, не крах (архитектура п. 9) ---

def test_broken_app_qm_warns_and_keeps_russian_source(
    qapp, monkeypatch, tmp_path, caplog, translators_down,
):
    """Битые байты в app_en.qm: QTranslator.load() = False -> warning,
    обычные строки остаются русскими source (fail-open каталога компенсирован
    fail-fast сборки — Security-ревью), active_language всё равно "en"."""
    broken_dir = tmp_path / "translations"
    broken_dir.mkdir()
    (broken_dir / "app_en.qm").write_bytes(b"not a qm file: garbage bytes \x00\x01")
    monkeypatch.setattr(i18n, "_APP_TRANSLATIONS_DIR", broken_dir)

    with caplog.at_level(logging.WARNING):
        installed = i18n.install_translators(qapp, "en")
    translators_down.extend(installed)

    assert any("app_en.qm" in r.getMessage() for r in caplog.records)
    assert i18n.active_language() == "en"
    # обычные строки — русский source (персистентность перевода не требуется)
    assert QCoreApplication.translate("MainWindow", "Индексировать") == "Индексировать"
