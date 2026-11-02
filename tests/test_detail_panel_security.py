# tests/test_detail_panel_security.py — security-доработка задачи 09 (allowlist схем)
"""Анти-тесты Security-ревью (HIGH): anchorClicked открывает ТОЛЬКО http/https
и только после Yes; file:/qrc:/кастомные/безсхемные URL НЕ доходят до
QDesktopServices.openUrl.

Диалоги QMessageBox и QDesktopServices.openUrl монкипатчатся — реальных окон,
блокировок и переходов нет; QT_QPA_PLATFORM=offscreen ставится до импорта PySide6.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")  # до импорта PySide6

import pytest

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QApplication, QMessageBox

from dashboard.models import ProjectEntry
from dashboard.qt.detail_panel import DetailPanel, _format_mtime


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def panel(qapp):
    return DetailPanel(max_render_chars=1000)


@pytest.fixture()
def open_spy(monkeypatch):
    """QDesktopServices.openUrl заменён на рекордер; реальных переходов нет."""
    calls: list[QUrl] = []
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda url: calls.append(url))
    return calls


@pytest.fixture()
def info_spy(monkeypatch):
    """QMessageBox.information (сообщение об отказе) заменён на рекордер."""
    calls: list[tuple] = []
    monkeypatch.setattr(QMessageBox, "information", lambda *args: calls.append(args))
    return calls


@pytest.fixture()
def answer_yes(monkeypatch):
    monkeypatch.setattr(
        QMessageBox, "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes)


def _click(panel: DetailPanel, url_string: str) -> None:
    """Клик по ссылке: anchorClicked эмитится QTextBrowser'ом и в рантайме."""
    panel._browser.anchorClicked.emit(QUrl(url_string))


@pytest.mark.parametrize("url_string", [
    "file:///etc/passwd",
    "file://localhost/etc/passwd",
    "qrc:///icons/logo.svg",
    "javascript:alert(1)",
    "ftp://example.com/pub",
    "www.example.com/page",        # без схемы
    "myapp:opaque-data",           # кастомная схема
])
def test_non_http_urls_never_reach_openurl(panel, open_spy, info_spy, url_string):
    """Анти-тест (HIGH): недоверенная схема — отказ БЕЗ вызова openUrl."""
    _click(panel, url_string)
    assert open_spy == []
    assert len(info_spy) == 1  # показано пояснительное сообщение об отказе
    assert "не открываются" in info_spy[0][2]


def test_http_url_opens_after_yes(panel, open_spy, answer_yes, info_spy):
    _click(panel, "http://example.com/")
    assert [u.toString() for u in open_spy] == ["http://example.com/"]
    assert info_spy == []


def test_https_url_opens_after_yes(panel, open_spy, answer_yes):
    _click(panel, "https://example.com/page?a=1")
    assert [u.toString() for u in open_spy] == ["https://example.com/page?a=1"]


def test_scheme_case_does_not_bypass_allowlist(panel, open_spy, answer_yes, info_spy):
    _click(panel, "FILE:///etc/passwd")
    assert open_spy == []
    assert len(info_spy) == 1


def test_no_answer_does_not_open(panel, open_spy, monkeypatch):
    monkeypatch.setattr(
        QMessageBox, "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.No)
    _click(panel, "https://example.com/")
    assert open_spy == []


def test_confirm_dialog_shows_full_url(panel, open_spy, monkeypatch):
    """Подтверждение для разрешённых http/https явно показывает URL."""
    seen: list[str] = []

    def fake_question(parent, title, text, *args, **kwargs):
        seen.append(text)
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(QMessageBox, "question", fake_question)
    _click(panel, "https://example.com/pa th?q=1")
    assert len(seen) == 1
    assert "https://example.com/pa th?q=1" in seen[0]


def test_show_entry_with_extreme_mtime_does_not_raise(qapp):
    """Недоверенный mtime из данных не роняет показ записи (панель целиком)."""
    panel = DetailPanel(max_render_chars=1000)
    entry = ProjectEntry(name="p", path="/tmp/p", rel_path="p",
                         mtime=1e18, readme_content="")
    panel.show_entry(entry)  # не бросает
    assert "—" in panel._mtime_label.text()


def test_format_mtime_extreme_and_nan_return_fallback():
    assert _format_mtime(1e18) == "—"
    assert _format_mtime(float("nan")) == "—"
    assert _format_mtime(0) == "—"
