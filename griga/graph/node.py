"""Узел графа знаний (ADR-001)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class NodeType(str, Enum):
    CONCEPT = "concept"
    RELATION = "relation"
    PROPERTY = "property"
    INTENT = "intent"
    CONSTRUCTION = "construction"
    USER = "user"


@dataclass
class Node:
    name: str
    node_type: NodeType = NodeType.CONCEPT
    metadata: dict[str, Any] = field(default_factory=dict)
    id: uuid.UUID = field(default_factory=uuid.uuid4)
    owner_id: uuid.UUID | None = None
    confidence: float = 0.5
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        self.name = self.name.strip()
        if not self.name:
            raise ValueError("Node.name must be non-empty")

        if not isinstance(self.node_type, NodeType):
            self.node_type = NodeType(self.node_type)

        if not isinstance(self.id, uuid.UUID):
            self.id = uuid.UUID(str(self.id))

        if self.owner_id is not None and not isinstance(self.owner_id, uuid.UUID):
            self.owner_id = uuid.UUID(str(self.owner_id))

        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("Node.confidence must be in [0, 1]")

    def to_row(self) -> dict[str, Any]:
        """Параметры для INSERT/UPDATE в таблицу nodes."""
        return {
            "id": self.id,
            "name": self.name,
            "type": self.node_type.value,
            "owner_id": self.owner_id,
            "confidence": self.confidence,
            "metadata": self.metadata,
        }

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "Node":
        return cls(
            id=row["id"],
            name=row["name"],
            node_type=NodeType(row["type"]),
            owner_id=row.get("owner_id"),
            confidence=float(row["confidence"]),
            metadata=dict(row.get("metadata") or {}),
            created_at=row.get("created_at"),
            updated_at=row.get("updated_at"),
        )

    def __repr__(self) -> str:
        return f"Node({self.name!r}, type={self.node_type.value}, id={self.id})"
