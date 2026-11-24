"""Валидация графа перед записью (ADR-008)."""

from griga.validation.validator import (
    FUNCTIONAL_RELATIONS,
    Conflict,
    GraphValidator,
    ValidationDecision,
)

__all__ = [
    "FUNCTIONAL_RELATIONS",
    "Conflict",
    "GraphValidator",
    "ValidationDecision",
]
