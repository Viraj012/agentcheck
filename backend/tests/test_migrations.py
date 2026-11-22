import uuid
from collections.abc import Iterator

import psycopg
import pytest
from alembic import command

from app.config import Settings
from tests.conftest import alembic_config

pytestmark = pytest.mark.db

TABLES = {
    "runs",
    "pages",
    "chunks",
    "test_cases",
    "results",
    "reports",
    "judge_labels",
    "chat_usage",
}


@pytest.fixture
def conn(migrated_url: str) -> Iterator[psycopg.Connection]:
    with psycopg.connect(migrated_url) as connection:
        yield connection
        connection.rollback()


def table_names(conn: psycopg.Connection) -> set[str]:
    rows = conn.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
    ).fetchall()
    return {name for (name,) in rows}


def insert_chunk(conn: psycopg.Connection, text: str) -> uuid.UUID:
    run_id = conn.execute(
        "INSERT INTO runs (start_url, normalized_url) VALUES ('https://x.test/', 'https://x.test/')"
        " RETURNING id"
    ).fetchone()[0]
    page_id = conn.execute(
        "INSERT INTO pages (run_id, url, title, content_hash, text)"
        " VALUES (%s, 'https://x.test/a', 'A', 'h1', %s) RETURNING id",
        (run_id, text),
    ).fetchone()[0]
    conn.execute(
        "INSERT INTO chunks (run_id, page_id, heading_path, text) VALUES (%s, %s, 'Returns', %s)",
        (run_id, page_id, text),
    )
    return run_id


def test_all_tables_exist(conn: psycopg.Connection) -> None:
    assert table_names(conn) >= TABLES


def test_embedding_dim_matches_config(conn: psycopg.Connection) -> None:
    column_type = conn.execute(
        "SELECT format_type(atttypid, atttypmod) FROM pg_attribute"
        " WHERE attrelid = 'chunks'::regclass AND attname = 'embedding'"
    ).fetchone()[0]
    assert column_type == f"vector({Settings(_env_file=None).embedding_dim})"


def test_search_indexes_exist(conn: psycopg.Connection) -> None:
    indexes = dict(
        conn.execute("SELECT indexname, indexdef FROM pg_indexes WHERE tablename = 'chunks'")
    )
    assert "USING hnsw (embedding vector_cosine_ops)" in indexes["chunks_embedding_hnsw"]
    assert "USING gin (tsv)" in indexes["chunks_tsv_gin"]


def test_tsv_is_generated_from_text(conn: psycopg.Connection) -> None:
    run_id = insert_chunk(conn, "Refunds are issued to the original payment method.")
    matches = conn.execute(
        "SELECT count(*) FROM chunks"
        " WHERE run_id = %s AND tsv @@ plainto_tsquery('english', 'refund')",
        (run_id,),
    ).fetchone()[0]
    assert matches == 1


def test_run_status_rejects_unknown_value(conn: psycopg.Connection) -> None:
    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute(
            "INSERT INTO runs (start_url, normalized_url, status) VALUES ('u', 'u', 'paused')"
        )


def test_new_run_is_queued(conn: psycopg.Connection) -> None:
    run_id = insert_chunk(conn, "text")
    status, attempts = conn.execute(
        "SELECT status, attempts FROM runs WHERE id = %s", (run_id,)
    ).fetchone()
    assert (status, attempts) == ("queued", 0)


def test_deleting_run_cascades_to_children(conn: psycopg.Connection) -> None:
    run_id = insert_chunk(conn, "text")
    conn.execute("DELETE FROM runs WHERE id = %s", (run_id,))
    assert (
        conn.execute("SELECT count(*) FROM chunks WHERE run_id = %s", (run_id,)).fetchone()[0] == 0
    )


def test_downgrade_then_upgrade_round_trips(migrated_url: str) -> None:
    config = alembic_config(migrated_url)
    command.downgrade(config, "base")
    with psycopg.connect(migrated_url) as connection:
        assert not TABLES & table_names(connection)
    command.upgrade(config, "head")
    with psycopg.connect(migrated_url) as connection:
        assert table_names(connection) >= TABLES


def test_results_record_invalid_citations(conn: psycopg.Connection) -> None:
    column = conn.execute(
        "SELECT format_type(atttypid, atttypmod) FROM pg_attribute"
        " WHERE attrelid = 'results'::regclass AND attname = 'invalid_cited_ids'"
    ).fetchone()
    assert column == ("bigint[]",)
