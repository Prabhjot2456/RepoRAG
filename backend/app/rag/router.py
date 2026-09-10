"""
Query routing — classify user queries to improve retrieval strategy.
Lightweight regex/keyword-based classifier.
"""

from __future__ import annotations

import re
from typing import Tuple

from app.models.schemas import QueryType


# Pattern → (QueryType, fetch_k_multiplier)
_ROUTING_RULES: list[Tuple[re.Pattern, QueryType, float]] = [
    # Architecture / overview
    (re.compile(r"\b(architect|overview|structure|design|how.+work|end.to.end|flow|pipeline|system|entire|complete)\b", re.I), QueryType.ARCHITECTURE_QUERY, 2.0),
    # Setup / installation
    (re.compile(r"\b(install|setup|run|start|deploy|docker|require|depend|environment|env var|config)\b", re.I), QueryType.SETUP_QUERY, 1.5),
    # Function-level
    (re.compile(r"\b(function|method|def |def\t|implement|how does \w+ work)\b", re.I), QueryType.FUNCTION_QUERY, 1.0),
    # Class-level
    (re.compile(r"\b(class|service|model|schema|interface|abstract)\b", re.I), QueryType.CLASS_QUERY, 1.0),
    # File-level
    (re.compile(r"\b(file|\.py|\.js|\.ts|\.java|\.go|what does \w+\.\w+ do)\b", re.I), QueryType.FILE_QUERY, 1.0),
    # Security
    (re.compile(r"\b(security|vulnerabilit|inject|auth|jwt|token|secret|password|sanitize|xss|csrf)\b", re.I), QueryType.SECURITY_QUERY, 1.5),
    # Dependencies
    (re.compile(r"\b(depend|library|package|import|require|pip|npm|version)\b", re.I), QueryType.DEPENDENCY_QUERY, 1.0),
    # Comparison
    (re.compile(r"\b(compare|difference|vs|versus|versus|similar|distinguish)\b", re.I), QueryType.COMPARISON_QUERY, 1.5),
    # Debugging
    (re.compile(r"\b(bug|error|issue|fix|problem|exception|fail|crash|debug)\b", re.I), QueryType.DEBUGGING_QUERY, 1.5),
]


def classify_query(query: str) -> Tuple[QueryType, float]:
    """
    Classify a query and return (QueryType, fetch_k_multiplier).
    The multiplier allows retrieving more chunks for broad queries.
    """
    for pattern, query_type, multiplier in _ROUTING_RULES:
        if pattern.search(query):
            return query_type, multiplier
    return QueryType.GENERAL_REPOSITORY_QUERY, 1.0
