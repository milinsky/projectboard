# tests/test_qa_epic.py — QA-тесты этапа приёмки эпика projects-dashboard (2026-11-02)
"""Собственные тесты QA: закрытие пробелов покрытия критериев приёмки брифа п. 8,
не закрытых юнит-тестами задач (GUI-смоуки исполнителей жили в /tmp и удалены).

Конвенции — как в test_detail_panel_security.py: QT_QPA_PLATFORM=offscreen до
импорта PySide6, module-scope QApplication, реальные data/-пути подменяются
monkeypatch'ем на tmp_path (продакшн-код не менялся).

Привязка к критериям брифа п. 8:
- критерий 2: первый запуск без кэша — пустая таблица + подсказка, никакого
  скана и записи на диск при старте;
- критерий 5: выбор строки показывает отрендеренный README; пустой README —
  notice-сообщение вместо HTML, без падения (проводка панель <-> render_readme);
- критерий 6: мгновенный фильтр-подстрока по имени/пути (кейс-инсенсивно),
  опциональный поиск по содержимому README, очистка запроса — модель
  (индекс) при фильтрации не меняется и не переиндексируется;
- критерий 7: сигнал панели open_requested -> MainWindow -> open_in_zcode
  (subprocess замокан), ошибка запуска -> предупреждение, не крах;
- критерий 8: повторный запуск показывает кэшированный индекс сразу, без
  автосканирования и перезаписи кэша; кэш от другого корня — пометка
  в статусбаре (архитектура п. 9);
- архитектура п. 9 «двойное нажатие Индексировать»: второй клик во время
  скана отменяет его, а не запускает второй поток; отменённый скан проходит
  штатный путь сохранения частичного результата;
- границы сканера: пустой корень и корень без единого README -> 0 проектов,
  0 ошибок (не падение).
"""

import json
import os
import threading
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")  # до импорта PySide6

import pytest

from PySide6.QtWidgets import QApplication, QMessageBox

import dashboard.config as config_module
import dashboard.qt.scan_worker as worker_module
import dashboard.storage as storage_module
from dashboard.models import ProjectEntry, ScanResult
from dashboard.qt.main_window import MainWindow
from dashboard.qt.project_model import ProjectFilterProxy, ProjectTableModel
from dashboard.scanner import ScanOptions, scan_root
from dashboard.storage import save_index
from dashboard.zcode_opener import OpenResult


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


def mk_entry(name: str, content: str, error: str | None = None) -> ProjectEntry:
    return ProjectEntry(
        name=name, path=f"/scan/root/{name}", rel_path=name, group=name,
        readme_path=f"/scan/root/{name}/README.md", mtime=1795000000.0,
        dir_size_bytes=10, file_count=1, readme_size_bytes=len(content),
        readme_truncated=False, readme_content=content, readme_error=error,
    )


def forbid_scan_and_writes(monkeypatch):
    """Автоскан и запись при старте запрещены: любая попытка — ошибка теста."""
    def _fail(*args, **kwargs):
        raise AssertionError("при старте приложения недопустимы скан или запись")
    monkeypatch.setattr(worker_module, "scan_root", _fail)
    monkeypatch.setattr(storage_module, "save_index", _fail)


# --- Критерий 2: первый запуск без кэша ---

def test_first_run_without_cache_empty_hint_no_scan_no_writes(qapp, isolated_paths, monkeypatch):
    cfg_path, idx_path = isolated_paths
    forbid_scan_and_writes(monkeypatch)

    window = MainWindow()

    assert window._model.rowCount() == 0                      # список пуст
    assert "Индексировать" in window._status_label.text()     # подсказка нажать кнопку
    assert window._scan_thread is None                        # скан не запускался
    assert not cfg_path.exists() and not idx_path.exists()    # диск не тронут
    window.close()


# --- Критерий 8: повторный запуск показывает кэш сразу, без автоскана ---

def test_restart_shows_cached_index_immediately(qapp, isolated_paths, monkeypatch):
    cfg_path, idx_path = isolated_paths
    cfg_path.write_text(json.dumps({"root": "/scan/root"}), encoding="utf-8")
    save_index(ScanResult(root="/scan/root", duration_ms=42,
                          projects=[mk_entry("alpha", "# A\n"), mk_entry("beta", "# B\n")]),
               idx_path)
    mtime_before = idx_path.stat().st_mtime_ns
    forbid_scan_and_writes(monkeypatch)

    window = MainWindow()

    assert window._model.rowCount() == 2                       # кэш показан сразу
    assert "2 проекта" in window._status_label.text()
    assert idx_path.stat().st_mtime_ns == mtime_before         # кэш не перезаписан
    assert window._scan_thread is None
    window.close()


