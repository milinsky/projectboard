# dashboard/config.py — только stdlib, без Qt
"""Конфигурация приложения: AppConfig, load_config, save + путь-константы data/.

Единственное место вычисления путей `data/` (карта файлов п. 4.1 архитектуры):
storage и main получают пути параметром. Инвариант: битый или отсутствующий
config.json никогда не валит приложение — load_config всегда возвращает
валидный AppConfig; замена битого файла происходит при следующем save, не при
загрузке.
"""

import json
import logging
import os
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
CONFIG_PATH = DATA_DIR / "config.json"
INDEX_PATH = DATA_DIR / "index.json"


def _is_int(value: object) -> bool:
    # bool — подкласс int, но true/false в конфиге не глубина и не лимит байтов.
    return isinstance(value, int) and not isinstance(value, bool)


@dataclass
class AppConfig:
    root: str = "/Users/milinsky/Projects"
    max_depth: int = 8
    # только дополнительные имена; объединение с DEFAULT_IGNORE_NAMES — задача 10
    extra_ignore_names: list[str] = field(default_factory=list)
    max_readme_store_bytes: int = 512 * 1024
    max_readme_render_chars: int = 200_000
    language: str = "system"          # "system" | "ru" | "en" | "zh_CN" (эпик i18n)

    def save(self, path: Path = CONFIG_PATH) -> None:
        """Атомарная запись: temp-файл в каталоге path, затем os.replace."""
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=".config-", suffix=".json.tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(asdict(self), f, ensure_ascii=False, indent=2)
            os.replace(tmp_name, path)
        except (OSError, ValueError):
            # OSError — сбой записи/замены; ValueError — ошибка кодирования JSON
            # (например UnicodeEncodeError с ensure_ascii=False для суррогатных
            # путей, Code-ревью MINOR). В обеих ветках temp-файл удаляется.
            try:
                os.unlink(tmp_name)
            except OSError:
                logging.warning("config: не удалось удалить временный файл %s", tmp_name)
            raise


def load_config(path: Path = CONFIG_PATH) -> AppConfig:
    """Загрузка конфига: нет файла -> дефолты; битый JSON/не-словарь -> warning + дефолты."""
    if not path.exists():
        return AppConfig()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logging.warning(
            "config: %s не читается (%s) — используются значения по умолчанию", path, exc,
        )
        return AppConfig()
    if not isinstance(data, dict):
        logging.warning(
            "config: %s — ожидается JSON-объект, получено %s — используются значения по умолчанию",
            path, type(data).__name__,
        )
        return AppConfig()

    # Защитительная загрузка: неизвестные ключи игнорируются, значения не того
    # типа или вне разумных рамок заменяются дефолтом поля.
    cfg = AppConfig()
    if isinstance(data.get("root"), str):
        cfg.root = data["root"]
    if _is_int(data.get("max_depth")) and data["max_depth"] >= 1:
        cfg.max_depth = data["max_depth"]
    extra = data.get("extra_ignore_names")
    if isinstance(extra, list) and all(isinstance(name, str) for name in extra):
        cfg.extra_ignore_names = list(extra)
    if _is_int(data.get("max_readme_store_bytes")) and data["max_readme_store_bytes"] >= 1:
        cfg.max_readme_store_bytes = data["max_readme_store_bytes"]
    if _is_int(data.get("max_readme_render_chars")) and data["max_readme_render_chars"] >= 1:
        cfg.max_readme_render_chars = data["max_readme_render_chars"]
    value = data.get("language")
    if isinstance(value, str) and value in ("system", "ru", "en", "zh_CN"):
        cfg.language = value
    return cfg
