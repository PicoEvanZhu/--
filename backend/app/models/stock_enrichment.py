from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class StockEnrichment(Base):
    __tablename__ = "stock_enrichment"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    symbol: Mapped[str] = mapped_column(String(20), unique=True, index=True, nullable=False)

    source: Mapped[str] = mapped_column(String(64), default="mixed_web_sources", nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="success", nullable=False)
    coverage_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    company_full_name: Mapped[Optional[str]] = mapped_column(String(240), nullable=True)
    english_name: Mapped[Optional[str]] = mapped_column(String(240), nullable=True)
    listing_date: Mapped[Optional[str]] = mapped_column(String(24), nullable=True)

    company_website: Mapped[Optional[str]] = mapped_column(String(320), nullable=True)
    investor_relations_url: Mapped[Optional[str]] = mapped_column(String(320), nullable=True)
    exchange_profile_url: Mapped[Optional[str]] = mapped_column(String(320), nullable=True)
    quote_url: Mapped[Optional[str]] = mapped_column(String(320), nullable=True)

    headquarters: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    legal_representative: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    employees: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    main_business: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    company_intro: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    products_services_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    key_risks_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    catalyst_events_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    news_highlights_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    financial_reports_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    valuation_history_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    dividend_history_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    shareholder_structure_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    peer_companies_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    raw_payload_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)
