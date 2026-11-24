"""CLI v0.1: статус проекта и интерактивный диалог."""

from __future__ import annotations

import argparse
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
        "command",
        nargs="?",
        choices=["chat", "status"],
        default="status",
        help="chat — диалог, status — состояние проекта",
    )
    return parser


def _run_chat(cfg, once_text: str | None = None) -> int:
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
        graph = KnowledgeGraph(storage)
        dialogue = Dialogue(graph, cfg)

        if once_text:
            turn = dialogue.turn(once_text)
            print(f"Гриша: {turn.response}")
            return 0

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
            print(f"Гриша: {turn.response}")

    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.version:
        print(f"griga {__version__}")
        return 0

    cfg = load_config(args.config)

    if args.command == "chat":
        return _run_chat(cfg, args.text)

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
