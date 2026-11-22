"""Run one readiness check end to end: crawl → index → exam → answer → grade → report."""

import logging
import time
from dataclasses import asdict
from uuid import UUID

import psycopg

from app.agent.agent import AgentQuestion, answer_questions
from app.config import Settings
from app.crawler.crawl import CrawlError, crawl
from app.crawler.fetch import SafeFetcher
from app.crawler.store import save_pages
from app.exam.gaps import group_missing_content, hard_to_find
from app.exam.generate import generate_exam, sample_source_chunks, site_outline
from app.exam.grade import GradeItem, grade
from app.exam.handover import handover_config, handover_markdown
from app.exam.models import GradedQuestion
from app.exam.score import score_run
from app.indexing.store import index_run
from app.llm.base import LLMClient, LLMError
from app.llm.limits import CallBudget, LLMBudgetExceeded, Usage
from app.pipeline import store
from app.retrieval.search import RetrievedChunk, hybrid_search

log = logging.getLogger(__name__)

NEEDS_JS_MESSAGE = (
    "This site renders its content with JavaScript, so almost no text could be read. "
    "Help centers that serve plain HTML work best."
)


async def execute_run(
    conn: psycopg.AsyncConnection,
    run_id: UUID,
    start_url: str,
    settings: Settings,
    *,
    llm: LLMClient,
    fetcher: SafeFetcher,
    usage: Usage,
    budget: CallBudget,
) -> str:
    """Returns the final status: done, needs_js or failed. Never raises for a run's own errors."""
    try:
        status = await _phases(conn, run_id, start_url, settings, llm, fetcher)
        error = NEEDS_JS_MESSAGE if status == "needs_js" else None
    except CrawlError as exc:
        status, error = "failed", str(exc)
    except LLMBudgetExceeded:
        status, error = "failed", f"stopped after reaching the limit of {budget.max_calls} AI calls"
    except LLMError as exc:
        status, error = "failed", f"AI service error: {exc}"
    except Exception:
        log.exception("run %s crashed", run_id)
        status, error = "failed", "internal error"
    await conn.rollback()  # discard a failed phase's partial writes; earlier phases are committed
    await store.finish_run(conn, run_id, status, usage, budget, error)
    return status


async def _phases(
    conn: psycopg.AsyncConnection,
    run_id: UUID,
    start_url: str,
    settings: Settings,
    llm: LLMClient,
    fetcher: SafeFetcher,
) -> str:
    await store.set_progress(conn, run_id, "crawling", 0.05)
    crawled = await crawl(start_url, settings, fetcher)
    if crawled.needs_js:
        return "needs_js"
    if not crawled.pages:
        raise CrawlError("no pages with readable text were found")
    await save_pages(conn, run_id, crawled.pages)

    await store.set_progress(conn, run_id, "indexing", 0.25)
    await index_run(conn, run_id, llm, settings)

    await store.set_progress(conn, run_id, "writing_exam", 0.4)
    chunks = await store.load_source_chunks(conn, run_id)
    sources = sample_source_chunks(chunks, settings.num_answerable, seed=str(run_id))
    cases = await generate_exam(llm, site_outline(chunks), sources, settings)
    case_ids = await store.insert_test_cases(conn, run_id, cases)

    await store.set_progress(conn, run_id, "answering", 0.55)
    questions = [case.question for case in cases]
    embeddings = await llm.embed(questions, task="query")
    items = [
        AgentQuestion(
            case_id, case.question, await hybrid_search(conn, run_id, case.question, emb, settings)
        )
        for case_id, case, emb in zip(case_ids, cases, embeddings, strict=True)
    ]
    retrieved = {item.id: item.chunks for item in items}
    for start in range(0, len(items), settings.answer_batch):
        batch = items[start : start + settings.answer_batch]
        began = time.monotonic()
        results = await answer_questions(llm, batch)
        per_question = int((time.monotonic() - began) * 1000 / len(batch))
        await store.insert_results(conn, results, {r.question_id: per_question for r in results})
        await store.heartbeat(conn, run_id)

    await store.set_progress(conn, run_id, "grading", 0.75)
    graded_so_far = await store.load_graded(conn, run_id)
    to_grade = [_grade_item(g, retrieved[g.test_case_id]) for g in graded_so_far]
    for start in range(0, len(to_grade), settings.grade_batch):
        grades = await grade(llm, to_grade[start : start + settings.grade_batch], settings)
        await store.save_grades(conn, grades)
        await store.heartbeat(conn, run_id)

    await store.set_progress(conn, run_id, "report", 0.9)
    graded = await store.load_graded(conn, run_id)
    await _report(conn, run_id, start_url, settings, llm, graded, page_count=len(crawled.pages))
    await conn.commit()
    return "done"


async def _report(
    conn: psycopg.AsyncConnection,
    run_id: UUID,
    start_url: str,
    settings: Settings,
    llm: LLMClient,
    graded: list[GradedQuestion],
    *,
    page_count: int,
) -> None:
    card = score_run([(g.category, g.verdict) for g in graded], settings)
    unanswerable = [(g.test_case_id, g.question) for g in graded if g.category == "unanswerable"]
    questions = dict(unanswerable)
    missing = await group_missing_content(llm, unanswerable)
    hard = hard_to_find(graded)
    config = handover_config(settings)
    await store.save_report(
        conn,
        run_id,
        score=card.score,
        verdict=card.verdict,
        category_scores={
            "categories": card.category_scores,
            "answerable_accuracy": card.answerable_accuracy,
            "hallucinations": card.hallucinations,
            "injection_tested": card.injection_tested,
            "injection_all_pass": card.injection_all_pass,
        },
        gaps={
            "missing_content": [
                {
                    "topic": t.topic,
                    "suggestion": t.suggestion,
                    "questions": [questions[i] for i in t.question_ids],
                }
                for t in missing
            ],
            "hard_to_find": [asdict(h) for h in hard],
        },
        handover={
            "config": config,
            "markdown": handover_markdown(
                site=start_url,
                pages=page_count,
                card=card,
                graded=graded,
                missing=missing,
                hard=hard,
                config=config,
            ),
        },
    )


def _grade_item(g: GradedQuestion, chunks: list[RetrievedChunk]) -> GradeItem:
    return GradeItem(
        id=g.test_case_id,
        category=g.category,
        question=g.question,
        reference_answer=g.reference_answer,
        answer=g.answer,
        abstained=g.abstained,
        context=[(chunk.id, chunk.text) for chunk in chunks],
    )
