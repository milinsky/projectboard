# tests/test_storage.py — roundtrip / битый файл / чужая схема / атомарность dashboard/storage.py
import json
import logging
import os
from datetime import datetime
from pathlib import Path

import pytest

from dashboard.models import ProjectEntry, ScanError, ScanResult
from dashboard.storage import SCHEMA_VERSION, load_index, save_index

STORAGE_SOURCE = Path(__file__).resolve().parent.parent / "dashboard" / "storage.py"


def make_full_entry(**overrides) -> ProjectEntry:
    values = dict(
        name="http-server",
        path="/Users/milinsky/Projects/Duyler/Duyler/packages/http-server",
        rel_path="Duyler/Duyler/packages/http-server",
        group="Duyler",
        readme_path="/Users/milinsky/Projects/Duyler/Duyler/packages/http-server/README.md",
        mtime=1795000000.123,
        dir_size_bytes=1_234_567,
        file_count=42,
        readme_size_bytes=2048,
        readme_truncated=True,
        readme_content="# README\n\nтестовое содержимое",
        readme_error=None,
    )
    values.update(overrides)
    return ProjectEntry(**values)


def make_result(**overrides) -> ScanResult:
    values = dict(
        root="/Users/milinsky/Projects",
        projects=[
            make_full_entry(),  # readme_error=None
            make_full_entry(
                name="rload",
                path="/Users/milinsky/Projects/rload",
                rel_path="rload",
                group="rload",
                readme_path="/Users/milinsky/Projects/rload/README.md",
                readme_error="permission denied",
                readme_content="",
                readme_truncated=False,
            ),
        ],
        errors=[ScanError(path="/Users/milinsky/Projects/locked", reason="PermissionError: доступ запрещён")],
        duration_ms=152,
        cancelled=False,
    )
    values.update(overrides)
    return ScanResult(**values)


def write_envelope(path: Path, **overrides) -> dict:
    envelope = {
        "schema_version": SCHEMA_VERSION,
        "created_at": "2026-11-02T10:15:00+03:00",
        "root": "/Users/milinsky/Projects",
        "scan_duration_ms": 152,
        "project_count": 1,
        "projects": [make_full_entry().to_dict()],
        "errors": [],
    }
    envelope.update(overrides)
    path.write_text(json.dumps(envelope, ensure_ascii=False, indent=2), encoding="utf-8")
    return envelope


# --- Полный roundtrip: ScanResult -> save_index -> load_index -> ScanResult ---

def test_roundtrip_full_without_loss(tmp_path):
    path = tmp_path / "index.json"
    result = make_result()
    save_index(result, path)
    loaded = load_index(path)
    # Полное равенство объектов: падает, если конверт теряет любое поле
    # ProjectEntry / ScanError / root / duration_ms.
    assert loaded == result
    assert loaded.duration_ms == 152  # из scan_duration_ms конверта
    assert isinstance(loaded.projects[0].mtime, float)
    assert loaded.projects[0].mtime == 1795000000.123
    assert loaded.projects[0].readme_error is None
    assert loaded.projects[1].readme_error == "permission denied"
    assert loaded.errors == [ScanError(path="/Users/milinsky/Projects/locked", reason="PermissionError: доступ запрещён")]


def test_roundtrip_empty_lists(tmp_path):
    path = tmp_path / "index.json"
    result = ScanResult(root="/r", duration_ms=5)
    save_index(result, path)
    assert load_index(path) == result


# --- Документированное поведение cancelled: не сериализуется, при загрузке False ---

def test_cancelled_not_serialized_and_restored_as_false(tmp_path):
    path = tmp_path / "index.json"
    save_index(make_result(cancelled=True), path)
    # cancelled НЕ добавлен в JSON-схему (п. 4.3) — это документированное поведение
    assert "cancelled" not in json.loads(path.read_text(encoding="utf-8"))
    assert load_index(path).cancelled is False


# --- Схема конверта: состав ключей, производные метаданные, формат записи ---

def test_envelope_matches_schema_and_keeps_all_entry_fields(tmp_path):
    path = tmp_path / "index.json"
    save_index(make_result(), path)
    text = path.read_text(encoding="utf-8")
    envelope = json.loads(text)
    assert set(envelope) == {
        "schema_version", "created_at", "root", "scan_duration_ms",
        "project_count", "projects", "errors",
    }
    assert envelope["schema_version"] == 1
    assert envelope["scan_duration_ms"] == 152
    assert envelope["project_count"] == 2
    assert envelope["root"] == "/Users/milinsky/Projects"
    # created_at — ISO 8601 с таймзоной
    assert datetime.fromisoformat(envelope["created_at"]).tzinfo is not None
    # все 12 полей ProjectEntry дошли до JSON (анти-тест на потерю поля)
    assert set(envelope["projects"][0]) == set(make_full_entry().to_dict())
    assert set(envelope["errors"][0]) == {"path", "reason"}
    # ensure_ascii=False и indent=2 — по сырому тексту файла
    assert "тестовое содержимое" in text
    assert text.startswith('{\n  "schema_version": 1,')


