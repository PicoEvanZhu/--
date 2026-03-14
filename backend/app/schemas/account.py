from datetime import datetime
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


FollowUpStatus = Literal["open", "in_progress", "closed"]
FollowUpStage = Literal["pre_open", "holding", "rebalancing", "exit_review"]
PositionStatus = Literal["holding", "closed", "watch_only"]
UserRole = Literal["user", "admin"]
NotificationType = Literal["price_alert", "report_alert", "followup_due", "watch_monitor"]


class UserPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    email: str
    display_name: Optional[str]
    role: str
    is_active: bool
    created_at: datetime
    last_login_at: Optional[datetime]


class RegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=50)
    email: str = Field(min_length=5, max_length=120)
    password: str = Field(min_length=8, max_length=128)
    display_name: Optional[str] = Field(default=None, max_length=120)


class LoginRequest(BaseModel):
    account: str = Field(min_length=3, max_length=120)
    password: str = Field(min_length=8, max_length=128)


class PasswordForgotRequest(BaseModel):
    account: str = Field(min_length=3, max_length=120)


class PasswordForgotResponse(BaseModel):
    message: str
    expires_in_minutes: int
    reset_code: Optional[str] = None


class PasswordResetRequest(BaseModel):
    account: str = Field(min_length=3, max_length=120)
    code: str = Field(min_length=4, max_length=20)
    new_password: str = Field(min_length=8, max_length=128)


class PasswordResetResponse(BaseModel):
    message: str


class AuthTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserPublic


MonitorIntervalMinutes = Literal[1, 5, 10, 15, 30, 60]


class WatchlistItemBase(BaseModel):
    symbol: str = Field(min_length=4, max_length=20)
    group_name: str = Field(default="默认分组", min_length=1, max_length=64)
    tags: List[str] = Field(default_factory=list)
    note: Optional[str] = None
    alert_price_up: Optional[float] = Field(default=None, gt=0)
    alert_price_down: Optional[float] = Field(default=None, gt=0)
    target_position_pct: Optional[float] = Field(default=None, ge=0, le=100)
    monitor_enabled: bool = False
    monitor_interval_minutes: MonitorIntervalMinutes = 15
    monitor_focus: List[str] = Field(default_factory=list, max_length=8)


class WatchlistItemCreate(WatchlistItemBase):
    pass


class WatchlistItemUpdate(BaseModel):
    group_name: Optional[str] = Field(default=None, min_length=1, max_length=64)
    tags: Optional[List[str]] = None
    note: Optional[str] = None
    alert_price_up: Optional[float] = Field(default=None, gt=0)
    alert_price_down: Optional[float] = Field(default=None, gt=0)
    target_position_pct: Optional[float] = Field(default=None, ge=0, le=100)
    monitor_enabled: Optional[bool] = None
    monitor_interval_minutes: Optional[MonitorIntervalMinutes] = None
    monitor_focus: Optional[List[str]] = Field(default=None, max_length=8)


class WatchlistItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    symbol: str
    name: str
    market: str
    industry: str
    current_price: float
    change_pct: float
    group_name: str
    tags: List[str]
    note: Optional[str]
    alert_price_up: Optional[float]
    alert_price_down: Optional[float]
    target_position_pct: Optional[float]
    monitor_enabled: bool = False
    monitor_interval_minutes: MonitorIntervalMinutes = 15
    monitor_focus: List[str] = Field(default_factory=list)
    monitor_last_checked_at: Optional[datetime] = None
    monitor_last_summary: Optional[str] = None
    monitor_last_signal_level: Optional[str] = None
    monitor_last_notified_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class WatchlistListResponse(BaseModel):
    total: int
    groups: List[str]
    items: List[WatchlistItem]


class PositionBase(BaseModel):
    symbol: str = Field(min_length=4, max_length=20)
    quantity: float = Field(gt=0)
    cost_price: float = Field(gt=0)
    stop_loss_price: Optional[float] = Field(default=None, gt=0)
    take_profit_price: Optional[float] = Field(default=None, gt=0)
    status: PositionStatus = "holding"
    thesis: Optional[str] = None


class PositionCreate(PositionBase):
    pass


class PositionUpdate(BaseModel):
    quantity: Optional[float] = Field(default=None, gt=0)
    cost_price: Optional[float] = Field(default=None, gt=0)
    stop_loss_price: Optional[float] = Field(default=None, gt=0)
    take_profit_price: Optional[float] = Field(default=None, gt=0)
    status: Optional[PositionStatus] = None
    thesis: Optional[str] = None


