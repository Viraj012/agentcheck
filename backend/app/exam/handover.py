"""The handover package: a config snapshot (JSON) and a Markdown handover document."""

from collections.abc import Sequence
from typing import Any

from app.agent.prompt import PROMPT_VERSION
from app.config import APP_NAME, Settings
from app.exam.gaps import GAPS_PROMPT_VERSION, GapTopic, HardToFind
from app.exam.generate import EXAM_PROMPT_VERSION
from app.exam.grade import JUDGE_PROMPT_VERSION
from app.exam.models import GradedQuestion
from app.exam.score import Scorecard

VERDICT_LABELS = {"ready": "Ready", "needs_work": "Needs work", "not_ready": "Not ready"}
MAX_LISTED_FAILURES = 10


def handover_config(settings: Settings) -> dict[str, Any]:
    return {
        "app": APP_NAME,
        "prompt_versions": {
            "agent": PROMPT_VERSION,
            "exam": EXAM_PROMPT_VERSION,
            "judge": JUDGE_PROMPT_VERSION,
            "gaps": GAPS_PROMPT_VERSION,
        },
        "models": {
            "answer": settings.gemini_model_fast,
            "judge": settings.gemini_model_judge,
            "embedding": settings.gemini_embedding_model,
            "embedding_dim": settings.embedding_dim,
        },
        "retrieval": {
            "method": "hybrid: Postgres full-text + pgvector cosine, fused with RRF",
            "retrieve_k": settings.retrieve_k,
            "candidates_per_retriever": settings.retrieve_candidates,
            "rrf_k": settings.rrf_k,
        },
        "chunking": {
            "split_on": "markdown headings",
            "target_tokens": settings.chunk_target_tokens,
            "min_tokens": settings.chunk_min_tokens,
            "max_tokens": settings.chunk_max_tokens,
            "overlap_tokens": settings.chunk_overlap_tokens,
        },
    }


def handover_markdown(
    *,
    site: str,
    pages: int,
    card: Scorecard,
    graded: Sequence[GradedQuestion],
    missing: Sequence[GapTopic],
    hard: Sequence[HardToFind],
    config: dict[str, Any],
) -> str:
    lines = [
        f"# {APP_NAME} handover: {site}",
        "",
        f"**Verdict: {VERDICT_LABELS[card.verdict]}** · score {card.score:.0f}/100 · "
        f"answerable accuracy {card.answerable_accuracy:.0%} · "
        f"hallucinations {card.hallucinations} · "
        f"injection tests {'all passed' if card.injection_all_pass else 'FAILED'}",
        "",
        "## What the agent covers",
        f"Built from {pages} help-center pages. Exam results by category:",
        "",
    ]
    for category, scores in card.category_scores.items():
        lines.append(
            f"- {category}: {scores['passed']:g}/{scores['total']:g} ({scores['rate']:.0%})"
        )

    failures = [g for g in graded if not g.passed][:MAX_LISTED_FAILURES]
    lines += ["", "## Known failure modes"]
    lines += [
        f"- [{g.category} · {g.verdict}] {g.question} — {g.judge_reason}" for g in failures
    ] or ["- None found in this exam."]

    lines += [
        "",
        "## Gaps to fix first",
        "",
        "**Missing content** (customers ask, docs don't say):",
    ]
    lines += [f"- {t.topic}: {t.suggestion}" for t in missing] or ["- None found."]
    lines += ["", "**Hard to find** (the answer exists but search missed it):"]
    lines += [
        f"- {h.question} → answered at {h.page_url} ({h.heading_path}). "
        "Give it its own page or a clearer heading."
        for h in hard
    ] or ["- None found."]

    lines += ["", "## Recommended guardrails", *_guardrails(card)]
    lines += [
        "",
        "## How to re-run the check",
        f"Submit {site} again (POST /api/runs) after changing the docs. Settings used:",
        "",
        f"- Answer model `{config['models']['answer']}`, judge `{config['models']['judge']}`, "
        f"embeddings `{config['models']['embedding']}`",
        f"- Prompt versions: {', '.join(f'{k} {v}' for k, v in config['prompt_versions'].items())}",
        f"- Retrieval: top {config['retrieval']['retrieve_k']} chunks, "
        f"{config['retrieval']['method']}",
        "",
    ]
    return "\n".join(lines)


def _guardrails(card: Scorecard) -> list[str]:
    rules = [
        "- Keep answers grounded: show citations to customers and log every answer's sources.",
        '- Route abstentions ("I don\'t have that information") to a human support queue.',
        "- Re-run this check after every docs or prompt change; block go-live on a lower verdict.",
    ]
    if card.hallucinations:
        rules.append(
            "- Hallucinations were found: require a citation for every factual claim "
            "and review the listed cases before launch."
        )
    if not card.injection_all_pass:
        rules.append(
            "- An injection test failed: do not launch until the agent resists it; "
            "strip instruction-like text from pages before indexing."
        )
    return rules
