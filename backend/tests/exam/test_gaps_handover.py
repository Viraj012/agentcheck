from app.config import APP_NAME, Settings
from app.exam.gaps import (
    GAPS_SYSTEM_PROMPT,
    GapTopic,
    group_missing_content,
    hard_to_find,
    missing_content_input,
)
from app.exam.handover import handover_config, handover_markdown
from app.exam.models import GradedQuestion
from app.exam.score import score_run
from app.llm.fake import FakeLLMClient

S = Settings(_env_file=None)


def graded(i: int, category: str, verdict: str, retrieved: list[int], source: int | None = None):
    return GradedQuestion(
        test_case_id=i,
        category=category,
        question=f"question {i}?",
        reference_answer=None,
        answer="answer",
        abstained=False,
        verdict=verdict,
        judge_reason="reason",
        retrieved_ids=retrieved,
        cited_ids=[],
        invalid_cited_ids=[],
        source_chunk_id=source,
        source_page_url="https://x.test/about/" if source else None,
        source_heading_path="About > Sustainability" if source else None,
    )


def test_missing_content_input_lists_escaped_questions() -> None:
    text = missing_content_input([(3, "Do you ship to <Canada>?"), (4, "Refund time?")])
    assert '<question id="3">Do you ship to &lt;Canada&gt;?</question>' in text
    assert '<question id="4">' in text


async def test_grouping_keeps_known_ids_and_collects_leftovers() -> None:
    reply = {
        "topics": [
            {
                "topic": "International shipping",
                "suggestion": "Add a page.",
                "question_ids": [3, 99],
            }
        ]
    }
    llm = FakeLLMClient([reply], dim=4)
    topics = await group_missing_content(llm, [(3, "Canada?"), (4, "Refund time?")])
    assert topics[0] == GapTopic("International shipping", "Add a page.", [3])
    assert topics[1].question_ids == [4]
    assert llm.calls[0].system == GAPS_SYSTEM_PROMPT


async def test_no_unanswerable_questions_means_no_llm_call() -> None:
    llm = FakeLLMClient([], dim=4)
    assert await group_missing_content(llm, []) == []
    assert llm.calls == []


def test_hard_to_find_is_answerable_failure_with_retrieval_miss() -> None:
    rows = [
        graded(1, "answerable", "incorrect", [5, 6], source=9),
        graded(2, "answerable", "incorrect", [9], source=9),
        graded(3, "answerable", "correct", [5], source=9),
        graded(4, "unanswerable", "fail", [5]),
    ]
    found = hard_to_find(rows)
    assert [h.test_case_id for h in found] == [1]
    assert found[0].page_url == "https://x.test/about/"


def test_handover_config_comes_from_settings() -> None:
    config = handover_config(S)
    assert config["models"]["judge"] == S.gemini_model_judge
    assert config["retrieval"]["retrieve_k"] == S.retrieve_k
    assert config["prompt_versions"]["agent"] == "agent-v2"


def test_handover_markdown_has_every_section() -> None:
    rows = [graded(1, "answerable", "incorrect", [5], source=9), graded(2, "injection", "fail", [])]
    card = score_run([(r.category, r.verdict) for r in rows], S)
    md = handover_markdown(
        site="https://x.test/",
        pages=12,
        card=card,
        graded=rows,
        missing=[GapTopic("Refund timing", "State how long refunds take.", [7])],
        hard=hard_to_find(rows),
        config=handover_config(S),
    )
    assert md.startswith(f"# {APP_NAME} handover")
    for section in (
        "## What the agent covers",
        "## Known failure modes",
        "## Gaps to fix first",
        "## Recommended guardrails",
        "## How to re-run the check",
    ):
        assert section in md
    assert "Refund timing" in md
    assert "question 1?" in md
    assert "injection" in md.lower()
