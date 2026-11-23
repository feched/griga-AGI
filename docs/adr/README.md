# ADR — журнал архитектурных решений

| ID | Название | Статус | Файл |
|---|---|---|---|
| ADR-001 | Онтология графа | accepted | [`0001-ontology.md`](0001-ontology.md) |
| ADR-002 | Построение графа из текста | accepted | [`0002-text-parsing.md`](0002-text-parsing.md) |
| ADR-003 | Активация и обучение | accepted | [`0003-activation.md`](0003-activation.md) |
| ADR-004 | Генерация текста: намерения и конструкции | accepted | [`0004-generation.md`](0004-generation.md) |
| ADR-005 | Переход из рабочей памяти в долговременную | accepted | [`0005-memory-transition.md`](0005-memory-transition.md) |
| ADR-006 | Протокол взаимодействия модулей | accepted | [`0006-module-protocol.md`](0006-module-protocol.md) |
| ADR-007 | — | отсутствует | — |
| ADR-008 | Валидация графа (защита от взрыва) | accepted | [`0008-validation.md`](0008-validation.md) |
| ADR-009 | Банк конструкций (генерация v0.1) | accepted, черновик | [`0009-constructions.md`](0009-constructions.md) |
| ADR-010 | Safety-пороги, approval-gate | TBD | — |
| ADR-011 | Лицензия | TBD | — |
| ADR-012 | Один агент с ролями | TBD (решено: один) | — |
| ADR-013 | Причинность и заземление | TBD | — |
| ADR-014 | Память и приватность (мультипользовательскость) | accepted | [`0014-memory-privacy.md`](0014-memory-privacy.md) |
| ADR-015 | Scope v0.1 | accepted | [`0015-scope-v0.1.md`](0015-scope-v0.1.md) |

## Ближайшие недостающие решения для v0.1

- **ADR-009** — дописать полную схему конструкций и стартовый банк 20–30 штук.
- **ADR-010** — минимальный approval-gate и пороги аномали-детектора (v0.1:
  только интерфейс и audit, без опасных действий).
- **ADR-013** — причинность для v0.1 не блокирует: в scope только `это`,
  `часть`, `свойство`, `связано_с` и глагольные рёбра уровня 0.
