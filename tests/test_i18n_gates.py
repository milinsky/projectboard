# tests/test_i18n_gates.py — постоянные приёмочные гейты эпика i18n (задача 07)
"""Четыре гейта-инварианта эпика i18n (жанр анти-тестов, conventions п. 7):
(а) в dashboard/qt/*.py и main.py нет голых кириллических литералов вне
tr()/translate()/tr_count() — allowlist ровно {"Projectboard", "Русский"};
(б) translations/app_*.ts полны: нет type="unfinished", у numerus-сообщений
непустые numerusform-формы, каждый translation непуст;
(в) закоммиченные .qm побайтово совпадают с lrelease(.ts) — lrelease
детерминирован (архитектура п. 3.4.5), сравнение строго shallow=False;
(г) в tr_count-call sites литерал в lambda-обёртке синхронен one-аргументу
(инвариант дубля литерала, Code-ревью MINOR-1).

Гейт (а) не проверяет комментарии и докстринги: весь проект документирован
по-русски, они кириллицу содержать МОГУТ (архитектура п. 13а) — детектор
парсит ast, комментарии до него не доходят, докстринги исключаются явно.
Мутационные тесты обязательны: гейт, который не падает на нарушении,
не гейт (QA TC-011). Тесты не требуют Qt: ast/xml/subprocess/filecmp —
stdlib; записи только в tmp_path. Бинарник lrelease — строго .venv/bin
(не PATH); при его отсутствии гейт (в) пропускается (skipif).
"""

import ast
import filecmp
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
ALLOWLIST = {"Projectboard", "Русский"}          # расширение запрещено (решение техлида)
GATED_FILES = sorted((ROOT / "dashboard" / "qt").glob("*.py")) + [ROOT / "main.py"]
TRANSLATIONS_DIR = ROOT / "translations"
LRELEASE = ROOT / ".venv" / "bin" / "pyside6-lrelease"
TR_CALL_NAMES = {"tr", "translate", "tr_count"}


def _has_cyrillic(text: str) -> bool:
    return any("\u0400" <= ch <= "\u04FF" for ch in text)


def _call_name(call: ast.Call) -> str | None:
    """Имя вызова без разбора объекта: tr(...) -> tr; X.tr(...) -> tr; иное -> None."""
    if isinstance(call.func, ast.Name):
        return call.func.id
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    return None


def _docstring_node_ids(tree: ast.AST) -> set[int]:
    """id Constant-узлов-докстрингов (первый Expr-стейтмент скоупа): их не проверяем."""
    docstrings: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            first = node.body[0] if node.body else None
            if (isinstance(first, ast.Expr)
                    and isinstance(first.value, ast.Constant)
                    and isinstance(first.value.value, str)):
                docstrings.add(id(first.value))
    return docstrings


def find_cyrillic_violations(source: str, filename: str = "<src>") -> list[str]:
    """Чистый детектор: кириллица в литерале допустима только как аргумент
    tr/translate/tr_count или литерал из allowlist. Комментарии/докстринги не проверяются."""
    violations: list[str] = []
    tree = ast.parse(source)
    docstrings = _docstring_node_ids(tree)
    parents: dict[int, ast.AST] = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parents[id(child)] = parent
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
            continue
        if not _has_cyrillic(node.value):
            continue                      # кириллицы нет
        if node.value in ALLOWLIST:
            continue
        if id(node) in docstrings:
            continue                      # докстринги не проверяются (архитектура п. 13а)
        parent = parents.get(id(node))
        if (isinstance(parent, ast.Call)
                and _call_name(parent) in TR_CALL_NAMES
                and any(node is arg for arg in parent.args)):
            continue                      # аргумент tr/translate/tr_count
        violations.append(
            f"{filename}:{node.lineno}: голый кириллический литерал {node.value!r}"
        )
    return violations


# --- (а) гейт кириллицы по прод-дереву ---

def test_gate_no_bare_cyrillic_literals():
    assert (ROOT / "dashboard" / "qt").is_dir() and (ROOT / "main.py").exists()
    assert len(GATED_FILES) >= 2         # гейт не должен проходить на пустом множестве файлов
    violations: list[str] = []
    for path in GATED_FILES:
        violations += find_cyrillic_violations(path.read_text(encoding="utf-8"), str(path))
    assert violations == []


