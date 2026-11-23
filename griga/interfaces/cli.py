"""CLI v0.1. Пока это каркас: показывает версию и загруженные параметры."""

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
        "command",
        nargs="?",
        choices=["chat", "status"],
        default="status",
        help="chat — диалог (появится позже), status — состояние каркаса",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.version:
        print(f"griga {__version__}")
        return 0

    cfg = load_config(args.config)

    if args.command == "chat":
        print("Диалог ещё не реализован: следующий этап — M1 (граф и хранилище).")
        return 2

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
    return 0


if __name__ == "__main__":
    sys.exit(main())
