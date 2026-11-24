"""CLI v0.1: статус проекта и интерактивный диалог."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from griga import __version__
from griga.config import load_config


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="griga",
        description="Griga AGI v0.1 — граф знаний и символический диалог.",
    )
    parser.add_argument("--version", action="store_true", help="показать версию")
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="путь к config.toml (по умолчанию — в корне проекта)",
    )
    parser.add_argument(
        "--text",
        default=None,
        help="одна реплика для chat, без интерактивного цикла",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="адрес визуализатора (по умолчанию 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8765,
        help="порт визуализатора (по умолчанию 8765, 0 — свободный)",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="не открывать браузер автоматически",
    )
    parser.add_argument(
        "--node",
        default=None,
        help="узел для стартовой активации в визуализаторе",
    )
    parser.add_argument(
        "--user",
        default=None,
        help=(
            "имя пользователя для личного подграфа "
            "(по умолчанию GRIGA_USER_NAME или «пользователь»)"
        ),
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="сколько событий истории показать (по умолчанию 20)",
    )
    parser.add_argument(
        "command",
        nargs="?",
        choices=["chat", "status", "visualize", "users", "history"],
        default="status",
        help=(
            "chat — диалог, visualize — граф в браузере, "
            "users — пользователи, history — аудит изменений, status — состояние"
        ),
    )
    return parser


def _resolve_user(storage, name: str | None):
    from griga.memory import DEFAULT_USER_NAME, UserDirectory

    chosen = name or os.environ.get("GRIGA_USER_NAME") or DEFAULT_USER_NAME
    return UserDirectory(storage).ensure(chosen)


def _run_chat(
    cfg,
    once_text: str | None = None,
    user_name: str | None = None,
) -> int:
    from griga.dialogue import Dialogue
    from griga.env import load_dotenv
    from griga.graph.graph import KnowledgeGraph
    from griga.storage.postgres import PostgresStorage

    load_dotenv()
    try:
        storage = PostgresStorage()
        storage.init_schema()
    except Exception as exc:  # noqa: BLE001 - CLI должен объяснить сбой
        print(f"Не удалось подключиться к PostgreSQL: {exc}")
        print("Проверь .env и запусти .\\.venv\\Scripts\\python.exe -m scripts.init_db")
        return 1

    with storage:
        user = _resolve_user(storage, user_name)
        graph = KnowledgeGraph(storage, owner_id=user.id)
        dialogue = Dialogue(graph, cfg, owner_id=user.id)

        if once_text:
            turn = dialogue.turn(once_text)
            _report_turn(turn)
            return 0

        print(f"Пользователь: {user.name}")
        print("Гриша v0.1. Пиши факты или вопросы. Выход: «выход».")
        while True:
            try:
                raw = input("Вы: ")
            except (EOFError, KeyboardInterrupt):
                print()
                break

            text = raw.strip()
            if not text:
                continue
            if text.lower() in {"выход", "exit", "quit", "пока"}:
                print("Гриша: До встречи.")
                break

            turn = dialogue.turn(text)
            _report_turn(turn)

    return 0


def _report_turn(turn) -> None:
    print(f"Гриша: {turn.response}")
    if turn.conflicts:
        print(
            "  (заметка: факт противоречит уже известному — "
            "сохранён с низкой уверенностью)"
        )


def _run_visualize(cfg, args) -> int:
    from griga.env import load_dotenv
    from griga.graph.graph import KnowledgeGraph
    from griga.storage.postgres import PostgresStorage
    from griga.visualization import VisualizerServer

    load_dotenv()
    try:
        storage = PostgresStorage()
        storage.init_schema()
    except Exception as exc:  # noqa: BLE001 - CLI должен объяснить сбой
        print(f"Не удалось подключиться к PostgreSQL: {exc}")
        print("Проверь .env и запусти .\\.venv\\Scripts\\python.exe -m scripts.init_db")
        return 1

    with storage:
        user = _resolve_user(storage, args.user)
        graph = KnowledgeGraph(storage, owner_id=user.id)
        print(f"Пользователь: {user.name}")
        server = VisualizerServer(
            graph, cfg, host=args.host, port=args.port
        )
        if args.node:
            if server.activate(args.node) is None:
                print(f"Узел {args.node!r} не найден в графе.")
                return 1
        server.serve_forever(open_browser=not args.no_browser)

    return 0


def _run_users(cfg) -> int:
    from griga.env import load_dotenv
    from griga.memory import UserDirectory
    from griga.storage.postgres import PostgresStorage

    load_dotenv()
    try:
        storage = PostgresStorage()
        storage.init_schema()
    except Exception as exc:  # noqa: BLE001 - CLI должен объяснить сбой
        print(f"Не удалось подключиться к PostgreSQL: {exc}")
        print("Проверь .env и запусти .\\.venv\\Scripts\\python.exe -m scripts.init_db")
        return 1

    with storage:
        users = UserDirectory(storage).list_users()
        if not users:
            print("Пользователей пока нет. Первый появится после `griga chat`.")
            return 0
        for user in users:
            print(f"{user.id}  {user.name}")

    return 0


def _run_history(cfg, limit: int = 20) -> int:
    from griga.env import load_dotenv
    from griga.storage.postgres import PostgresStorage

    load_dotenv()
    try:
        storage = PostgresStorage()
        storage.init_schema()
    except Exception as exc:  # noqa: BLE001 - CLI должен объяснить сбой
        print(f"Не удалось подключиться к PostgreSQL: {exc}")
        print("Проверь .env и запусти .\\.venv\\Scripts\\python.exe -m scripts.init_db")
        return 1

    with storage:
        events = storage.load_events(max(1, limit))
        if not events:
            print("История изменений пуста.")
            return 0
        for event in events:
            source = event.get("source") or ""
            print(
                f"{event['created_at']:%Y-%m-%d %H:%M:%S}  "
                f"{event['action']:<14} {event['entity_type']:<5} "
                f"{event['entity_id']}  {source}"
            )

    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.version:
        print(f"griga {__version__}")
        return 0

    cfg = load_config(args.config)

    if args.command == "chat":
        return _run_chat(cfg, args.text, args.user)

    if args.command == "visualize":
        return _run_visualize(cfg, args)

    if args.command == "users":
        return _run_users(cfg)

    if args.command == "history":
        return _run_history(cfg, args.limit)

    print(f"Griga AGI v0.1 ({__version__}) — каркас проекта.")
    print(f"storage: {cfg.storage.backend} ({cfg.storage.database_url_env})")
    print(
        "activation: "
        f"D={cfg.activation.decay}, T={cfg.activation.threshold}, "
        f"max_depth={cfg.activation.max_depth}, top_k={cfg.memory.top_k}"
    )
    print(
        "learning: "
        f"eta={cfg.learning.eta}, supervised_delta={cfg.learning.supervised_delta}, "
        f"forgetting={cfg.learning.forgetting_factor}"
    )
    print(
        "perception: "
        f"udpipe={'on' if cfg.perception.use_syntax else 'off'}, "
        f"model={cfg.perception.udpipe_model}"
    )
    print(f"generation: max_attempts={cfg.generation.max_attempts}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
