# ADR-009: Банк конструкций (Генерация v0.1)

**Статус:** accepted
**Дата:** 23.11.2026
**Связанные доки:** ADR-004; ARCHITECTURE.md §6.2

## Контекст
Как именно из активных узлов рождается текст? Нужен стартовый набор правил, чтобы Гриша мог связно ответить.

## Решение
Конструкции хранятся в базе данных (или `constructions.json`) в виде JSON-объектов. 
Схема объекта:
```json
{
  "id": "answer_is_a",
  "intent": "ответить_прямо",
  "template": "{X} — это {Y}.",
  "graph_pattern": {"relation": "is_a", "direction": "forward"},
  "slots": {
    "X": {"pos": "noun", "case": "nominative"},
    "Y": {"pos": "noun", "case": "nominative"}
  }
}