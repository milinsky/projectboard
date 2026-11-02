# tests/test_zcode_opener.py — OpenResult / zcode_app_exists / open_in_zcode (monkeypatch, без реального subprocess)
import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest

from dashboard.zcode_opener import OpenResult, open_in_zcode, zcode_app_exists

ZCODE_OPENER_SOURCE = Path(__file__).resolve().parent.parent / "dashboard" / "zcode_opener.py"

SPECIAL_PATH = "/tmp/my projects/a b$c/"


def fake_run(returncode=0, stdout="", stderr=""):
    """Fake subprocess.run, возвращающий готовый CompletedProcess."""
    def _run(cmd, **kwargs):
        return subprocess.CompletedProcess(args=cmd, returncode=returncode,
                                           stdout=stdout, stderr=stderr)
    return _run


def test_success_returns_ok(monkeypatch, tmp_path):
    monkeypatch.setattr(subprocess, "run", fake_run(returncode=0))
    result = open_in_zcode(str(tmp_path))
    assert result == OpenResult(ok=True, error_message=None)


def test_nonzero_with_stderr(monkeypatch, tmp_path):
    monkeypatch.setattr(
        subprocess, "run",
        lambda cmd, **kw: subprocess.CompletedProcess(
            args=[], returncode=1, stdout="",
            stderr="unable to find application named 'ZCode'"))
    result = open_in_zcode(str(tmp_path))
    assert result.ok is False
    assert "unable to find application named 'ZCode'" in result.error_message


def test_nonzero_without_output_falls_back_to_returncode(monkeypatch, tmp_path):
    monkeypatch.setattr(
        subprocess, "run",
        lambda cmd, **kw: subprocess.CompletedProcess(
            args=[], returncode=2, stdout="", stderr=""))
    result = open_in_zcode(str(tmp_path))
    assert result.ok is False
    assert result.error_message == "open вернул код 2"


def test_stdout_used_when_stderr_empty(monkeypatch, tmp_path):
    monkeypatch.setattr(
        subprocess, "run",
        lambda cmd, **kw: subprocess.CompletedProcess(
            args=[], returncode=3, stdout="что-то в stdout", stderr=""))
    result = open_in_zcode(str(tmp_path))
    assert result.ok is False
    assert result.error_message == "что-то в stdout"


def test_timeout(monkeypatch, tmp_path):
    def raise_timeout(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=10)

    monkeypatch.setattr(subprocess, "run", raise_timeout)
    result = open_in_zcode(str(tmp_path))
    assert result.ok is False
    assert result.error_message == "превышено время ожидания (10 с)"


def test_open_utility_missing(monkeypatch, tmp_path):
    def raise_not_found(cmd, **kwargs):
        raise FileNotFoundError(2, "No such file or directory", "open")

    monkeypatch.setattr(subprocess, "run", raise_not_found)
    result = open_in_zcode(str(tmp_path))
    assert result.ok is False
    assert result.error_message == "утилита open не найдена"


def test_missing_dir_no_subprocess_call(monkeypatch):
    mock_run = Mock()
    monkeypatch.setattr(subprocess, "run", mock_run)
    result = open_in_zcode("/tmp/definitely-missing-dir-xyz")
    assert result.ok is False
    assert result.error_message == "каталог не найден: /tmp/definitely-missing-dir-xyz"
    mock_run.assert_not_called()


def test_relative_path_refused_without_subprocess(monkeypatch):
    """Анти-тест (Security-ревью, INFO): относительный путь — отказ до запуска open."""
    mock_run = Mock()
    monkeypatch.setattr(subprocess, "run", mock_run)
    result = open_in_zcode("relative/dir")
    assert result.ok is False
    assert result.error_message == "ожидается абсолютный путь: relative/dir"
    mock_run.assert_not_called()


def test_argv_injection_style_path_refused(monkeypatch):
    """Анти-тест (Security-ревью, INFO): "-a ДругоеПриложение" — это относительный путь."""
    mock_run = Mock()
    monkeypatch.setattr(subprocess, "run", mock_run)
    result = open_in_zcode("-a Calculator")
    assert result.ok is False
    mock_run.assert_not_called()


def test_special_chars_path_is_single_argument(monkeypatch):
    """Инъекция невозможна по построению: путь с пробелами/$ — ровно один элемент списка."""
    monkeypatch.setattr(Path, "is_dir", lambda self: True)  # спецкаталог не создаём на диске
    mock_run = Mock(return_value=subprocess.CompletedProcess(
        args=[], returncode=0, stdout="", stderr=""))
    monkeypatch.setattr(subprocess, "run", mock_run)
    result = open_in_zcode(SPECIAL_PATH)
    assert result.ok is True
    cmd = mock_run.call_args[0][0]
    assert cmd == ["open", "-a", "ZCode", SPECIAL_PATH]
    assert len(cmd) == 4
    assert cmd[-1] == SPECIAL_PATH


@pytest.mark.skipif(not Path("/Applications/ZCode.app").exists(),
                    reason="ZCode.app отсутствует на этой машине")
def test_zcode_app_exists_on_this_machine():
    assert zcode_app_exists() is True


def test_zcode_app_exists_false_when_missing(monkeypatch):
    monkeypatch.setattr(Path, "exists", lambda self: False)
    assert zcode_app_exists() is False


def test_no_shell_in_source():
    """Анти-тест (security): source не содержит shell=True ни в одной записи."""
    source = ZCODE_OPENER_SOURCE.read_text(encoding="utf-8")
    assert "shell=True" not in source
    assert "shell = True" not in source