class PositionSnapshot(BaseModel):
    id: int
    symbol: str
    name: str
    market: str
    industry: str
    quantity: float
    cost_price: float
    current_price: float
    cost_value: float
    market_value: float
    pnl: float
    pnl_pct: float
    weight: float
    stop_loss_price: Optional[float]
    take_profit_price: Optional[float]
    status: PositionStatus
    thesis: Optional[str]
    latest_follow_up_status: Optional[FollowUpStatus] = None
    latest_follow_up_date: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class PositionListResponse(BaseModel):
    total: int
    items: List[PositionSnapshot]


class PositionAnalysisResponse(BaseModel):
    total_positions: int
    total_cost: float
    total_market_value: float
    total_pnl: float
    total_pnl_pct: float
    win_count: int
    loss_count: int
    concentration_top3_pct: float
    market_distribution: Dict[str, float]
    industry_distribution: Dict[str, float]
    risk_notes: List[str]


class PositionFollowUpBase(BaseModel):
    position_id: int
    follow_date: str = Field(min_length=10, max_length=10)
    stage: FollowUpStage = "holding"
    status: FollowUpStatus = "open"
    summary: str = Field(min_length=6, max_length=4000)
    action_items: List[str] = Field(default_factory=list)
    next_follow_date: Optional[str] = Field(default=None, min_length=10, max_length=10)
    confidence_score: Optional[int] = Field(default=None, ge=0, le=100)
    discipline_score: Optional[int] = Field(default=None, ge=0, le=100)


class PositionFollowUpCreate(PositionFollowUpBase):
    pass


class PositionFollowUpUpdate(BaseModel):
    follow_date: Optional[str] = Field(default=None, min_length=10, max_length=10)
    stage: Optional[FollowUpStage] = None
    status: Optional[FollowUpStatus] = None
    summary: Optional[str] = Field(default=None, min_length=6, max_length=4000)
    action_items: Optional[List[str]] = None
    next_follow_date: Optional[str] = Field(default=None, min_length=10, max_length=10)
    confidence_score: Optional[int] = Field(default=None, ge=0, le=100)
    discipline_score: Optional[int] = Field(default=None, ge=0, le=100)


class PositionFollowUpItem(BaseModel):
    id: int
    position_id: int
    symbol: str
    position_name: str
    follow_date: str
    stage: FollowUpStage
    status: FollowUpStatus
    summary: str
    action_items: List[str]
    next_follow_date: Optional[str]
    confidence_score: Optional[int]
    discipline_score: Optional[int]
    is_due: bool
    created_at: datetime
    updated_at: datetime


class PositionFollowUpListResponse(BaseModel):
    total: int
    due_count: int
    items: List[PositionFollowUpItem]


class NotificationSetting(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    enable_price_alert: bool
    enable_report_alert: bool
    enable_followup_due_alert: bool
    enable_watch_monitor_alert: bool
    updated_at: datetime


class NotificationSettingUpdate(BaseModel):
    enable_price_alert: Optional[bool] = None
    enable_report_alert: Optional[bool] = None
    enable_followup_due_alert: Optional[bool] = None
    enable_watch_monitor_alert: Optional[bool] = None


class NotificationItem(BaseModel):
    id: int
    category: NotificationType
    symbol: Optional[str]
    title: str
    content: str
    payload: Dict[str, object]
    is_read: bool
    created_at: datetime
    read_at: Optional[datetime]


class NotificationListResponse(BaseModel):
    total: int
    unread_count: int
    items: List[NotificationItem]


class NotificationRefreshResponse(BaseModel):
    created_count: int
    created_by_type: Dict[NotificationType, int]


class NotificationReadResponse(BaseModel):
    item: NotificationItem


class WatchlistMonitorRunResponse(BaseModel):
    item_id: int
    symbol: str
    summary: str
    signal_level: str
    checked_at: datetime
    created_notification: bool


class WatchlistMonitorBatchRunResponse(BaseModel):
    checked_count: int
    created_notification_count: int
    high_signal_count: int
    medium_signal_count: int
    low_signal_count: int
    checked_at: datetime


class WatchlistMonitorDailyReportItem(BaseModel):
    item_id: int
    symbol: str
    name: str
    signal_level: str
    summary: str
    interval_minutes: int
    last_checked_at: Optional[datetime] = None


class WatchlistMonitorDailyReportResponse(BaseModel):
    generated_at: datetime
    total_enabled: int
    checked_today_count: int
    high_signal_count: int
    medium_signal_count: int
    low_signal_count: int
    overview: str
    highlights: List[str]
    action_items: List[str]
    focus_items: List[WatchlistMonitorDailyReportItem]


class AdminUserListResponse(BaseModel):
    total: int
    items: List[UserPublic]


class AdminUserUpdateRequest(BaseModel):
    role: Optional[UserRole] = None
    is_active: Optional[bool] = None
