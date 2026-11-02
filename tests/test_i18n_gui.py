# tests/test_i18n_gui.py — GUI-тесты эпика i18n: меню «Язык» (задача 05) +
# en/zh-прогоны поверх каталога translations/ (задача 06), teardown-фикстура
"""Нативное меню «Язык» MainWindow (4 exclusive checkable-пункта, checked
синхронен конфигу, запись ТОЛЬКО по клику) и фикстура translator с
обязательным teardown (MUST DO 4).

Отдельный файл (архитектура п. 15): фикстура translator не смешивается с
чужими GUI-тестами. Один QApplication на pytest-процесс — тест, ставивший
трансляторы, обязан снять их (removeTranslator всех + reset_active_language),
иначе транслятор (parent = app) переживёт тест и уронит test_qa_epic
en-строками интермиттентно.

Канон test_qa_epic.py: QT_QPA_PLATFORM=offscreen до импорта PySide6,
module-scope qapp, isolated_paths (monkeypatch CONFIG_PATH/INDEX_PATH на
tmp_path), forbid_scan_and_writes (при старте — только чтение).

«Системный», заголовок меню и «Русский» проверяются на source-строках:
offscreen-локаль ['C'] -> resolve -> 'ru' -> install ничего не грузит;
en/zh-прогоны поверх этой же фикстуры добавит задача 06. Для (д) мини-.ts
с контекстом MainWindow (Русский -> «Russian») «заряжает» анти-тест:
если реализация обернёт самоназвание в tr, пункт станет «Russian» — падение.
QMessageBox.information в offscreen модален и блокирует exec — monkeypatch
обязателен (gui.md, «Грабли»).
"""

import json
import os
import subprocess
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")  # до импорта PySide6

import pytest

from PySide6.QtCore import QCoreApplication, Qt
from PySide6.QtGui import QActionGroup
from PySide6.QtWidgets import QApplication

import dashboard.config as config_module
import dashboard.qt.main_window as main_window_module
import dashboard.qt.scan_worker as worker_module
import dashboard.storage as storage_module
from dashboard.models import ProjectEntry, ScanError, ScanResult
from dashboard.qt import i18n
from dashboard.qt.main_window import MainWindow
from dashboard.storage import save_index

PROJECT_ROOT = Path(__file__).resolve().parents[1]
_LRELEASE = PROJECT_ROOT / ".venv" / "bin" / "pyside6-lrelease"
_needs_lrelease = pytest.mark.skipif(
    not _LRELEASE.exists(), reason="pyside6-lrelease отсутствует в .venv/bin",
)
_needs_app_qm = pytest.mark.skipif(
    not (PROJECT_ROOT / "translations" / "app_en.qm").exists()
    or not (PROJECT_ROOT / "translations" / "app_zh_CN.qm").exists(),
    reason="translations/app_{en,zh_CN}.qm отсутствуют (артефакт задачи 06)",
)

# Мини-.ts с ПЕРЕВОДОМ самоназвания «Русский» в контексте MainWindow:
# translate("MainWindow", "Русский") начнёт возвращать «Russian», поэтому
# обёртка самоназвания в tr стала бы видимой (анти-тест (д) ловит мутацию).
_MINI_TS = """<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE TS>
<TS version="2.1" language="en_US">
<context>
    <name>MainWindow</name>
    <message>
        <source>Русский</source>
        <translation>Russian</translation>
    </message>
</context>
</TS>
"""


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def isolated_paths(tmp_path, monkeypatch):
    """data/-пути MainWindow направляются в tmp_path; реальный data/ не трогается."""
    cfg_path = tmp_path / "config.json"
    idx_path = tmp_path / "index.json"
    monkeypatch.setattr(config_module, "CONFIG_PATH", cfg_path)
    monkeypatch.setattr(config_module, "INDEX_PATH", idx_path)
    return cfg_path, idx_path


def forbid_scan_and_writes(monkeypatch):
    """Автоскан и запись при старте запрещены: любая попытка — ошибка теста."""
    def _fail(*args, **kwargs):
        raise AssertionError("при старте приложения недопустимы скан или запись")
    monkeypatch.setattr(worker_module, "scan_root", _fail)
    monkeypatch.setattr(storage_module, "save_index", _fail)


