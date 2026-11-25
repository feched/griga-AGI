# Griga AGI — домашняя страница

Этот каталог `docs/` — **и есть Obsidian-vault**. Ничего никуда не
копируется: и человек, и агент редактируют одни и те же Markdown-файлы в
репозитории. Obsidian только показывает их с графом ссылок.

> Статус проекта: **v0.1.0** (25.11.2026).

## С чего начать

- [[VISION]] — зачем проект и что считаем успехом.
- [[ARCHITECTURE]] — как устроено: граф, активация, генерация, safety.
- [[GLOSSARY]] — термины.
- [[DEBT]] — все нерешённые архитектурные вопросы и инженерные долги.
- [[adr/README|Индекс ADR]] — журнал решений.

## Карта решений

| Решение | Статус |
|---|---|
| [[adr/0001-ontology\|ADR-001 Онтология]] | accepted |
| [[adr/0002-text-parsing\|ADR-002 Парсинг текста]] | accepted |
| [[adr/0003-activation\|ADR-003 Активация]] | accepted |
| [[adr/0004-generation\|ADR-004 Генерация]] | accepted |
| [[adr/0005-memory-transition\|ADR-005 Память]] | accepted |
| [[adr/0006-module-protocol\|ADR-006 Протокол модулей]] | accepted |
| [[adr/0008-validation\|ADR-008 Валидация]] | accepted |
| [[adr/0009-constructions\|ADR-009 Конструкции]] | accepted |
| [[adr/0010-safety-shell\|ADR-010 Safety shell]] | accepted |
| [[adr/0014-memory-privacy\|ADR-014 Приватность]] | accepted |
| [[adr/0015-scope-v0.1\|ADR-015 Scope v0.1]] | accepted |
| ADR-011 Лицензия | TBD → [[DEBT#A. Архитектурные решения (ADR)\|DEBT-001]] |
| ADR-012 Один агент с ролями | TBD → DEBT-002 |
| ADR-013 Причинность | TBD → DEBT-003 |

## Как мы работаем одновременно

1. Vault открывается как папка `H:\GRISHA\griga-v01\docs`.
2. Правки — обычные Markdown-файлы; их видит и Obsidian, и агент.
3. Git — источник истины: `git pull` перед работой, `git commit` после.
4. Не создавай копии документов «для Obsidian» — редактируй оригинал.
5. Служебная папка `.obsidian/` в git не попадает (в `.gitignore`).

## Быстрые ссылки на код

- `README.md` в корне — запуск, CLI, визуализатор, eval.
- `interfaces/README.md` — agent-style CLI и ярлыки.
- `eval/README.md` — как устроен eval-набор.
- `CHANGELOG.md` — что вошло в релиз.

## Открытые вопросы

Все долги собраны в [[DEBT]]. Если нашёл новый `TBD` — добавь строку туда
и, если вопрос архитектурный, заведи ADR.
