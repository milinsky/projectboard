# tests/test_scanner.py — кейсы (a)–(n) для dashboard/scanner.py; все деревья — tmp_path
import builtins
import os
import threading
from pathlib import Path

import pytest

import dashboard.scanner as scanner_module
from dashboard.scanner import DEFAULT_IGNORE_NAMES, ScanOptions, scan_root
from dashboard.models import ScanResult

SCANNER_SOURCE = Path(__file__).resolve().parent.parent / "dashboard" / "scanner.py"


def make_readme(dir_path: Path, name: str = "README.md", text: str = "# проект\n") -> Path:
    """Создаёт каталог с README.md; возвращает путь к README."""
    dir_path.mkdir(parents=True, exist_ok=True)
    readme = dir_path / name
    readme.write_text(text, encoding="utf-8")
    return readme


def rel_paths(result: ScanResult) -> list[str]:
    return [p.rel_path for p in result.projects]


# --- Контракт DEFAULT_IGNORE_NAMES (уточнение №2, состав для задачи 10) ---

def test_default_ignore_names_exact_contract():
    assert DEFAULT_IGNORE_NAMES == frozenset(
        {"node_modules", "vendor", "dist", "build", "target",
         "__pycache__", "venv", "site-packages"}
    )


def test_extra_ignore_names_respected(tmp_path):
    # Контракт с задачей 10: ignore_names=frozenset(DEFAULT_IGNORE_NAMES | set(extra))
    make_readme(tmp_path / "keep")
    make_readme(tmp_path / "scratch" / "x")

    result = scan_root(ScanOptions(
        root=tmp_path, ignore_names=DEFAULT_IGNORE_NAMES | {"scratch"}))

    assert rel_paths(result) == ["keep"]


# --- (a) «Верхний README побеждает»: проект внутри проекта не индексируется ---

def test_a_top_readme_wins_inner_not_indexed(tmp_path):
    outer_readme = make_readme(tmp_path / "outer")
    make_readme(tmp_path / "outer" / "inner")  # появился бы в индексе, если бы спускались внутрь

    result = scan_root(ScanOptions(root=tmp_path))

    assert rel_paths(result) == ["outer"]  # анти-тест: падает при «доспуске» внутрь outer
    entry = result.projects[0]
    assert entry.name == "outer"
    assert entry.path == str(tmp_path / "outer")
    assert entry.rel_path == "outer"
    assert entry.group == "outer"  # первый сегмент rel_path (инвариант п. 8)
    assert entry.readme_path == str(outer_readme)
    # инвариант п. 8: mtime проекта = mtime его README.md
    assert entry.mtime == pytest.approx(outer_readme.stat().st_mtime)
    assert entry.readme_error is None
    assert result.cancelled is False


# --- (b) ignore-имена и скрытые каталоги не travers'ятся ---

def test_b_ignored_and_hidden_dirs_not_traversed(tmp_path):
    make_readme(tmp_path / "real")
    for junk in ("vendor", "node_modules", "dist", "build", "target",
                 "__pycache__", "venv", "site-packages"):
        make_readme(tmp_path / junk / "x")  # нашлись бы при обходе — глубина 2
    make_readme(tmp_path / ".hidden" / "z")
    make_readme(tmp_path / ".git" / "hooks")

    result = scan_root(ScanOptions(root=tmp_path))

    assert rel_paths(result) == ["real"]
    joined = " ".join(p.path for p in result.projects)
    for junk in ("vendor", "node_modules", "site-packages", ".hidden", ".git"):
        assert junk not in joined


# --- (c) depth-cap: глубже max_depth не спускаемся ---

def test_c_depth_cap(tmp_path):
    make_readme(tmp_path / "a" / "b")        # глубина 2 == max_depth — находится
    make_readme(tmp_path / "x" / "y" / "z")  # глубина 3 > max_depth — нет

    result = scan_root(ScanOptions(root=tmp_path, max_depth=2))

    assert rel_paths(result) == ["a/b"]
    assert "x/y/z" not in rel_paths(result)


# --- (d) symlink-цикл не зацикливает; symlink-README не детектится ---

def test_d_symlink_loop_and_symlink_readme(tmp_path):
    real_readme = make_readme(tmp_path / "outer")
    os.symlink(tmp_path, tmp_path / "loop", target_is_directory=True)  # dir -> родитель
    link_proj = tmp_path / "link_proj"
    link_proj.mkdir()
    os.symlink(real_readme, link_proj / "README.md")  # README — symlink: не проект
    os.symlink(tmp_path / "outer", tmp_path / "link2", target_is_directory=True)

    result = scan_root(ScanOptions(root=tmp_path))  # завершается — не зацикливается

    names = [p.name for p in result.projects]
    assert names == ["outer"]
    # symlink-каталог не travers'ится; фантомный проект через symlink-dir не создаётся
    assert "loop" not in names
    assert "link2" not in names
    assert "link_proj" not in names


# --- (e) PermissionError на os.scandir -> errors, скан завершается ---

