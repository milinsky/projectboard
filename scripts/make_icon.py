# scripts/make_icon.py — генератор иконки Projectboard (эпик app-naming, задача 01)
"""Генератор AppIcon.iconset: offscreen Qt-рендер -> 10 PNG канонических имён.

Контракт CLI (используется scripts/build_app.sh, задача 02, дословно):
    make_icon.py <output_iconset_dir>
Ровно один позиционный аргумент — каталог iconset; создаётся при
отсутствии; флагов и опций нет. Пишет ТОЛЬКО в переданный каталог:
ровно 10 PNG, имя и пиксельный размер каждого заданы таблицей ICONSET
ниже (единственный источник размеров). Конвертация в .icns выполняется
iconutil в build_app.sh и здесь НЕ вызывается. Повторный запуск поверх
существующего каталога перезаписывает файлы. Exit-коды: 0 — успех;
1 — ошибка рендера/записи (сообщение в stderr); 2 — неверное
использование CLI (usage в stderr).
Запуск: "$ROOT/.venv/bin/python" "$ROOT/scripts/make_icon.py" <dir>
(shebang намеренно не ставится).
Соглашение main(argv): argv — аргументы командной строки БЕЗ имени
программы (блок __main__ передаёт sys.argv[1:]); ровно один элемент —
успешный путь.
"""

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")  # до импорта PySide6

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QImage, QLinearGradient, QPainter
from PySide6.QtWidgets import QApplication

# Канонический состав macOS-iconset: имя файла -> пиксельный размер (Ш=В).
# ЕДИНСТВЕННЫЙ источник размеров: iconutil -c icns строго валидирует
# фактические пиксели PNG против числа в имени, при рассинхроне падает
# с бесполезным «Failed to generate ICNS». Не править размеры иначе,
# чем через эту таблицу.
ICONSET: dict[str, int] = {
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


def draw_icon(size_px: int) -> QImage:
    """Рисует иконку заново в заданном размере (без даунскейла мастрайзинга:
    на 16px детали отдельной отрисовки остаются читаемыми)."""
    image = QImage(size_px, size_px, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    side = float(size_px)

    # Подложка: скруглённый квадрат с вертикальным градиентом.
    margin = side * 0.06
    radius = side * 0.20
    plate = QRectF(margin, margin, side - 2.0 * margin, side - 2.0 * margin)
    gradient = QLinearGradient(plate.topLeft(), plate.bottomLeft())
    gradient.setColorAt(0.0, QColor("#4f8fd9"))
    gradient.setColorAt(1.0, QColor("#274b73"))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QBrush(gradient))
    painter.drawRoundedRect(plate, radius, radius)

    # Символ «доска проектов»: три белые колонки разной высоты.
    # Все координаты относительные — каждый размер рисуется самостоятельной
    # композицией, а не масштабированной копией.
    bar_width = side * 0.11
    gap = side * 0.075
    board_width = bar_width * 3.0 + gap * 2.0
    start_x = (side - board_width) / 2.0
    top = side * 0.26
    painter.setBrush(QColor("#f5f7fa"))
    for index, height in enumerate((0.34, 0.52, 0.42)):
        x = start_x + index * (bar_width + gap)
        column = QRectF(x, top, bar_width, side * height)
        painter.drawRoundedRect(column, bar_width * 0.4, bar_width * 0.4)
    painter.end()
    return image


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("usage: make_icon.py <output_iconset_dir>", file=sys.stderr)
        return 2
    out_dir = Path(argv[0])
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        print(f"make_icon: не удалось создать каталог {out_dir}: {exc}", file=sys.stderr)
        return 1
    _app = QApplication.instance() or QApplication([])  # толерантность к уже созданному QApplication
    for name, size in ICONSET.items():
        try:
            image = draw_icon(size)
            saved = image.save(str(out_dir / name), "PNG")
        except (OSError, RuntimeError) as exc:
            print(f"make_icon: ошибка рендера/записи {name}: {exc}", file=sys.stderr)
            return 1
        if not saved:
            print(f"make_icon: ошибка записи {name}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
