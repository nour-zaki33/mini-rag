"""add user_id to projects (one project per user)

Revision ID: d9c3a5b1f742
Revises: b7d2e4f6a913
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "d9c3a5b1f742"
down_revision: Union[str, None] = "b7d2e4f6a913"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # nullable: old projects have no user until you assign one by hand.
    # UNIQUE: one user can have only one project (several NULLs are allowed).
    op.execute("ALTER TABLE projects ADD COLUMN IF NOT EXISTS user_id INTEGER REFERENCES users (user_id)")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS projects_user_id_key ON projects (user_id)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS projects_user_id_key")
    op.execute("ALTER TABLE projects DROP COLUMN IF EXISTS user_id")
