# Changelog

Формат — [Keep a Changelog](https://keepachangelog.com/ru/1.1.0/),
версии — [SemVer](https://semver.org/lang/ru/).

## [Unreleased]

### Added

- **Многоходовые сценарии (M11)** — `eval/multi_turn/scenarios.json`
  (5 сценариев по 12–14 ходов), `griga/evaluation/multi_turn.py`,
  `scripts/run_multi_turn.py`, тесты. Каждый сценарий идёт на чистом
  in-memory графе; проверяются намерения, слова и инварианты графа.
- `MemoryStorage` — in-memory хранилище с тем же API, что PostgreSQL.
- `griga/evaluation/text.py` — сравнение слов с учётом склонения.

### Known issues (M12)

- Baseline M11: 46/64 ходов (72%), 0/5 сценариев. Дыры: местоимения и
  личные факты, агрегация свойств, удаление опровергнутых рёбер, оговорка
  на yes/no, выбор связи по смыслу вопроса, транзитивный вывод. Полный
  список — `docs/DEBT.md` (DEBT-207…DEBT-215).

## [0.1.0] — 2026-11-25

Первый релиз v0.1: граф знаний, активация, обучение, диалог на русском,
визуализатор, приватность, валидация, safety shell и eval.

### Added

- **Граф и хранилище (M0–M1)** — PostgreSQL-схема `users / nodes / edges`,
  модели `Node`/`Edge`, `KnowledgeGraph` с дедупликацией и индексами,
  `PostgresStorage` с upsert.
- **Восприятие (M2)** — `PerceptionParser` на UDPipe + pymorphy2 с
  эвристическим fallback; узлы, утверждения, маркеры; в граф пишутся
  только факты (не вопросы, не отрицания, не «наверное»).
- **Активация (M3)** — `Spreader` с формулой ADR-003, clamp, fan-effect,
  рабочая память top-K.
- **Диалог и генерация (M4)** — намерения `Intent`, банк конструкций
  `griga/speech/constructions.json`, мониторинг и максимум 3 попытки,
  grounded generation, CLI `griga chat`.
- **Обучение (M5)** — Хебб, `confirm/deny`, забывание; `Dialogue.learning`,
  `TurnResult.learned/forgotten`.
- **Визуализатор (M6)** — D3-страница активного графа, локальный
  HTTP-сервер на stdlib, CLI `griga visualize`.
- **Личные подграфы (M7)** — `UserDirectory`, изоляция по `owner_id`,
  CLI `griga users`, `--user` для чата и визуализатора.
- **Валидация и аудит (M8)** — `GraphValidator` (конфликты `is_a`/`part_of`
  получают низкую уверенность), таблица `graph_events`, CLI `griga history`.
- **Safety shell (M9)** — классы действий, approval-gate, блокировка после
  запрещённых попыток, пороги аномалий, CLI `griga safety`.
- **Eval (M10)** — `eval/corpus.txt`, `eval/questions.json`,
  `griga/evaluation`, `scripts/run_eval.py`; 20/20 вопросов.

### Docs

- ADR-001–006, 008–010, 014, 015 — accepted; ADR-009 дополнен полной
  схемой конструкций.
- README: быстрый старт, разделы по каждому модулю, структура проекта.

### Tests

- 144 теста: граф, PostgreSQL, парсер, активация, генерация, обучение,
  память, визуализация, валидация, аудит, safety, eval.

### Known limitations

- Один пользователь и только русский язык (ADR-015).
- Нет веб-поиска, исполнения кода и самоизменения — запрещено политикой.
- ADR-011 (лицензия), ADR-012 (один агент с ролями), ADR-013
  (причинность) остаются TBD и не блокируют v0.1.
- Рассказ о дне и сценарии диалога в eval — следующий этап.
