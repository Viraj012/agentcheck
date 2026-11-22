"""Keep citations the agent made to chunks it was never given (a grading signal).

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-21
"""

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE results ADD COLUMN invalid_cited_ids bigint[] NOT NULL DEFAULT '{}';")


def downgrade() -> None:
    op.execute("ALTER TABLE results DROP COLUMN IF EXISTS invalid_cited_ids;")
