"""PostgreSQL-хранилище графа v0.1."""

from __future__ import annotations

import os
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

import psycopg2
from psycopg2.extras import Json, RealDictCursor, register_uuid

from griga.env import load_dotenv
from griga.graph.edge import Edge
from griga.graph.node import Node


SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"

# Без этого psycopg2 не умеет передавать uuid.UUID в параметрах запроса.
register_uuid()


class PostgresStorage:
    """Тонкая прослойка над psycopg2.

    Соединение в autocommit-режиме: один вызов = одна атомарная запись.
    Для v0.1 этого достаточно; транзакции появятся вместе с audit/versioning.
    """

    def __init__(self, dsn: str | None = None) -> None:
        load_dotenv()
        self.dsn = dsn or os.environ.get("GRIGA_DATABASE_URL")
        if not self.dsn:
            raise RuntimeError(
                "GRIGA_DATABASE_URL is not set (see .env.example)"
            )
        self.conn = psycopg2.connect(self.dsn)
        self.conn.autocommit = True

    @contextmanager
    def _cursor(self) -> Iterator[RealDictCursor]:
        with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
            yield cur

    def init_schema(self, path: str | Path | None = None) -> None:
        sql = (Path(path) if path is not None else SCHEMA_PATH).read_text(
            encoding="utf-8"
        )
        with self._cursor() as cur:
            cur.execute(sql)

    # --- users ---------------------------------------------------------

    def save_user(
        self,
        user_id: uuid.UUID | str,
        name: str,
        metadata: dict[str, Any] | None = None,
    ) -> uuid.UUID:
        user_uuid = (
            user_id if isinstance(user_id, uuid.UUID) else uuid.UUID(str(user_id))
        )
        with self._cursor() as cur:
            cur.execute(
                """
                INSERT INTO users (id, name, metadata)
                VALUES (%s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    name = EXCLUDED.name,
                    metadata = EXCLUDED.metadata
                RETURNING id
                """,
                (user_uuid, name, Json(metadata or {})),
            )
            return cur.fetchone()["id"]

    def load_users(self) -> list[dict[str, Any]]:
        with self._cursor() as cur:
            cur.execute("SELECT * FROM users ORDER BY created_at, id")
            return [dict(row) for row in cur.fetchall()]

    # --- nodes ---------------------------------------------------------

    def save_node(self, node: Node) -> uuid.UUID:
        params = node.to_row()
        params["metadata"] = Json(params["metadata"])
        with self._cursor() as cur:
            cur.execute(
                """
                INSERT INTO nodes (id, name, type, owner_id, confidence, metadata)
                VALUES (
                    %(id)s, %(name)s, %(type)s, %(owner_id)s,
                    %(confidence)s, %(metadata)s
                )
                ON CONFLICT (id) DO UPDATE SET
                    name = EXCLUDED.name,
                    type = EXCLUDED.type,
                    owner_id = EXCLUDED.owner_id,
                    confidence = EXCLUDED.confidence,
                    metadata = EXCLUDED.metadata,
                    updated_at = now()
                RETURNING id
                """,
                params,
            )
            return cur.fetchone()["id"]

    def load_all_nodes(
        self,
        owner_id: uuid.UUID | str | None = None,
        *,
        include_global: bool = True,
    ) -> list[Node]:
        sql = "SELECT * FROM nodes"
        params: list[Any] = []

        if owner_id is not None:
            owner_uuid = (
                owner_id
                if isinstance(owner_id, uuid.UUID)
                else uuid.UUID(str(owner_id))
            )
            if include_global:
                sql += " WHERE owner_id IS NULL OR owner_id = %s"
            else:
                sql += " WHERE owner_id = %s"
            params.append(owner_uuid)

        sql += " ORDER BY created_at, id"
        with self._cursor() as cur:
            cur.execute(sql, params)
            return [Node.from_row(dict(row)) for row in cur.fetchall()]

    # --- edges ---------------------------------------------------------

    def save_edge(self, edge: Edge) -> uuid.UUID:
        params = edge.to_row()
        params["metadata"] = Json(params["metadata"])
        with self._cursor() as cur:
            cur.execute(
                """
                INSERT INTO edges (
                    id, source_id, target_id, relation_type,
                    weight, owner_id, metadata
                )
                VALUES (
                    %(id)s, %(source_id)s, %(target_id)s, %(relation_type)s,
                    %(weight)s, %(owner_id)s, %(metadata)s
                )
                ON CONFLICT (source_id, target_id, relation_type) DO UPDATE SET
                    weight = EXCLUDED.weight,
                    owner_id = EXCLUDED.owner_id,
                    metadata = EXCLUDED.metadata,
                    updated_at = now()
                RETURNING id
                """,
                params,
            )
            return cur.fetchone()["id"]

    def load_all_edges(
        self,
        owner_id: uuid.UUID | str | None = None,
        *,
        include_global: bool = True,
    ) -> list[Edge]:
        sql = "SELECT * FROM edges"
        params: list[Any] = []

        if owner_id is not None:
            owner_uuid = (
                owner_id
                if isinstance(owner_id, uuid.UUID)
                else uuid.UUID(str(owner_id))
            )
            if include_global:
                sql += " WHERE owner_id IS NULL OR owner_id = %s"
            else:
                sql += " WHERE owner_id = %s"
            params.append(owner_uuid)

        sql += " ORDER BY created_at, id"
        with self._cursor() as cur:
            cur.execute(sql, params)
            return [Edge.from_row(dict(row)) for row in cur.fetchall()]

    # --- maintenance ---------------------------------------------------

    def truncate_all(self) -> None:
        """Очищает граф. Используется тестами и /reset в будущем."""
        with self._cursor() as cur:
            cur.execute("TRUNCATE TABLE edges, nodes, users CASCADE")

    def close(self) -> None:
        if self.conn is not None:
            self.conn.close()

    def __enter__(self) -> "PostgresStorage":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
