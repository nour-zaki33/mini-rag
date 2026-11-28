"""add users table

Revision ID: b7d2e4f6a913
Revises: a3f1c9d7e582
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "b7d2e4f6a913"
down_revision: Union[str, None] = "a3f1c9d7e582"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id SERIAL PRIMARY KEY,
            email VARCHAR(255) NOT NULL,
            password_hash VARCHAR(255) NOT NULL,
            is_active BOOLEAN NOT NULL DEFAULT true,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ
        )
    """)
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS users_email_key ON users (email)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS users_email_key")
    op.execute("DROP TABLE IF EXISTS users")
