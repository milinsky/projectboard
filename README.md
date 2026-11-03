# Projectboard

**English** | [Русский](README.ru.md) | [简体中文](README.zh-CN.md)

A macOS desktop dashboard for local projects (Python 3.14 + PySide6): it scans a
projects root (default: `~/Projects`), finds folders that contain their own
`README.md` (the topmost README wins), and shows a master–detail view — a
searchable table on the left, the rendered README on the right, plus an
**Open in ZCode** button.

## Features

- Scans a configurable projects root (default: `~/Projects`, max depth 8)
- A project is a folder with its own `README.md` — the topmost README wins
- Master–detail UI: searchable project table + rendered README preview
- **Open in ZCode** button for the selected project
- On-demand indexing (button) with a JSON index cache — no scanning at startup
- UI in Russian, English, and Simplified Chinese
- Installs as a macOS app bundle: **Projectboard.app**

## Requirements

- macOS, Python 3.14 (`python3.14`)

## Installation

```bash
python3.14 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## Running

Two ways.

Development — from the project root:

```bash
.venv/bin/python main.py
```

Everyday — the Projectboard.app application from /Applications (double-click).
On first launch you may need right-click → “Open”
(see [First launch of the unsigned app](#first-launch-of-the-unsigned-app)).

## Building and installing the app (Projectboard.app)

The script builds Projectboard.app and installs it into /Applications. Run it
from the project root, without arguments. Precondition: the app is closed.
Re-running fully rebuilds and updates the installed app.

```bash
./scripts/build_app.sh
```

## First launch of the unsigned app

The bundle is not signed (signing and notarization are out of scope for this
project). A locally built bundle usually gets no quarantine attribute and opens
with a plain double-click. If Projectboard.app does not start on double-click
(for example, the repository was downloaded or moved and macOS quarantined the
bundle) — first launch: right-click Projectboard.app → “Open”.

## Updating the app

After updating the code, rebuild and reinstall the app:

```bash
git pull
./scripts/build_app.sh
```

If the project folder has been moved or renamed, the launcher (absolute paths)
will no longer find the project files and the app won't start. Fix: open a
terminal in the project folder and run `scripts/build_app.sh` — the bundle will
be rebuilt with up-to-date paths.

## Tests

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest tests/ -q
```

## Configuration

The scan root is changed in the app window (root field + “Browse…”); indexing
runs only via the “Index” button. App data lives in `data/` (`config.json` —
settings, `index.json` — index cache).

## UI language

The **Language** menu (System / Русский / English / 简体中文) sets the interface
language; it is applied after the app restarts.

## Translations (development)

Source strings are Russian `tr()` literals. `scripts/update_translations.sh`
regenerates `translations/*.ts` / `*.qm` (pyside6-lupdate / lrelease) and fails
if any translation is unfinished. For the initial `.ts` generation, run
`lupdate` directly.

## License

Copyright © 2026 Mikhail Ilinsky.

This program is free software: you can redistribute it and/or modify it under
the terms of the GNU General Public License as published by the Free Software
Foundation, either version 3 of the License, or (at your option) any later
version (SPDX: `GPL-3.0-or-later`). See [LICENSE](LICENSE).
