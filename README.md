# Griga AGI v0.1

Новая реализация Griga AGI по архитектуре v0.1: граф знаний + распространение
активации + обучение по Хеббу + генерация через намерения и конструкции.
Без LLM в ядре.

**Статус:** M0 — каркас проекта. Ядро ещё не реализовано.

## Документы

- [`docs/VISION.md`](docs/VISION.md) — что и зачем.
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — как устроено.
- [`docs/GLOSSARY.md`](docs/GLOSSARY.md) — термины.
- [`docs/adr/`](docs/adr/README.md) — журнал архитектурных решений.

## Scope v0.1 (ADR-015)

- Один пользователь, локальный CLI.
- Только русский язык.
- PostgreSQL (строго).
- Общий граф + один личный подграф.
- Визуализатор активного графа (D3).
- Диалог и ответы на фактические вопросы из графа.
- Без веб-поиска, исполнения кода и самоизменения кода.

## Быстрый старт

```powershell
cd H:\GRISHA\griga-v01
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m griga --version
```

### PostgreSQL

```powershell
# 1. Создать базы. Если psql не в PATH — полный путь:
#    & "C:\Program Files\PostgreSQL\18\bin\psql.exe"
& "C:\Program Files\PostgreSQL\18\bin\psql.exe" -U postgres -c "CREATE DATABASE griga_v01;"
& "C:\Program Files\PostgreSQL\18\bin\psql.exe" -U postgres -c "CREATE DATABASE griga_v01_test;"

# 2. Скопировать .env.example в .env и указать свой пароль
Copy-Item .env.example .env

# 3. Создать таблицы users / nodes / edges
.\.venv\Scripts\python.exe -m scripts.init_db

# 4. Тесты (используют griga_v01_test и очищают её)
.\.venv\Scripts\python.exe -m pytest
```

Схема лежит в [`griga/storage/schema.sql`](griga/storage/schema.sql).

## Структура

```text
griga/
  config.py        загрузка config.toml (параметры D/T/eta/depth — не в коде)
  graph/           узлы, рёбра, онтология
  storage/         PostgreSQL, миграции, audit/versioning
  perception/      текст -> nodes / statements / markers
  thinking/        активация и рабочая память
  learning/        Хебб, обучение с учителем, забывание
  speech/          намерения, конструкции, генератор, мониторинг
  memory/          общий граф + личные подграфы, owner_id
  shell/           внешний safety shell (approval, audit, validator)
  interfaces/      CLI (позже — Telegram/VK/Discord/web)
docs/              спецификация и ADR
eval/              eval-наборы v0.1
scripts/           init_db и служебные скрипты
tests/             юнит- и интеграционные тесты
```

## Принципы

- Знания — только в графе. Ответы — только из графа (grounded generation).
- Параметры активации и обучения — в `config.toml`, не в коде.
- Хебб меняет только существующие рёбра; новые рёбра создаёт парсер.
- Личные данные изолированы `owner_id` на уровне запросов к БД.
- Каждое изменение графа проходит audit-log и версионирование.
