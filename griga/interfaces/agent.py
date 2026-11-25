"""Agent-style CLI для Гриши v0.1.

Интерактивная оболочка в духе агентских CLI: баннер, подсказка, слэш-команды
(`/status`, `/history`, `/graph`, `/export`, `/user`), компактная строка
трассировки после каждого ответа. Только стандартная библиотека.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from griga import __version__
from griga.config import Config, load_config

DEFAULT_USER_NAME = "пользователь"
INTERFACES_DIR = Path(__file__).resolve().parent.parent.parent / "interfaces"

HELP_LINES = (
    ("/help", "эта справка"),
    ("/status", "узлы, рёбра, ходы, последнее намерение"),
    ("/history [N]", "последние N событий audit-log (по умолчанию 10)"),
    ("/graph", "открыть D3-визуализатор активного графа"),
    ("/export [путь]", "сохранить снимок графа в JSON"),
    ("/user <имя>", "переключиться на личный подграф пользователя"),
    ("/verbose on|off", "показывать трассировку ответа"),
    ("/clear", "очистить экран"),
    ("/quit", "выйти"),
)


@dataclass(frozen=True)
class AgentCommand:
    name: str
    argument: str = ""


def parse_command(text: str) -> AgentCommand | None:
    """``/status`` → AgentCommand, обычный текст → None."""
    stripped = text.strip()
    if not stripped.startswith("/"):
        return None
    head, _, tail = stripped.partition(" ")
    return AgentCommand(head.casefold(), tail.strip())


def format_banner(
    user_name: str,
    node_count: int,
    edge_count: int,
    *,
    version: str = __version__,
) -> str:
    title = f"Гриша v{version}"
    subtitle = "граф знаний · активация · конструкции"
    stats = f"пользователь: {user_name} · узлов: {node_count} · рёбер: {edge_count}"
    width = max(len(title), len(subtitle), len(stats)) + 2
    line = "─" * width
    return "\n".join(
        [
            f"╭{line}╮",
            f"│ {title.ljust(width - 1)}│",
            f"│ {subtitle.ljust(width - 1)}│",
            f"│ {stats.ljust(width - 1)}│",
            f"╰{line}╯",
            "Введи факт или вопрос. /help — команды, /quit — выход.",
        ]
    )


def format_status(
    *,
    node_count: int,
    edge_count: int,
    turn_index: int,
    user_name: str,
    last_intent: str | None,
    learning: bool,
    conflicts: int = 0,
    anomalies: int = 0,
) -> str:
    lines = [
        f"пользователь:      {user_name}",
        f"узлы / рёбра:      {node_count} / {edge_count}",
        f"ходов в сессии:    {turn_index}",
        f"последнее желание: {last_intent or '—'}",
        f"обучение:          {'вкл' if learning else 'выкл'}",
        f"конфликты / аномалии: {conflicts} / {anomalies}",
    ]
    return "\n".join(lines)


def format_history(events: Iterable[dict[str, Any]]) -> str:
    rows: list[str] = []
    for event in events:
        created = event.get("created_at")
        stamp = (
            created.strftime("%Y-%m-%d %H:%M:%S")
            if isinstance(created, datetime)
            else str(created or "—")
        )
        source = event.get("source") or ""
        rows.append(
            f"{stamp}  {event.get('action', '?'):<14} "
            f"{event.get('entity_type', '?'):<6} "
            f"{event.get('entity_id', '?')}  {source}"
        )
    return "\n".join(rows) if rows else "История изменений пуста."


def format_trace(turn) -> str:
    """Компактная строка «как рассуждал агент»."""
    notes: list[str] = [
        f"намерение: {turn.intent}",
        f"конструкция: {turn.construction_id}",
        f"попыток: {turn.attempts}",
    ]
    if turn.conflicts:
        notes.append(f"конфликтов: {turn.conflicts}")
    if turn.anomalies:
        notes.append(f"аномалий: {len(turn.anomalies)}")
    return " · ".join(notes)


def _resolve_user_name(name: str | None) -> str:
    return name or os.environ.get("GRIGA_USER_NAME") or DEFAULT_USER_NAME


def _export_snapshot(graph, path: str | None) -> Path:
    from griga.visualization import build_snapshot

    target = (
        Path(path).expanduser()
        if path
        else INTERFACES_DIR / "graph_snapshot.json"
    )
    if not target.is_absolute():
        target = (Path.cwd() / target).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(build_snapshot(graph).to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return target


def _open_visualizer(graph, cfg: Config) -> None:
    from griga.visualization import VisualizerServer

    server = VisualizerServer(graph, cfg)
    print("Визуализатор: http://127.0.0.1:8765  (Ctrl+C — вернуться в чат)")
    try:
        server.serve_forever(open_browser=True)
    except KeyboardInterrupt:
        print("\nВизуализатор остановлен.")


def _clear_screen() -> None:
    os.system("cls" if os.name == "nt" else "clear")


def _print_help() -> None:
    width = max(len(name) for name, _ in HELP_LINES)
    print("Команды:")
    for name, description in HELP_LINES:
        print(f"  {name:<{width}}  {description}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="griga-agent",
        description="Интерактивная CLI-оболочка Гриши (agent style).",
    )
    parser.add_argument("--user", default=None, help="имя пользователя")
    parser.add_argument(
        "--no-learning",
        action="store_true",
        help="отключить Хебба и забывание в этой сессии",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    from griga.dialogue import Dialogue
    from griga.env import load_dotenv
    from griga.graph.graph import KnowledgeGraph
    from griga.memory import UserDirectory
    from griga.storage.postgres import PostgresStorage

    args = build_parser().parse_args(argv)
    load_dotenv()

    try:
        storage = PostgresStorage()
        storage.init_schema()
    except Exception as exc:  # noqa: BLE001 - CLI должен объяснить сбой
        print(f"Не удалось подключиться к PostgreSQL: {exc}")
        print("Проверь .env и запусти: python -m scripts.init_db")
        return 1

    with storage:
        user = UserDirectory(storage).ensure(_resolve_user_name(args.user))
        graph = KnowledgeGraph(storage, owner_id=user.id)
        cfg = load_config()
        dialogue = Dialogue(
            graph,
            cfg,
            owner_id=user.id,
            learning=not args.no_learning,
        )

        verbose = True
        conflicts = 0
        anomalies = 0
        last_intent: str | None = None

        print(format_banner(user.name, graph.node_count, graph.edge_count))
        while True:
            try:
                raw = input("\nвы › ")
            except (EOFError, KeyboardInterrupt):
                print("\nДо встречи.")
                break

            text = raw.strip()
            if not text:
                continue

            command = parse_command(text)
            if command is None:
                turn = dialogue.turn(text)
                conflicts += turn.conflicts
                anomalies += len(turn.anomalies)
                last_intent = turn.intent
                print(f"Гриша › {turn.response}")
                if verbose:
                    print(f"        {format_trace(turn)}")
                continue

            name = command.name
            if name in {"/quit", "/exit"}:
                print("До встречи.")
                break
            if name in {"/help", "/?"}:
                _print_help()
                continue
            if name == "/status":
                print(
                    format_status(
                        node_count=graph.node_count,
                        edge_count=graph.edge_count,
                        turn_index=dialogue.turn_index,
                        user_name=user.name,
                        last_intent=last_intent,
                        learning=dialogue.learning_enabled,
                        conflicts=conflicts,
                        anomalies=anomalies,
                    )
                )
                continue
            if name == "/history":
                try:
                    limit = int(command.argument or 10)
                except ValueError:
                    print("Нужно число: /history 20")
                    continue
                print(format_history(storage.load_events(max(1, limit))))
                continue
            if name == "/graph":
                _open_visualizer(graph, cfg)
                continue
            if name == "/export":
                target = _export_snapshot(graph, command.argument or None)
                print(f"Снимок графа: {target}")
                continue
            if name == "/user":
                if not command.argument:
                    print("Укажи имя: /user Алиса")
                    continue
                user = UserDirectory(storage).ensure(command.argument)
                graph = KnowledgeGraph(storage, owner_id=user.id)
                dialogue = Dialogue(
                    graph,
                    cfg,
                    owner_id=user.id,
                    learning=not args.no_learning,
                )
                conflicts = 0
                anomalies = 0
                last_intent = None
                print(
                    f"Пользователь: {user.name} · "
                    f"узлов: {graph.node_count} · рёбер: {graph.edge_count}"
                )
                continue
            if name == "/verbose":
                value = command.argument.casefold()
                if value in {"on", "вкл", "1"}:
                    verbose = True
                elif value in {"off", "выкл", "0"}:
                    verbose = False
                else:
                    print("Использование: /verbose on|off")
                    continue
                print(f"Трассировка: {'вкл' if verbose else 'выкл'}")
                continue
            if name == "/clear":
                _clear_screen()
                continue

            print(f"Неизвестная команда: {name}. /help — список.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