# --- Битый / не-словарь / чужая схема / отсутствующий файл ---

def test_corrupt_json_renamed_with_warning(tmp_path, caplog):
    path = tmp_path / "index.json"
    raw = '{"schema_version": 1, "projects": ['
    path.write_text(raw, encoding="utf-8")
    with caplog.at_level(logging.WARNING):
        assert load_index(path) is None
    assert not path.exists()
    corrupted = list(tmp_path.glob("index.corrupt-*.json"))
    assert len(corrupted) == 1
    assert corrupted[0].read_text(encoding="utf-8") == raw  # содержимое сохранено
    assert any(r.levelno == logging.WARNING for r in caplog.records)


def test_non_dict_json_renamed(tmp_path, caplog):
    path = tmp_path / "index.json"
    path.write_text("[1, 2, 3]", encoding="utf-8")
    with caplog.at_level(logging.WARNING):
        assert load_index(path) is None
    assert not path.exists()
    assert len(list(tmp_path.glob("index.corrupt-*.json"))) == 1
    assert caplog.records


def test_foreign_schema_ignored_without_rename(tmp_path, caplog):
    path = tmp_path / "index.json"
    write_envelope(path, schema_version=99)
    with caplog.at_level(logging.WARNING):
        assert load_index(path) is None
    assert path.exists()  # файл НЕ переименован (архитектура п. 12)
    assert list(tmp_path.glob("index.corrupt-*.json")) == []
    assert any(r.levelno == logging.WARNING for r in caplog.records)


def test_missing_schema_version_is_foreign_schema(tmp_path):
    # schema_version отсутствует -> .get() вернёт None -> ветка «чужая схема»
    path = tmp_path / "index.json"
    write_envelope(path)
    raw = json.loads(path.read_text(encoding="utf-8"))
    del raw["schema_version"]
    path.write_text(json.dumps(raw), encoding="utf-8")
    assert load_index(path) is None
    assert path.exists()


def test_missing_file_returns_none_and_creates_nothing(tmp_path):
    assert load_index(tmp_path / "index.json") is None
    assert list(tmp_path.iterdir()) == []


# --- Атомарность записи ---

def test_save_leaves_no_temp_files(tmp_path):
    path = tmp_path / "index.json"
    save_index(make_result(), path)
    assert [p.name for p in tmp_path.iterdir()] == ["index.json"]
    # повторная запись (перезапись поверх существующего) — по-прежнему чисто
    save_index(make_result(duration_ms=999), path)
    assert [p.name for p in tmp_path.iterdir()] == ["index.json"]
    assert load_index(path).duration_ms == 999


def test_save_creates_nested_dirs(tmp_path):
    path = tmp_path / "a" / "b" / "index.json"
    save_index(make_result(), path)
    assert path.exists()
    assert load_index(path) == make_result()


# --- Сбой записи: исключение наружу, temp-мусора нет (Code-ревью MINOR) ---

def test_save_replace_failure_raises_and_leaves_no_temp(tmp_path, monkeypatch):
    path = tmp_path / "index.json"

    def broken_replace(src, dst):
        raise OSError("диск переполнен")

    monkeypatch.setattr(os, "replace", broken_replace)
    with pytest.raises(OSError):
        save_index(make_result(), path)
    assert list(tmp_path.iterdir()) == []  # temp-файл удалён


def test_save_surrogate_encoding_failure_raises_and_leaves_no_temp(tmp_path):
    """Суррогат в данных (UnicodeEncodeError при ensure_ascii=False) ловится
    как ValueError: исключение наружу, temp-файла на диске нет (Code-ревью)."""
    path = tmp_path / "index.json"
    entry = make_full_entry(name="bad", readme_content="битый путь \udcff внутри")
    with pytest.raises(UnicodeEncodeError):
        save_index(make_result(projects=[entry]), path)
    assert list(tmp_path.iterdir()) == []


# --- load_index не бросает исключений ни при каком содержимом (анти-тест) ---

GARBAGE_CONTENTS = [
    b'{"schema_version": 1, "projects": [',  # обрезанный JSON
    b"[1, 2, 3]",  # валидный JSON, но не словарь
    b'{"schema_version": 99, "root": "/x"}',  # чужая схема
    b"",  # пустой файл
    b"\x00\xff",  # бинарный мусор
    b'{"schema_version": 1}',  # схема верна, остальных полей нет
    b'{"schema_version": 1, "projects": "not-a-list", "errors": 5, "root": 1}',
]


@pytest.mark.parametrize("content", GARBAGE_CONTENTS, ids=lambda c: c[:32])
def test_load_index_never_raises_on_garbage(tmp_path, content):
    path = tmp_path / "index.json"
    path.write_bytes(content)
    result = load_index(path)
    assert result is None or isinstance(result, ScanResult)


# --- Headless-инвариант: storage.py без PySide6 (раздел 5 п. 6 декомпозиции) ---

def test_storage_source_has_no_pyside6():
    assert "PySide6" not in STORAGE_SOURCE.read_text(encoding="utf-8")
