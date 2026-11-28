"""add quiz_attempts table and exam_entries.card_id

Revision ID: f2a6b8c4d1e7
Revises: d9c3a5b1f742
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "f2a6b8c4d1e7"
down_revision: Union[str, None] = "d9c3a5b1f742"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS quiz_attempts (
            attempt_id SERIAL PRIMARY KEY,
            quiz_id INTEGER NOT NULL REFERENCES quizzes(quiz_id) ON DELETE CASCADE,
            project_id INTEGER NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
            card_id INTEGER NOT NULL,
            score INTEGER NOT NULL,
            total INTEGER NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_quiz_attempts_score CHECK (total > 0 AND score >= 0 AND score <= total)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_quiz_attempts_quiz_id ON quiz_attempts (quiz_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_quiz_attempts_project_id ON quiz_attempts (project_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_quiz_attempts_card_id ON quiz_attempts (card_id)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_quiz_attempts_project_card "
        "ON quiz_attempts (project_id, card_id)"
    )

    op.execute("ALTER TABLE exam_entries ADD COLUMN IF NOT EXISTS card_id INTEGER")
    op.execute("CREATE INDEX IF NOT EXISTS ix_exam_entries_card_id ON exam_entries (card_id)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_exam_entries_card_id")
    op.execute("ALTER TABLE exam_entries DROP COLUMN IF EXISTS card_id")
    op.execute("DROP TABLE IF EXISTS quiz_attempts")
