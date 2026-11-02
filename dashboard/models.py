# dashboard/models.py — только stdlib
"""Схема данных индекса: ProjectEntry, ScanError, ScanResult + сериализация to_dict/from_dict.

Единственное место владения схемой (карта файлов п. 4.1 архитектуры).
Модуль headless: не импортирует ничего, кроме stdlib.
"""

from dataclasses import dataclass, field, fields


def _value_type_ok(value: object, expected: object) -> bool:
    """Проверка типа значения поля схемы (защитительная загрузка).

    bool проверяется отдельно (подкласс int — true/false не должен пройти как
    число); для float допустимы целые (JSON-числа без точки); для list-полей —
    только список; для str | None — строка или None."""
    if expected is str:
        return isinstance(value, str)
    if expected is bool:
        return isinstance(value, bool)
    if expected is int:
        return isinstance(value, int) and not isinstance(value, bool)
    if expected is float:
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == (str | None):
        return value is None or isinstance(value, str)
    if expected == list[ProjectEntry] or expected == list[ScanError]:
        return isinstance(value, list)
    return False


def _typed_known_kwargs(cls, data: dict) -> dict:
    """Ключи data, известные схеме cls, со значениями корректного типа.

    Лишние ключи и значения не того типа (мусор из повреждённого/рукописного
    кэша, например "mtime": "abc") отбрасываются — поле получит дефолт
    dataclass и не дойдёт до форматтеров/сортировки с чужим типом."""
    known = {f.name: f.type for f in fields(cls)}
    return {
        k: v for k, v in data.items()
        if k in known and _value_type_ok(v, known[k])
    }


@dataclass
class ProjectEntry:
    name: str = ""                       # имя каталога проекта
    path: str = ""                       # абсолютный путь
    rel_path: str = ""                   # относительно root, например "Duyler/Duyler/packages/http-server"
    group: str = ""                      # первый сегмент rel_path; для проектов в корне — имя проекта
    readme_path: str = ""
    mtime: float = 0.0                   # epoch; mtime файла README.md (инвариант архитектуры п. 8)
    dir_size_bytes: int = 0
    file_count: int = 0
    readme_size_bytes: int = 0
    readme_truncated: bool = False
    readme_content: str = ""             # может быть "" (пустой/нечитаемый)
    readme_error: str | None = None      # причина нечитаемости; None = прочитан

    def to_dict(self) -> dict:
        return {f.name: getattr(self, f.name) for f in fields(self)}

    @classmethod
    def from_dict(cls, data: dict) -> "ProjectEntry":
        # Защитительная загрузка: лишние ключи игнорируются, значения не того
        # типа и отсутствующие поля заменяются дефолтами dataclass (Code-ревью
        # MINOR: "mtime": "abc" из кэша больше не роняет форматтеры TypeError'ом).
        kwargs = _typed_known_kwargs(cls, data)
        if isinstance(kwargs.get("mtime"), int):
            kwargs["mtime"] = float(kwargs["mtime"])  # схема объявляет float
        return cls(**kwargs)


@dataclass
class ScanError:
    path: str = ""
    reason: str = ""                     # человекочитаемо, без traceback

    def to_dict(self) -> dict:
        return {f.name: getattr(self, f.name) for f in fields(self)}

    @classmethod
    def from_dict(cls, data: dict) -> "ScanError":
        return cls(**_typed_known_kwargs(cls, data))


@dataclass
class ScanResult:
    root: str = ""
    projects: list[ProjectEntry] = field(default_factory=list)  # отсортированы по (group, name) — порядок задаёт сканер, не модели
    errors: list[ScanError] = field(default_factory=list)
    duration_ms: int = 0
    cancelled: bool = False

    def to_dict(self) -> dict:
        return {
            "root": self.root,
            "projects": [p.to_dict() for p in self.projects],
            "errors": [e.to_dict() for e in self.errors],
            "duration_ms": self.duration_ms,
            "cancelled": self.cancelled,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ScanResult":
        # Типовая валидация значений отбрасывает и не-списочные projects/errors
        # (раньше int здесь падал TypeError'ом на итерации), и скалярные поля
        # не того типа (duration_ms: "9", cancelled: "yes" и т.п.).
        kwargs = _typed_known_kwargs(cls, data)
        # Вложенные dict собираются в объекты; не-dict элементы молча пропускаются
        # (защитительная загрузка: битый/расширенный кэш не должен валить приложение).
        kwargs["projects"] = [
            ProjectEntry.from_dict(p) for p in kwargs.get("projects") or []
            if isinstance(p, dict)
        ]
        kwargs["errors"] = [
            ScanError.from_dict(e) for e in kwargs.get("errors") or []
            if isinstance(e, dict)
        ]
        return cls(**kwargs)
