# tests/test_make_icon.py — приёмочный тест генератора иконки (эпик app-naming, задача 01)
"""make_icon.py производит валидный iconset: ровно 10 PNG канонических имён,
пиксельный размер каждого равен числу в имени (инвариант iconutil: при
рассинхроне «имя/размер» конвертация в icns в задаче 02 падает с бесполезной
диагностикой). Тест читает фактические пиксели через QImage и не доверяет
скрипту. Запуск генератора — importlib в этом же процессе (subprocess в
тестах не используется), записи только в tmp_path,
QT_QPA_PLATFORM=offscreen ставится до импорта PySide6.
"""

import importlib.util
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")  # до импорта PySide6

from PySide6.QtGui import QImage

# Те же 10 пар имя->размер, что в ICONSET скрипта (контракт задачи 02).
EXPECTED: dict[str, int] = {
    "icon_16x16.png": 16,
    "icon_16x16@2x.png": 32,
    "icon_32x32.png": 32,
    "icon_32x32@2x.png": 64,
    "icon_128x128.png": 128,
    "icon_128x128@2x.png": 256,
    "icon_256x256.png": 256,
    "icon_256x256@2x.png": 512,
    "icon_512x512.png": 512,
    "icon_512x512@2x.png": 1024,
}


def _load_module():
    """Каталог scripts/ — не пакет; грузим make_icon.py по пути."""
    script = Path(__file__).resolve().parent.parent / "scripts" / "make_icon.py"
    spec = importlib.util.spec_from_file_location("make_icon", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_generates_canonical_iconset(tmp_path):
    module = _load_module()
    iconset_dir = tmp_path / "AppIcon.iconset"
    assert module.main([str(iconset_dir)]) == 0
    # Ровно 10 файлов, точное множество имён (сравнение списков, не подстроки/glob).
    assert sorted(p.name for p in iconset_dir.iterdir()) == sorted(EXPECTED)
    # Пиксельный размер каждого PNG — фактическим чтением, по всем 10 файлам.
    for name, size in EXPECTED.items():
        image = QImage(str(iconset_dir / name))
        assert not image.isNull(), name
        assert (image.width(), image.height()) == (size, size), name
    # Повторный запуск поверх существующего каталога не падает.
    assert module.main([str(iconset_dir)]) == 0
    assert sorted(p.name for p in iconset_dir.iterdir()) == sorted(EXPECTED)


def test_rejects_wrong_argc():
    assert _load_module().main([]) != 0
