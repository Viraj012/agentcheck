"""Reciprocal Rank Fusion: combine ranked lists without comparing their raw scores.

score(d) = sum over lists of 1 / (k + rank of d in that list), with ranks starting at 1.
Full-text and vector scores live on different scales; ranks don't, so RRF needs no tuning
beyond k (60 is the value from the original paper).
"""

from collections.abc import Sequence


def rrf_scores(rankings: Sequence[Sequence[int]], *, k: int) -> dict[int, float]:
    scores: dict[int, float] = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking, start=1):
            scores[item] = scores.get(item, 0.0) + 1.0 / (k + rank)
    return scores


def rrf(rankings: Sequence[Sequence[int]], *, k: int) -> list[int]:
    """Items ordered by fused score; ties go to the better single rank, then the lower id."""
    scores = rrf_scores(rankings, k=k)
    best_rank = {item: min(r.index(item) for r in rankings if item in r) for item in scores}
    return sorted(scores, key=lambda item: (-scores[item], best_rank[item], item))
