"""Initial schema: runs (also the job queue), pages, chunks, exam and report tables.

The embedding dimension (768) must equal Settings.embedding_dim; a test enforces this.
Changing it needs a new migration, because pgvector fixes the dimension in the column type.

Revision ID: 0001
Revises:
Create Date: 2026-11-21
"""

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

UPGRADE_SQL = """
CREATE EXTENSION IF NOT EXISTS vector;

-- runs is also the job queue: workers claim rows with SELECT ... FOR UPDATE SKIP LOCKED.
CREATE TABLE runs (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    start_url       text NOT NULL,
    normalized_url  text NOT NULL,
    status          text NOT NULL DEFAULT 'queued'
                    CHECK (status IN ('queued', 'running', 'needs_js', 'failed', 'done')),
    phase           text,
    progress        real NOT NULL DEFAULT 0 CHECK (progress BETWEEN 0 AND 1),
    error           text,
    ip_hash         text,
    input_tokens    integer NOT NULL DEFAULT 0,
    output_tokens   integer NOT NULL DEFAULT 0,
    llm_calls       integer NOT NULL DEFAULT 0,
    created_at      timestamptz NOT NULL DEFAULT now(),
    started_at      timestamptz,
    finished_at     timestamptz,
    locked_at       timestamptz,
    attempts        integer NOT NULL DEFAULT 0
);
CREATE INDEX runs_queue_idx ON runs (status, created_at);
CREATE INDEX runs_cache_idx ON runs (normalized_url, finished_at) WHERE status = 'done';
CREATE INDEX runs_ip_day_idx ON runs (ip_hash, created_at);

CREATE TABLE pages (
    id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id        uuid NOT NULL REFERENCES runs (id) ON DELETE CASCADE,
    url           text NOT NULL,
    title         text,
    content_hash  text NOT NULL,
    text          text NOT NULL,
    UNIQUE (run_id, url),
    UNIQUE (run_id, content_hash)
);

CREATE TABLE chunks (
    id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id        uuid NOT NULL REFERENCES runs (id) ON DELETE CASCADE,
    page_id       bigint NOT NULL REFERENCES pages (id) ON DELETE CASCADE,
    heading_path  text NOT NULL DEFAULT '',
    text          text NOT NULL,
    tsv           tsvector GENERATED ALWAYS AS
                  (to_tsvector('english', heading_path || ' ' || text)) STORED,
    embedding     vector(768)
);
CREATE INDEX chunks_run_idx ON chunks (run_id);
CREATE INDEX chunks_tsv_gin ON chunks USING gin (tsv);
CREATE INDEX chunks_embedding_hnsw ON chunks USING hnsw (embedding vector_cosine_ops);

CREATE TABLE test_cases (
    id                bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id            uuid NOT NULL REFERENCES runs (id) ON DELETE CASCADE,
    category          text NOT NULL
                      CHECK (category IN
                      ('answerable', 'unanswerable', 'out_of_scope', 'injection')),
    question          text NOT NULL,
    source_chunk_id   bigint REFERENCES chunks (id) ON DELETE SET NULL,
    reference_answer  text
);
CREATE INDEX test_cases_run_idx ON test_cases (run_id);

CREATE TABLE results (
    id                   bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    test_case_id         bigint NOT NULL UNIQUE REFERENCES test_cases (id) ON DELETE CASCADE,
    answer               text NOT NULL,
    abstained            boolean NOT NULL,
    cited_chunk_ids      bigint[] NOT NULL DEFAULT '{}',
    retrieved_chunk_ids  bigint[] NOT NULL DEFAULT '{}',
    verdict              text CHECK (verdict IN
                         ('correct', 'partial', 'incorrect', 'hallucinated', 'pass', 'fail')),
    judge_reason         text,
    latency_ms           integer
);

-- A report's id is its run's id.
CREATE TABLE reports (
    run_id           uuid PRIMARY KEY REFERENCES runs (id) ON DELETE CASCADE,
    score            real NOT NULL,
    verdict          text NOT NULL CHECK (verdict IN ('ready', 'needs_work', 'not_ready')),
    category_scores  jsonb NOT NULL,
    gaps             jsonb NOT NULL,
    handover         jsonb NOT NULL,
    created_at       timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE judge_labels (
    id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    result_id      bigint NOT NULL REFERENCES results (id) ON DELETE CASCADE,
    human_verdict  text NOT NULL CHECK (human_verdict IN
                   ('correct', 'partial', 'incorrect', 'hallucinated', 'pass', 'fail')),
    note           text,
    created_at     timestamptz NOT NULL DEFAULT now()
);
"""

DOWNGRADE_SQL = """
DROP TABLE IF EXISTS judge_labels, reports, results, test_cases, chunks, pages, runs;
"""


def upgrade() -> None:
    op.execute(UPGRADE_SQL)


def downgrade() -> None:
    op.execute(DOWNGRADE_SQL)
