"""Загрузка параметров v0.1 из config.toml.

Числа из ADR-003 (decay, threshold, eta, max_depth и т.д.) живут в конфиге,
а не в коде: их нужно калибровать на диалогах без правки модулей.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

try:  # Python 3.11+
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib


DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.toml"


@dataclass(frozen=True)
class ActivationConfig:
    decay: float = 0.85
    threshold: float = 0.1
    max_depth: int = 3
    clamp: float = 1.0
    fan_effect: bool = True


@dataclass(frozen=True)
class LearningConfig:
    eta: float = 0.05
    min_weight: float = 0.05
    max_weight: float = 1.0
    supervised_delta: float = 0.2
    forgetting_factor: float = 0.99
    forgetting_every_turns: int = 1000


@dataclass(frozen=True)
class GenerationConfig:
    max_attempts: int = 3


@dataclass(frozen=True)
class StorageConfig:
    backend: str = "postgres"
    database_url_env: str = "GRIGA_DATABASE_URL"


@dataclass(frozen=True)
class MemoryConfig:
    top_k: int = 5
    working_ttl_turns: int = 20


@dataclass(frozen=True)
class PerceptionConfig:
    """ADR-002: локальный синтаксический парсер, без внешних API."""

    use_syntax: bool = True
    udpipe_model: str = "data/models/russian-syntagrus-ud-2.5-191206.udpipe"


@dataclass(frozen=True)
class Config:
    activation: ActivationConfig = ActivationConfig()
    learning: LearningConfig = LearningConfig()
    generation: GenerationConfig = GenerationConfig()
    storage: StorageConfig = StorageConfig()
    memory: MemoryConfig = MemoryConfig()
    perception: PerceptionConfig = PerceptionConfig()


def _section(data: dict, name: str) -> dict:
    value = data.get(name, {})
    if not isinstance(value, dict):
        raise ValueError(f"config: section [{name}] must be a table")
    return value


def _number(section: dict, key: str, default: float) -> float:
    value = section.get(key, default)
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(f"config: {key} must be a number")
    return float(value)


def _integer(section: dict, key: str, default: int) -> int:
    value = section.get(key, default)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"config: {key} must be an integer")
    return value


def load_config(path: str | Path | None = None) -> Config:
    """Читает config.toml и возвращает типизированный снимок параметров."""
    config_path = Path(path) if path is not None else DEFAULT_CONFIG_PATH
    with config_path.open("rb") as fh:
        data = tomllib.load(fh)

    activation = _section(data, "activation")
    learning = _section(data, "learning")
    generation = _section(data, "generation")
    storage = _section(data, "storage")
    memory = _section(data, "memory")
    perception = _section(data, "perception")

    cfg = Config(
        activation=ActivationConfig(
            decay=_number(activation, "decay", 0.85),
            threshold=_number(activation, "threshold", 0.1),
            max_depth=_integer(activation, "max_depth", 3),
            clamp=_number(activation, "clamp", 1.0),
            fan_effect=bool(activation.get("fan_effect", True)),
        ),
        learning=LearningConfig(
            eta=_number(learning, "eta", 0.05),
            min_weight=_number(learning, "min_weight", 0.05),
            max_weight=_number(learning, "max_weight", 1.0),
            supervised_delta=_number(learning, "supervised_delta", 0.2),
            forgetting_factor=_number(learning, "forgetting_factor", 0.99),
            forgetting_every_turns=_integer(learning, "forgetting_every_turns", 1000),
        ),
        generation=GenerationConfig(
            max_attempts=_integer(generation, "max_attempts", 3),
        ),
        storage=StorageConfig(
            backend=str(storage.get("backend", "postgres")),
            database_url_env=str(storage.get("database_url_env", "GRIGA_DATABASE_URL")),
        ),
        memory=MemoryConfig(
            top_k=_integer(memory, "top_k", 5),
            working_ttl_turns=_integer(memory, "working_ttl_turns", 20),
        ),
        perception=PerceptionConfig(
            use_syntax=bool(perception.get("use_syntax", True)),
            udpipe_model=str(
                perception.get(
                    "udpipe_model",
                    "data/models/russian-syntagrus-ud-2.5-191206.udpipe",
                )
            ),
        ),
    )
    _validate(cfg)
    return cfg


def _validate(cfg: Config) -> None:
    if not 0.0 < cfg.activation.decay <= 1.0:
        raise ValueError("activation.decay must be in (0, 1]")
    if cfg.activation.threshold <= 0.0:
        raise ValueError("activation.threshold must be > 0")
    if cfg.activation.max_depth < 1:
        raise ValueError("activation.max_depth must be >= 1")
    if cfg.learning.eta <= 0.0:
        raise ValueError("learning.eta must be > 0")
    if not 0.0 <= cfg.learning.min_weight < cfg.learning.max_weight:
        raise ValueError("learning min_weight must be < max_weight")
    if cfg.generation.max_attempts < 1:
        raise ValueError("generation.max_attempts must be >= 1")
    if cfg.memory.top_k < 1:
        raise ValueError("memory.top_k must be >= 1")
    if cfg.storage.backend != "postgres":
        raise ValueError("v0.1 supports only PostgreSQL (ADR-015)")
