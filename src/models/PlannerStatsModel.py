import logging

from sqlalchemy import func, select

from .BaseDataModel import BaseDataModel
from .db_schemes import Asset, DataChunk, QuizAttempt

logger = logging.getLogger(__name__)


class PlannerStatsModel(BaseDataModel):
    """Read-only numbers the study planner needs, per card of one project."""

    def __init__(self, db_client: object):
        super().__init__(db_client=db_client)
        self.db_client = db_client

    @classmethod
    async def create_instance(cls, db_client: object):
        return cls(db_client)

    async def get_card_stats(self, project_id: int, card_ids: list[int]) -> dict[int, dict]:
        """
        {card_id: {"chars": int, "chunks": int, "accuracy": float | None, "quizzes": int}}

        - chars/chunks: how much material the card has (from its files' chunks).
        - accuracy: score / total over the student's quizzes of that card, using only the
          latest attempt of each quiz. None when the student has not taken any quiz yet.
        Every query is scoped by project_id.
        """
        card_ids = sorted({c for c in card_ids if c})
        if not card_ids:
            return {}

        stats = {c: {"chars": 0, "chunks": 0, "accuracy": None, "quizzes": 0} for c in card_ids}

        async with self.db_client() as session:
            size_rows = (
                await session.execute(
                    select(
                        Asset.card_id,
                        func.coalesce(func.sum(func.length(DataChunk.chunk_text)), 0),
                        func.count(DataChunk.chunk_id),
                    )
                    .join(Asset, DataChunk.chunk_asset_id == Asset.asset_id)
                    .where(
                        DataChunk.chunk_project_id == project_id,
                        Asset.asset_project_id == project_id,
                        Asset.card_id.in_(card_ids),
                    )
                    .group_by(Asset.card_id)
                )
            ).all()
            for card_id, chars, chunks in size_rows:
                stats[card_id]["chars"] = int(chars)
                stats[card_id]["chunks"] = int(chunks)

            # latest attempt of each quiz (PostgreSQL DISTINCT ON)
            attempt_rows = (
                await session.execute(
                    select(QuizAttempt.card_id, QuizAttempt.score, QuizAttempt.total)
                    .where(
                        QuizAttempt.project_id == project_id,
                        QuizAttempt.card_id.in_(card_ids),
                    )
                    .distinct(QuizAttempt.quiz_id)
                    .order_by(
                        QuizAttempt.quiz_id,
                        QuizAttempt.created_at.desc(),
                        QuizAttempt.attempt_id.desc(),
                    )
                )
            ).all()

        scored, possible, taken = {}, {}, {}
        for card_id, score, total in attempt_rows:
            scored[card_id] = scored.get(card_id, 0) + score
            possible[card_id] = possible.get(card_id, 0) + total
            taken[card_id] = taken.get(card_id, 0) + 1
        for card_id in taken:
            if possible[card_id] > 0:
                stats[card_id]["accuracy"] = scored[card_id] / possible[card_id]
                stats[card_id]["quizzes"] = taken[card_id]

        return stats
