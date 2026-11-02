# dashboard/zcode_opener.py — stdlib only, без Qt
"""Запуск ZCode.app: open_in_zcode(path) через URL-схему `zcode://workspace/open`
+ zcode_app_exists().

Механизм (доработка 2026-11-02): `open -a ZCode <path>` ZCode игнорирует
(Electron-приложение не обрабатывает файловые аргументы — кнопка «ничего не
делала»). Рабочий формат найден в app.asar самого ZCode и подтверждён
пользователем визуально: `zcode://workspace/open?path=${encodeURIComponent(path)}`.
Команда фиксирована и передаётся списком аргументов без shell-интерпретатора
(инъекция невозможна, архитектура п. 10); любые неудачи (отказ/timeout/ненулевой
код open) возвращаются как OpenResult(ok=False), не исключения — решение о
показе сообщения принимает MainWindow (единственный вызывающий, задача 10).
"""
import subprocess
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote


@dataclass
class OpenResult:
    ok: bool
    error_message: str | None
    error_code: str | None = None


def zcode_app_exists() -> bool:
    return Path("/Applications/ZCode.app").exists()


def open_in_zcode(project_path: str) -> OpenResult:
    p = Path(project_path)
    if not p.is_absolute():
        # Security: относительный путь (и argv-инъекция вида "-a ...") — отказ
        # до запуска open; резолвить относительно cwd недоверенной строке нельзя.
        return OpenResult(False, f"ожидается абсолютный путь: {project_path}",
                          error_code="not_absolute")
    if not p.is_dir():
        return OpenResult(False, f"каталог не найден: {project_path}",
                          error_code="dir_not_found")
    # encodeURIComponent-эквивалент: кодируем всё, включая "/" (проверено:
    # zcode://workspace/open?path=%2FUsers%2F... открывает проект)
    url = f"zcode://workspace/open?path={quote(project_path, safe='')}"
    try:
        proc = subprocess.run(["open", url],
                              capture_output=True, text=True, timeout=10)
    except subprocess.TimeoutExpired:
        return OpenResult(False, "превышено время ожидания (10 с)", error_code="timeout")
    except FileNotFoundError:
        return OpenResult(False, "утилита open не найдена", error_code="open_missing")
    if proc.returncode != 0:
        msg = (proc.stderr or proc.stdout or f"open вернул код {proc.returncode}").strip()
        return OpenResult(False, msg, error_code="open_failed")
    return OpenResult(True, None)