def test_cached_index_for_other_root_marked_in_status(qapp, isolated_paths, monkeypatch):
    cfg_path, idx_path = isolated_paths
    # конфиг и кэш с разными корнями (архитектура п. 9: пометка, не пересканирование)
    cfg_path.write_text(json.dumps({"root": "/new/root"}), encoding="utf-8")
    save_index(ScanResult(root="/old/root", projects=[mk_entry("alpha", "# A\n")]), idx_path)
    forbid_scan_and_writes(monkeypatch)

    window = MainWindow()

    assert window._model.rowCount() == 1                       # индекс всё равно показан
    assert "другого корня" in window._status_label.text()
    window.close()


# --- Критерий 5: выбор строки -> отрендеренный README / notice для пустого ---

def test_selection_shows_rendered_readme_and_empty_notice(qapp, isolated_paths):
    cfg_path, idx_path = isolated_paths
    cfg_path.write_text(json.dumps({"root": "/scan/root"}), encoding="utf-8")
    save_index(ScanResult(root="/scan/root", duration_ms=1, projects=[
        mk_entry("alpha", "# Alpha Title\n\nтекст README\n"),
        mk_entry("beta", ""),                                   # пустой README (реальный случай)
    ]), idx_path)

    window = MainWindow()
    window._table.selectRow(0)                                  # выбор в таблице -> панель

    assert window._panel._name_label.text() == "alpha"
    assert "Alpha Title" in window._panel._browser.toPlainText()  # markdown отрендерен

    window._table.selectRow(1)
    assert window._panel._name_label.text() == "beta"
    assert window._panel._browser.toPlainText() == "README пуст"   # notice, не HTML и не крах
    window.close()


# --- Критерий 6: мгновенный фильтр по имени/пути/README без переиндексации ---

def _proxy_with(entries):
    model = ProjectTableModel()
    model.set_projects(entries)
    proxy = ProjectFilterProxy()
    proxy.setSourceModel(model)
    return model, proxy


def test_filter_substring_name_relpath_case_insensitive(qapp):
    model, proxy = _proxy_with([
        mk_entry("alpha", "# a\n"),
        mk_entry("Beta", "# b\n"),
        ProjectEntry(name="gamma", path="/x/gamma", rel_path="sub/dir/gamma", group="sub",
                     readme_content="# g\n"),
    ])

    assert proxy.rowCount() == 3                       # без запроса — все
    proxy.setFilterFixedString("ALPH")                 # кейс-инсенсивно по имени
    assert proxy.rowCount() == 1
    proxy.setFilterFixedString("sub/dir")              # по относительному пути
    assert proxy.rowCount() == 1
    proxy.setFilterFixedString("zzz-nothing")
    assert proxy.rowCount() == 0
    proxy.setFilterFixedString("")                     # очистка запроса возвращает всё
    assert proxy.rowCount() == 3
    assert model.rowCount() == 3                       # индекс/модель не переиндексировались


def test_filter_readme_search_only_when_enabled(qapp):
    model, proxy = _proxy_with([mk_entry("plain", "текст с unicorn-secret внутри\n")])

    proxy.setFilterFixedString("unicorn-secret")
    assert proxy.rowCount() == 0                       # по README по умолчанию НЕ ищем

    proxy.set_search_in_readme(True)
    assert proxy.rowCount() == 1                       # чекбокс включил поиск по содержимому

    proxy.set_search_in_readme(False)
    assert proxy.rowCount() == 0                       # выключил — снова отфильтровано


# --- Критерий 7: проводка open_requested -> MainWindow -> open_in_zcode ---

