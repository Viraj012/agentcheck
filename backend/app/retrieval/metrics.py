"""Retrieval quality metrics over ranked lists of page identifiers (one entry per chunk)."""

from collections.abc import Sequence


def recall_at_k(ranked_pages: Sequence[str], relevant: str, *, k: int) -> float:
    """1.0 if any of the top-k retrieved chunks comes from the relevant page, else 0.0."""
    return 1.0 if relevant in ranked_pages[:k] else 0.0


def reciprocal_rank(ranked_pages: Sequence[str], relevant: str) -> float:
    """1 / position of the first chunk from the relevant page (0.0 if never retrieved)."""
    for position, page in enumerate(ranked_pages, start=1):
        if page == relevant:
            return 1.0 / position
    return 0.0


def mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0
