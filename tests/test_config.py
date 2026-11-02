# tests/test_config.py — дефолты/битый JSON/roundtrip/атомарность dashboard/config.py
import json
import logging
import os
from pathlib import Path

import pytest

from dashboard.config import AppConfig, load_config

CONFIG_SOURCE = Path(__file__).resolve().parent.parent / "dashboard" / "config.py"


# --- Отсутствие файла -> дефолты ---

def test_missing_file_returns_defaults(tmp_path):
    cfg = load_config(tmp_path / "config.json")
    assert cfg == AppConfig()
    assert cfg.root == "/Users/milinsky/Projects"
    assert cfg.max_depth == 8
    assert cfg.extra_ignore_names == []
    assert cfg.max_readme_store_bytes == 512 * 1024
    assert cfg.max_readme_render_chars == 200_000


# --- Битый JSON / не-словарь -> дефолты + logging.warning, файл не переписывается ---

def test_broken_json_returns_defaults_and_warns(tmp_path, caplog):
    p = tmp_path / "config.json"
    broken = '{"root": "/x",'
    p.write_text(broken, encoding="utf-8")
    with caplog.at_level(logging.WARNING):
        cfg = load_config(p)  # исключение наружу не летит
    assert cfg == AppConfig()
    assert cfg.root == "/Users/milinsky/Projects"
    assert any(r.levelno == logging.WARNING for r in caplog.records)
    # MUST NOT DO 3: замена битого файла происходит только при следующем save
    assert p.read_text(encoding="utf-8") == broken


def test_non_dict_json_returns_defaults_and_warns(tmp_path, caplog):
    p = tmp_path / "config.json"
    p.write_text("[1, 2, 3]", encoding="utf-8")
    with caplog.at_level(logging.WARNING):
        cfg = load_config(p)
    assert cfg == AppConfig()
    assert any(r.levelno == logging.WARNING for r in caplog.records)


def test_unreadable_file_returns_defaults_and_warns(tmp_path, caplog, monkeypatch):
    p = tmp_path / "config.json"
    p.write_text("{}", encoding="utf-8")

    def raise_os_error(self, *args, **kwargs):
        raise OSError("нет доступа")

    monkeypatch.setattr(Path, "read_text", raise_os_error)
    with caplog.at_level(logging.WARNING):
        cfg = load_config(p)
    assert cfg == AppConfig()
    assert any(r.levelno == logging.WARNING for r in caplog.records)


# --- Значения вне разумных рамок -> дефолт поля ---

@pytest.mark.parametrize("bad", [0, -3])
def test_max_depth_below_one_replaced_with_default(tmp_path, bad):
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"max_depth": bad}), encoding="utf-8")
    assert load_config(p).max_depth == 8


def test_wrong_typed_fields_replaced_with_defaults(tmp_path):
    p = tmp_path / "config.json"
    p.write_text(json.dumps({
        "root": 123,
        "max_depth": "8",
        "extra_ignore_names": "node_modules",
        "max_readme_store_bytes": True,
        "max_readme_render_chars": [1],
    }), encoding="utf-8")
    assert load_config(p) == AppConfig()


def test_valid_fields_loaded_partial_json_fills_defaults(tmp_path):
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"max_depth": 3}), encoding="utf-8")
    cfg = load_config(p)
    assert cfg.max_depth == 3
    assert cfg.root == "/Users/milinsky/Projects"


def test_unknown_keys_ignored(tmp_path):
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"root": "/x", "future_field": 1}), encoding="utf-8")
    cfg = load_config(p)
    assert cfg.root == "/x"
    assert cfg.max_depth == 8


# --- Поле language (эпик i18n): allowlist "system"|"ru"|"en"|"zh_CN" ---

@pytest.mark.parametrize("language", ["system", "ru", "en", "zh_CN"])
def test_valid_language_values_loaded(tmp_path, language):
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"language": language}), encoding="utf-8")
    assert load_config(p).language == language


