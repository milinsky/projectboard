# dashboard/scanner.py — только stdlib + dashboard.models; без Qt
"""Сканер файловой системы: итеративный DFS с правилом «верхний README побеждает».

Проект = каталог, напрямую содержащий README.md (реальный файл, не symlink).
Внутрь найденного проекта сканер не спускается; скрытые каталоги (имя начинается
с «.») и служебные (DEFAULT_IGNORE_NAMES) не обходятся вовсе. Модуль headless
(только stdlib, без Qt): прогресс — обычная функция-колбэк с троттлингом ~50 мс
по time.monotonic() плюс обязательный финальный вызов (архитектура п. 4.2, п. 11).
"""

import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from dashboard.models import ProjectEntry, ScanError, ScanResult

# Точный состав по архитектуре п. 4.2 (уточнение №2 декомпозиции); расширение
# состава — только через extra_ignore_names конфига на стороне задачи 10.
DEFAULT_IGNORE_NAMES = frozenset({"node_modules", "vendor", "dist", "build", "target",
                                  "__pycache__", "venv", "site-packages"})

_PROGRESS_MIN_INTERVAL_SEC = 0.05  # троттлинг колбэка прогресса, ~50 мс (архитектура п. 11)


@dataclass(frozen=True)
class ScanOptions:
    root: Path
    ignore_names: frozenset[str] = DEFAULT_IGNORE_NAMES
    max_depth: int = 8
    max_readme_store_bytes: int = 512 * 1024


def scan_root(
    options: ScanOptions,
    cancel: threading.Event | None = None,
    progress: "Callable[[int, int], None] | None" = None,   # (visited_dirs, found_projects)
) -> ScanResult:
    """Обходит options.root и возвращает ScanResult.

    Единственные исключения наружу: root не существует (FileNotFoundError) или
    не каталог (NotADirectoryError). Все остальные ошибки ФС собираются в
    ScanResult.errors и скан не прерывают (архитектура п. 4.2 п. 7).
    """
    root = options.root
    if not root.exists():
        raise FileNotFoundError(f"корень сканирования не существует: {root}")
    if not root.is_dir():
        raise NotADirectoryError(f"корень сканирования не каталог: {root}")

    started = time.monotonic()
    stack: list[tuple[Path, int]] = [(root, 0)]  # (каталог, глубина); root — глубина 0
    projects: list[ProjectEntry] = []
    errors: list[ScanError] = []
    visited = 0
    cancelled = False
    last_progress_at = started

    while stack:
        # Кооперативная отмена: проверка перед каждой итерацией цикла.
        if cancel is not None and cancel.is_set():
            cancelled = True
            break
        dir_path, depth = stack.pop()
        visited += 1
        try:
            with os.scandir(dir_path) as it:
                entries = sorted(it, key=lambda e: e.name)  # детерминированный порядок
        except OSError as exc:  # включает PermissionError
            errors.append(ScanError(path=str(dir_path), reason=_error_reason(exc)))
            continue

        readme_entry = _find_readme_entry(entries)
        if readme_entry is not None and depth > 0:
            # Проект найден: внутрь НЕ спускаемся («верхний README побеждает»).
            # Сам root (depth == 0) проектом не считается даже при наличии README.md.
            projects.append(_make_project(dir_path, root, readme_entry, options, cancel))
        elif depth < options.max_depth:
            # Спуск: только реальные подкаталоги, без скрытых и служебных.
            # depth + 1 <= max_depth — guard от глубоких деревьев и symlink-циклов.
            for entry in entries:
                if entry.name.startswith(".") or entry.name in options.ignore_names:
                    continue
                child = dir_path / entry.name
                try:
                    is_dir = entry.is_dir(follow_symlinks=False)
                except OSError as exc:
                    errors.append(ScanError(path=str(child), reason=_error_reason(exc)))
                    continue
                if is_dir:  # symlink-каталоги (is_dir с follow_symlinks=False) не travers'им
                    stack.append((child, depth + 1))

        now = time.monotonic()
        if progress is not None and now - last_progress_at >= _PROGRESS_MIN_INTERVAL_SEC:
            progress(visited, len(projects))
            last_progress_at = now

    # Отмена могла сработать ВНУТРИ _make_project/_measure_tree при обработке
    # последнего элемента стека: верхнеспусковая проверка её уже не увидит
    # (Code-ревью MAJOR — замер прерывается, результат обязан быть cancelled=True).
    if cancel is not None and cancel.is_set():
        cancelled = True

    if progress is not None:  # обязательный финальный вызов, в том числе после отмены
        progress(visited, len(projects))

    projects.sort(key=lambda p: (p.group, p.name))
    duration_ms = int(round((time.monotonic() - started) * 1000))
    return ScanResult(
        root=str(root),
        projects=projects,
        errors=errors,
        duration_ms=duration_ms,
        cancelled=cancelled,
    )