def test_e_permission_error_recorded_scan_completes(tmp_path, monkeypatch):
    make_readme(tmp_path / "ok")
    blocked = tmp_path / "blocked"
    make_readme(blocked / "inner")

    real_scandir = os.scandir

    def fake_scandir(path, *args, **kwargs):
        if Path(path) == blocked:
            raise PermissionError(13, "Permission denied")
        return real_scandir(path, *args, **kwargs)

    monkeypatch.setattr(os, "scandir", fake_scandir)

    # Анти-тест: без обработки PermissionError исключение вышло бы наружу и
    # тест упал бы с ошибкой; обработка обязана вернуть результат с errors.
    result = scan_root(ScanOptions(root=tmp_path))

    assert len(result.errors) == 1
    assert result.errors[0].path == str(blocked)
    assert result.errors[0].reason  # человекочитаемо и непусто
    assert rel_paths(result) == ["ok"]
    assert "blocked" not in " ".join(p.path for p in result.projects)
    assert result.cancelled is False


# --- (f) пустой README (0 байт) ---

def test_f_empty_readme_project_indexed(tmp_path):
    readme = make_readme(tmp_path / "empty", text="")

    result = scan_root(ScanOptions(root=tmp_path))

    assert len(result.projects) == 1
    entry = result.projects[0]
    assert entry.name == "empty"
    assert entry.readme_content == ""
    assert entry.readme_error is None
    assert entry.readme_truncated is False
    assert entry.readme_size_bytes == 0
    assert entry.mtime == pytest.approx(readme.stat().st_mtime)


# --- (g) нечитаемый README (OSError при чтении): проект в индексе, readme_error ---