# --- мутационные тесты детектора (обязательная часть жанра, QA TC-011) ---

def test_mutation_bare_cyrillic_string_is_caught():
    violations = find_cyrillic_violations('x = "привет"\n', "mut.py")
    assert len(violations) == 1
    assert "mut.py:1" in violations[0] and "привет" in violations[0]


def test_mutation_tr_wrapped_strings_are_not_caught():
    source = (
        "class A:\n"
        "    def m(self, translate):\n"
        '        a = self.tr("привет")\n'
        '        b = translate("Контекст", "привет")\n'
        '        c = tr_count(self.tr, "привет", "привета", "приветов", 2)\n'
        '        d = tr_count(lambda s, t, n: self.tr("ошибка", None, n),\n'
        '                     "ошибка", "ошибки", "ошибок", 2)\n'
        "        return a, b, c, d\n"
    )
    assert find_cyrillic_violations(source, "mut.py") == []


def test_mutation_docstring_and_comment_are_not_caught():
    source = (
        '"""Докстринг модуля: привет из документации."""\n'
        "# комментарий по-русски: привет\n"
        "def f():\n"
        '    """Докстринг функции: привет."""\n'
        "    return 1\n"
    )
    assert find_cyrillic_violations(source, "mut.py") == []


def test_mutation_allowlist_literals_are_not_caught():
    source = 'title = "Projectboard"\nlabel = "Русский"\n'
    assert find_cyrillic_violations(source, "mut.py") == []


def test_mutation_cyrillic_fragment_inside_fstring_is_caught():
    source = 'name = "x"\nlabel = f"привет {name}"\n'
    violations = find_cyrillic_violations(source, "mut.py")
    assert len(violations) == 1
    assert "mut.py:2" in violations[0] and "привет" in violations[0]


def test_gate_catches_mutation_of_main_py_copy(tmp_path):
    """Анти-тест TC-011-класса: копия main.py с голой кириллической строкой
    обязана дать нарушение — гейт падает при поломке инварианта."""
    mutated = tmp_path / "main.py"
    mutated.write_text(
        (ROOT / "main.py").read_text(encoding="utf-8") + '\nx = "привет"\n',
        encoding="utf-8",
    )
    violations = find_cyrillic_violations(mutated.read_text(encoding="utf-8"), str(mutated))
    assert violations, "детектор обязан поймать голую кириллическую строку в копии main.py"
    assert any("привет" in v for v in violations)


# --- (г) гейт синхронности lambda/one в tr_count (Code-ревью MINOR-1) ---

def scan_lambda_one_sync(source: str, filename: str = "<src>") -> tuple[int, list[str]]:
    """(проверено lambda-call-site'ов, рассинхроны) инварианта «литерал в
    lambda-обёртке tr_count синхронен one-аргументу». Проверяются вызовы,
    где args[0] — Lambda с телом Call на tr и строковым литералом первым
    аргументом, а args[1] — литерал; не-литеральные пары статически
    непроверяемы и нарушением не считаются."""
    checked = 0
    desyncs: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if not (isinstance(node, ast.Call) and _call_name(node) == "tr_count"):
            continue
        if len(node.args) < 2 or not isinstance(node.args[1], ast.Constant):
            continue                      # one не литерал — статически непроверяемо
        lam = node.args[0]
        if not (isinstance(lam, ast.Lambda) and isinstance(lam.body, ast.Call)):
            continue                      # без lambda-обёртки — не call-site инварианта
        body = lam.body
        first = body.args[0] if body.args else None
        if _call_name(body) != "tr" or not (
            isinstance(first, ast.Constant) and isinstance(first.value, str)
        ):
            continue
        checked += 1
        if first.value != ast.literal_eval(node.args[1]):
            desyncs.append(
                f"{filename}:{node.lineno}: lambda-литерал {first.value!r} "
                f"!= one-аргумент {node.args[1].value!r}"
            )
    return checked, desyncs


def test_gate_lambda_literal_synced_with_one_argument():
    """Call sites: main_window «проект»/«ошибка», project_model «файл»."""
    checked, desyncs = 0, []
    for path in GATED_FILES:
        n, d = scan_lambda_one_sync(path.read_text(encoding="utf-8"), str(path))
        checked += n
        desyncs += d
    assert checked >= 1, "гейт не нашёл ни одного lambda-call-site tr_count — вырожден"
    assert desyncs == []


