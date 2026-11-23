"""Минимальная загрузка .env без внешних зависимостей."""

from __future__ import annotations

import os
from pathlib import Path


DEFAULT_ENV_PATH = Path(__file__).resolve().parent.parent / ".env"


def load_dotenv(path: str | Path | None = None) -> None:
    """Читает KEY=VALUE из .env и не перезаписывает уже заданные env."""
    env_path = Path(path) if path is not None else DEFAULT_ENV_PATH
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        if key:
            os.environ.setdefault(key, value)
