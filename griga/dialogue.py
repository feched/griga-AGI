"""Диалоговый цикл v0.1: реплика → восприятие → граф → активация → ответ.

Один ход:
1. PerceptionParser разбирает текст (узлы/утверждения/маркеры);
2. apply_parse пишет только факты в граф;
3. Spreader считает рабочую память (top-K);
4. Generator выбирает намерение и конструкцию, проверяет ответ;
5. HebbLearner усиливает рёбра между узлами, активными в этом такте;
6. Forgetting раз в N ходов гасит веса (ADR-005).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from griga.config import Config, load_config
from griga.graph.graph import KnowledgeGraph
from griga.learning import EdgeChange, Forgetting, HebbLearner
from griga.perception import AppliedParse, PerceptionParser, apply_parse
from griga.perception.models import ParseResult
from griga.speech.generator import (
    GeneratedResponse,
    Generator,
    TurnContext,
)
from griga.thinking.spreader import Spreader, WorkingMemory


@dataclass(frozen=True)
class TurnResult:
    user_text: str
    response: str
    parse: ParseResult
    applied: AppliedParse
    memory: WorkingMemory
    intent: str
    construction_id: str
    attempts: int = 1
    learned: tuple[EdgeChange, ...] = ()
    forgotten: tuple[EdgeChange, ...] = ()

    @property
    def conflicts(self) -> int:
        return self.applied.conflicting_edges


class Dialogue:
    """Состояние одного диалога поверх общего графа."""

    def __init__(
        self,
        graph: KnowledgeGraph,
        config: Config | None = None,
        *,
        owner_id: uuid.UUID | None = None,
        parser: PerceptionParser | None = None,
        generator: Generator | None = None,
        learning: bool = True,
    ) -> None:
        self.graph = graph
        self.config = config or load_config()
        self.owner_id = owner_id
        self.parser = parser or PerceptionParser(self.config)
        self.generator = generator or Generator(self.graph, self.config)
        self.spreader = Spreader(self.graph, self.config)
        self.learning_enabled = learning
        self.hebb = HebbLearner(self.graph, self.config)
        self.forgetting = Forgetting(self.graph, self.config)

        self.turn_index = 0
        self.last_response: str | None = None
        self.history: list[tuple[str, str]] = []
        self.learning_log: list[EdgeChange] = []

    def turn(self, text: str) -> TurnResult:
        parse = self.parser.parse(text)
        applied = apply_parse(
            parse, self.graph, owner_id=self.owner_id
        )

        memory = self.spreader.activate(
            self._seed_nodes(parse),
            top_k=self.config.memory.top_k,
        )
        generated: GeneratedResponse = self.generator.generate(
            parse,
            memory,
            TurnContext(
                last_response=self.last_response,
                turn_index=self.turn_index,
            ),
            owner_id=self.owner_id,
        )

        learned: tuple[EdgeChange, ...] = ()
        forgotten: tuple[EdgeChange, ...] = ()
        if self.learning_enabled:
            learned = self.hebb.reinforce(memory)
            result = self.forgetting.tick(self.turn_index + 1)
            forgotten = result.changes
            self.learning_log.extend(learned)
            self.learning_log.extend(forgotten)

        self.history.append((text, generated.text))
        self.last_response = generated.text
        self.turn_index += 1

        return TurnResult(
            user_text=text,
            response=generated.text,
            parse=parse,
            applied=applied,
            memory=memory,
            intent=generated.intent.value,
            construction_id=generated.construction_id,
            attempts=generated.attempts,
            learned=learned,
            forgotten=forgotten,
        )

    def _seed_nodes(self, parse: ParseResult):
        seeds = []
        seen: set[uuid.UUID] = set()
        for mention in parse.nodes:
            node = self.graph.find_visible_node(
                mention.lemma, mention.node_type, self.owner_id
            )
            if node is not None and node.id not in seen:
                seen.add(node.id)
                seeds.append(node)
        return seeds
