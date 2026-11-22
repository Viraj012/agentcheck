"""Start a readiness check, follow its progress, and read the finished report."""

from typing import Any
from uuid import UUID

import psycopg
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.crawler.urls import InvalidURLError, normalize_url
from app.deps import ConnDep, SettingsDep, TurnstileDep
from app.security import hash_ip

router = APIRouter()

EXCERPT_CHARS = 600


class CreateRun(BaseModel):
    url: str
    turnstile_token: str | None = None


class RunStatus(BaseModel):
    run_id: UUID
    status: str
    phase: str | None
    progress: float
    error: str | None
    report_id: UUID | None


LIMIT_MESSAGES = {
    "per_visitor": "You've used today's free checks. Open a sample report, or try again tomorrow.",
    "global": "Today's free checks are used up for everyone. Open a sample report, "
    "or try again tomorrow.",
}


@router.post("/api/runs", response_model=None)
async def create_run(
    body: CreateRun,
    request: Request,
    conn: ConnDep,
    settings: SettingsDep,
    turnstile: TurnstileDep,
) -> dict[str, Any] | JSONResponse:
    try:
        url = normalize_url(body.url)
    except InvalidURLError as exc:
        raise HTTPException(422, str(exc)) from exc
    ip = request.client.host if request.client else "unknown"
    if not await turnstile(body.turnstile_token, ip):
        raise HTTPException(403, "The bot check failed. Reload the page and try again.")
    cached = await _one(
        conn,
        """
        SELECT r.id FROM runs r JOIN reports rep ON rep.run_id = r.id
        WHERE r.normalized_url = %s AND r.status = 'done'
          AND r.finished_at > now() - make_interval(days => %s)
        ORDER BY r.finished_at DESC LIMIT 1
        """,
        (url, settings.cache_days),
    )
    if cached:
        return {"report_id": cached[0], "cached": True}
    in_progress = await _one(
        conn,
        "SELECT id FROM runs WHERE normalized_url = %s AND status IN ('queued', 'running')"
        " ORDER BY created_at DESC LIMIT 1",
        (url,),
    )
    if in_progress:
        return {"run_id": in_progress[0]}
    visitor = hash_ip(ip, settings.ip_hash_salt.get_secret_value())
    # One lock for all run creation: count-then-insert can't race past a limit.
    await conn.execute("SELECT pg_advisory_xact_lock(hashtext('create_run'))")
    limit = await _limit_reached(conn, visitor, settings)
    if limit:
        await conn.rollback()
        return JSONResponse(
            status_code=429, content={"detail": LIMIT_MESSAGES[limit], "limit": limit}
        )
    created = await _one(
        conn,
        "INSERT INTO runs (start_url, normalized_url, ip_hash) VALUES (%s, %s, %s) RETURNING id",
        (body.url.strip(), url, visitor),
    )
    await conn.commit()
    return {"run_id": created[0]}


async def _limit_reached(
    conn: psycopg.AsyncConnection, visitor: str, settings: SettingsDep
) -> str | None:
    row = await _one(
        conn,
        """
        SELECT count(*) FILTER (WHERE ip_hash = %s), count(*)
        FROM runs WHERE created_at > now() - interval '1 day'
        """,
        (visitor,),
    )
    if row[0] >= settings.runs_per_ip_per_day:
        return "per_visitor"
    if row[1] >= settings.max_runs_per_day:
        return "global"
    return None


@router.get("/api/samples")
async def samples(conn: ConnDep, settings: SettingsDep) -> list[dict[str, Any]]:
    """Pre-generated sample reports, in the configured order."""
    if not settings.sample_report_ids:
        return []
    cursor = await conn.execute(
        """
        SELECT rep.run_id::text, r.start_url, rep.verdict, rep.score
        FROM reports rep JOIN runs r ON r.id = rep.run_id
        WHERE rep.run_id::text = ANY(%s)
        """,
        (settings.sample_report_ids,),
    )
    found = {row[0]: row for row in await cursor.fetchall()}
    return [
        {"report_id": i, "start_url": found[i][1], "verdict": found[i][2], "score": found[i][3]}
        for i in settings.sample_report_ids
        if i in found
    ]