def test_panel_open_requested_routes_to_opener(qapp, isolated_paths, monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr("dashboard.qt.main_window.open_in_zcode",
                        lambda p: (calls.append(p), OpenResult(True, None))[1])
    window = MainWindow()

    window._panel.open_requested.emit("/tmp/project with spaces")

    assert calls == ["/tmp/project with spaces"]       # путь передан дословно, одним аргументом
    window.close()


def test_double_click_row_opens_in_zcode(qapp, isolated_paths, monkeypatch):
    """Компаньон BUG-001: двойной клик по строке ПОДКЛЮЧЁН (в отличие от кнопки
    панели) — границы дефекта точны: не подключён только сигнал open_requested."""
    cfg_path, idx_path = isolated_paths
    cfg_path.write_text(json.dumps({"root": "/scan/root"}), encoding="utf-8")
    save_index(ScanResult(root="/scan/root", projects=[mk_entry("alpha", "# A\n")]), idx_path)
    calls: list[str] = []
    monkeypatch.setattr("dashboard.qt.main_window.open_in_zcode",
                        lambda p: (calls.append(p), OpenResult(True, None))[1])
    window = MainWindow()

    window._table.doubleClicked.emit(window._proxy.index(0, 0))

    assert calls == ["/scan/root/alpha"]
    window.close()


def test_open_failure_shows_warning_not_crash(qapp, isolated_paths, monkeypatch):
    """Ошибка запуска (ok=False) -> QMessageBox.warning, не крах. Вызывается
    обработчик MainWindow напрямую: проводка панели — отдельный тест (BUG-001)."""
    shown: list[tuple] = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kwargs: shown.append(args))
    monkeypatch.setattr("dashboard.qt.main_window.open_in_zcode",
                        lambda p: OpenResult(False, "нет приложения"))
    window = MainWindow()

    window._open_in_zcode("/scan/root/alpha")

    assert len(shown) == 1 and "нет приложения" in shown[0][2]   # деградация с сообщением
    window.close()


# --- Архитектура п. 9: двойное нажатие «Индексировать» = отмена, не второй поток ---

def test_second_index_click_cancels_scan_and_saves_partial(qapp, tmp_path, isolated_paths, monkeypatch):
    cfg_path, idx_path = isolated_paths
    # Корень — РЕАЛЬНЫЙ каталог: несуществующий корень легитимно даёт модальный
    # QMessageBox.warning, который в offscreen блокирует exec() (проверено
    # отдельным наблюдением QA; это корректное поведение продакшна, не баг).
    live_root = str(tmp_path)
    cfg_path.write_text(json.dumps({"root": live_root}), encoding="utf-8")
    save_index(ScanResult(root=live_root, projects=[mk_entry("old", "# old\n")]), idx_path)
    calls: list[str] = []
    dialogs: list[tuple] = []
    # Страховка теста от любых модальных диалогов (оффскрин- exec() не закрыть).
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: dialogs.append(a))
    monkeypatch.setattr(QMessageBox, "critical", lambda *a, **k: dialogs.append(a))

    def slow_scan(options, cancel=None, progress=None):
        calls.append(str(options.root))
        while cancel is None or not cancel.is_set():   # «долгий» скан, отзывчивый к отмене
            time.sleep(0.005)
        return ScanResult(root=str(options.root), projects=[], errors=[],
                          duration_ms=1, cancelled=True)

    monkeypatch.setattr(worker_module, "scan_root", slow_scan)
    window = MainWindow()
    assert window._model.rowCount() == 1               # старт: показан кэш

    window._on_index_clicked()                          # первый клик: запуск
    assert window._scan_thread is not None
    assert window._index_action.text() == "Отмена"
    window._on_index_clicked()                          # второй клик: отмена, НЕ второй поток

    deadline = time.time() + 5
    while window._scan_thread is not None and time.time() < deadline:
        qapp.processEvents()
        time.sleep(0.005)

    assert dialogs == []                                # ни предупреждений, ни ошибок
    assert calls == [live_root]                         # scan_root вызван ровно один раз
    assert window._scan_thread is None                  # lifecycle завершён
    assert window._index_action.text() == "Индексировать"
    # отменённый скан проходит штатный путь: частичный результат сохранён (задача 10)
    assert idx_path.exists()
    assert storage_module.load_index(idx_path).projects == []
    window.close()


# --- Границы сканера: пустой вход ---

def test_scan_empty_root_returns_zero_projects_zero_errors(tmp_path):
    result = scan_root(ScanOptions(root=tmp_path))     # пустой корень

    assert result.projects == []
    assert result.errors == []
    assert result.cancelled is False


def test_scan_root_without_any_readme_returns_nothing(tmp_path):
    (tmp_path / "notproj").mkdir(parents=True)          # каталог без README
    (tmp_path / "nested" / "deep").mkdir(parents=True)
    (tmp_path / "plain.md").write_text("# отдельный файл .md — не проект\n", encoding="utf-8")
    (tmp_path / "archive.zip").write_bytes(b"PK\x03\x04")

    result = scan_root(ScanOptions(root=tmp_path))

    assert result.projects == []                        # ни одного проекта
    assert result.errors == []                          # и ни одной ошибки
