# tests/test_scan_failure_codes.py — коды ошибок не-Qt модулей на границе Qt (эпик i18n, задача 04)
"""Тесты задачи 04: ScanWorker.failed — пара (code, detail) со строковым
контрактом "root_missing" | "root_not_dir" | "oserror", а MainWindow переводит
коды в tr-шаблоны (_on_scan_failed) и OpenResult.error_code
("not_absolute" | "dir_not_found" | "timeout" | "open_missing" | "open_failed")
в _open_in_zcode. Недоверенный detail/path — только %1-подстановка.

Трансляторы НЕ устанавливаются (en/zh — задача 06): tr возвращает русский
source. Канон test_qa_epic.py: QT_QPA_PLATFORM=offscreen до импорта PySide6,
module-scope QApplication, пути в tmp_path, модальные QMessageBox
monkeypatch'ятся (offscreen: неперехваченный exec() блокирует pytest).
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")  # до импорта PySide6

from pathlib import Path

import pytest

from PySide6.QtWidgets import QApplication, QMessageBox

import dashboard.config as config_module
import dashboard.qt.scan_worker as worker_module
import dashboard.storage as storage_module
from dashboard.qt.main_window import MainWindow
from dashboard.qt.scan_worker import ScanWorker
from dashboard.scanner import ScanOptions
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


def _forbid_startup_side_effects(monkeypatch):
    """Автоскан и запись при старте запрещены: любая попытка — ошибка теста."""
    def _fail(*args, **kwargs):
        raise AssertionError("при старте приложения недопустимы скан или запись")
    monkeypatch.setattr(worker_module, "scan_root", _fail)
    monkeypatch.setattr(storage_module, "save_index", _fail)


# --- (а) воркер: FileNotFoundError/NotADirectoryError/OSError -> (code, detail) ---

@pytest.mark.parametrize("exc, expected_code, expected_detail", [
    (FileNotFoundError(), "root_missing", "/scan/root"),
    (NotADirectoryError(), "root_not_dir", "/scan/root"),
    (OSError("disk boom"), "oserror", "disk boom"),
])
def test_worker_emits_code_and_detail_pair(qapp, monkeypatch, exc,
                                           expected_code, expected_detail):
    """Прямой вызов start() без потока; monkeypatch scan_root в модуле
    dashboard.qt.scan_worker (канон test_qa_epic), рекордер сигнала ловит
    пару (code, detail). Анти-тест: откат failed к Signal(str) роняет тест
    (emit с двумя аргументами — TypeError по арности)."""
    def _raise(options, cancel=None, progress=None):
        raise exc
    monkeypatch.setattr(worker_module, "scan_root", _raise)
    worker = ScanWorker(ScanOptions(root=Path("/scan/root")))
    received: list[tuple[str, str]] = []
    worker.failed.connect(lambda code, detail: received.append((code, detail)))

    worker.start()  # прямой вызов без QThread: исключение перехвачено в start()

    assert received == [(expected_code, expected_detail)]


# --- (б) _on_scan_failed: код -> tr-шаблон, недоверенный detail — %1-подстановка ---

def test_on_scan_failed_root_missing_shows_template(qapp, isolated_paths, monkeypatch):
    _forbid_startup_side_effects(monkeypatch)
    shown: list[tuple] = []
    monkeypatch.setattr(QMessageBox, "critical", lambda *a, **k: shown.append(a))
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: shown.append(a))
    window = MainWindow()

    window._on_scan_failed("root_missing", "/x")

    assert len(shown) == 1
    assert shown[0][1] == "Ошибка индексации"
    assert shown[0][2] == "Корень сканирования не существует:\n/x"  # detail через %1
    window.close()


def test_on_scan_failed_oserror_shows_detail_verbatim(qapp, isolated_paths, monkeypatch):
    """oserror-detail — техническая строка: показывается как есть, без tr-шаблона."""
    _forbid_startup_side_effects(monkeypatch)
    shown: list[tuple] = []
    monkeypatch.setattr(QMessageBox, "critical", lambda *a, **k: shown.append(a))
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: shown.append(a))
    window = MainWindow()

    window._on_scan_failed("oserror", "errno 36: имя слишком длинное")

    assert len(shown) == 1
    assert shown[0][1] == "Ошибка индексации"
    assert shown[0][2] == "errno 36: имя слишком длинное"  # дословно, без склейки с шаблоном
    window.close()


# --- (г) _open_in_zcode: error_code -> tr-шаблон; без кода — message как есть ---

def test_open_in_zcode_not_absolute_shows_template(qapp, isolated_paths, monkeypatch):
    """error_code="not_absolute" -> переведённый шаблон с %1-подстановкой path."""
    _forbid_startup_side_effects(monkeypatch)
    shown: list[tuple] = []
    monkeypatch.setattr(QMessageBox, "critical", lambda *a, **k: shown.append(a))
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: shown.append(a))
    monkeypatch.setattr("dashboard.qt.main_window.open_in_zcode",
                        lambda p: OpenResult(False, "x", "not_absolute"))
    window = MainWindow()

    window._open_in_zcode("x")

    assert len(shown) == 1
    assert shown[0][1] == "Открыть в ZCode"
    assert "Ожидается абсолютный путь" in shown[0][2]
    window.close()
