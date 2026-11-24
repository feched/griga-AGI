"""Пользователи и личные подграфы (ADR-014).

Общий граф читают все, личные факты привязаны к ``owner_id``. Каждый
пользователь получает узел ``[пользователь <имя>]`` — центр его личного
подграфа.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from griga.graph.graph import KnowledgeGraph
from griga.graph.node import Node, NodeType
from griga.storage.postgres import PostgresStorage


DEFAULT_USER_NAME = "пользователь"


@dataclass(frozen=True)
class User:
    id: uuid.UUID
    name: str
    metadata: dict

    @property
    def node_name(self) -> str:
        return f"пользователь {self.name}"


def _as_user(row: dict) -> User:
    return User(
        id=row["id"],
        name=row["name"],
        metadata=dict(row.get("metadata") or {}),
    )


class UserDirectory:
    """Реестр пользователей поверх PostgreSQL."""

    def __init__(self, storage: PostgresStorage) -> None:
        self.storage = storage

    def list_users(self) -> list[User]:
        return [_as_user(row) for row in self.storage.load_users()]

    def find(self, name: str) -> User | None:
        wanted = name.strip().casefold()
        if not wanted:
            return None
        for user in self.list_users():
            if user.name.casefold() == wanted:
                return user
        return None

    def get(self, user_id: uuid.UUID | str) -> User | None:
        target = (
            user_id
            if isinstance(user_id, uuid.UUID)
            else uuid.UUID(str(user_id))
        )
        for user in self.list_users():
            if user.id == target:
                return user
        return None

    def ensure(self, name: str) -> User:
        """Возвращает пользователя, создавая его при первом обращении."""
        clean = name.strip()
        if not clean:
            raise ValueError("User name must be non-empty")

        existing = self.find(clean)
        if existing is not None:
            return existing

        user = User(
            id=uuid.uuid4(),
            name=clean,
            metadata={"role": "owner"},
        )
        self.storage.save_user(user.id, user.name, user.metadata)
        self._ensure_user_node(user)
        return user

    def _ensure_user_node(self, user: User) -> Node:
        """Создаёт личный узел-центр подграфа, если его ещё нет."""
        node = Node(
            name=user.node_name,
            node_type=NodeType.USER,
            owner_id=user.id,
            metadata={"user_id": str(user.id), "user_name": user.name},
        )
        saved = self.storage.save_node(node)
        node.id = saved
        return node

    def graph_for(self, user: User) -> KnowledgeGraph:
        """Общий граф + личный подграф пользователя."""
        return KnowledgeGraph(self.storage, owner_id=user.id)
