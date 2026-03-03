from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class TradeReview(Base):
    __tablename__ = "trade_reviews"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    symbol: Mapped[str] = mapped_column(String(20), index=True, nullable=False)
    user_id: Mapped[Optional[int]] = mapped_column(Integer, index=True, nullable=True)

    trade_date: Mapped[str] = mapped_column(String(10), nullable=False)
    action: Mapped[str] = mapped_column(String(16), nullable=False)
    price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    quantity: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    thesis: Mapped[str] = mapped_column(Text, nullable=False)
    execution_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    outcome_review: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    lessons_learned: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    follow_up_items_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    follow_up_status: Mapped[str] = mapped_column(String(20), default="open", nullable=False)
    next_review_date: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)

    confidence_score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    discipline_score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)
