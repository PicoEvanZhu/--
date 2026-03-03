from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class AppUser(Base):
    __tablename__ = "app_users"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)
    email: Mapped[str] = mapped_column(String(120), unique=True, index=True, nullable=False)
    display_name: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    password_hash: Mapped[str] = mapped_column(String(512), nullable=False)
    role: Mapped[str] = mapped_column(String(20), default="user", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("app_users.id"), index=True, nullable=False)
    code_hash: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class UserWatchlistItem(Base):
    __tablename__ = "user_watchlist_items"
    __table_args__ = (UniqueConstraint("user_id", "symbol", name="uq_user_watchlist_symbol"),)

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("app_users.id"), index=True, nullable=False)
    symbol: Mapped[str] = mapped_column(String(20), index=True, nullable=False)
    group_name: Mapped[str] = mapped_column(String(64), default="默认分组", nullable=False)
    tags_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    alert_price_up: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    alert_price_down: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    target_position_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)


class UserPosition(Base):
    __tablename__ = "user_positions"
    __table_args__ = (UniqueConstraint("user_id", "symbol", name="uq_user_position_symbol"),)

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("app_users.id"), index=True, nullable=False)
    symbol: Mapped[str] = mapped_column(String(20), index=True, nullable=False)
    quantity: Mapped[float] = mapped_column(Float, nullable=False)
    cost_price: Mapped[float] = mapped_column(Float, nullable=False)
    stop_loss_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    take_profit_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="holding", nullable=False)
    thesis: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)


class UserPositionFollowUp(Base):
    __tablename__ = "user_position_followups"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("app_users.id"), index=True, nullable=False)
    position_id: Mapped[int] = mapped_column(ForeignKey("user_positions.id"), index=True, nullable=False)
    symbol: Mapped[str] = mapped_column(String(20), index=True, nullable=False)
    follow_date: Mapped[str] = mapped_column(String(10), nullable=False)
    stage: Mapped[str] = mapped_column(String(24), default="holding", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="open", nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    action_items_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    next_follow_date: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    confidence_score: Mapped[Optional[int]] = mapped_column(nullable=True)
    discipline_score: Mapped[Optional[int]] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)


class UserNotificationSetting(Base):
    __tablename__ = "user_notification_settings"
    __table_args__ = (UniqueConstraint("user_id", name="uq_user_notification_setting_user"),)

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("app_users.id"), index=True, nullable=False)
    enable_price_alert: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    enable_report_alert: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    enable_followup_due_alert: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)


class UserNotification(Base):
    __tablename__ = "user_notifications"
    __table_args__ = (UniqueConstraint("user_id", "event_key", name="uq_user_notification_event"),)

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("app_users.id"), index=True, nullable=False)
    event_key: Mapped[str] = mapped_column(String(190), nullable=False)
    symbol: Mapped[Optional[str]] = mapped_column(String(20), index=True, nullable=True)
    category: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    payload_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    read_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