@pytest.fixture()
def translator(qapp):
    """Монтаж трансляторов как в main(), с обязательным teardown (MUST DO 4,
    архитектура п. 9): install(lang) возвращает список установленных;
    после теста — removeTranslator всех + reset_active_language."""
    installed: list = []

    def _install(language: str) -> list:
        mounted = i18n.install_translators(qapp, language)
        installed.extend(mounted)
        return mounted

    yield _install
    for translator_item in installed:
        qapp.removeTranslator(translator_item)
    i18n.reset_active_language()


def _language_menu(window: MainWindow):
    """Единственное меню первого (и единственного) menuBar приложения.

    menuBar().actions() возвращает title-QAction'ы меню; сам QMenu — за
    QAction.menu()."""
    actions = window.menuBar().actions()
    assert len(actions) == 1  # один menuBar, одно меню (MUST NOT DO 4)
    menu = actions[0].menu()
    assert menu is not None
    return menu


# --- (а) состав меню: 4 exclusive checkable-пункта, заголовок-источник ---

def test_language_menu_four_exclusive_checkable_items(qapp, isolated_paths, monkeypatch):
    forbid_scan_and_writes(monkeypatch)

    window = MainWindow()

    menu = _language_menu(window)
    assert menu.title() == "Язык"  # source-строка: без транслятора tr = source
    actions = menu.actions()
    assert [action.data() for action in actions] == ["system", "ru", "en", "zh_CN"]
    labels = {action.data(): action.text() for action in actions}
    assert labels["system"] == "Системный"   # «Системный» — через self.tr, source без транслятора
    assert labels["ru"] == "Русский"         # самоназвания — литералы
    assert labels["en"] == "English"
    assert labels["zh_CN"] == "简体中文"
    for action in actions:
        assert action.isCheckable()
    groups = {action.actionGroup() for action in actions}
    assert len(groups) == 1
    group = groups.pop()
    assert isinstance(group, QActionGroup)
    assert group.isExclusive()
    window.close()


# --- (б) checked синхронен cfg.language ---

@pytest.mark.parametrize(("configured", "expected"), [("en", "en"), ("system", "system")])
def test_checked_item_follows_config_language(
    qapp, isolated_paths, monkeypatch, configured, expected,
):
    cfg_path, _idx_path = isolated_paths
    cfg_path.write_text(json.dumps({"language": configured}), encoding="utf-8")
    forbid_scan_and_writes(monkeypatch)

    window = MainWindow()

    checked = [action for action in _language_menu(window).actions() if action.isChecked()]
    assert len(checked) == 1
    assert checked[0].data() == expected
    window.close()


# --- (в) клик "en": запись конфига + диалог ровно 1 раз ---

def test_click_en_writes_config_and_shows_dialog_once(qapp, isolated_paths, monkeypatch):
    cfg_path, _idx_path = isolated_paths
    forbid_scan_and_writes(monkeypatch)
    shown: list = []
    monkeypatch.setattr(
        main_window_module.QMessageBox, "information",
        lambda *args, **kwargs: shown.append(True),
    )

    window = MainWindow()
    en_action = next(a for a in _language_menu(window).actions() if a.data() == "en")
    en_action.trigger()

    assert json.loads(cfg_path.read_text(encoding="utf-8"))["language"] == "en"
    assert shown == [True]  # ровно один диалог
    window.close()


# --- (г) клик текущего значения: конфиг не перезаписан, диалога нет ---

def test_click_current_value_does_not_rewrite_config(qapp, isolated_paths, monkeypatch):
    cfg_path, _idx_path = isolated_paths
    cfg_path.write_text(json.dumps({"language": "en"}), encoding="utf-8")
    mtime_before = cfg_path.stat().st_mtime_ns
    content_before = cfg_path.read_bytes()
    forbid_scan_and_writes(monkeypatch)
    shown: list = []
    monkeypatch.setattr(
        main_window_module.QMessageBox, "information",
        lambda *args, **kwargs: shown.append(True),
    )

    window = MainWindow()
    en_action = next(a for a in _language_menu(window).actions() if a.data() == "en")
    en_action.trigger()

    assert cfg_path.stat().st_mtime_ns == mtime_before  # ранний return — без записи
    assert cfg_path.read_bytes() == content_before
    assert shown == []  # диалог тоже за ранним return
    window.close()


