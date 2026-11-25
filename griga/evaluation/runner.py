"""Eval-раннер v0.1: корпус → граф → вопросы → проверки (ADR-015).

Проверяются не только «правильные слова», но и инварианты:
ответ не пустой, не fallback, не повторяет предыдущий, активация не
превышает ``clamp``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from griga.config import Config
from griga.dialogue import Dialogue, TurnResult
from griga.graph.graph import KnowledgeGraph
from griga.perception import PerceptionParser, apply_parse


DEFAULT_CORPUS_PATH = Path(__file__).resolve().parent.parent.parent / "eval" / "corpus.txt"
DEFAULT_QUESTIONS_PATH = (
    Path(__file__).resolve().parent.parent.parent / "eval" / "questions.json"
)


@dataclass(frozen=True)
class EvalCase:
    id: str
    question: str
    intent: str | None = None
    contains: tuple[str, ...] = ()
    allow_fallback: bool = False


@dataclass(frozen=True)
class EvalResult:
    case: EvalCase
    response: str
    intent: str
    construction_id: str
    attempts: int
    failures: tuple[str, ...] = ()

    @property
    def passed(self) -> bool:
        return not self.failures


@dataclass(frozen=True)
class EvalReport:
    name: str
    results: tuple[EvalResult, ...]

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def passed_count(self) -> int:
        return sum(1 for result in self.results if result.passed)

    @property
    def failed_count(self) -> int:
        return self.total - self.passed_count

    @property
    def pass_rate(self) -> float:
        return self.passed_count / self.total if self.total else 0.0

    @property
    def ok(self) -> bool:
        return self.total > 0 and self.failed_count == 0

    def failures(self) -> tuple[EvalResult, ...]:
        return tuple(result for result in self.results if not result.passed)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "total": self.total,
            "passed": self.passed_count,
            "failed": self.failed_count,
            "pass_rate": round(self.pass_rate, 4),
            "cases": [
                {
                    "id": result.case.id,
                    "question": result.case.question,
                    "response": result.response,
                    "intent": result.intent,
                    "construction_id": result.construction_id,
                    "attempts": result.attempts,
                    "passed": result.passed,
                    "failures": list(result.failures),
                }
                for result in self.results
            ],
        }


def load_corpus(path: str | Path | None = None) -> tuple[str, ...]:
    target = Path(path) if path is not None else DEFAULT_CORPUS_PATH
    lines = [
        line.strip()
        for line in target.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if not lines:
        raise ValueError(f"{target}: corpus is empty")
    return tuple(lines)


def load_questions(path: str | Path | None = None) -> tuple[str, tuple[EvalCase, ...]]:
    target = Path(path) if path is not None else DEFAULT_QUESTIONS_PATH
    raw = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{target}: expected an object with 'cases'")

    name = str(raw.get("name") or target.stem)
    items = raw.get("cases")
    if not isinstance(items, list) or not items:
        raise ValueError(f"{target}: 'cases' must be a non-empty list")

    cases: list[EvalCase] = []
    seen: set[str] = set()

    for item in items:
        if not isinstance(item, dict):
            raise ValueError(f"{target}: each case must be an object")

        case_id = str(item.get("id", "")).strip()
        if not case_id:
            raise ValueError(f"{target}: case id is required")
        if case_id in seen:
            raise ValueError(f"{target}: duplicate case id {case_id!r}")
        seen.add(case_id)

        question = str(item.get("question", "")).strip()
        if not question:
            raise ValueError(f"{target}: {case_id}: question is required")

        contains_raw = item.get("contains") or []
        if not isinstance(contains_raw, list):
            raise ValueError(f"{target}: {case_id}: 'contains' must be a list")
        contains = tuple(str(word) for word in contains_raw if str(word).strip())

        intent_raw = item.get("intent")
        intent = str(intent_raw).strip() if intent_raw else None

        cases.append(
            EvalCase(
                id=case_id,
                question=question,
                intent=intent,
                contains=contains,
                allow_fallback=bool(item.get("allow_fallback", False)),
            )
        )

    return name, tuple(cases)


def seed_graph(
    graph: KnowledgeGraph,
    corpus: Iterable[str],
    *,
    parser: PerceptionParser | None = None,
) -> tuple[int, int]:
    """Пишет корпус в граф; возвращает (созданные узлы, созданные рёбра)."""
    parser = parser or PerceptionParser()
    nodes_before = graph.node_count
    edges_before = graph.edge_count
    for line in corpus:
        apply_parse(parser.parse(line), graph)
    return graph.node_count - nodes_before, graph.edge_count - edges_before


def _mentions(response: str, word: str) -> bool:
    """Совпадение с учётом склонения: «дерево» ≈ «дерева»."""
    needle = word.casefold().strip()
    if not needle:
        return True
    if needle in response:
        return True
    if len(needle) <= 4:
        return False
    stem = needle[: len(needle) - 2]
    return stem in response


def _check_turn(
    case: EvalCase,
    turn: TurnResult,
    previous: str | None,
    clamp: float,
) -> tuple[str, ...]:
    failures: list[str] = []

    if not turn.response.strip():
        failures.append("пустой ответ")
    if not case.allow_fallback and turn.construction_id == "fallback":
        failures.append("fallback вместо заземлённого ответа")
    if case.intent is not None and turn.intent != case.intent:
        failures.append(f"намерение {turn.intent!r}, ожидалось {case.intent!r}")

    response = turn.response.casefold()
    for word in case.contains:
        if not _mentions(response, word):
            failures.append(f"в ответе нет {word!r}")

    if previous is not None and turn.response == previous:
        failures.append("ответ повторяет предыдущую реплику")

    for item in turn.memory:
        if item.activation > clamp + 1e-9:
            failures.append(
                f"активация {item.activation:.3f} выше clamp={clamp}"
            )
            break

    return tuple(failures)


def run_eval(
    graph: KnowledgeGraph,
    cases: Iterable[EvalCase],
    *,
    name: str = "eval",
    config: Config | None = None,
    learning: bool = False,
) -> EvalReport:
    dialogue = Dialogue(graph, config, learning=learning)
    clamp = dialogue.config.activation.clamp

    results: list[EvalResult] = []
    previous: str | None = None
    for case in cases:
        turn = dialogue.turn(case.question)
        failures = _check_turn(case, turn, previous, clamp)
        results.append(
            EvalResult(
                case=case,
                response=turn.response,
                intent=turn.intent,
                construction_id=turn.construction_id,
                attempts=turn.attempts,
                failures=failures,
            )
        )
        previous = turn.response

    return EvalReport(name=name, results=tuple(results))
