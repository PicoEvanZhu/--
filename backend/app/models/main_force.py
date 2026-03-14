from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, DateTime, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class MainForceSetting(Base):
    __tablename__ = "main_force_settings"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    scan_interval_minutes: Mapped[int] = mapped_column(Integer, default=180, nullable=False)
    overrides_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    last_run_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)


class MainForceScan(Base):
    __tablename__ = "main_force_scans"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    total_scanned: Mapped[int] = mapped_column(Integer, nullable=False)
    candidates_json: Mapped[str] = mapped_column(Text, nullable=False)
    config_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class MainForceJob(Base):
    __tablename__ = "main_force_jobs"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    status: Mapped[str] = mapped_column(Text, default="pending", nullable=False)
    market: Mapped[str] = mapped_column(Text, default="A股", nullable=False)
    total: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    processed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    candidates_found: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    scan_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    config_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)