# --- (д) самоназвание «Русский» — литерал даже под переводчиком ---

@_needs_lrelease
def test_russian_item_is_literal_even_with_translator(
    qapp, isolated_paths, monkeypatch, translator, tmp_path,
):
    """Анти-тест: если реализация обернёт «Русский» в tr, перевод
    MainWindow::Русский = «Russian» из мини-.qm сделает текст пункта
    «Russian» и тест упадёт; литерал остаётся «Русский» на любом языке."""
    _cfg_path, _idx_path = isolated_paths
    app_dir = tmp_path / "translations"
    app_dir.mkdir()
    ts_path = tmp_path / "mini_en.ts"
    ts_path.write_text(_MINI_TS, encoding="utf-8")
    subprocess.run(
        [str(_LRELEASE), str(ts_path), "-qm", str(app_dir / "app_en.qm")],
        check=True, capture_output=True, text=True,
    )
    monkeypatch.setattr(i18n, "_APP_TRANSLATIONS_DIR", app_dir)
    translator("en")
    # Ловушка заряжена: контекст MainWindow реально переводится («Russian»).
    assert QCoreApplication.translate("MainWindow", "Русский", None) == "Russian"
    assert i18n.active_language() == "en"  # фикстура установила трансляторы

    forbid_scan_and_writes(monkeypatch)
    window = MainWindow()

    ru_item = next(a for a in _language_menu(window).actions() if a.data() == "ru")
    assert ru_item.text() == "Русский"  # самоназвание НЕ зависит от транслятора
    window.close()


# --- (е) en/zh-прогоны поверх каталога translations/ (задача 06, MUST DO 6) ---

def _mk_entry(name: str, size_bytes: int = 10, file_count: int = 1) -> ProjectEntry:
    """Локальный аналог mk_entry канона test_qa_epic (паттерн дублируется
    локально): mtime=0 -> «—» в панели, size управляет форматом format_size."""
    return ProjectEntry(
        name=name, path=f"/scan/root/{name}", rel_path=name, group=name,
        readme_path=f"/scan/root/{name}/README.md", mtime=0.0,
        dir_size_bytes=size_bytes, file_count=file_count, readme_size_bytes=4,
        readme_truncated=False, readme_content="# T\n", readme_error=None,
    )


def _seed_two_projects_two_errors(cfg_path, idx_path):
    """Конфиг+кэш: 2 проекта, 2 ошибки, duration_ms=42 (статусбар «0.04»)."""
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


@_needs_app_qm
def test_en_run_translates_all_surfaces(qapp, isolated_paths, monkeypatch, translator):
    """en-прогон: тулбар, меню, заголовки колонок, статусбар (включая числовые
    формы через .qm), кнопка ошибок, панель. Строки ассертов == строки .ts."""
    cfg_path, idx_path = isolated_paths
    forbid_scan_and_writes(monkeypatch)
    translator("en")  # транслятор ДО конструирования окна (порядок монтажа main())

    empty = MainWindow()  # без кэша: плейсхолдер статусбара и панели
    assert empty._status_label.text() == "No data — press “Index”"
    assert empty._panel._browser.toPlainText() == "Press “Index”"
    empty.close()

    _seed_two_projects_two_errors(cfg_path, idx_path)
    window = MainWindow()
    assert window._index_action.text() == "Index"
    assert window.menuBar().actions()[0].text() == "Language"
    assert window._root_edit.toolTip() == "Scan root"
    assert window._search_edit.placeholderText() == "Search by name and path…"
    assert window._model.headerData(0, Qt.Orientation.Horizontal) == "Name"
    assert window._status_label.text() == "2 projects, scan 0.04 s"
    assert window._errors_button.text() == "2 errors"
    assert window._panel._copy_button.text() == "Copy path"
    assert window._panel._open_button.text() == "Open in ZCode"
    assert window._panel._truncated_label.text() == "README truncated"
    window._panel.show_entry(_mk_entry("gamma", size_bytes=512))
    assert window._panel._mtime_label.text() == "Modified: —"
    # байтовая ветка format_size при переводе единиц: «512 B», не «512.0 B»
    assert window._panel._size_label.text() == "Size: 512 B"
    # тултип таблицы: число добавляет вызывающий, форма из .qm без числа
    window._model.set_projects([_mk_entry("gamma", file_count=2)])
    tooltip = window._model.data(
        window._model.index(0, 0), Qt.ItemDataRole.ToolTipRole
    )
    assert tooltip == "<span style='white-space:pre'>/scan/root/gamma\n2 files</span>"
    window.close()


