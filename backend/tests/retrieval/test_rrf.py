import pytest

from app.retrieval.rrf import rrf, rrf_scores


def test_scores_follow_the_formula() -> None:
    scores = rrf_scores([[10, 20], [20, 30]], k=60)
    assert scores[20] == pytest.approx(1 / 62 + 1 / 61)
    assert scores[10] == pytest.approx(1 / 61)
    assert scores[30] == pytest.approx(1 / 62)


def test_item_in_both_lists_beats_top_of_one() -> None:
    assert rrf([[1, 2, 3], [4, 2, 5]], k=60)[0] == 2


def test_ties_break_by_best_rank_then_id() -> None:
    assert rrf([[7, 3], [3, 7]], k=60) == [3, 7]
    assert rrf([[9], [4]], k=60) == [4, 9]


def test_empty_inputs() -> None:
    assert rrf([], k=60) == []
    assert rrf([[], []], k=60) == []