def test_g_unreadable_readme_error_recorded_project_indexed(tmp_path, monkeypatch):
    readme = make_readme(tmp_path / "locked", text="# secret\n")
    real_open = builtins.open

    def fake_open(file, mode="r", *args, **kwargs):
        if "b" in mode and str(file) == str(readme):
            raise OSError(13, "Permission denied")
        return real_open(file, mode, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", fake_open)

    result = scan_root(ScanOptions(root=tmp_path))

    assert len(result.projects) == 1  # проект В индексе
    entry = result.projects[0]
    assert entry.readme_content == ""
    assert entry.readme_error  # заполнен человекочитаемой причиной
    assert entry.readme_size_bytes == len("# secret\n")  # stat прошёл, полный размер известен
    assert entry.readme_truncated is False


# --- (h) большой README (> лимита): усечение, флаг, полный st_size ---

def test_h_oversized_readme_truncated(tmp_path):
    make_readme(tmp_path / "big", text="A" * 100)

    result = scan_root(ScanOptions(root=tmp_path, max_readme_store_bytes=16))

    entry = result.projects[0]
    assert entry.readme_truncated is True
    assert entry.readme_content == "A" * 16
    assert len(entry.readme_content.encode("utf-8")) <= 16
    assert entry.readme_size_bytes == 100  # полный st_size, а не усечённый
    assert entry.readme_error is None


# --- (i) cancel, выставленный заранее: частичный результат + cancelled=True ---

def test_i_cancel_before_scan_partial_result(tmp_path):
    make_readme(tmp_path / "outer")
    cancel = threading.Event()
    cancel.set()
    calls: list[tuple[int, int]] = []

    result = scan_root(ScanOptions(root=tmp_path), cancel=cancel,
                       progress=lambda v, f: calls.append((v, f)))

    assert result.cancelled is True
    assert result.projects == []
    assert result.errors == []
    assert calls == [(0, 0)]  # обязательный финальный вызов даже при мгновенной отмене


def test_i2_cancel_during_measure_tree_partial_size(tmp_path, monkeypatch):
    """Code-ревью MAJOR: cancel, выставленный ВНУТРИ _measure_tree (в момент
    замера большого дерева), прерывает os.walk — скан завершается быстро с
    cancelled=True и частичным (но корректным) размером. Без фикса walk прошёл
    бы все файлы: file_count был бы полным и тест падал (анти-тест)."""
    project = tmp_path / "big"
    project.mkdir()
    (project / "README.md").write_text("# big\n", encoding="utf-8")
    total_files = 2000
    file_body = b"x" * 32
    for i in range(total_files):
        (project / f"f{i:04d}.bin").write_bytes(file_body)

    cancel = threading.Event()
    real_stat = os.stat
    calls = {"stat": 0}

    def fake_stat(path, **kwargs):
        # счётчик и отмена — только внутри замера: scan_root сам по себе
        # os.stat не вызывает (scandir/DirEntry), а DirEntry.stat не наш.
        calls["stat"] += 1
        if calls["stat"] >= 10:
            cancel.set()
        return real_stat(path, **kwargs)

    monkeypatch.setattr(scanner_module.os, "stat", fake_stat)

    result = scan_root(ScanOptions(root=tmp_path), cancel=cancel)

    assert result.cancelled is True
    assert len(result.projects) == 1
    entry = result.projects[0]
    # частичный подсчёт: не всё дерево, но и не ноль
    assert calls["stat"] == 10
    assert 0 < entry.file_count < total_files
    assert 0 < entry.dir_size_bytes < total_files * len(file_body)


# --- (j) root с собственным README.md не попадает в результаты ---

def test_j_root_readme_not_a_project(tmp_path):
    make_readme(tmp_path, text="# корень\n")
    make_readme(tmp_path / "real")

    result = scan_root(ScanOptions(root=tmp_path))

    assert rel_paths(result) == ["real"]
    assert all(p.path != str(tmp_path) for p in result.projects)
    assert all("корень" not in p.readme_content for p in result.projects)


# --- (k) сортировка по (group, name); группа проекта в корне = имя проекта ---

def test_k_sorted_by_group_and_name_root_level_group(tmp_path):
    make_readme(tmp_path / "zeta" / "alpha")
    make_readme(tmp_path / "beta" / "bbb")
    make_readme(tmp_path / "beta" / "aaa")
    make_readme(tmp_path / "solo")  # проект в корне — rel_path из одного сегмента

    result = scan_root(ScanOptions(root=tmp_path))

    observed = [(p.group, p.name) for p in result.projects]
    assert observed == [("beta", "aaa"), ("beta", "bbb"), ("solo", "solo"), ("zeta", "alpha")]
    solo = result.projects[2]
    assert solo.group == solo.name == "solo"  # не "" и не "."
    assert solo.rel_path == "solo"


# --- (l) инвариант: ни один path проектов не является префиксом другого ---

def test_l_no_project_path_is_prefix_of_another(tmp_path):
    make_readme(tmp_path / "p")          # проект p
    make_readme(tmp_path / "p" / "q")    # вложенный «проект» — не индексируется
    make_readme(tmp_path / "plain" / "sub")
    make_readme(tmp_path / "solo")

    result = scan_root(ScanOptions(root=tmp_path))
    assert len(result.projects) == 3

    paths = [Path(p.path) for p in result.projects]
    for a in paths:
        for b in paths:
            if a != b:
                assert not a.is_relative_to(b), f"{a} оказался внутри {b}"
    # то же через строковый префикс с разделителем
    for a in result.projects:
        for b in result.projects:
            if a is not b:
                assert not a.path.startswith(b.path + "/")


# --- (m) progress: колбэк вызывается, финальный вызов есть ---

def test_m_progress_final_call_contract(tmp_path):
    make_readme(tmp_path / "outer")
    make_readme(tmp_path / "plain" / "sub")
    # посещаются ровно: root, outer, plain, plain/sub
    calls: list[tuple[int, int]] = []

    result = scan_root(ScanOptions(root=tmp_path), progress=lambda v, f: calls.append((v, f)))

    assert calls, "финальный вызов progress обязателен"
    assert calls[-1] == (4, len(result.projects))
    assert calls[-1] == (4, 2)


def test_m_progress_zero_interval_emits_each_iteration(tmp_path, monkeypatch):
    make_readme(tmp_path / "outer")
    make_readme(tmp_path / "plain" / "sub")
    monkeypatch.setattr(scanner_module, "_PROGRESS_MIN_INTERVAL_SEC", 0.0)
    calls: list[tuple[int, int]] = []

    result = scan_root(ScanOptions(root=tmp_path), progress=lambda v, f: calls.append((v, f)))

    # 4 посещённых каталога -> 4 вызова в цикле + 1 финальный
    assert len(calls) == 5
    assert [c[0] for c in calls] == [1, 2, 3, 4, 4]  # visited монотонен, в конце — итог
    assert calls[-1] == (4, len(result.projects))
    assert calls[-1] == (4, 2)


# --- (n) не-UTF8 README читается с заменой, не падает ---

def test_n_non_utf8_readme_replaced_not_raising(tmp_path):
    (tmp_path / "binreadme").mkdir()
    (tmp_path / "binreadme" / "README.md").write_bytes(b"\xff\xfe# \x88")

    result = scan_root(ScanOptions(root=tmp_path))

    entry = result.projects[0]
    assert entry.readme_error is None
    assert entry.readme_content == "\ufffd\ufffd# \ufffd"
    assert entry.readme_size_bytes == 5


# --- Исключения только для плохого root (архитектура п. 4.2 п. 7) ---

def test_root_missing_raises_file_not_found(tmp_path):
    with pytest.raises(FileNotFoundError):
        scan_root(ScanOptions(root=tmp_path / "nope"))


def test_root_is_file_raises_not_a_directory(tmp_path):
    target = tmp_path / "plainfile.txt"
    target.write_text("x", encoding="utf-8")
    with pytest.raises(NotADirectoryError):
        scan_root(ScanOptions(root=target))


# --- Headless-инвариант: scanner.py без PySide6 (конвенция test_models.py) ---

def test_scanner_source_has_no_pyside6():
    assert "PySide6" not in SCANNER_SOURCE.read_text(encoding="utf-8")
