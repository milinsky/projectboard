#!/bin/bash
# scripts/update_translations.sh — регенерация translations/*.ts и *.qm (эпик i18n, задача 06).
# Запуск: ./scripts/update_translations.sh — из корня проекта, БЕЗ аргументов.
# Рассчитан на запуск ПОСЛЕ заполнения переводов: первичная генерация .ts — прямым lupdate.
# Гейт полноты: незаполненные (type="unfinished") — список в stderr и exit 1, без lrelease.
set -euo pipefail
if [ "$#" -ne 0 ]; then
  echo "Ошибка: скрипт не принимает аргументы. Запуск: ./scripts/update_translations.sh" >&2
  exit 1
fi
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
# -extensions py: дефолтный список lupdate (java,ui,cpp,...,qml) НЕ содержит py —
# без него скан каталога молча находит 0 строк (явные .py не страдают).
# -source-language ru: без флага lupdate пишет source-language "POSIX"/опускает
# атрибут; формат каталога требует source-language="ru" (архитектура п. 8).
.venv/bin/pyside6-lupdate -extensions py -source-language ru -recursive dashboard main.py \
  -ts translations/app_en.ts translations/app_zh_CN.ts
UNFINISHED=$(grep -c 'type="unfinished"' translations/app_en.ts || true)
UNFINISHED_ZH=$(grep -c 'type="unfinished"' translations/app_zh_CN.ts || true)
if [ "$UNFINISHED" -ne 0 ] || [ "$UNFINISHED_ZH" -ne 0 ]; then
  echo "Ошибка: есть незаполненные переводы (en: $UNFINISHED, zh: $UNFINISHED_ZH):" >&2
  grep -n 'type="unfinished"' translations/*.ts >&2 || true
  exit 1
fi
.venv/bin/pyside6-lrelease translations/app_en.ts -qm translations/app_en.qm
.venv/bin/pyside6-lrelease translations/app_zh_CN.ts -qm translations/app_zh_CN.qm
echo "Переводы обновлены: en и zh_CN скомпилированы без незаполненных строк."