@pytest.mark.parametrize("bad", ["fr", 42, None, ["ru"]])
def test_invalid_language_values_replaced_with_default(tmp_path, bad):
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"language": bad}), encoding="utf-8")
    assert load_config(p).language == "system"


def test_missing_language_key_reads_as_default(tmp_path):
    # старые конфиги без ключа language читаются с дефолтом
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"root": "/x"}), encoding="utf-8")
    assert load_config(p).language == "system"


def test_roundtrip_language(tmp_path):
    p = tmp_path / "config.json"
    AppConfig(language="en").save(p)
    assert load_config(p).language == "en"


# --- Roundtrip save -> load без потерь ---

def test_roundtrip_lossless_including_extra_ignore_names(tmp_path):
    p = tmp_path / "config.json"
    cfg = AppConfig(
        root="/Users/milinsky/Code",
        max_depth=3,
        extra_ignore_names=[".venv-old", "target2"],
        max_readme_store_bytes=1024,
        max_readme_render_chars=5000,
    )
    cfg.save(p)
    loaded = load_config(p)
    # Равенство dataclass целиком: потеря ЛЮБОГО поля в save/load уронит тест
    # (все значения выше не-дефолтные, поэтому подмена дефолтом не маскируется).
    assert loaded == cfg
    assert loaded.extra_ignore_names == [".venv-old", "target2"]


def test_roundtrip_defaults(tmp_path):
    p = tmp_path / "config.json"
    AppConfig().save(p)
    assert load_config(p) == AppConfig()


def test_saved_json_shape_and_encoding(tmp_path):
    p = tmp_path / "config.json"
    AppConfig(root="/Users/milinsky/Проекты").save(p)
    data = json.loads(p.read_text(encoding="utf-8"))
    # "language" — язык интерфейса (эпик i18n): единственная правка существующего
    # теста эпика, арифметическое следствие брифа §4.2 — поле обязательно в
    # save-форме; см. архитектура i18n п. 9.
    assert set(data) == {
        "root", "max_depth", "extra_ignore_names",
        "max_readme_store_bytes", "max_readme_render_chars",
        "language",
    }
    raw = p.read_text(encoding="utf-8")
    assert "/Users/milinsky/Проекты" in raw  # ensure_ascii=False
    assert '\n  "root"' in raw  # indent=2


# --- Атомарность и каталоги ---

def test_save_creates_missing_nested_dirs(tmp_path):
    p = tmp_path / "a" / "b" / "config.json"
    AppConfig().save(p)
    assert p.exists()
    assert load_config(p) == AppConfig()


def test_save_leaves_no_temp_files(tmp_path):
    p = tmp_path / "config.json"
    AppConfig().save(p)
    assert sorted(x.name for x in tmp_path.iterdir()) == ["config.json"]


# --- Сбой записи: исключение наружу, temp-мусора нет (Code-ревью MINOR) ---

def test_save_replace_failure_raises_and_leaves_no_temp(tmp_path, monkeypatch):
    p = tmp_path / "config.json"

    def broken_replace(src, dst):
        raise OSError("диск переполнен")

    monkeypatch.setattr(os, "replace", broken_replace)
    with pytest.raises(OSError):
        AppConfig().save(p)
    assert list(tmp_path.iterdir()) == []  # temp-файл удалён


def test_save_surrogate_encoding_failure_raises_and_leaves_no_temp(tmp_path):
    """Суррогат в root (UnicodeEncodeError при ensure_ascii=False) ловится
    как ValueError: исключение наружу, temp-файла на диске нет (Code-ревью)."""
    p = tmp_path / "config.json"
    with pytest.raises(UnicodeEncodeError):
        AppConfig(root="/Users/x/\udcffсломанный").save(p)
    assert list(tmp_path.iterdir()) == []


# --- Headless-инвариант: config.py без PySide6 и без зависимостей от модулей проекта ---

def test_config_source_imports_stdlib_only():
    src = CONFIG_SOURCE.read_text(encoding="utf-8")
    assert "PySide6" not in src
    assert "import dashboard" not in src
    assert "from dashboard" not in src
