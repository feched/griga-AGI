"""Eval-набор v0.1: загрузка корпуса и вопросов (ADR-015)."""

from griga.evaluation.runner import (
    EvalCase,
    EvalReport,
    EvalResult,
    load_corpus,
    load_questions,
    run_eval,
    seed_graph,
)

__all__ = [
    "EvalCase",
    "EvalReport",
    "EvalResult",
    "load_corpus",
    "load_questions",
    "run_eval",
    "seed_graph",
]
