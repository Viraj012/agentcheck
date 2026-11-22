"""Hybrid retrieval over one run's chunks: full-text + vector, fused with RRF."""

from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

import psycopg

from app.config import Settings
from app.indexing.store import vector_literal
from app.retrieval.rrf import rrf, rrf_scores

# plainto_tsquery ANDs every word, so a natural question rarely matches anything.
# Swapping '&' for '|' turns it into "any of these words", ranked by ts_rank_cd.
KEYWORD_SQL = """
SELECT c.id
FROM chunks c,
     LATERAL (SELECT nullif(replace(plainto_tsquery('english', %(query)s)::text, '&', '|'), '')
                     ::tsquery AS q) AS t
WHERE c.run_id = %(run_id)s AND t.q IS NOT NULL AND c.tsv @@ t.q
ORDER BY ts_rank_cd(c.tsv, t.q) DESC, c.id
LIMIT %(k)s
"""

# Iterative scan lets the HNSW index keep searching until it finds k rows for this run,
# instead of returning fewer when nearby vectors belong to other runs. relaxed_order can
# return rows slightly out of order, so we re-sort the materialized result.
VECTOR_SQL = """
WITH nearest AS MATERIALIZED (
    SELECT id, embedding <=> %(embedding)s::vector AS distance
    FROM chunks
    WHERE run_id = %(run_id)s AND embedding IS NOT NULL
    ORDER BY distance
    LIMIT %(k)s
)
SELECT id FROM nearest ORDER BY distance, id
"""

DETAILS_SQL = """
SELECT c.id, p.url, p.title, c.heading_path, c.text
FROM chunks c JOIN pages p ON p.id = c.page_id
WHERE c.id = ANY(%s)
"""


@dataclass(frozen=True)
class RetrievedChunk:
    id: int
    page_url: str
    title: str
    heading_path: str
    text: str
    score: float


async def keyword_search(
    conn: psycopg.AsyncConnection, run_id: UUID | str, query: str, *, k: int
) -> list[int]:
    cursor = await conn.execute(KEYWORD_SQL, {"query": query, "run_id": run_id, "k": k})
    return [row[0] for row in await cursor.fetchall()]


async def vector_search(
    conn: psycopg.AsyncConnection, run_id: UUID | str, embedding: Sequence[float], *, k: int
) -> list[int]:
    async with conn.transaction():
        await conn.execute("SET LOCAL hnsw.iterative_scan = relaxed_order")
        cursor = await conn.execute(
            VECTOR_SQL, {"embedding": vector_literal(embedding), "run_id": run_id, "k": k}
        )
        return [row[0] for row in await cursor.fetchall()]


async def hybrid_search(
    conn: psycopg.AsyncConnection,
    run_id: UUID | str,
    query: str,
    embedding: Sequence[float],
    settings: Settings,
) -> list[RetrievedChunk]:
    candidates = settings.retrieve_candidates
    keyword = await keyword_search(conn, run_id, query, k=candidates)
    dense = await vector_search(conn, run_id, embedding, k=candidates)
    top = rrf([keyword, dense], k=settings.rrf_k)[: settings.retrieve_k]
    return await fetch_chunks(conn, top, rrf_scores([keyword, dense], k=settings.rrf_k))


async def fetch_chunks(
    conn: psycopg.AsyncConnection, ids: Sequence[int], scores: dict[int, float]
) -> list[RetrievedChunk]:
    cursor = await conn.execute(DETAILS_SQL, (list(ids),))
    rows = {row[0]: row for row in await cursor.fetchall()}
    return [RetrievedChunk(*rows[i], score=scores[i]) for i in ids if i in rows]
