import pytest
from pydantic import ValidationError

from app.config import Settings


def make(**overrides: object) -> Settings:
    return Settings(_env_file=None, **overrides)


def test_defaults_match_spec() -> None:
    s = make()
    assert s.max_pages == 40
    assert s.retrieve_k == 6
    assert s.rrf_k == 60
    assert s.num_questions == 24
    assert (s.num_answerable, s.num_unanswerable, s.num_out_of_scope, s.num_injection) == (
        14,
        6,
        2,
        2,
    )
    assert s.grade_batch == 8
    assert s.gemini_model_judge == "gemini-3.5-flash-lite"
    assert s.llm_rpm == 12
    assert s.max_llm_calls_per_run == 20
    assert s.runs_per_ip_per_day == 3
    assert s.max_runs_per_day == 30
    assert s.ready_min_accuracy == 0.85
    assert s.not_ready_below_accuracy == 0.60


def test_category_counts_must_sum_to_num_questions() -> None:
    with pytest.raises(ValidationError, match="must sum to num_questions"):
        make(num_answerable=10)


def test_limits_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        make(max_pages=0)


def test_verdict_thresholds_must_be_ordered() -> None:
    with pytest.raises(ValidationError, match="not_ready_below_accuracy"):
        make(not_ready_below_accuracy=0.9)


def test_env_var_overrides_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAX_PAGES", "12")
    assert make().max_pages == 12


def test_blank_env_value_keeps_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_MODEL_FAST", "")
    assert make().gemini_model_fast == Settings.model_fields["gemini_model_fast"].default
