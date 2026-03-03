from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, DateTime, Float, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class StockUniverse(Base):
    __tablename__ = "stock_universe"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    symbol: Mapped[str] = mapped_column(String(20), unique=True, index=True, nullable=False)
    code: Mapped[str] = mapped_column(String(16), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), index=True, nullable=False)
    market: Mapped[str] = mapped_column(String(16), index=True, nullable=False)
    board: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    exchange: Mapped[str] = mapped_column(String(16), index=True, nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    listed: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    change_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    volume: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    turnover: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)

