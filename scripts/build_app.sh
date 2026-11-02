#!/bin/bash
# Сборка и установка Projectboard.app (эпик app-naming, задача 02).
# Запуск: ./scripts/build_app.sh — из корня проекта, БЕЗ аргументов.
# Идемпотентная «полная пересборка поверх»: staging в mktemp -> rm -rf + cp -R
# в /Applications. Бандл — тонкая обёртка: код и venv остаются в проекте;
# внутрь бандла при сборке кладётся единственная копия Mach-O фронт-энда
# интерпретатора (python3.14) — решение Техлида по эскалации, утверждено
# пользователем 2026-11-02 (иначе LaunchServices показывает «Python» в меню).
# Скрипт не принимает аргументы, не выходит в сеть и не повышает привилегии;
# rm -rf выполняется только по двум фиксированным путям: "$STAGING" и
# /Applications/Projectboard.app.
set -euo pipefail

if [ "$#" -ne 0 ]; then
  echo "Ошибка: скрипт не принимает аргументы. Запуск: ./scripts/build_app.sh" >&2
  exit 1
fi

# 2: корень проекта от местоположения скрипта (абсолютный путь).
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

# Security-ревью (LOW) + Code-ревью (MINOR): путь проекта интерполируется в
# heredoc лаунчера и pgrep-паттерн; спецсимволы shell ИЛИ ERE в имени каталога
# ломают quoting/паттерн (fail-open гейта) — отказ сборки (fail-closed).
case "$ROOT" in
  *[\"\$\`\(\)\[\]\{\}\*\+\?\|\\]*)
    echo "Ошибка: путь проекта содержит спецсимволы shell/ERE: $ROOT" >&2
    exit 1
    ;;
esac

# 3: предусловия -x python / -f main.py, иначе сообщение + exit 1.
if [ ! -x "$ROOT/.venv/bin/python" ]; then
  echo "Ошибка: не найден интерпретатор \"$ROOT/.venv/bin/python\"." >&2
  echo "Создайте venv проекта (см. README, раздел «Установка») и повторите сборку." >&2
  exit 1
fi
if [ ! -f "$ROOT/main.py" ]; then
  echo "Ошибка: не найден \"$ROOT/main.py\"." >&2
  exit 1
fi
if [ ! -f "$ROOT/translations/app_en.qm" ]; then
  echo "Ошибка: не найден \"$ROOT/translations/app_en.qm\" — переводы не собраны (scripts/update_translations.sh)." >&2
  exit 1
fi
if [ ! -f "$ROOT/translations/app_zh_CN.qm" ]; then
  echo "Ошибка: не найден \"$ROOT/translations/app_zh_CN.qm\" — переводы не собраны (scripts/update_translations.sh)." >&2
  exit 1
fi

# 4: staging вне репозитория, удаляется при любом исходе (EXIT).
STAGING="$(mktemp -d)"
trap 'rm -rf "$STAGING"' EXIT

# 5: структура бандла в staging (два явных mkdir -p: кавычки подавляют
# brace-expansion, скобочная форма одной строкой создала бы каталог-литерал).
mkdir -p "$STAGING/Projectboard.app/Contents/MacOS"
mkdir -p "$STAGING/Projectboard.app/Contents/Resources"

# 5a: копия фронт-энда интерпретатора (GUI-стаб LS) в бандл — решение Техлида
# по эскалации «меню/Dock = Python», утверждено пользователем 2026-11-02
# (venv/код/данные НЕ копируются, одна копия Mach-O). Фронт-энд определяется
# детерминистично: sys.base_prefix + Resources/Python.app/Contents/MacOS/Python —
# это бинарник, который фактически исполняется в момент регистрации
# LaunchServices. Замена предписанного ps-трюка обоснована прогонами
# 2026-11-02: ps-снимок сразу после fork даёт venv-путь (CLI-бинарник), его
# копия при старте GUI перезапускается в стаб фреймворка -> атрибуция снова
# org.python.python («Python» в меню); копия СТАБА остаётся исполняться из
# бандла -> атрибуция com.milinsky.projectboard (lsappinfo-доказательства
# в отчёте задачи 02).
PY_FRONTEND="$("$ROOT/.venv/bin/python" -c 'import sys; print(sys.base_prefix + "/Resources/Python.app/Contents/MacOS/Python")')"
if [ -z "$PY_FRONTEND" ] || [ ! -x "$PY_FRONTEND" ]; then
  echo "Ошибка: фронт-энд интерпретатора не найден (ожидался: \"$PY_FRONTEND\")." >&2
  exit 1
fi
cp "$PY_FRONTEND" "$STAGING/Projectboard.app/Contents/MacOS/python3.14"

# 5b: fail-fast — скопированный бинарник обязан импортировать PySide6 из
# site-packages venv, иначе сборка падает здесь, а не молча ломает запуск.
if ! PYTHONPATH="$ROOT/.venv/lib/python3.14/site-packages" "$STAGING/Projectboard.app/Contents/MacOS/python3.14" -c "import PySide6"; then
  echo "Ошибка: бинарник в бандле не импортирует PySide6 (диагностика выше)." >&2
  exit 1
fi

# 6: иконка — генератор задачи 01 (offscreen), затем iconutil и явная
# проверка «существует и не пуст» (set -e сам по себе недостаточен).
QT_QPA_PLATFORM=offscreen "$ROOT/.venv/bin/python" "$ROOT/scripts/make_icon.py" "$STAGING/AppIcon.iconset"
/usr/bin/iconutil -c icns -o "$STAGING/Projectboard.app/Contents/Resources/AppIcon.icns" "$STAGING/AppIcon.iconset"
if [ ! -s "$STAGING/Projectboard.app/Contents/Resources/AppIcon.icns" ]; then
  echo "Ошибка: iconutil не создал непустой AppIcon.icns." >&2
  exit 1
fi

# 7: Info.plist — ключи и значения строго по таблице задачи (архитектура, п. 4.2).
cat > "$STAGING/Projectboard.app/Contents/Info.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>CFBundleName</key><string>Projectboard</string>
	<key>CFBundleDisplayName</key><string>Projectboard</string>
	<key>CFBundleExecutable</key><string>Projectboard</string>
	<key>CFBundleIdentifier</key><string>com.milinsky.projectboard</string>
	<key>CFBundlePackageType</key><string>APPL</string>
	<key>CFBundleIconFile</key><string>AppIcon</string>
	<key>CFBundleInfoDictionaryVersion</key><string>6.0</string>
	<key>CFBundleShortVersionString</key><string>1.0.0</string>
	<key>CFBundleVersion</key><string>1</string>
	<key>NSHighResolutionCapable</key><true/>
	<key>LSMinimumSystemVersion</key><string>12.0</string>
	<key>LSApplicationCategoryType</key><string>public.app-category.developer-tools</string>
	<key>CFBundleAllowMixedLocalizations</key><true/>
</dict>
</plist>
EOF

# 9: лаунчер — целевая форма архитектуры (п. 4.3, ред. Техлида по эскалации):
# exec в бинарник-копию ВНУТРИ бандла (атрибуция LaunchServices = Projectboard.app),
# site-packages venv через PYTHONPATH. $ROOT подставляется при сборке;
# \$SELF_DIR/\$PY/\$SP/\$MAIN экранированы и остаются переменными лаунчера;
# \" и \n сохраняются буквально — osascript трактует \n как перевод строки.
cat > "$STAGING/Projectboard.app/Contents/MacOS/Projectboard" <<EOF
#!/bin/bash
SELF_DIR="\$(cd "\$(dirname "\$0")" && pwd)"
PY="\$SELF_DIR/python3.14"
SP="$ROOT/.venv/lib/python3.14/site-packages"
MAIN="$ROOT/main.py"
if [ ! -x "\$PY" ] || [ ! -f "\$MAIN" ] || [ ! -d "\$SP" ]; then
  /usr/bin/osascript -e "display dialog \"Projectboard: не найден файл запуска.\nПохоже, папка проекта перемещена.\nОткройте терминал в папке проекта и выполните: scripts/build_app.sh\" with title \"Projectboard\" buttons {\"OK\"} with icon caution"
  exit 1
fi
export PYTHONPATH="\$SP"
exec "\$PY" "\$MAIN"
EOF
chmod +x "$STAGING/Projectboard.app/Contents/MacOS/Projectboard"

# 10: валидность plist — системный линтер.
/usr/bin/plutil -lint "$STAGING/Projectboard.app/Contents/Info.plist"

# 11: НЕ rm под работающим приложением — гейт перед установкой.
# Лаунчер делает `exec "$PY" "$MAIN"`: после exec в argv живого процесса
# пути внутрь бандла не остаются, поэтому проверяются ОБЕ сигнатуры —
# сам лаунчер (ветка osascript-диалога) и исполняемый процесс.
# Code-ревью (MINOR): вторая сигнатура сужена до «python* <абсолютный
# main.py>$» — якорь отсекает ложные срабатывания (редактор/cat/less с
# открытым main.py), а guard спецсимволов ERE выше исключает fail-open
# (некомпилируемый паттерн pgrep выходил бы кодом 2 = «не запущено»).
if /usr/bin/pgrep -f "Projectboard.app/Contents/MacOS/Projectboard" >/dev/null \
   || /usr/bin/pgrep -f "python[^ ]* $ROOT/main.py\$" >/dev/null; then
  echo "Ошибка: приложение Projectboard сейчас запущено." >&2
  echo "Закройте приложение Projectboard и перезапустите сборку." >&2
  exit 1
fi

# 12: установка полной заменой; при ошибке копирования — откат частичной
# копии (тот же фиксированный путь), диагностика cp выводится выше.
rm -rf /Applications/Projectboard.app
if ! cp -R "$STAGING/Projectboard.app" /Applications/; then
  rm -rf /Applications/Projectboard.app
  echo "Ошибка: копирование бандла в /Applications не удалось (диагностика cp выше)." >&2
  echo "Скрипт не повышает привилегии; проверьте права записи в /Applications и повторите запуск." >&2
  exit 1
fi

# 13: финальная самопроверка установки.
if [ ! -d /Applications/Projectboard.app ]; then
  echo "Ошибка: /Applications/Projectboard.app отсутствует после установки." >&2
  exit 1
fi
echo "Projectboard.app установлен в /Applications."
echo "Запуск: откройте Projectboard.app в Finder или выполните: open /Applications/Projectboard.app"
