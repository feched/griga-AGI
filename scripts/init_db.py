"""Создаёт таблицы v0.1 в базе из GRIGA_DATABASE_URL."""

from __future__ import annotations

from griga.storage.postgres import PostgresStorage


def main() -> int:
    with PostgresStorage() as storage:
        storage.init_schema()
        target = storage.dsn.rsplit("@", 1)[-1]
        print(f"schema ready: {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
