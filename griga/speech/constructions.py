"""Банк конструкций (ADR-009, расширенная схема v0.1).

Конструкция — объект: шаблон с переменными, граф-паттерн и слоты.
Шаблон содержит ``{X}``/``{Y}`` (слоты) и служебные ``{VERB_PRES}``,
``{PREP}``, ``{EMOTION_ADV}``, которые заполняет генератор.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Mapping

from griga.graph.relations import RelationType
from griga.speech.intents import Intent


DEFAULT_CONSTRUCTIONS_PATH = Path(__file__).resolve().parent / "constructions.json"

_PLACEHOLDER_RE = re.compile(r"\{([A-Za-z_]+)\}")
_SPECIAL_PLACEHOLDERS = frozenset({"VERB_PRES", "PREP", "EMOTION_ADV"})
_SLOT_POS = frozenset({"noun", "adjective"})
_SLOT_CASES = frozenset(
    {
        "nominative",
        "genitive",
        "dative",
        "accusative",
        "instrumental",
        "prepositional",
        "auto",
    }
)
_DIRECTIONS = frozenset({"forward", "reverse"})


@dataclass(frozen=True)
class SlotSpec:
    pos: str = "noun"
    case: str = "nominative"
    agree_with: str | None = None


@dataclass(frozen=True)
class GraphPattern:
    relation: RelationType | None = None
    direction: str = "forward"

    @property
    def has_edge(self) -> bool:
        return self.relation is not None

    @property
    def is_forward(self) -> bool:
        return self.direction == "forward"


@dataclass(frozen=True)
class Construction:
    id: str
    intent: Intent
    template: str
    graph_pattern: GraphPattern = GraphPattern()
    slots: Mapping[str, SlotSpec] = field(default_factory=dict)
    weight: float = 1.0
    emotion: str | None = None
    yes_no: bool = False
    label: str | None = None
    user_only: bool = False

    @property
    def placeholders(self) -> frozenset[str]:
        return frozenset(_PLACEHOLDER_RE.findall(self.template))

    @property
    def slot_names(self) -> frozenset[str]:
        return frozenset(name for name in self.placeholders if name not in _SPECIAL_PLACEHOLDERS)


def _load_cached(path: str) -> tuple[Construction, ...]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(raw, dict):
        items = raw.get("constructions", [])
    else:
        items = raw

    if not isinstance(items, list) or not items:
        raise ValueError(f"{path}: expected a non-empty 'constructions' list")

    constructions: list[Construction] = []
    seen_ids: set[str] = set()

    for item in items:
        if not isinstance(item, dict):
            raise ValueError(f"{path}: construction must be an object")

        construction_id = str(item.get("id", "")).strip()
        if not construction_id:
            raise ValueError(f"{path}: construction id is required")
        if construction_id in seen_ids:
            raise ValueError(f"{path}: duplicate construction id {construction_id!r}")
        seen_ids.add(construction_id)

        try:
            intent = Intent(item["intent"])
        except (KeyError, ValueError) as exc:
            raise ValueError(
                f"{path}: {construction_id}: unknown intent {item.get('intent')!r}"
            ) from exc

        template = str(item.get("template", "")).strip()
        if not template:
            raise ValueError(f"{path}: {construction_id}: template is required")

        pattern_raw = item.get("graph_pattern") or {}
        relation_raw = pattern_raw.get("relation")
        relation = None
        if relation_raw:
            try:
                relation = RelationType(str(relation_raw))
            except ValueError as exc:
                raise ValueError(
                    f"{path}: {construction_id}: unknown relation "
                    f"{relation_raw!r}"
                ) from exc

        direction = str(pattern_raw.get("direction", "forward"))
        if direction not in _DIRECTIONS:
            raise ValueError(
                f"{path}: {construction_id}: direction must be "
                f"one of {sorted(_DIRECTIONS)}"
            )

        slots_raw = item.get("slots") or {}
        if not isinstance(slots_raw, dict):
            raise ValueError(f"{path}: {construction_id}: slots must be an object")

        slots: dict[str, SlotSpec] = {}
        for name, spec_raw in slots_raw.items():
            spec_raw = spec_raw or {}
            pos = str(spec_raw.get("pos", "noun"))
            case = str(spec_raw.get("case", "nominative"))
            if pos not in _SLOT_POS:
                raise ValueError(
                    f"{path}: {construction_id}: slot {name}: bad pos {pos!r}"
                )
            if case not in _SLOT_CASES:
                raise ValueError(
                    f"{path}: {construction_id}: slot {name}: bad case {case!r}"
                )
            slots[str(name)] = SlotSpec(
                pos=pos,
                case=case,
                agree_with=spec_raw.get("agree_with"),
            )

        construction = Construction(
            id=construction_id,
            intent=intent,
            template=template,
            graph_pattern=GraphPattern(relation=relation, direction=direction),
            slots=slots,
            weight=float(item.get("weight", 1.0)),
            emotion=item.get("emotion"),
            yes_no=bool(item.get("yes_no", False)),
            label=(str(item["label"]).strip() or None)
            if item.get("label")
            else None,
            user_only=bool(item.get("user_only", False)),
        )

        placeholders = construction.placeholders
        unknown = placeholders - set(slots) - _SPECIAL_PLACEHOLDERS
        if unknown:
            raise ValueError(
                f"{path}: {construction_id}: placeholders without slots: "
                f"{sorted(unknown)}"
            )
        unused = set(slots) - placeholders
        if unused:
            raise ValueError(
                f"{path}: {construction_id}: slots not used in template: "
                f"{sorted(unused)}"
            )

        constructions.append(construction)

    return tuple(constructions)


def load_constructions(
    path: str | Path | None = None,
) -> tuple[Construction, ...]:
    target = Path(path) if path is not None else DEFAULT_CONSTRUCTIONS_PATH
    return _load_cached(str(target.resolve()))


def by_intent(
    constructions: tuple[Construction, ...], intent: Intent
) -> list[Construction]:
    return [item for item in constructions if item.intent is intent]
