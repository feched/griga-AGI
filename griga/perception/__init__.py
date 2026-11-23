"""Perception: текст → узлы, утверждения, маркеры (ADR-002)."""

from griga.perception.materialize import AppliedParse, apply_parse
from griga.perception.models import (
    Markers,
    Mention,
    ParseResult,
    Polarity,
    SpeechAct,
    Statement,
)
from griga.perception.morphology import Morphology
from griga.perception.parser import PerceptionParser
from griga.perception.syntax import DependencyParser, SyntaxToken, SyntaxTree

__all__ = [
    "AppliedParse",
    "DependencyParser",
    "Markers",
    "Mention",
    "Morphology",
    "ParseResult",
    "PerceptionParser",
    "Polarity",
    "SpeechAct",
    "Statement",
    "SyntaxToken",
    "SyntaxTree",
    "apply_parse",
]
