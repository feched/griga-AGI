from pathlib import Path

import pytest

from griga.config import load_config


ROOT = Path(__file__).resolve().parent.parent


def test_default_config_matches_adr_003():
    cfg = load_config(ROOT / "config.toml")

    assert cfg.activation.decay == 0.85
    assert cfg.activation.threshold == 0.1
    assert cfg.activation.max_depth == 3
    assert cfg.activation.clamp == 1.0
    assert cfg.activation.fan_effect is True

    assert cfg.learning.eta == 0.05
    assert cfg.learning.min_weight == 0.05
    assert cfg.learning.max_weight == 1.0
    assert cfg.learning.supervised_delta == 0.2
    assert cfg.learning.forgetting_factor == 0.99

    assert cfg.generation.max_attempts == 3
    assert cfg.memory.top_k == 5
    assert cfg.storage.backend == "postgres"
    assert cfg.perception.use_syntax is True
    assert cfg.perception.udpipe_model.endswith(".udpipe")


def test_non_postgres_backend_is_rejected(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(
        '[storage]\nbackend = "json"\n',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="PostgreSQL"):
        load_config(path)


def test_invalid_activation_values_are_rejected(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(
        "[activation]\ndecay = 1.5\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="decay"):
        load_config(path)
