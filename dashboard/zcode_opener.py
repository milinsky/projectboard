# dashboard/zcode_opener.py — stdlib only, без Qt
"""Запуск ZCode.app: open_in_zcode(path) через `open -a ZCode <path>` + zcode_app_exists().

Команда фиксирована и передаётся списком аргументов без shell-интерпретатора
(инъекция через имена каталогов невозможна, архитектура п. 10); любые неудачи
(отказ/timeout/ненулевой код open) возвращаются как OpenResult(ok=False), не
исключения — решение о показе сообщения принимает MainWindow (единственный
вызывающий, задача 10).
"""
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class OpenResult:
    ok: bool
    error_message: str | None


def zcode_app_exists() -> bool:
    return Path("/Applications/ZCode.app").exists()


def open_in_zcode(project_path: str) -> OpenResult:
    p = Path(project_path)
    if not p.is_absolute():
        # Security: относительный путь (и argv-инъекция вида "-a ...") — отказ
        # до запуска open; резолвить относительно cwd недоверенной строке нельзя.
        return OpenResult(False, f"ожидается абсолютный путь: {project_path}")
    if not p.is_dir():
        return OpenResult(False, f"каталог не найден: {project_path}")
    try:
        proc = subprocess.run(["open", "-a", "ZCode", project_path],
                              capture_output=True, text=True, timeout=10)
    except subprocess.TimeoutExpired:
        return OpenResult(False, "превышено время ожидания (10 с)")
    except FileNotFoundError:
        return OpenResult(False, "утилита open не найдена")
    if proc.returncode != 0:
        msg = (proc.stderr or proc.stdout or f"open вернул код {proc.returncode}").strip()
        return OpenResult(False, msg)
    return OpenResult(True, None)