def test_mutation_synced_lambda_site_passes_scanner():
    source = (
        "class A:\n"
        "    def m(self, n):\n"
        '        return tr_count(lambda _s, _d, k: self.tr("файл", None, k),\n'
        '                       "файл", "файла", "файлов", n)\n'
    )
    checked, desyncs = scan_lambda_one_sync(source, "mut.py")
    assert checked == 1 and desyncs == []


def test_mutation_desynced_lambda_site_is_caught():
    source = (
        "class A:\n"
        "    def m(self, n):\n"
        '        return tr_count(lambda _s, _d, k: self.tr("проекты", None, k),\n'
        '                       "проект", "проекта", "проектов", n)\n'
    )
    checked, desyncs = scan_lambda_one_sync(source, "mut.py")
    assert checked == 1
    assert len(desyncs) == 1 and "проекты" in desyncs[0]


def test_gate_catches_desync_in_project_model_copy(tmp_path):
    """Анти-тест TC-011-класса: рассинхрон lambda/one в копии реального
    файла обязан ронять гейт (мутационная проверка MINOR-1)."""
    original = (ROOT / "dashboard" / "qt" / "project_model.py").read_text(encoding="utf-8")
    mutated = tmp_path / "project_model.py"
    mutated.write_text(
        original.replace(
            'lambda _s, _d, n: self.tr("файл", None, n)',
            'lambda _s, _d, n: self.tr("файлика", None, n)',
        ),
        encoding="utf-8",
    )
    checked, desyncs = scan_lambda_one_sync(mutated.read_text(encoding="utf-8"), str(mutated))
    assert checked == 1
    assert len(desyncs) == 1 and "файлика" in desyncs[0]


# --- (б) гейт полноты .ts ---

def test_gate_ts_complete():
    ts_files = sorted(TRANSLATIONS_DIR.glob("app_*.ts"))
    assert len(ts_files) == 2            # en и zh_CN (контракт задачи 06)
    for ts in ts_files:
        root = ET.parse(ts).getroot()
        messages = list(root.iter("message"))
        assert messages, f"{ts.name}: не найдено ни одного message — каталог пуст?"

        unfinished = [
            message for message in messages
            if message.find("translation") is not None
            and message.find("translation").get("type") == "unfinished"
        ]
        assert unfinished == [], (
            f"{ts.name}: незаполненные переводы: "
            f"{[m.find('source').text for m in unfinished]}"
        )

        for message in messages:
            source_text = message.find("source").text if message.find("source") is not None else None
            translation = message.find("translation")
            if message.get("numerus") == "yes":
                forms = translation.findall("numerusform") if translation is not None else []
                assert any((form.text or "").strip() for form in forms), (
                    f"{ts.name}: у numerus-сообщения {source_text!r} нет непустой numerusform-формы"
                )
            else:
                assert translation is not None and (translation.text or "").strip(), (
                    f"{ts.name}: пустой translation у {source_text!r}"
                )


# --- (в) гейт свежести .qm ---

@pytest.mark.skipif(not LRELEASE.exists(),
                    reason="pyside6-lrelease отсутствует в .venv/bin (среда без venv-инструментов)")
@pytest.mark.parametrize("language", ["en", "zh_CN"])
def test_gate_qm_fresh(language, tmp_path):
    ts = TRANSLATIONS_DIR / f"app_{language}.ts"
    committed_qm = TRANSLATIONS_DIR / f"app_{language}.qm"
    tmp_qm = tmp_path / f"app_{language}.qm"
    assert ts.exists() and committed_qm.exists()

    process = subprocess.run(
        [str(LRELEASE), str(ts), "-qm", str(tmp_qm)],
        capture_output=True, text=True,
    )
    assert process.returncode == 0, f"lrelease упал: {process.stderr}"

    assert filecmp.cmp(tmp_qm, committed_qm, shallow=False), (
        f"translations/app_{language}.qm не свеж относительно .ts: "
        f"перегоните ./scripts/update_translations.sh (мораторий на строки, декомпозиция риск №2)"
    )
