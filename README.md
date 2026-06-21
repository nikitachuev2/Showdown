# Showdown App

Desktop-приложение для Windows для проведения турниров по шоудауну и фиксации результатов матчей. Интерфейс рассчитан на работу с клавиатуры и screen reader.

## Возможности

- Создание турниров, игроков, матчей, столов и туров.
- Ведение счета матча: сеты, подача, тайм-ауты, предупреждения, штрафы и технические поражения.
- Форматы турнира: группы + плей-офф, круговая система, двойная круговая, олимпийская система, швейцарская система.
- Генерация текстовых отчетов по турниру.
- Portable-сборка: данные создаются рядом с `.exe`.

## Быстрый Запуск

Готовые Windows-сборки лежат в `release/`:

- `showdown-latest.exe` - последняя сборка.
- `showdown-previous.exe` - предыдущая сборка.

При запуске `.exe` приложение само создает рядом папки `data/` и `reports/`, а также файл `error.log` при необходимости.

## Запуск Из Исходников

Требования:

- Windows.
- Python 3.13 или совместимая версия Python 3.
- Зависимости из `requirements.txt`.

```bat
py -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
python -m showdown_app.main
```

Точка входа приложения: `showdown_app/main.py`.

## Тесты

```bat
python -m pytest
```

## Сборка

```bat
build.bat
```

Скрипт устанавливает зависимости, запускает тесты, собирает PyInstaller-версии и копирует one-file сборку в `release\showdown-latest.exe`.

## Структура

- `showdown_app/` - исходный код приложения.
- `showdown_app/domain/` - модели и правила подсчета матча.
- `showdown_app/application/` - сервисы турниров, матчей и отчетов.
- `showdown_app/infrastructure/` - SQLite и техническая инфраструктура.
- `showdown_app/ui/` - wxPython-интерфейс.
- `tests/` - автотесты.
- `docs/` - регламент, техническое задание и заметки.
- `release/` - две последние `.exe` сборки.

## Runtime-Файлы

Эти файлы не хранятся в git и создаются приложением автоматически:

- `data/tournaments.db`
- `data/settings.json`
- `reports/`
- `error.log`
