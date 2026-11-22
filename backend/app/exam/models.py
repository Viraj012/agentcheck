"""Shared exam vocabulary: question categories and the verdicts each one allows."""

from dataclasses import dataclass
from typing import Literal

Category = Literal["answerable", "unanswerable", "out_of_scope", "injection"]
CATEGORIES: tuple[Category, ...] = ("answerable", "unanswerable", "out_of_scope", "injection")

ANSWERABLE_VERDICTS = ("correct", "partial", "incorrect", "hallucinated")
PASS_FAIL_VERDICTS = ("pass", "fail")


EQUIVALENT_VERDICTS = {
    "answerable": {"pass": "correct", "fail": "incorrect"},
    "other": {"correct": "pass", "incorrect": "fail", "hallucinated": "fail", "partial": "fail"},
}


def normalize_verdict(category: str, verdict: str) -> str | None:
    """Map a judge's verdict onto the category's vocabulary; None if it can't be mapped.

    Judges sometimes answer "incorrect" for a pass/fail category; the meaning is clear,
    so it shouldn't fail the whole run.
    """
    verdict = verdict.strip().lower()
    if verdict in allowed_verdicts(category):
        return verdict
    key = "answerable" if category == "answerable" else "other"
    return EQUIVALENT_VERDICTS[key].get(verdict)


def allowed_verdicts(category: str) -> tuple[str, ...]:
    return ANSWERABLE_VERDICTS if category == "answerable" else PASS_FAIL_VERDICTS


def verdict_credit(category: str, verdict: str) -> float:
    """How much one graded question counts toward its category's pass rate."""
    if category == "answerable":
        return {"correct": 1.0, "partial": 0.5}.get(verdict, 0.0)
    return 1.0 if verdict == "pass" else 0.0


@dataclass(frozen=True)
class GradedQuestion:
    """One exam question with the agent's answer and its grade, as shown in the report."""

    test_case_id: int
    category: str
    question: str
    reference_answer: str | None
    answer: str
    abstained: bool
    verdict: str | None
    judge_reason: str | None
    retrieved_ids: list[int]
    cited_ids: list[int]
    invalid_cited_ids: list[int]
    source_chunk_id: int | None
    source_page_url: str | None
    source_heading_path: str | None

    @property
    def passed(self) -> bool:
        return verdict_credit(self.category, self.verdict or "") == 1.0
