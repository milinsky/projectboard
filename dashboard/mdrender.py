# dashboard/mdrender.py — markdown + stdlib, без Qt
"""Рендер README в HTML для панели деталей (задача 09 применяет его в QTextBrowser).

Чистая функция ProjectEntry -> RenderedReadme без исключений:
либо валидный HTML-фрагмент, либо notice-сообщение с html=None.
Сырой HTML из README не фильтруется (markdown 3.x без safe mode):
безопасность обеспечивает QTextBrowser — без JS и сетевой автозагрузки
(архитектура п. 4.6, п. 10).
"""

import markdown
from dataclasses import dataclass

from dashboard.models import ProjectEntry

STYLESHEET: str = """
body { font-family: -apple-system, 'Helvetica Neue', sans-serif; }
pre { background-color: #f5f5f5; white-space: pre-wrap; }
code { font-family: 'Menlo', monospace; }
"""


@dataclass
class RenderedReadme:
    html: str | None                     # HTML-фрагмент; None для пустого/нечитаемого README
    notice: str | None                   # сообщение для панели; None при успешном рендере


def render_readme(entry: ProjectEntry, max_chars: int = 200_000,
                  truncation_label: str | None = None) -> RenderedReadme:
    """Порядок ветвления — архитектура п. 4.6: ошибка -> пустота -> усечение -> рендер.

    truncation_label — уже переведённая метка усечения от вызывающего (панель
    передаёт её лениво из tr); None — русская source-метка. Модуль без Qt:
    перевод своих строк не выполняет, метка приходит параметром."""
    # 1) readme_error -> notice с причиной, до вызова markdown (короткое замыкание)
    if entry.readme_error:
        return RenderedReadme(None, f"README нечитаем: {entry.readme_error}")
    # 2) пустой README -> notice, тоже до рендера
    if entry.readme_content == "":
        return RenderedReadme(None, "README пуст")
    # 3) усечение по символам на ИСХОДНОМ тексте, до рендера
    text = entry.readme_content
    truncated = len(text) > max_chars
    if truncated:
        text = text[:max_chars]
    # 4) markdown -> HTML-фрагмент
    html = markdown.markdown(text, extensions=["tables", "fenced_code", "sane_lists"])
    # 5) заметка об усечении принадлежит HTML, не notice
    if truncated:
        label = truncation_label if truncation_label is not None else "README усечён для отображения"
        html += f"<blockquote>{label}</blockquote>"
    # 6)
    return RenderedReadme(html, None)
