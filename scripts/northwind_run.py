"""Run the full readiness check on the Northwind sample with the real Gemini API.

Run from the backend folder (needs the database and GEMINI_API_KEY):
    uv run python ../scripts/northwind_run.py [--keep]

Northwind is served from fixtures/northwind/site through an in-memory transport, so no hosting
is needed; the SSRF guard still runs. The run is deleted afterwards unless --keep is given
(then you can open it with GET /api/reports/<id>).
"""

import argparse
import asyncio
import sys
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
warnings.filterwarnings("ignore", message="SOCKS support in urllib3")

from app.config import get_settings  # noqa: E402
from app.crawler.fetch import SafeFetcher  # noqa: E402
from app.crawler.local_site import static_resolver, static_site_transport  # noqa: E402
from app.db import connect  # noqa: E402
from app.llm.gemini import GeminiLLMClient, embed_limiter_for  # noqa: E402
from app.llm.limits import CallBudget, TokenBucket, Usage  # noqa: E402
from app.pipeline.run import execute_run  # noqa: E402

HOST = "northwind.test"
START = f"http://{HOST}/"


async def main(keep: bool) -> None:
    settings = get_settings()
    usage, budget = Usage(), CallBudget(settings.max_llm_calls_per_run)
    llm = GeminiLLMClient(
        settings,
        limiter=TokenBucket(settings.llm_rpm, burst=settings.llm_burst),
        embed_limiter=embed_limiter_for(settings),
        budget=budget,
        usage=usage,
    )
    fetcher = SafeFetcher(
        settings,
        resolver=static_resolver({HOST: ["93.184.216.34"]}),
        transport=static_site_transport(ROOT / "fixtures" / "northwind" / "site", HOST),
    )
    conn = await connect(settings.database_url)
    try:
        cursor = await conn.execute(
            "INSERT INTO runs (start_url, normalized_url, status) VALUES (%s, %s, 'running')"
            " RETURNING id",
            (START, START),
        )
        run_id = (await cursor.fetchone())[0]
        await conn.commit()
        status = await execute_run(
            conn, run_id, START, settings, llm=llm, fetcher=fetcher, usage=usage, budget=budget
        )
        await print_summary(conn, run_id, status, budget)
    finally:
        if not keep:
            await conn.execute("DELETE FROM runs WHERE id = %s", (run_id,))
            await conn.commit()
        await conn.close()
        await fetcher.aclose()


async def print_summary(conn, run_id, status: str, budget: CallBudget) -> None:
    run = await (await conn.execute("SELECT error FROM runs WHERE id = %s", (run_id,))).fetchone()
    print(f"run {run_id}: {status}  ·  LLM calls {budget.used}/{budget.max_calls}")
    if status != "done":
        print(f"error: {run[0]}")
        return
    report = await (
        await conn.execute(
            "SELECT score, verdict, category_scores, gaps FROM reports WHERE run_id = %s", (run_id,)
        )
    ).fetchone()
    score, verdict, categories, gaps = report
    print(
        f"verdict {verdict}  ·  score {score:.0f}  ·  hallucinations {categories['hallucinations']}"
    )
    for name, s in categories["categories"].items():
        print(f"  {name:<13} {s['passed']:g}/{s['total']:g}")
    print("missing content:")
    for topic in gaps["missing_content"]:
        print(f"  - {topic['topic']}: {'; '.join(topic['questions'])}")
    print("hard to find:")
    for item in gaps["hard_to_find"] or [{"question": "(none)", "page_url": ""}]:
        print(f"  - {item['question']} {item['page_url'] or ''}")
    rows = await (
        await conn.execute(
            """
            SELECT t.category, t.question, r.answer, r.verdict, r.judge_reason
            FROM test_cases t JOIN results r ON r.test_case_id = t.id
            WHERE t.run_id = %s
              AND (t.category = 'injection' OR r.verdict NOT IN ('correct', 'pass'))
            ORDER BY t.category, t.id
            """,
            (run_id,),
        )
    ).fetchall()
    print("injection tests and failures:")
    for category, question, answer, verdict_, reason in rows:
        print(
            f"  [{category} · {verdict_}] {question}\n      → {answer[:160]}\n      judge: {reason}"
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--keep", action="store_true", help="keep the run in the database")
    asyncio.run(main(parser.parse_args().keep))
