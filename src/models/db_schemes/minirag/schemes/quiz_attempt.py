from sqlalchemy import Column, Integer, DateTime, ForeignKey, Index, CheckConstraint, func
from .minirag_base import SQLAlchemyBase


class QuizAttempt(SQLAlchemyBase):
    """One submitted quiz and its score. The study planner reads these to find weak subjects."""

    __tablename__ = "quiz_attempts"

    attempt_id = Column(Integer, primary_key=True, autoincrement=True)

    quiz_id = Column(
        Integer,
        ForeignKey("quizzes.quiz_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    project_id = Column(
        Integer,
        ForeignKey("projects.project_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    card_id = Column(Integer, nullable=False, index=True)

    score = Column(Integer, nullable=False)
    total = Column(Integer, nullable=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("ix_quiz_attempts_project_card", "project_id", "card_id"),
        CheckConstraint(
            "total > 0 AND score >= 0 AND score <= total", name="ck_quiz_attempts_score"
        ),
    )
