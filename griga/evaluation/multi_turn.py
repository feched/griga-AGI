"""Многоходовые сценарии v0.1 (M11): удержание контекста диалога.

Сценарий — это последовательность реплик и ожиданий. Каждый сценарий
запускается на **чистом** графе (``KnowledgeGraph`` + ``MemoryStorage``),
поэтому сценарии не влияют друг на друга и не трогают PostgreSQL.

Проверяется три вещи:

- ``expected_intent`` — намерение ответа (алиасы: greet, statement,
  answer, dont_know, clarify);
- ``expected_contains`` — слова в ответе с учётом склонения;
- ``invariants`` — состояние графа после сценария (например, после
  коррекции старого ребра быть не должно).

Инварианты — единственный надёжный способ поймать «Гриша сказал нет, но
ребро осталось»: текстовые проверки такого не видят.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

from griga.config import Config
from griga.dialogue import Dialogue, TurnResult
from griga.evaluation.text import mentions_word
from griga.graph.graph import KnowledgeGraph
from griga.graph.relations import RelationType
from griga.perception.morphology import Morphology
from griga.speech.intents import Intent
from griga.storage.memory import MemoryStorage


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_SCENARIOS_PATH = PROJECT_ROOT / "eval" / "multi_turn" / "scenarios.json"


# Алиасы для читаемых сценариев. Нативные значения Intent тоже принимаются.
INTENT_ALIASES: dict[str, tuple[str, ...]] = {
    "greet": (Intent.GREET.value,),
    "statement": (Intent.ACKNOWLEDGE.value,),
    "answer": (
        Intent.ANSWER_DIRECTLY.value,
        Intent.ANSWER_WITH_HEDGE.value,
    ),
    "dont_know": (Intent.ADMIT_IGNORANCE.value,),
    "unknown": (Intent.ADMIT_IGNORANCE.value,),
    "clarify": (Intent.CLARIFY.value,),
    "empathize": (Intent.EMPATHIZE.value,),
    "refuse": (Intent.REFUSE.value,),
}

_NATIVE_INTENTS = frozenset(intent.value for intent in Intent)


def resolve_intent(name: str) -> tuple[str, ...]:
    """Алиас или нативное намерение → набор допустимых значений."""
    key = name.strip()
    if key in INTENT_ALIASES:
        return INTENT_ALIASES[key]
    if key in _NATIVE_INTENTS:
        return (key,)
    raise ValueError(
        f"unknown intent {name!r}; expected one of "
        f"{sorted(INTENT_ALIASES)} or a native Intent value"
    )


@dataclass(frozen=True)
class ScenarioTurn:
    user: str
    expected_intent: str | None = None
    expected_contains: tuple[str, ...] = ()
    note: str | None = None


@dataclass(frozen=True)
class GraphCheck:
    """Ожидаемое состояние ребра после сценария."""

    source: str
    relation: str
    target: str
    present: bool = True


@dataclass(frozen=True)
class Scenario:
    id: str
    description: str
    turns: tuple[ScenarioTurn, ...]
    invariants: tuple[GraphCheck, ...] = ()


@dataclass(frozen=True)
class TurnOutcome:
    index: int
    turn: ScenarioTurn
    response: str
    intent: str
    construction_id: str
    attempts: int
    failures: tuple[str, ...] = ()

    @property
    def passed(self) -> bool:
        return not self.failures


@dataclass(frozen=True)
class InvariantOutcome:
    check: GraphCheck
    passed: bool
    detail: str = ""


@dataclass(frozen=True)
class ScenarioOutcome:
    scenario: Scenario
    turns: tuple[TurnOutcome, ...]
    invariants: tuple[InvariantOutcome, ...] = ()

    @property
    def total_turns(self) -> int:
        return len(self.turns)

    @property
    def passed_turns(self) -> int:
        return sum(1 for turn in self.turns if turn.passed)

    @property
    def failed_turns(self) -> int:
        return self.total_turns - self.passed_turns

    @property
    def failed_invariants(self) -> int:
        return sum(1 for item in self.invariants if not item.passed)

    @property
    def ok(self) -> bool:
        return (
            self.total_turns > 0
            and self.failed_turns == 0
            and self.failed_invariants == 0
        )

    def first_failure(self) -> str | None:
        for turn in self.turns:
            if turn.failures:
                return turn.failures[0]
        for item in self.invariants:
            if not item.passed:
                return item.detail or "инвариант графа не выполнен"
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.scenario.id,
            "description": self.scenario.description,
            "ok": self.ok,
            "turns_total": self.total_turns,
            "turns_passed": self.passed_turns,
            "turns_failed": self.failed_turns,
            "invariants_total": len(self.invariants),
            "invariants_failed": self.failed_invariants,
            "turns": [
                {
                    "index": turn.index,
                    "user": turn.turn.user,
                    "response": turn.response,
                    "intent": turn.intent,
                    "construction_id": turn.construction_id,
                    "attempts": turn.attempts,
                    "passed": turn.passed,
                    "failures": list(turn.failures),
                }
                for turn in self.turns
            ],
            "invariants": [
                {
                    "source": item.check.source,
                    "relation": item.check.relation,
                    "target": item.check.target,
                    "present": item.check.present,
                    "passed": item.passed,
                    "detail": item.detail,
                }
                for item in self.invariants
            ],
        }


def load_scenarios(
    path: str | Path | None = None,
) -> tuple[Scenario, ...]:
    """Читает и валидирует ``scenarios.json`` (список сценариев)."""
    target = Path(path) if path is not None else DEFAULT_SCENARIOS_PATH
    raw = json.loads(target.read_text(encoding="utf-8"))

    if isinstance(raw, dict):
        raw = raw.get("scenarios")
    if not isinstance(raw, list) or not raw:
        raise ValueError(f"{target}: expected a non-empty list of scenarios")

    scenarios: list[Scenario] = []
    seen: set[str] = set()

    for item in raw:
        if not isinstance(item, dict):
            raise ValueError(f"{target}: each scenario must be an object")

        scenario_id = str(item.get("id", "")).strip()
        if not scenario_id:
            raise ValueError(f"{target}: scenario id is required")
        if scenario_id in seen:
            raise ValueError(f"{target}: duplicate scenario id {scenario_id!r}")
        seen.add(scenario_id)

        description = str(item.get("description", "")).strip()
        turns_raw = item.get("turns")
        if not isinstance(turns_raw, list) or not turns_raw:
            raise ValueError(
                f"{target}: {scenario_id}: 'turns' must be a non-empty list"
            )

        turns: list[ScenarioTurn] = []
        for turn_raw in turns_raw:
            if not isinstance(turn_raw, dict):
                raise ValueError(
                    f"{target}: {scenario_id}: each turn must be an object"
                )

            user = str(turn_raw.get("user", "")).strip()
            if not user:
                raise ValueError(
                    f"{target}: {scenario_id}: turn has no 'user' text"
                )

            intent_raw = turn_raw.get("expected_intent")
            expected_intent = None
            if intent_raw is not None and str(intent_raw).strip():
                expected_intent = str(intent_raw).strip()
                resolve_intent(expected_intent)  # валидация на входе

            contains_raw = turn_raw.get("expected_contains") or []
            if not isinstance(contains_raw, list):
                raise ValueError(
                    f"{target}: {scenario_id}: "
                    "'expected_contains' must be a list"
                )
            contains = tuple(
                str(word) for word in contains_raw if str(word).strip()
            )

            note_raw = turn_raw.get("note")
            turns.append(
                ScenarioTurn(
                    user=user,
                    expected_intent=expected_intent,
                    expected_contains=contains,
                    note=str(note_raw) if note_raw else None,
                )
            )

        invariants_raw = item.get("invariants") or []
        if not isinstance(invariants_raw, list):
            raise ValueError(
                f"{target}: {scenario_id}: 'invariants' must be a list"
            )

        invariants: list[GraphCheck] = []
        for check_raw in invariants_raw:
            if not isinstance(check_raw, dict):
                raise ValueError(
                    f"{target}: {scenario_id}: each invariant must be an object"
                )
            source = str(check_raw.get("source", "")).strip()
            target_name = str(check_raw.get("target", "")).strip()
            relation = str(check_raw.get("relation", "")).strip()
            if not source or not target_name or not relation:
                raise ValueError(
                    f"{target}: {scenario_id}: invariant needs "
                    "source, relation and target"
                )
            _relation(relation)  # валидация на входе
            invariants.append(
                GraphCheck(
                    source=source,
                    relation=relation,
                    target=target_name,
                    present=bool(check_raw.get("present", True)),
                )
            )

        scenarios.append(
            Scenario(
                id=scenario_id,
                description=description,
                turns=tuple(turns),
                invariants=tuple(invariants),
            )
        )

    return tuple(scenarios)


def _relation(name: str) -> RelationType:
    try:
        return RelationType(name)
    except ValueError:
        try:
            return RelationType[name.upper()]
        except KeyError as exc:
            raise ValueError(f"unknown relation {name!r}") from exc


def _check_turn(
    turn: ScenarioTurn,
    result: TurnResult,
    previous_response: str | None,
) -> tuple[str, ...]:
    failures: list[str] = []
    text = result.response.strip()

    if not text:
        failures.append("пустой ответ")
    if result.construction_id == "fallback":
        failures.append("fallback: генератор не собрал заземлённый ответ")

    if turn.expected_intent is not None:
        allowed = resolve_intent(turn.expected_intent)
        if result.intent not in allowed:
            failures.append(
                f"намерение {result.intent!r}, ожидалось "
                f"{turn.expected_intent!r}"
            )

    for word in turn.expected_contains:
        if not mentions_word(text, word):
            failures.append(f"в ответе нет {word!r}")

    if previous_response is not None and text == previous_response:
        failures.append("ответ дословно повторяет предыдущую реплику")

    return tuple(failures)


def _check_invariant(
    graph: KnowledgeGraph,
    check: GraphCheck,
    morph: Morphology,
) -> InvariantOutcome:
    relation = _relation(check.relation)
    source = graph.find_visible_node(morph.normal_form(check.source))
    target = graph.find_visible_node(morph.normal_form(check.target))

    present = False
    if source is not None and target is not None:
        edge = graph.find_edge(source.id, target.id, relation)
        # Погашенное ребро (status=negated) для сценария значит «нет».
        present = edge is not None and not edge.is_negated

    passed = present == check.present
    if passed:
        return InvariantOutcome(check=check, passed=True)

    if source is None or target is None:
        missing = check.source if source is None else check.target
        detail = f"узел {missing!r} не найден в графе"
    else:
        detail = (
            f"ребро {check.source} -[{relation.value}]-> {check.target} "
            f"{'есть, а не должно' if present else 'отсутствует'}"
        )
    return InvariantOutcome(check=check, passed=False, detail=detail)


def run_scenario(
    scenario: Scenario,
    *,
    config: Config | None = None,
    learning: bool = False,
    morph: Morphology | None = None,
) -> ScenarioOutcome:
    """Прогоняет один сценарий на чистом графе."""
    graph = KnowledgeGraph(MemoryStorage())
    dialogue = Dialogue(graph, config, learning=learning)
    morph = morph or Morphology()

    outcomes: list[TurnOutcome] = []
    previous: str | None = None
    for index, turn in enumerate(scenario.turns, start=1):
        result = dialogue.turn(turn.user)
        outcomes.append(
            TurnOutcome(
                index=index,
                turn=turn,
                response=result.response,
                intent=result.intent,
                construction_id=result.construction_id,
                attempts=result.attempts,
                failures=_check_turn(turn, result, previous),
            )
        )
        previous = result.response

    return ScenarioOutcome(
        scenario=scenario,
        turns=tuple(outcomes),
        invariants=tuple(
            _check_invariant(graph, check, morph)
            for check in scenario.invariants
        ),
    )


def run_scenarios(
    scenarios: Sequence[Scenario],
    *,
    config: Config | None = None,
    learning: bool = False,
) -> tuple[ScenarioOutcome, ...]:
    """Все сценарии; каждый — на своём чистом графе."""
    morph = Morphology()
    return tuple(
        run_scenario(
            scenario, config=config, learning=learning, morph=morph
        )
        for scenario in scenarios
    )


def summarize(outcomes: Iterable[ScenarioOutcome]) -> dict[str, Any]:
    results = list(outcomes)
    turns_total = sum(item.total_turns for item in results)
    turns_passed = sum(item.passed_turns for item in results)
    invariants_total = sum(len(item.invariants) for item in results)
    invariants_failed = sum(item.failed_invariants for item in results)
    return {
        "scenarios": len(results),
        "scenarios_passed": sum(1 for item in results if item.ok),
        "turns": turns_total,
        "turns_passed": turns_passed,
        "turns_failed": turns_total - turns_passed,
        "pass_rate": (
            round(turns_passed / turns_total, 4) if turns_total else 0.0
        ),
        "invariants": invariants_total,
        "invariants_failed": invariants_failed,
    }
