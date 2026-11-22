"""Global count of chat messages per day, for a daily cap across all visitors.

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-22
"""

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE TABLE chat_daily (day date PRIMARY KEY, count integer NOT NULL DEFAULT 0);")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS chat_daily;")
