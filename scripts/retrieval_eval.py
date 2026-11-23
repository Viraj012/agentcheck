"""Compare dense, keyword and hybrid retrieval on the Northwind sample site.

Run from the backend folder (needs the database and GEMINI_API_KEY):
    uv run python ../scripts/retrieval_eval.py --queries ../fixtures/northwind/queries.jsonl

Each line of the queries file: {"query": "How long do refunds take?", "page": "/returns/"}
Pages are read straight from the fixture HTML files (no crawling). Everything is written
inside one transaction that is rolled back at the end, so the database is left unchanged.
It uses about 3 LLM calls: chunk embeddings, then one batched call for all queries.
"""

import argparse
import asyncio
import json
import sys
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
warnings.filterwarnings("ignore", message="SOCKS support in urllib3")

from app.config import get_settings  # noqa: E402
from app.crawler.crawl import CrawledPage  # noqa: E402
from app.crawler.extract import extract_page  # noqa: E402
from app.crawler.store import save_pages  # noqa: E402
from app.db import connect  # noqa: E402
from app.indexing.store import index_run  # noqa: E402
from app.llm.gemini import GeminiLLMClient, embed_limiter_for  # noqa: E402
from app.llm.limits import CallBudget, TokenBucket, Usage  # noqa: E402
from app.retrieval.metrics import mean, recall_at_k, reciprocal_rank  # noqa: E402
from app.retrieval.rrf import rrf  # noqa: E402
from app.retrieval.search import keyword_search, vector_search  # noqa: E402

BASE_URL = "https://northwind.test"
K = 5


def site_path(file: Path, site: Path) -> str:
    relative = file.relative_to(site)
    if relative.name == "index.html":
        parent = relative.parent.as_posix()
        return "/" if parent == "." else f"/{parent}/"
    return f"/{relative.as_posix()}"


def load_pages(site: Path) -> list[CrawledPage]:
    pages = []
    for file in sorted(site.rglob("*.html")):
        path = site_path(file, site)
        if path.startswith("/internal/"):
            continue
        extracted = extract_page(file.read_text(), BASE_URL + path)
        pages.append(CrawledPage(BASE_URL + path, extracted.title, extracted.text, path))
    return pages


def load_queries(path: Path, known_paths: set[str]) -> list[dict[str, str]]:
    queries = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    unknown = sorted({q["page"] for q in queries} - known_paths)
    if unknown:
        raise SystemExit(f"queries reference pages that don't exist: {unknown}")
    return queries


async def main(queries_file: Path, site: Path, verbose: bool) -> None:
    settings = get_settings()
    pages = load_pages(site)
    queries = load_queries(queries_file, {page.content_hash for page in pages})
    usage = Usage()
    llm = GeminiLLMClient(
        settings,
        limiter=TokenBucket(settings.llm_rpm, burst=settings.llm_burst),
        embed_limiter=embed_limiter_for(settings),
        budget=CallBudget(settings.max_llm_calls_per_run),
        usage=usage,
    )
    conn = await connect(settings.database_url)
    try:
        cursor = await conn.execute(
            "INSERT INTO runs (start_url, normalized_url) VALUES (%s, %s) RETURNING id",
            (BASE_URL + "/", BASE_URL + "/"),
        )
        run_id = (await cursor.fetchone())[0]
        await save_pages(conn, run_id, pages)
        chunk_count = await index_run(conn, run_id, llm, settings)
        cursor = await conn.execute(
            "SELECT c.id, p.url FROM chunks c JOIN pages p ON p.id = c.page_id WHERE c.run_id = %s",
            (run_id,),
        )
        rows = await cursor.fetchall()
        page_of = {chunk_id: url.removeprefix(BASE_URL) for chunk_id, url in rows}
        embeddings = await llm.embed([q["query"] for q in queries], task="query")

        details: list[str] = []
        results: dict[str, dict[str, list[float]]] = {
            name: {"recall": [], "rr": []} for name in ("dense", "keyword", "hybrid")
        }
        for query, embedding in zip(queries, embeddings, strict=True):
            candidates = settings.retrieve_candidates
            dense = await vector_search(conn, run_id, embedding, k=candidates)
            keyword = await keyword_search(conn, run_id, query["query"], k=candidates)
            hybrid = rrf([keyword, dense], k=settings.rrf_k)
            ranks = []
            for name, ranked in (("dense", dense), ("keyword", keyword), ("hybrid", hybrid)):
                ranked_pages = [page_of[chunk_id] for chunk_id in ranked]
                results[name]["recall"].append(recall_at_k(ranked_pages, query["page"], k=K))
                rr = reciprocal_rank(ranked_pages, query["page"])
                results[name]["rr"].append(rr)
                ranks.append(f"{name}={round(1 / rr) if rr else '-'}")
            details.append(f"  {' '.join(ranks):<28} {query['page']:<28} {query['query'][:60]}")
    finally:
        await conn.rollback()
        await conn.close()

    print(f"{len(pages)} pages, {chunk_count} chunks, {len(queries)} queries")
    print(f"{'retriever':<10} {'recall@' + str(K):>9} {'MRR':>7}")
    for name, scores in results.items():
        print(f"{name:<10} {mean(scores['recall']):>9.3f} {mean(scores['rr']):>7.3f}")
    if verbose:
        print("\nrank of the correct page per query (1 = first):")
        print("\n".join(details))
    print(f"LLM calls used: {usage.calls}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--queries", type=Path, default=ROOT / "fixtures/northwind/queries.jsonl")
    parser.add_argument("--site", type=Path, default=ROOT / "fixtures/northwind/site")
    parser.add_argument("--verbose", action="store_true", help="print per-query ranks")
    args = parser.parse_args()
    asyncio.run(main(args.queries, args.site, args.verbose))
