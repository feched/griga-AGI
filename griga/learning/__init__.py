"""Обучение: Хебб, обучение с учителем, забывание (ADR-005)."""

from griga.learning.forgetting import Forgetting, ForgettingResult
from griga.learning.hebb import EdgeChange, HebbLearner
from griga.learning.supervised import SupervisedLearner

__all__ = [
    "EdgeChange",
    "Forgetting",
    "ForgettingResult",
    "HebbLearner",
    "SupervisedLearner",
]
