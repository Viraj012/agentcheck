"""Per-visitor chat counter for each report.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-21
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE chat_usage (
            run_id   uuid NOT NULL REFERENCES runs (id) ON DELETE CASCADE,
            ip_hash  text NOT NULL,
            count    integer NOT NULL DEFAULT 0,
            PRIMARY KEY (run_id, ip_hash)
        );
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS chat_usage;")
