# dashboard/qt/i18n.py — определение языка и установка трансляторов (только QtCore)
"""Инфраструктура интернационализации (эпик i18n, архитектура п. 4.1).

Инварианты модуля:
- Каталоги переводов вычисляются ТОЛЬКО от ``__file__``, никогда от cwd:
  cwd различается между dev-запуском, pytest и стартом из бандла, а
  ``__file__`` абсолютен во всех трёх сценариях (лаунчер бандла стартует
  ``main.py`` абсолютным путём).
- Системный транслятор грузится строго из ``qtbase_<lang>.qm``, НЕ из
  ``qt_<lang>.qm``: файлы ``qt_<lang>.qm`` в пине PySide6 6.12 —
  метаманифесты-пустышки (~100 Б, ``QTranslator.load()`` = False),
  реальные переводы стандартных диалогов Qt — в ``qtbase_<lang>.qm``.
- ``install_translators`` возвращает список установленных трансляторов и НЕ
  хранит их в глобальном состоянии: вызывающий ОБЯЗАН удерживать ссылки
  (монтаж-владелец — ``main()`` в задаче 05), иначе сборщик мусора
  уничтожит транслятор и перевод молча исчезнет.
- Активный язык процесса (``active_language``): ``None`` ⇔
  ``install_translators`` не вызывался или был ``reset_active_language``
  (teardown тестов); меняется только рестартом приложения.
- Модуль не содержит переводимых строк и вызовов tr/translate: модульные
  константы вычисляются при импорте — до QApplication и трансляторов
  (правило ленивости, архитектура п. 4.6). Лог-сообщения — латиницей,
  чтобы будущий гейт кириллицы (задача 07) не цеплял этот модуль.
"""

import logging
from pathlib import Path

import PySide6
from PySide6.QtCore import QCoreApplication, QTranslator

SUPPORTED_LANGUAGES = ("ru", "en", "zh_CN")

# от __file__, не от cwd: корень проекта (dashboard/qt/i18n.py -> parents[2])
_APP_TRANSLATIONS_DIR = Path(__file__).resolve().parents[2] / "translations"
# от __file__, не от cwd: каталог системных переводов PySide6 внутри venv
_QT_TRANSLATIONS_DIR = Path(PySide6.__file__).parent / "Qt" / "translations"

_active_language: str | None = None


def resolve_language(setting: str, system_ui_languages: list[str]) -> str:
    """Язык процесса из настройки конфига.

    ``ru``/``en``/``zh_CN`` -> как задано; ``system``/мусор -> первый
    поддержанный из ``system_ui_languages`` по primary-субтегу до ``-``
    без учёта регистра (``zh-Hans-CN`` -> ``zh`` -> ``zh_CN``), иначе
    фолбэк ``ru`` (бриф §10 п. 1). Чистая функция БЕЗ Qt-вызовов: список
    локалей передаётся параметром, поэтому юнит-тесты не зависят ни от
    QLocale, ни от локали машины (offscreen даёт ``['C']``).
    """
    if setting in SUPPORTED_LANGUAGES:
        return setting
    for tag in system_ui_languages:
        primary = tag.split("-")[0].lower()
        if primary == "ru":
            return "ru"
        if primary == "en":
            return "en"
        if primary == "zh":
            return "zh_CN"
    return "ru"


def install_translators(app: QCoreApplication, language: str) -> list[QTranslator]:
    """Установка трансляторов на ``app`` (язык после resolve_language).

    ``ru`` — source-язык: ничего не грузим, но активный язык фиксируется.
    Иначе — два транслятора: 1) ``qtbase_<lang>.qm`` из PySide6 (строго
    qtbase, см. инвариант модуля), 2) ``app_<lang>.qm`` из ``translations/``
    проекта вторым — последний установленный ищется первым, поэтому наши
    строки приоритетнее системных. Отсутствие/битый ``app_<lang>.qm`` —
    logging.warning, не крах (симметрично политике «битый config не валит
    приложение»), но деградация ЧАСТИЧНАЯ и несогласованная: обычные строки
    остаются русскими source, а plural-формы ``tr_count`` при активном
    не-ru языке уходят в Qt-numerus БЕЗ перевода — Qt возвращает
    singular-source на любой n («2 проект» вместо «2 проекта»/«2 projects»),
    а не русскую plural-форму. Контракт ``active_language`` не меняется;
    фактическое поведение зафиксировано поведенческим тестом (test_i18n.py).

    Возвращает список установленных трансляторов: ВЫЗЫВАЮЩИЙ ОБЯЗАН
    удерживать ссылки весь жизненный цикл приложения (см. инвариант
    модуля про GC).
    """
    installed: list[QTranslator] = []
    if language == "ru":
        _set_active(language)
        return installed
    qt_translator = QTranslator(app)
    qt_path = _QT_TRANSLATIONS_DIR / f"qtbase_{language}.qm"
    if qt_translator.load(str(qt_path)):
        app.installTranslator(qt_translator)
        installed.append(qt_translator)
    else:
        logging.warning(
            "i18n: qtbase_%s.qm failed to load from %s", language, qt_path,
        )
    app_translator = QTranslator(app)
    app_path = _APP_TRANSLATIONS_DIR / f"app_{language}.qm"
    if app_translator.load(str(app_path)):
        app.installTranslator(app_translator)
        installed.append(app_translator)
    else:
        # не крах, но деградация частичная: обычные строки остаются русскими
        # source, а plural-формы tr_count при активном не-ru языке уходят в
        # Qt-numerus без перевода (singular-source на любой n) — см. докстринг.
        logging.warning(
            "i18n: app_%s.qm failed to load from %s; source strings fall back to "
            "Russian, but plural forms (tr_count) degrade to untranslated Qt "
            "numerus (singular source for any n)", language, app_path,
        )
    _set_active(language)
    return installed


def active_language() -> str | None:
    """Активный язык процесса; ``None`` ⇔ трансляторы не устанавливались
    (install не вызывался или был reset_active_language)."""
    return _active_language


def reset_active_language() -> None:
    """Сброс активного языка — только для teardown тестов."""
    _set_active(None)


def _set_active(language: str | None) -> None:
    global _active_language
    _active_language = language
