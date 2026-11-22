"""Chunk a run's pages, embed the chunks, and store them for search."""

from collections.abc import Sequence
from uuid import UUID

import psycopg

from app.config import Settings
from app.indexing.chunker import PATH_SEPARATOR, chunk_page
from app.llm.base import LLMClient

INSERT_CHUNK = """
INSERT INTO chunks (run_id, page_id, heading_path, text, embedding)
VALUES (%s, %s, %s, %s, %s::vector)
"""


def vector_literal(values: Sequence[float]) -> str:
    """pgvector's text format, so we need no extra adapter library."""
    return "[" + ",".join(f"{v:.7g}" for v in values) + "]"


async def index_run(
    conn: psycopg.AsyncConnection, run_id: UUID | str, llm: LLMClient, settings: Settings
) -> int:
    cursor = await conn.execute(
        "SELECT id, title, text FROM pages WHERE run_id = %s ORDER BY id", (run_id,)
    )
    rows = await cursor.fetchall()
    items = [
        (page_id, title, chunk)
        for page_id, title, text in rows
        for chunk in chunk_page(text, settings)
    ]
    if not items:
        return 0
    embeddings = await llm.embed(
        [chunk.text for _, _, chunk in items],
        task="document",
        titles=[
            PATH_SEPARATOR.join(filter(None, [title, chunk.heading_path]))
            for _, title, chunk in items
        ],
    )
    async with conn.cursor() as insert:
        await insert.executemany(
            INSERT_CHUNK,
            [
                (run_id, page_id, chunk.heading_path, chunk.text, vector_literal(embedding))
                for (page_id, _, chunk), embedding in zip(items, embeddings, strict=True)
            ],
        )
    return len(items)