def _error_reason(exc: OSError) -> str:
    """Человекочитаемая причина без traceback (ScanError.reason / readme_error)."""
    text = str(exc).strip()
    return f"{type(exc).__name__}: {text}" if text else type(exc).__name__


def _find_readme_entry(entries: list[os.DirEntry[str]]) -> os.DirEntry[str] | None:
    """README-детект (архитектура п. 4.2 шаг 3): точное имя README.md; при
    отсутствии — первое имя с name.lower() == "readme.md" в сортировке.
    Symlink-кандидат проектом не считается (иначе symlink на чужой README
    создал бы фантомный проект)."""
    candidate: os.DirEntry[str] | None = None
    for entry in entries:
        if entry.name == "README.md":
            candidate = entry
            break
    if candidate is None:
        for entry in entries:
            if entry.name.lower() == "readme.md":
                candidate = entry
                break
    if candidate is None:
        return None
    try:
        if candidate.is_symlink():
            return None
    except OSError:
        # Не удалось убедиться, что это реальный файл, — неподтверждённый
        # кандидат проектом не считается (тот же принцип, что и для symlink).
        return None
    return candidate


def _make_project(dir_path: Path, root: Path, readme_entry: os.DirEntry[str],
                  options: ScanOptions, cancel: threading.Event | None = None) -> ProjectEntry:
    """Собирает ProjectEntry для каталога-проекта (внутрь не спускается только
    обход; размер поддерева здесь считается рекурсивно — архитектура п. 4.2)."""
    rel_path = dir_path.relative_to(root).as_posix()
    readme_path = os.path.join(dir_path, readme_entry.name)
    mtime = 0.0
    readme_size = 0
    readme_error: str | None = None
    try:
        st = readme_entry.stat(follow_symlinks=False)  # mtime проекта = mtime README (п. 8)
        mtime = st.st_mtime
        readme_size = st.st_size
    except OSError as exc:
        readme_error = _error_reason(exc)
    content, truncated, read_error = _read_readme(readme_path, options.max_readme_store_bytes)
    if readme_error is None and read_error is not None:
        readme_error = read_error
    dir_size, file_count = _measure_tree(dir_path, cancel)
    return ProjectEntry(
        name=dir_path.name,
        path=str(dir_path),
        rel_path=rel_path,
        group=rel_path.split("/")[0],  # первый сегмент; для проекта в корне — имя проекта
        readme_path=readme_path,
        mtime=mtime,
        dir_size_bytes=dir_size,
        file_count=file_count,
        readme_size_bytes=readme_size,
        readme_truncated=truncated,
        readme_content=content,
        readme_error=readme_error,
    )


def _read_readme(readme_path: str, limit: int) -> tuple[str, bool, str | None]:
    """Читает README байтово: не более limit + 1 байт (детект превышения без
    чтения гигантских файлов целиком). Возвращает (content, truncated, error);
    декодирование utf-8/errors="replace" переживает не-UTF8 и разрыв
    мультибайтовой последовательности на срезе."""
    try:
        with open(readme_path, "rb") as fh:
            data = fh.read(limit + 1)
    except OSError as exc:
        return "", False, _error_reason(exc)
    if len(data) > limit:
        return data[:limit].decode("utf-8", errors="replace"), True, None
    return data.decode("utf-8", errors="replace"), False, None


def _measure_tree(dir_path: Path, cancel: threading.Event | None = None) -> tuple[int, int]:
    """Рекурсивный (dir_size_bytes, file_count) через os.walk(followlinks=False).

    Ошибки подкаталогов пропускаются (onerror по умолчанию), весь вызов обёрнут
    в try/except OSError; symlink-деревья не обходятся и не считаются. cancel
    проверяется на каждом каталоге и файле: при отмене возвращается частичный
    результат — размер/счётчик остаются корректными для посчитанной части, а
    скан в целом пометит результат cancelled=True (Code-ревью MAJOR: без этого
    os.walk по дереву в ~143k файлов не прерывался и держал closeEvent)."""
    total_size = 0
    total_files = 0
    try:
        for dirpath, _dirnames, filenames in os.walk(dir_path, followlinks=False):
            if cancel is not None and cancel.is_set():
                break
            for fname in filenames:
                if cancel is not None and cancel.is_set():
                    break
                try:
                    st = os.stat(os.path.join(dirpath, fname), follow_symlinks=False)
                except OSError:
                    continue  # нечитаемый файл — пропускаем, остальное дерево считается
                total_size += st.st_size
                total_files += 1
    except OSError:
        # Неожиданный сбой самого walk — оставляем накопленное, скан не роняем.
        pass
    return total_size, total_files