@router.get("/api/runs/{run_id}")
async def run_status(run_id: UUID, conn: ConnDep) -> RunStatus:
    row = await _one(
        conn,
        """
        SELECT r.id, r.status, r.phase, r.progress, r.error, rep.run_id
        FROM runs r LEFT JOIN reports rep ON rep.run_id = r.id WHERE r.id = %s
        """,
        (run_id,),
    )
    if row is None:
        raise HTTPException(404, "run not found")
    return RunStatus(
        run_id=row[0], status=row[1], phase=row[2], progress=row[3], error=row[4], report_id=row[5]
    )


@router.get("/api/reports/{run_id}")
async def get_report(run_id: UUID, conn: ConnDep) -> dict[str, Any]:
    row = await _one(
        conn,
        """
        SELECT r.start_url, r.finished_at, r.llm_calls, r.input_tokens, r.output_tokens,
               rep.score, rep.verdict, rep.category_scores, rep.gaps, rep.handover, rep.created_at,
               (SELECT count(*) FROM pages p WHERE p.run_id = r.id)
        FROM reports rep JOIN runs r ON r.id = rep.run_id WHERE rep.run_id = %s
        """,
        (run_id,),
    )
    if row is None:
        raise HTTPException(404, "report not found")
    (
        start_url,
        finished_at,
        calls,
        tokens_in,
        tokens_out,
        score,
        verdict,
        categories,
        gaps,
        handover,
        created_at,
        pages,
    ) = row
    return {
        "report_id": run_id,
        "start_url": start_url,
        "finished_at": finished_at,
        "created_at": created_at,
        "score": score,
        "verdict": verdict,
        "category_scores": categories,
        "failures": await _failures(conn, run_id),
        "gaps": gaps,
        "handover": handover,
        "usage": {
            "pages": pages,
            "llm_calls": calls,
            "input_tokens": tokens_in,
            "output_tokens": tokens_out,
        },
    }


async def _failures(conn: psycopg.AsyncConnection, run_id: UUID) -> list[dict[str, Any]]:
    cursor = await conn.execute(
        """
        SELECT t.id, t.category, t.question, t.reference_answer, r.answer, r.abstained,
               r.verdict, r.judge_reason, r.retrieved_chunk_ids, r.cited_chunk_ids,
               t.source_chunk_id
        FROM test_cases t JOIN results r ON r.test_case_id = t.id
        WHERE t.run_id = %s AND r.verdict NOT IN ('correct', 'pass')
        ORDER BY t.id
        """,
        (run_id,),
    )
    rows = await cursor.fetchall()
    chunk_ids = {chunk_id for row in rows for chunk_id in row[8]}
    chunks = await _chunk_details(conn, chunk_ids)
    return [
        {
            "test_case_id": row[0],
            "category": row[1],
            "question": row[2],
            "reference_answer": row[3],
            "answer": row[4],
            "abstained": row[5],
            "verdict": row[6],
            "judge_reason": row[7],
            "cited_ids": row[9],
            "retrieval_miss": row[10] is not None and row[10] not in row[8],
            "retrieved": [chunks[c] for c in row[8] if c in chunks],
        }
        for row in rows
    ]


async def _chunk_details(conn: psycopg.AsyncConnection, ids: set[int]) -> dict[int, dict[str, Any]]:
    cursor = await conn.execute(
        """
        SELECT c.id, p.url, c.heading_path, left(c.text, %s)
        FROM chunks c JOIN pages p ON p.id = c.page_id WHERE c.id = ANY(%s)
        """,
        (EXCERPT_CHARS, list(ids)),
    )
    return {
        row[0]: {"id": row[0], "page_url": row[1], "heading_path": row[2], "text": row[3]}
        for row in await cursor.fetchall()
    }


async def _one(conn: psycopg.AsyncConnection, sql: str, params: tuple) -> tuple | None:
    return await (await conn.execute(sql, params)).fetchone()
