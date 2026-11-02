# tests/test_models.py — roundtrip и защитительная загрузка dashboard/models.py
import dataclasses
from pathlib import Path

from dashboard.models import ProjectEntry, ScanError, ScanResult

MODELS_SOURCE = Path(__file__).resolve().parent.parent / "dashboard" / "models.py"


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


# --- Roundtrip: to_dict(from_dict(d)) == d для каждого класса ---

def test_project_entry_roundtrip_readme_ok():
    entry = make_full_entry()
    d = entry.to_dict()
    assert ProjectEntry.from_dict(d) == entry
    assert ProjectEntry.from_dict(d).to_dict() == d


def test_project_entry_roundtrip_readme_error():
    entry = make_full_entry(readme_error="permission denied", readme_content="")
    d = entry.to_dict()
    assert ProjectEntry.from_dict(d) == entry
    assert ProjectEntry.from_dict(d).to_dict() == d


def test_project_entry_roundtrip_float_mtime_exact():
    d = make_full_entry(mtime=1795000000.123).to_dict()
    restored = ProjectEntry.from_dict(d)
    assert isinstance(restored.mtime, float)
    assert restored.mtime == 1795000000.123


def test_scan_error_roundtrip():
    err = ScanError(path="/Users/milinsky/Projects/locked", reason="PermissionError: доступ запрещён")
    d = err.to_dict()
    assert ScanError.from_dict(d) == err
    assert ScanError.from_dict(d).to_dict() == d


def test_scan_result_roundtrip_nonempty():
    result = ScanResult(
        root="/Users/milinsky/Projects",
        projects=[make_full_entry(), make_full_entry(name="rload", group="rload", rel_path="rload")],
        errors=[ScanError(path="/Users/milinsky/Projects/locked", reason="PermissionError")],
        duration_ms=152,
        cancelled=False,
    )
    d = result.to_dict()
    restored = ScanResult.from_dict(d)
    assert restored == result
    # вложенные dict собраны в объекты
    assert isinstance(restored.projects[0], ProjectEntry)
    assert isinstance(restored.errors[0], ScanError)
    assert ScanResult.from_dict(d).to_dict() == d


# --- Анти-тест: ни одно поле не теряется при сериализации ---

def test_project_entry_to_dict_covers_all_12_fields():
    # Если поле выпадет из to_dict, from_dict заполнит его дефолтом и
    # проверки равенства объектов выше упадут; здесь — прямая проверка состава ключей.
    d = make_full_entry().to_dict()
    expected = {f.name for f in dataclasses.fields(ProjectEntry)}
    assert set(d.keys()) == expected
    assert len(expected) == 12


def test_scan_result_to_dict_covers_all_fields():
    d = ScanResult().to_dict()
    expected = {f.name for f in dataclasses.fields(ScanResult)}
    assert set(d.keys()) == expected


# --- Защитительная загрузка from_dict ---

def test_from_dict_ignores_unknown_keys():
    d = make_full_entry().to_dict()
    d["future_field"] = 1
    d["another_unknown"] = "x"
    entry = ProjectEntry.from_dict(d)  # не падает
    assert entry == make_full_entry()
    assert not hasattr(entry, "future_field")


def test_scan_error_from_dict_ignores_unknown_keys():
    d = ScanError(path="/p", reason="r").to_dict()
    d["future_field"] = 1
    assert ScanError.from_dict(d) == ScanError(path="/p", reason="r")


def test_scan_result_from_dict_ignores_unknown_keys():
    d = ScanResult(root="/r").to_dict()
    d["future_field"] = 1
    assert ScanResult.from_dict(d) == ScanResult(root="/r")


def test_from_dict_missing_keys_uses_dataclass_defaults():
    assert ProjectEntry.from_dict({}) == ProjectEntry()
    assert ScanError.from_dict({}) == ScanError()
    assert ScanResult.from_dict({}) == ScanResult()


def test_scan_result_from_dict_skips_non_dict_items():
    d = {
        "root": "/r",
        "projects": [{"name": "x"}, "not-a-dict"],
        "errors": ["oops"],
        "duration_ms": 0,
        "cancelled": False,
    }
    restored = ScanResult.from_dict(d)
    assert restored.projects == [ProjectEntry(name="x")]
    assert restored.errors == []


# --- Типовая валидация ЗНАЧЕНИЙ (Code-ревью MINOR): мусор -> дефолт поля ---

def test_project_entry_from_dict_wrong_types_fall_back_to_defaults():
    """Кэш с "mtime": "abc" больше не доходит до форматтеров с чужим типом."""
    d = make_full_entry().to_dict()
    d.update({
        "mtime": "abc",
        "dir_size_bytes": "12",
        "file_count": None,
        "readme_size_bytes": [1],
        "readme_truncated": 1,          # int не проходит как bool
        "name": 42,
        "path": ["x"],
        "group": True,                  # bool не проходит как str... и как число
        "readme_path": 3.5,
        "readme_content": {"md": "#"},
        "readme_error": 5,
    })
    entry = ProjectEntry.from_dict(d)   # не падает
    assert entry.mtime == 0.0 and isinstance(entry.mtime, float)
    assert entry.dir_size_bytes == 0
    assert entry.file_count == 0
    assert entry.readme_size_bytes == 0
    assert entry.readme_truncated is False
    assert entry.name == ""
    assert entry.path == ""
    assert entry.group == ""
    assert entry.readme_path == ""
    assert entry.readme_content == ""
    assert entry.readme_error is None
    # корректные поля того же словаря сохранены
    assert entry.rel_path == d["rel_path"]


def test_project_entry_from_dict_int_mtime_coerced_to_float():
    """Целые JSON-числа допустимы для float-поля и нормализуются к float."""
    entry = ProjectEntry.from_dict({"mtime": 1795000000})
    assert isinstance(entry.mtime, float)
    assert entry.mtime == 1795000000.0


def test_project_entry_from_dict_bool_not_accepted_as_number():
    assert ProjectEntry.from_dict({"mtime": True}).mtime == 0.0
    assert ProjectEntry.from_dict({"dir_size_bytes": True}).dir_size_bytes == 0


def test_scan_error_from_dict_wrong_types_fall_back_to_defaults():
    assert ScanError.from_dict({"path": 1, "reason": []}) == ScanError()
    assert ScanError.from_dict({"path": "/p", "reason": "ок"}).reason == "ок"


def test_scan_result_from_dict_wrong_types_fall_back_to_defaults():
    """Не-списочные projects/errors и скаляры не того типа — дефолты, без краха."""
    restored = ScanResult.from_dict({
        "root": 5,
        "projects": 7,                  # раньше — TypeError на итерации
        "errors": {"a": 1},
        "duration_ms": "9",
        "cancelled": "yes",
    })
    assert restored == ScanResult()


def test_scan_result_from_dict_keeps_typed_fields():
    restored = ScanResult.from_dict({
        "root": "/r", "duration_ms": 9, "cancelled": True,
        "projects": [{"name": "x", "mtime": "abc"}],   # вложенная валидация тоже
        "errors": [{"path": "/p", "reason": "r"}],
    })
    assert restored.root == "/r"
    assert restored.duration_ms == 9
    assert restored.cancelled is True
    assert restored.projects == [ProjectEntry(name="x")]  # mtime "abc" -> дефолт
    assert restored.errors == [ScanError(path="/p", reason="r")]


# --- Headless-инвариант: models.py без PySide6 ---

def test_models_source_has_no_pyside6():
    assert "PySide6" not in MODELS_SOURCE.read_text(encoding="utf-8")
