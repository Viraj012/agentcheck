import pytest

from app.retrieval.metrics import mean, recall_at_k, reciprocal_rank

RANKED = ["/a", "/b", "/a", "/c", "/d", "/e"]


def test_recall_at_k_hits_when_relevant_page_is_in_top_k() -> None:
    assert recall_at_k(RANKED, "/c", k=5) == 1.0
    assert recall_at_k(RANKED, "/e", k=5) == 0.0
    assert recall_at_k([], "/a", k=5) == 0.0


def test_reciprocal_rank_uses_first_occurrence() -> None:
    assert reciprocal_rank(RANKED, "/a") == 1.0
    assert reciprocal_rank(RANKED, "/c") == pytest.approx(1 / 4)
    assert reciprocal_rank(RANKED, "/zzz") == 0.0


def test_mean() -> None:
    assert mean([1.0, 0.0, 0.5]) == pytest.approx(0.5)
    assert mean([]) == 0.0
