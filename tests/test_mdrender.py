# tests/test_mdrender.py — рендер/усечение/пустой/ошибка dashboard/mdrender.py
import inspect
from pathlib import Path

import markdown

import dashboard.mdrender as mdrender_module
from dashboard.mdrender import STYLESHEET, render_readme
from dashboard.models import ProjectEntry

MDRENDER_SOURCE = Path(__file__).resolve().parent.parent / "dashboard" / "mdrender.py"

# Payload из задачи 05 (буквально): таблица + fenced code
SAMPLE_MARKDOWN = """# Title

| A | B |
|---|---|
| 1 | 2 |

```python
print("hi")
```"""


def make_entry(**overrides) -> ProjectEntry:
    values = dict(
        name="http-server",
        path="/Users/milinsky/Projects/Duyler/Duyler/packages/http-server",
        rel_path="Duyler/Duyler/packages/http-server",
        group="Duyler",
        readme_content=SAMPLE_MARKDOWN,
        readme_error=None,
    )
    values.update(overrides)
    return ProjectEntry(**values)


# --- Functional: обычный markdown (таблица + fenced code) ---
def test_render_table_and_fenced_code():
    result = render_readme(make_entry())
    assert result.notice is None
    assert result.html is not None
    assert "<table>" in result.html
    assert "<pre>" in result.html
    assert "<code" in result.html


def test_render_below_limit_has_no_truncation_note():
    result = render_readme(make_entry(readme_content="# small\n\nтекст\n"))
    assert result.notice is None
    assert result.html is not None
    assert "README усечён для отображения" not in result.html


# --- Functional: усечение ---
def test_truncation_cuts_source_before_render(monkeypatch):
    captured = {}
    real_markdown = markdown.markdown

    def spy(text, **kwargs):
        captured["len"] = len(text)
        return real_markdown(text, **kwargs)

    monkeypatch.setattr(mdrender_module.markdown, "markdown", spy)

    content = "# head\n" + "a" * (2 * 1000)
    assert len(content) > 1000  # payload действительно больше лимита
    result = render_readme(make_entry(readme_content=content), max_chars=1000)

    assert result.notice is None
    assert result.html is not None
    assert "README усечён для отображения" in result.html
    assert captured["len"] == 1000  # рендерился исходник ровно max_chars символов
    assert "a" * 1001 not in result.html  # хвостовых 'a' сверх фрагмента нет


def test_truncation_note_in_html_not_notice():
    # MUST NOT DO 3: заметка об усечении принадлежит HTML, не notice
    content = "# head\n" + "a" * 3000
    result = render_readme(make_entry(readme_content=content), max_chars=1000)
    assert result.html is not None
    assert "README усечён для отображения" in result.html
    assert result.notice is None


# --- Functional: пустой README ---
def test_empty_readme_gives_notice():
    result = render_readme(make_entry(readme_content="", readme_error=None))
    assert result.notice == "README пуст"
    assert result.html is None


# --- Functional: нечитаемый README ---
def test_error_readme_gives_notice_with_reason():
    result = render_readme(make_entry(readme_content="", readme_error="permission denied"))
    assert result.notice is not None
    assert "permission denied" in result.notice
    assert result.html is None


def test_error_branch_wins_over_empty():
    # порядок ветвления §2 (архитектура п. 4.6): readme_error проверяется раньше пустоты
    result = render_readme(make_entry(readme_content="", readme_error="permission denied"))
    assert result.notice == "README нечитаем: permission denied"
    assert result.html is None


# --- Анти-тест: html строго None в notice-ветках (падает, если ветвление перепутано) ---
def test_notice_branches_have_html_none_strictly():
    for entry in (
        make_entry(readme_content="", readme_error=None),
        make_entry(readme_content="# x", readme_error="boom"),
    ):
        result = render_readme(entry)
        assert result.html is None
        assert result.notice is not None


# --- Compliance: сигнатура дословно (архитектура п. 8, контракт с задачей 09) ---
def test_signature_and_default_max_chars():
    sig = inspect.signature(render_readme)
    assert list(sig.parameters) == ["entry", "max_chars"]
    assert sig.parameters["max_chars"].default == 200_000


# --- Headless-инвариант: mdrender.py без PySide6, без фильтров (§3/§4, раздел 5 п. 6) ---
def test_mdrender_source_has_no_pyside6_or_bleach():
    source = MDRENDER_SOURCE.read_text(encoding="utf-8")
    assert "PySide6" not in source
    assert "bleach" not in source


def test_stylesheet_has_required_pre_rule():
    # MUST DO 4: перенос длинных строк в код-блоках
    assert "pre { background-color: #f5f5f5; white-space: pre-wrap; }" in STYLESHEET