@_needs_app_qm
def test_en_run_cancel_button_toggles(qapp, isolated_paths, monkeypatch, translator, tmp_path):
    """en-прогон: кнопка «Индексировать»<->«Cancel» через _on_index_clicked с
    замоканным сканом (канон test_qa_epic), прогресс-плейсхолдер en."""
    cfg_path, _idx_path = isolated_paths
    live_root = str(tmp_path)
    cfg_path.write_text(json.dumps({"root": live_root}), encoding="utf-8")
    dialogs: list = []
    monkeypatch.setattr(main_window_module.QMessageBox, "warning",
                        lambda *args, **kwargs: dialogs.append(args))
    monkeypatch.setattr(main_window_module.QMessageBox, "critical",
                        lambda *args, **kwargs: dialogs.append(args))

    def slow_scan(options, cancel=None, progress=None):
        while cancel is None or not cancel.is_set():
            time.sleep(0.005)
        return ScanResult(root=str(options.root), projects=[], errors=[],
                          duration_ms=1, cancelled=True)

    monkeypatch.setattr(worker_module, "scan_root", slow_scan)
    translator("en")
    window = MainWindow()
    window._on_index_clicked()
    assert window._index_action.text() == "Cancel"
    assert window._status_label.text() == "Scanned 0, found 0…"
    window._on_index_clicked()  # второй клик: отмена, НЕ второй поток
    deadline = time.time() + 5
    while window._scan_thread is not None and time.time() < deadline:
        qapp.processEvents()
        time.sleep(0.005)
    assert window._scan_thread is None
    assert window._index_action.text() == "Index"
    assert dialogs == []
    window.close()


@_needs_app_qm
def test_zh_run_translates_key_surfaces(qapp, isolated_paths, monkeypatch, translator):
    """zh-прогон: ключевые поверхности на китайском (числовая форма — одна),
    плюс «текст != русский source» для каждой проверенной поверхности."""
    cfg_path, idx_path = isolated_paths
    forbid_scan_and_writes(monkeypatch)
    translator("zh_CN")

    empty = MainWindow()
    placeholder = empty._status_label.text()
    assert placeholder == "暂无数据 — 请点击“索引”"
    assert placeholder != "Нет данных — нажмите «Индексировать»"
    assert empty._panel._browser.toPlainText() == "请点击“索引”"
    empty.close()

    _seed_two_projects_two_errors(cfg_path, idx_path)
    window = MainWindow()
    header = window._model.headerData(0, Qt.Orientation.Horizontal)
    assert header == "名称"
    assert header != "Имя"
    action_text = window._index_action.text()
    assert action_text == "索引"
    assert action_text != "Индексировать"
    assert window._status_label.text() == "2 个项目，扫描 0.04 秒"
    assert window._errors_button.text() == "2 个错误"
    window._panel.show_entry(_mk_entry("gamma", size_bytes=512))
    assert window._panel._size_label.text() == "大小：512 B"
    assert window._panel._copy_button.text() == "复制路径"
    window._model.set_projects([_mk_entry("gamma", file_count=2)])
    tooltip = window._model.data(
        window._model.index(0, 0), Qt.ItemDataRole.ToolTipRole
    )
    assert tooltip == "<span style='white-space:pre'>/scan/root/gamma\n2 个文件</span>"
    window.close()
