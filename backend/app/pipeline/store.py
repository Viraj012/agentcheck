"""SQL for the pipeline: run progress, exam questions, answers, grades and the report."""

import json
from collections.abc import Sequence
from typing import Any
from uuid import UUID

import psycopg

from app.agent.agent import AgentResult
from app.exam.generate import NewTestCase, SourceChunk
from app.exam.grade import Grade
from app.exam.models import GradedQuestion
from app.llm.limits import CallBudget, Usage


async def set_progress(
    conn: psycopg.AsyncConnection, run_id: UUID, phase: str, progress: float
) -> None:
    """Record the phase; also refreshes locked_at, which is the worker's heartbeat."""
    await conn.execute(
        "UPDATE runs SET phase = %s, progress = %s, locked_at = now() WHERE id = %s",
        (phase, progress, run_id),
    )
    await conn.commit()


async def finish_run(
    conn: psycopg.AsyncConnection,
    run_id: UUID,
    status: str,
    usage: Usage,
    budget: CallBudget,
    error: str | None = None,
) -> None:
    await conn.execute(
        """
        UPDATE runs SET status = %s, error = %s, finished_at = now(), locked_at = NULL,
               progress = CASE WHEN %s = 'done' THEN 1 ELSE progress END,
               input_tokens = %s, output_tokens = %s, llm_calls = %s
        WHERE id = %s
        """,
        (status, error, status, usage.input_tokens, usage.output_tokens, budget.used, run_id),
    )
    await conn.commit()


async def clear_run_data(conn: psycopg.AsyncConnection, run_id: UUID) -> None:
    """Remove everything a previous attempt produced, so a retried run starts clean."""
    for table in ("reports", "chat_usage", "test_cases", "pages"):
        await conn.execute(f"DELETE FROM {table} WHERE run_id = %s", (run_id,))
    await conn.commit()


async def load_source_chunks(conn: psycopg.AsyncConnection, run_id: UUID) -> list[SourceChunk]:
    cursor = await conn.execute(
        """
        SELECT c.id, p.url, p.title, c.heading_path, c.text
        FROM chunks c JOIN pages p ON p.id = c.page_id
        WHERE c.run_id = %s ORDER BY c.id
        """,
        (run_id,),
    )
    return [SourceChunk(*row) for row in await cursor.fetchall()]


async def insert_test_cases(
    conn: psycopg.AsyncConnection, run_id: UUID, cases: Sequence[NewTestCase]
) -> list[int]:
    ids = []
    for case in cases:
        cursor = await conn.execute(
            """
            INSERT INTO test_cases (run_id, category, question, source_chunk_id, reference_answer)
            VALUES (%s, %s, %s, %s, %s) RETURNING id
            """,
            (run_id, case.category, case.question, case.source_chunk_id, case.reference_answer),
        )
        ids.append((await cursor.fetchone())[0])
    return ids


async def insert_results(
    conn: psycopg.AsyncConnection, results: Sequence[AgentResult], latency_ms: dict[int, int]
) -> None:
    async with conn.cursor() as cursor:
        await cursor.executemany(
            """
            INSERT INTO results (test_case_id, answer, abstained, cited_chunk_ids,
                                 retrieved_chunk_ids, invalid_cited_ids, latency_ms)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            [
                (
                    r.question_id,
                    r.answer,
                    r.abstained,
                    r.citations,
                    r.retrieved_ids,
                    r.invalid_citations,
                    latency_ms.get(r.question_id),
                )
                for r in results
            ],
        )


async def save_grades(conn: psycopg.AsyncConnection, grades: Sequence[Grade]) -> None:
    async with conn.cursor() as cursor:
        await cursor.executemany(
            "UPDATE results SET verdict = %s, judge_reason = %s WHERE test_case_id = %s",
            [(g.verdict, g.reason, g.item_id) for g in grades],
        )


async def load_graded(conn: psycopg.AsyncConnection, run_id: UUID) -> list[GradedQuestion]:
    cursor = await conn.execute(
        """
        SELECT t.id, t.category, t.question, t.reference_answer, r.answer, r.abstained,
               r.verdict, r.judge_reason, r.retrieved_chunk_ids, r.cited_chunk_ids,
               r.invalid_cited_ids, t.source_chunk_id, p.url, c.heading_path
        FROM test_cases t
        JOIN results r ON r.test_case_id = t.id
        LEFT JOIN chunks c ON c.id = t.source_chunk_id
        LEFT JOIN pages p ON p.id = c.page_id
        WHERE t.run_id = %s ORDER BY t.id
        """,
        (run_id,),
    )
    return [GradedQuestion(*row) for row in await cursor.fetchall()]


async def chunk_texts(conn: psycopg.AsyncConnection, ids: Sequence[int]) -> dict[int, str]:
    cursor = await conn.execute("SELECT id, text FROM chunks WHERE id = ANY(%s)", (list(ids),))
    return dict(await cursor.fetchall())


async def save_report(
    conn: psycopg.AsyncConnection,
    run_id: UUID,
    *,
    score: float,
    verdict: str,
    category_scores: dict[str, Any],
    gaps: dict[str, Any],
    handover: dict[str, Any],
) -> None:
    await conn.execute(
        """
        INSERT INTO reports (run_id, score, verdict, category_scores, gaps, handover)
        VALUES (%s, %s, %s, %s, %s, %s)
        """,
        (
            run_id,
            score,
            verdict,
            json.dumps(category_scores),
            json.dumps(gaps),
            json.dumps(handover),
        ),
    )
