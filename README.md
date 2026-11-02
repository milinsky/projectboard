# Projects Dashboard

Десктоп-дашборд локальных проектов (macOS, Python 3.14 + PySide6): сканирует каталог
с проектами (по умолчанию ~/Projects), находит папки с собственным README.md
(«верхний README побеждает»), показывает мастер-детейл: таблица с поиском слева,
отрендеренный README справа, кнопка «Открыть в ZCode».

## Требования
- macOS, Python 3.14 (`python3.14`)

## Установка
    python3.14 -m venv .venv
    .venv/bin/pip install -r requirements.txt

## Запуск
    .venv/bin/python main.py

## Тесты
    .venv/bin/pip install -r requirements-dev.txt
    .venv/bin/python -m pytest tests/ -q

## Настройка
Корень сканирования меняется в окне приложения (поле корня + «Обзор…»);
индексация — только по кнопке «Индексировать». Данные приложения: data/
(config.json — настройки, index.json — кэш индекса).
