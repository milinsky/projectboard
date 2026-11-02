# dashboard/storage.py — только stdlib + dashboard.models
"""Хранилище индекса: атомарная запись и отказоустойчивое чтение кэша data/index.json.

Схема JSON-конверта — п. 4.3 архитектуры (schema_version: 1), владелец схемы
полей проектов — models.py (to_dict/from_dict). Контракт п. 8:
load_index(path) -> ScanResult | None — None = нет файла / битый / чужая схема;
причины не дифференцируются наружу (декомпозиция, уточнение №3), только
logging.warning внутри. save_index(result, path) -> None — атомарно.
"""

import json
import logging
import os
import tempfile
import time
from datetime import datetime
from pathlib import Path

from dashboard.models import ScanResult

SCHEMA_VERSION = 1


def save_index(result: ScanResult, path: Path) -> None:
    """Атомарно записывает индекс в path по схеме п. 4.3 (temp-файл + os.replace)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "created_at": datetime.now().astimezone().isoformat(),
        "root": result.root,
        "scan_duration_ms": result.duration_ms,
        "project_count": len(result.projects),
        "projects": [p.to_dict() for p in result.projects],
        "errors": [e.to_dict() for e in result.errors],
    }
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=".index-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(tmp_name, path)
    except (OSError, ValueError):
        # Не оставляем temp-файл при сбое записи/замены (OSError) и при ошибке
        # кодирования JSON (ValueError, например UnicodeEncodeError с
        # ensure_ascii=False для суррогатных путей — Code-ревью MINOR):
        # исключение поднимается вызывающему, temp-файл удаляется.
        Path(tmp_name).unlink(missing_ok=True)
        raise


def _rename_corrupt(path: Path) -> None:
    """Best-effort переименование битого файла в <stem>.corrupt-<unix-ts>.json.

    Неудача самого переименования не поднимается: логируется warning.
    """
    corrupt = path.with_name(f"{path.stem}.corrupt-{int(time.time())}.json")
    try:
        path.replace(corrupt)
    except OSError as exc:
        logging.warning("Не удалось переименовать битый индекс %s в %s: %s", path, corrupt, exc)


def load_index(path: Path) -> ScanResult | None:
    """Читает кэш индекса; None без дифференциации причин наружу.

    нет файла -> None; битый JSON / OSError чтения / не-словарь -> переименовать
    в index.corrupt-<unix-ts>.json (best-effort) и None; schema_version !=
    SCHEMA_VERSION -> None без переименования; иначе сборка ScanResult через
    from_dict моделей.
    """
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return None
    except OSError as exc:
        logging.warning("Индекс %s не читается: %s", path, exc)
        _rename_corrupt(path)
        return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        logging.warning("Индекс %s — битый JSON, переименован: %s", path, exc)
        _rename_corrupt(path)
        return None
    if not isinstance(payload, dict):
        logging.warning(
            "Индекс %s — не словарь (%s), переименован", path, type(payload).__name__
        )
        _rename_corrupt(path)
        return None
    if payload.get("schema_version") != SCHEMA_VERSION:
        logging.warning(
            "Индекс %s: schema_version=%r не поддерживается (ожидалась %d), кэш игнорируется",
            path,
            payload.get("schema_version"),
            SCHEMA_VERSION,
        )
        return None
    # Защитительная сборка: from_dict моделей игнорирует неизвестные ключи и
    # не-словарные элементы списков; отсутствующие поля -> дефолты dataclass.
    projects = payload.get("projects")
    errors = payload.get("errors")
    return ScanResult.from_dict(
        {
            "root": payload.get("root", ""),
            "duration_ms": payload.get("scan_duration_ms", 0),
            "projects": projects if isinstance(projects, list) else [],
            "errors": errors if isinstance(errors, list) else [],
            "cancelled": False,  # cancelled в схеме п. 4.3 не хранится
        }
    )
