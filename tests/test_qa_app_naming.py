# tests/test_qa_app_naming.py — QA-тесты этапа приёмки эпика app-naming (2026-11-02)
"""Собственные тесты QA: закрытие пробелов покрытия критериев приёмки брифа
app-naming, не закрытых постоянными тестами задач (offscreen-смоук задачи 03
жил в /tmp и удалён; README-контракты проверялись только grep-гейтами ревью).

Конвенции — как в test_qa_epic.py: QT_QPA_PLATFORM=offscreen до импорта
PySide6, module-scope QApplication, реальные data/-пути подменяются
monkeypatch'ем на tmp_path (продакшн-код не менялся), записи только в
tmp_path, реальный /Users/milinsky/Projects не трогается.

Привязка к критериям брифа app-naming (п. 8 «Критерии успеха»):
- критерий 6: заголовок главного окна — «Projectboard» (не «Проекты»);
  окно «Ошибки скана» и прочие UI-тексты этим тестом не создаются;
- критерий 8: README описывает оба способа запуска (dev: .venv/bin/python
  main.py; повседневный: Projectboard.app из /Applications), сборку
  ./scripts/build_app.sh без аргументов, первый запуск неподписанного
  (правый клик → «Открыть»), обновление (git pull → скрипт сборки) и
  лечение переноса папки проекта; упоминаемый скрипт существует и
  исполняем; устаревшего имени «Projects Dashboard» нет.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")  # до импорта PySide6

from pathlib import Path

import pytest

from PySide6.QtWidgets import QApplication

import dashboard.config as config_module
import dashboard.qt.scan_worker as worker_module
import dashboard.storage as storage_module
from dashboard.qt.main_window import MainWindow

PROJECT_ROOT = Path(__file__).resolve().parent.parent


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
    """Автоскан и запись при старте запрещены: старт окна — только чтение конфига."""
    def _fail(*args, **kwargs):
        raise AssertionError("при старте приложения недопустимы скан или запись")
    monkeypatch.setattr(worker_module, "scan_root", _fail)
    monkeypatch.setattr(storage_module, "save_index", _fail)


def test_main_window_title_is_projectboard(qapp, isolated_paths, monkeypatch):
    """Критерий 6: заголовок главного окна — «Projectboard» (бриф п. 8)."""
    forbid_scan_and_writes(monkeypatch)

    window = MainWindow()

    assert window.windowTitle() == "Projectboard"
    window.close()


def test_readme_documents_launch_build_first_run_and_update():
    """Критерий 8: README — оба способа запуска, сборка, первый запуск,
    обновление и лечение переноса; упомянутый скрипт существует и исполняем."""
    text = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")

    # Имя продукта единообразно (бриф п. 6): H1 — Projectboard, старого имени нет.
    assert text.startswith("# Projectboard")
    assert "Projects Dashboard" not in text

    # Два способа запуска: разработка (дословная команда проекта) и приложение.
    assert ".venv/bin/python main.py" in text
    assert "Projectboard.app" in text
    assert "/Applications" in text

    # Сборка/установка: единственная команда из корня, без аргументов.
    assert "./scripts/build_app.sh" in text
    build_script = PROJECT_ROOT / "scripts" / "build_app.sh"
    assert build_script.is_file()
    assert os.access(build_script, os.X_OK)

    # Первый запуск неподписанного: правый клик → «Открыть».
    assert "Открыть" in text

    # Обновление: git pull → пересборка скриптом; лечение переноса папки.
    assert "git pull" in text
    assert "scripts/build_app.sh" in text
