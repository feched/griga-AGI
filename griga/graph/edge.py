"""Ребро графа знаний (ADR-001, ADR-003)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, ClassVar

from griga.graph.relations import RelationType


@dataclass
class Edge:
    MIN_WEIGHT: ClassVar[float] = 0.05
    MAX_WEIGHT: ClassVar[float] = 1.0

    source_id: uuid.UUID
    target_id: uuid.UUID
    relation_type: RelationType
    weight: float = 0.5
    id: uuid.UUID = field(default_factory=uuid.uuid4)
    owner_id: uuid.UUID | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.source_id, uuid.UUID):
            self.source_id = uuid.UUID(str(self.source_id))
        if not isinstance(self.target_id, uuid.UUID):
            self.target_id = uuid.UUID(str(self.target_id))
        if not isinstance(self.relation_type, RelationType):
            self.relation_type = RelationType(self.relation_type)
        if not isinstance(self.id, uuid.UUID):
            self.id = uuid.UUID(str(self.id))
        if self.owner_id is not None and not isinstance(self.owner_id, uuid.UUID):
            self.owner_id = uuid.UUID(str(self.owner_id))

        if self.source_id == self.target_id:
            raise ValueError("Edge cannot connect a node to itself")
        if not 0.05 <= self.weight <= 1.0:
            raise ValueError("Edge.weight must be in [0.05, 1.0]")

    @property
    def is_negated(self) -> bool:
        """Ребро опровергнуто более поздним фактом (DEBT-209)."""
        return self.metadata.get("status") == "negated"

    def to_row(self) -> dict[str, Any]:
        """Параметры для INSERT/UPDATE в таблицу edges."""
        return {
            "id": self.id,
            "source_id": self.source_id,
            "target_id": self.target_id,
            "relation_type": self.relation_type.value,
            "weight": self.weight,
            "owner_id": self.owner_id,
            "metadata": self.metadata,
        }

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "Edge":
        return cls(
            id=row["id"],
            source_id=row["source_id"],
            target_id=row["target_id"],
            relation_type=RelationType(row["relation_type"]),
            weight=float(row["weight"]),
            owner_id=row.get("owner_id"),
            metadata=dict(row.get("metadata") or {}),
            created_at=row.get("created_at"),
            updated_at=row.get("updated_at"),
        )

    def __repr__(self) -> str:
        return (
            f"Edge({self.source_id} --{self.relation_type.value}--> "
            f"{self.target_id}, w={self.weight})"
        )
