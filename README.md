# Griga AGI v0.1

Новая реализация Griga AGI по архитектуре v0.1: граф знаний + распространение
активации + обучение по Хеббу + генерация через намерения и конструкции.
Без LLM в ядре.

**Статус:** M6 — визуализатор активного графа (D3), диалог и обучение готовы.

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

### Активация (ADR-003)

```powershell
# Демо: волна от узла «Трава» по графу из PostgreSQL
.\.venv\Scripts\python.exe -m scripts.demo_spread
```

Параметры `D=0.85`, `T=0.1`, `max_depth=3`, `top_k=5` берутся из `config.toml`.
Формула передачи: `A * W * D / max(2, log(1 + степень))`, затем clamp до `1.0`.

### Восприятие (ADR-002)

```powershell
# Разбор текста: узлы, утверждения, маркеры (без записи в БД)
.\.venv\Scripts\python.exe -m scripts.demo_perception "Трава растёт на газоне."

# Разбор + запись фактов в PostgreSQL + волна активации
.\.venv\Scripts\python.exe -m scripts.demo_perception --write
```

Парсер использует локальный UDPipe (`data/models/*.udpipe`) и pymorphy2.
Модель не хранится в git: положи файл
`russian-syntagrus-ud-2.5-191206.udpipe` в `data/models/`. Если модели нет,
включается эвристический fallback на pymorphy2, и парсер продолжает работать.

### Диалог (ADR-004, ADR-009)

```powershell
# Интерактивный диалог поверх рабочей БД griga_v01
.\.venv\Scripts\python.exe -m griga chat

# Одна реплика без REPL
.\.venv\Scripts\python.exe -m griga chat --text "Что такое трава?"

# Демо-сценарий: в памяти процесса (по умолчанию) или в PostgreSQL (--db)
.\.venv\Scripts\python.exe -m scripts.demo_dialogue
.\.venv\Scripts\python.exe -m scripts.demo_dialogue --db
```

Один ход диалога:

1. `PerceptionParser` разбирает реплику на узлы, утверждения и маркеры;
2. `apply_parse` пишет в граф **только факты** — вопросы, отрицания и
   «наверное» не сохраняются;
3. `Spreader` считает рабочую память (top-K);
4. `Generator` выбирает намерение, подбирает конструкцию из
   `griga/speech/constructions.json` и проверяет ответ мониторингом
   (не более 3 попыток, затем честное «не знаю»).

Ответы строятся только из узлов и рёбер графа. Слоты конструкции
склоняются через pymorphy2; для вопросов «да/нет» есть отдельные
конструкции (`yes_*`), поэтому на «Трава зелёная?» звучит «Да, трава —
зелёная.». Банк конструкций — данные, а не код: его можно расширять без
изменения генератора.

### Обучение (ADR-005)

```powershell
# Демо: повторение факта, подтверждение/опровержение, затухание
.\.venv\Scripts\python.exe -m scripts.demo_learning
```

- **Хебб** (`griga/learning/hebb.py`): после каждого хода рёбра между
  узлами рабочей памяти усиливаются по `Δw = η × x_A × x_B` (`η=0.05`).
  Новые рёбра не создаются — только существующие.
- **Коррекция** (`griga/learning/supervised.py`): `confirm()` и `deny()`
  меняют вес ребра на `supervised_delta=0.2`; вес зажат в `[0.05, 1.0]`.
- **Забывание** (`griga/learning/forgetting.py`): раз в
  `forgetting_every_turns` ходов все веса умножаются на
  `forgetting_factor=0.99` и не опускаются ниже `min_weight`.

`Dialogue` включает обучение по умолчанию; `Dialogue(..., learning=False)`
отключает его для тестов и отладки. Журнал изменений — `dialogue.learning_log`,
а каждый ход возвращает `TurnResult.learned` и `TurnResult.forgotten`.

### Визуализатор (ADR-015 §5)

```powershell
# Граф из PostgreSQL в браузере (откроется автоматически)
.\.venv\Scripts\python.exe -m griga visualize

# Другая стартовая активация, порт и без автозапуска браузера
.\.venv\Scripts\python.exe -m griga visualize --node "трава" --port 9000 --no-browser

# Демо на данных в памяти процесса
.\.venv\Scripts\python.exe -m scripts.demo_visualize --no-browser
```

Страница на D3.js (вендорная копия в `griga/visualization/static/vendor/`)
показывает узлы, рёбра и рабочую память:

- размер и яркость узла — активация, толщина ребра — вес;
- клик по узлу или поиск запускает волну `Spreader` и подсвечивает
  активный подграф;
- «Сбросить» очищает рабочую память, «Обновить» перечитывает граф.

Сервер — только стандартная библиотека Python (`http.server`), слушает
`127.0.0.1` и не требует интернета: D3 лежит локально.

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
  visualization/   снимок графа, локальный HTTP-сервер и D3-страница
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
