import json
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Sequence, Tuple

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.stock_universe import StockUniverse
from app.schemas.account import (
    WatchlistMonitorBatchRunResponse,
    WatchlistMonitorDailyReportItem,
    WatchlistMonitorDailyReportResponse,
    WatchlistMonitorRunResponse,
)
from app.services.stock_service import _detect_sector_theme, get_sector_rotation_summary, get_stock_snapshot
from app.models.user_platform import (
    UserNotification,
    UserNotificationSetting,
    UserPosition,
    UserPositionFollowUp,
    UserWatchlistItem,
)
from app.schemas.account import (
    NotificationItem,
    NotificationListResponse,
    NotificationReadResponse,
    NotificationRefreshResponse,
    NotificationSetting,
    NotificationSettingUpdate,
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _today() -> str:
    return _utc_now().date().isoformat()


def _safe_payload(raw: Optional[str]) -> Dict[str, object]:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _dump_payload(payload: Optional[Dict[str, object]]) -> Optional[str]:
    if not payload:
        return None
    return json.dumps(payload, ensure_ascii=False)


def _setting_to_schema(row: UserNotificationSetting) -> NotificationSetting:
    return NotificationSetting(
        enable_price_alert=row.enable_price_alert,
        enable_report_alert=row.enable_report_alert,
        enable_followup_due_alert=row.enable_followup_due_alert,
        enable_watch_monitor_alert=row.enable_watch_monitor_alert,
        updated_at=row.updated_at,
    )


def _notification_to_schema(row: UserNotification) -> NotificationItem:
    return NotificationItem(
        id=row.id,
        category=row.category,  # type: ignore[arg-type]
        symbol=row.symbol,
        title=row.title,
        content=row.content,
        payload=_safe_payload(row.payload_json),
        is_read=row.is_read,
        created_at=row.created_at,
        read_at=row.read_at,
    )


def get_or_create_notification_setting(db: Session, user_id: int) -> UserNotificationSetting:
    row = db.query(UserNotificationSetting).filter(UserNotificationSetting.user_id == user_id).first()
    if row is not None:
        return row

    row = UserNotificationSetting(user_id=user_id)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def get_user_notification_setting(db: Session, user_id: int) -> NotificationSetting:
    row = get_or_create_notification_setting(db=db, user_id=user_id)
    return _setting_to_schema(row)


def update_user_notification_setting(
    db: Session,
    user_id: int,
    payload: NotificationSettingUpdate,
) -> NotificationSetting:
    row = get_or_create_notification_setting(db=db, user_id=user_id)

    if payload.enable_price_alert is not None:
        row.enable_price_alert = payload.enable_price_alert
    if payload.enable_report_alert is not None:
        row.enable_report_alert = payload.enable_report_alert
    if payload.enable_followup_due_alert is not None:
        row.enable_followup_due_alert = payload.enable_followup_due_alert
    if payload.enable_watch_monitor_alert is not None:
        row.enable_watch_monitor_alert = payload.enable_watch_monitor_alert

    db.add(row)
    db.commit()
    db.refresh(row)
    return _setting_to_schema(row)


def _create_notification_if_absent(
    db: Session,
    user_id: int,
    event_key: str,
    category: str,
    title: str,
    content: str,
    symbol: Optional[str] = None,
    payload: Optional[Dict[str, object]] = None,
) -> bool:
    exists = db.query(UserNotification.id).filter(
        UserNotification.user_id == user_id,
        UserNotification.event_key == event_key,
    ).first()
    if exists is not None:
        return False

    row = UserNotification(
        user_id=user_id,
        event_key=event_key,
        category=category,
        symbol=symbol,
        title=title,
        content=content,
        payload_json=_dump_payload(payload),
    )
    db.add(row)
    return True


def _load_stock_map(db: Session, symbols: Sequence[str]) -> Dict[str, StockUniverse]:
    normalized = sorted({symbol.strip().upper() for symbol in symbols if symbol.strip()})
    if not normalized:
        return {}

    rows = (
        db.query(StockUniverse)
        .filter(func.upper(StockUniverse.symbol).in_(normalized))
        .all()
    )
    return {row.symbol.upper(): row for row in rows}


WATCH_MONITOR_DEFAULT_FOCUS = {"price_move", "near_alert", "trend_breakout"}


def _normalize_monitor_focus(raw: Optional[str]) -> List[str]:
    if not raw:
        return sorted(WATCH_MONITOR_DEFAULT_FOCUS)
    try:
        values = json.loads(raw)
    except json.JSONDecodeError:
        return sorted(WATCH_MONITOR_DEFAULT_FOCUS)
    if not isinstance(values, list):
        return sorted(WATCH_MONITOR_DEFAULT_FOCUS)
    cleaned = [str(item).strip() for item in values if str(item).strip()]
    return cleaned or sorted(WATCH_MONITOR_DEFAULT_FOCUS)


def _monitor_interval_due(row: UserWatchlistItem, now: datetime) -> bool:
    last_checked_at = _as_utc(row.monitor_last_checked_at)
    if last_checked_at is None:
        return True
    return (now - last_checked_at) >= timedelta(minutes=max(1, int(row.monitor_interval_minutes or 15)))


def _build_watch_monitor_result(db: Session, row: UserWatchlistItem, stock: StockUniverse) -> Tuple[str, str, List[str], str]:
    snapshot = get_stock_snapshot(db=db, symbol=row.symbol)
    focus = set(_normalize_monitor_focus(row.monitor_focus_json))
    if snapshot is None:
        return ("未能获取最新研究快照，建议稍后重试。", "low", ["数据快照暂不可用。"], f"{row.symbol} 盯盘检查")

    detail = snapshot.detail
    analysis = snapshot.analysis
    theme = _detect_sector_theme(stock.name, stock.board)
    bullets: List[str] = []
    signal_level = "low"

    if "price_move" in focus and abs(detail.change_pct) >= 2:
        bullets.append(f"价格异动：当前涨跌幅 {detail.change_pct:+.2f}%。")
        signal_level = "high" if abs(detail.change_pct) >= 5 else "medium"

    if "near_alert" in focus:
        if row.alert_price_up and detail.price >= float(row.alert_price_up) * 0.995:
            bullets.append(f"接近/触发上沿提醒：现价 {detail.price:.2f}，上沿 {float(row.alert_price_up):.2f}。")
            signal_level = "high"
        if row.alert_price_down and detail.price <= float(row.alert_price_down) * 1.005:
            bullets.append(f"接近/触发下沿提醒：现价 {detail.price:.2f}，下沿 {float(row.alert_price_down):.2f}。")
            signal_level = "high"

    if "trend_breakout" in focus:
        if detail.price >= detail.resistance_price * 0.995:
            bullets.append(f"技术位观察：现价接近/突破压力位 {detail.resistance_price:.2f}。")
            signal_level = "high" if signal_level == "low" else signal_level
        elif detail.price <= detail.support_price * 1.005:
            bullets.append(f"技术位观察：现价接近支撑位 {detail.support_price:.2f}。")
            signal_level = "medium" if signal_level == "low" else signal_level

    if "turnover_spike" in focus and stock.turnover and detail.avg_volume_20d > 0 and float(stock.turnover) >= detail.avg_volume_20d * 1.5:
        bullets.append(f"成交额放大：当前成交额 {float(stock.turnover):.0f}，高于20期均值 {detail.avg_volume_20d:.0f}。")
        signal_level = "medium" if signal_level == "low" else signal_level

    if "sector_rotation" in focus and stock.market in {"A股", "创业板", "科创板"}:
        rotation = get_sector_rotation_summary(db=db, market=stock.market, top_n=6)
        hot_names = {item.name for item in rotation.current_hot_sectors}
        next_name = rotation.next_potential_sector.name if rotation.next_potential_sector else None
        if theme in hot_names or (next_name and theme == next_name):
            bullets.append(f"板块联动：{theme} 与当前轮动热点方向存在共振。")
            signal_level = "medium" if signal_level == "low" else signal_level

    if not bullets:
        bullets = [
            f"现价 {detail.price:.2f}，涨跌幅 {detail.change_pct:+.2f}%，模型评分 {analysis.score}/99。",
            f"所属方向：{theme}，建议动作 {analysis.recommendation}。",
        ]

    summary = f"{detail.name} 盯盘摘要：现价 {detail.price:.2f}，涨跌幅 {detail.change_pct:+.2f}%，评分 {analysis.score}/99。{bullets[0]}"
    title = f"{detail.name} 盯盘{'强提醒' if signal_level == 'high' else '提醒' if signal_level == 'medium' else '检查完成'}"
    return summary[:300], signal_level, bullets[:4], title


def _run_watch_monitor_for_row(
    db: Session,
    row: UserWatchlistItem,
    stock: Optional[StockUniverse],
    *,
    notify_enabled: bool,
    force: bool = False,
) -> bool:
    now = _utc_now()
    if not row.monitor_enabled or stock is None:
        return False
    if not force and not _monitor_interval_due(row, now):
        return False

    summary, signal_level, bullets, title = _build_watch_monitor_result(db=db, row=row, stock=stock)
    row.monitor_last_checked_at = now
    row.monitor_last_summary = summary
    row.monitor_last_signal_level = signal_level
    created = False
    if notify_enabled and signal_level in {"medium", "high"}:
        bucket_minutes = max(1, int(row.monitor_interval_minutes or 15))
        bucket_start = now.replace(second=0, microsecond=0) - timedelta(minutes=now.minute % bucket_minutes)
        event_key = f"watch_monitor:{row.id}:{bucket_start.isoformat()}"
        created = _create_notification_if_absent(
            db=db,
            user_id=row.user_id,
            event_key=event_key,
            category="watch_monitor",
            symbol=row.symbol,
            title=title,
            content=summary,
            payload={"signal_level": signal_level, "bullets": bullets, "checked_at": now.isoformat()},
        )
        if created:
            row.monitor_last_notified_at = now
    db.add(row)
    return created


def _refresh_watch_monitor_alerts(db: Session, user_id: int) -> int:
    setting = get_or_create_notification_setting(db=db, user_id=user_id)
    rows = db.query(UserWatchlistItem).filter(UserWatchlistItem.user_id == user_id, UserWatchlistItem.monitor_enabled.is_(True)).all()
    stock_map = _load_stock_map(db, [row.symbol for row in rows])
    created = 0
    for row in rows:
        created += int(
            _run_watch_monitor_for_row(
                db=db,
                row=row,
                stock=stock_map.get(row.symbol.upper()),
                notify_enabled=setting.enable_watch_monitor_alert,
            )
        )
    return created


def refresh_watch_monitor_for_item(db: Session, user_id: int, item_id: int) -> Optional[WatchlistMonitorRunResponse]:
    row = db.query(UserWatchlistItem).filter(UserWatchlistItem.id == item_id, UserWatchlistItem.user_id == user_id).first()
    if row is None:
        return None
    stock_map = _load_stock_map(db, [row.symbol])
    notify_enabled = get_or_create_notification_setting(db=db, user_id=user_id).enable_watch_monitor_alert
    created = _run_watch_monitor_for_row(db=db, row=row, stock=stock_map.get(row.symbol.upper()), notify_enabled=notify_enabled, force=True)
    db.commit()
    db.refresh(row)
    return WatchlistMonitorRunResponse(
        item_id=row.id,
        symbol=row.symbol,
        summary=row.monitor_last_summary or "暂无摘要",
        signal_level=row.monitor_last_signal_level or "low",
        checked_at=row.monitor_last_checked_at or _utc_now(),
        created_notification=created,
    )


def refresh_watch_monitor_for_user(db: Session, user_id: int) -> WatchlistMonitorBatchRunResponse:
    rows = db.query(UserWatchlistItem).filter(UserWatchlistItem.user_id == user_id, UserWatchlistItem.monitor_enabled.is_(True)).all()
    stock_map = _load_stock_map(db, [row.symbol for row in rows])
    notify_enabled = get_or_create_notification_setting(db=db, user_id=user_id).enable_watch_monitor_alert
    checked_count = 0
    created_count = 0
    high_count = 0
    medium_count = 0
    low_count = 0
    checked_at = _utc_now()

    for row in rows:
        checked = _run_watch_monitor_for_row(
            db=db,
            row=row,
            stock=stock_map.get(row.symbol.upper()),
            notify_enabled=notify_enabled,
            force=True,
        )
        if row.monitor_last_checked_at is not None:
            checked_count += 1
            if row.monitor_last_signal_level == "high":
                high_count += 1
            elif row.monitor_last_signal_level == "medium":
                medium_count += 1
            else:
                low_count += 1
        created_count += int(checked)

    db.commit()
    return WatchlistMonitorBatchRunResponse(
        checked_count=checked_count,
        created_notification_count=created_count,
        high_signal_count=high_count,
        medium_signal_count=medium_count,
        low_signal_count=low_count,
        checked_at=checked_at,
    )


def get_watch_monitor_daily_report(db: Session, user_id: int) -> WatchlistMonitorDailyReportResponse:
    rows = (
        db.query(UserWatchlistItem)
        .filter(UserWatchlistItem.user_id == user_id, UserWatchlistItem.monitor_enabled.is_(True))
        .order_by(UserWatchlistItem.updated_at.desc())
        .all()
    )
    stock_map = _load_stock_map(db, [row.symbol for row in rows])
    today = _today()

    focus_items: List[WatchlistMonitorDailyReportItem] = []
    high_count = 0
    medium_count = 0
    low_count = 0
    checked_today_count = 0

    for row in rows:
        checked_at = _as_utc(row.monitor_last_checked_at)
        checked_today = checked_at is not None and checked_at.date().isoformat() == today
        if checked_today:
            checked_today_count += 1

        signal_level = row.monitor_last_signal_level or "low"
        if signal_level == "high":
            high_count += 1
        elif signal_level == "medium":
            medium_count += 1
        else:
            low_count += 1

        stock = stock_map.get(row.symbol.upper())
        focus_items.append(
            WatchlistMonitorDailyReportItem(
                item_id=row.id,
                symbol=row.symbol,
                name=stock.name if stock is not None else row.symbol,
                signal_level=signal_level,
                summary=row.monitor_last_summary or "暂无盯盘摘要。",
                interval_minutes=int(row.monitor_interval_minutes or 15),
                last_checked_at=checked_at,
            )
        )

    priority_map = {"high": 0, "medium": 1, "low": 2}
    focus_items.sort(key=lambda item: (priority_map.get(item.signal_level, 9), item.symbol))

    recent_notifications = list_user_notifications(db=db, user_id=user_id, unread_only=False, limit=20).items
    monitor_notifications = [item for item in recent_notifications if item.category == "watch_monitor"]

    overview = (
        f"今日已启用盯盘 {len(rows)} 只，完成检查 {checked_today_count} 只，"
        f"高优先级 {high_count} 只，中优先级 {medium_count} 只。"
    )

    highlights: List[str] = []
    if focus_items:
        top_item = focus_items[0]
        highlights.append(
            f"当前最需要关注的是 {top_item.name}（{top_item.symbol}），最近信号级别为 {top_item.signal_level}。"
        )
    if monitor_notifications:
        latest = monitor_notifications[0]
        highlights.append(
            f"最近盯盘提醒：{latest.title}，时间 {latest.created_at.strftime('%Y-%m-%d %H:%M')}。"
        )
    if checked_today_count < len(rows):
        highlights.append("仍有部分盯盘股票今天未完成检查，建议手动执行一次“全部检查”。")
    if not highlights:
        highlights.append("当前暂无显著盯盘异动，系统会继续按频率扫描。")

    action_items: List[str] = []
    if high_count > 0:
        action_items.append("优先复核高优先级股票的价格位置、成交额与计划仓位。")
    if medium_count > 0:
        action_items.append("中优先级股票建议结合板块方向与预警价继续观察。")
    if checked_today_count == 0 and rows:
        action_items.append("今日尚未形成有效盯盘结果，可手动执行全部检查。")
    if not action_items:
        action_items.append("保持当前盯盘节奏，收盘后复核摘要并补充复盘记录。")

    return WatchlistMonitorDailyReportResponse(
        generated_at=_utc_now(),
        total_enabled=len(rows),
        checked_today_count=checked_today_count,
        high_signal_count=high_count,
        medium_signal_count=medium_count,
        low_signal_count=low_count,
        overview=overview,
        highlights=highlights[:4],
        action_items=action_items[:4],
        focus_items=focus_items[:8],
    )


def run_watch_monitor_cycle(db: Session) -> int:
    rows = db.query(UserWatchlistItem).filter(UserWatchlistItem.monitor_enabled.is_(True)).all()
    if not rows:
        return 0
    settings = {item.user_id: item for item in db.query(UserNotificationSetting).all()}
    stock_map = _load_stock_map(db, [row.symbol for row in rows])
    created = 0
    for row in rows:
        setting = settings.get(row.user_id)
        notify_enabled = setting.enable_watch_monitor_alert if setting is not None else True
        created += int(_run_watch_monitor_for_row(db=db, row=row, stock=stock_map.get(row.symbol.upper()), notify_enabled=notify_enabled))
    if rows:
        db.commit()
    return created


def _refresh_price_alerts(db: Session, user_id: int) -> int:
    watch_rows = (
        db.query(UserWatchlistItem)
        .filter(UserWatchlistItem.user_id == user_id)
        .order_by(UserWatchlistItem.updated_at.desc())
        .all()
    )
    stock_map = _load_stock_map(db, [row.symbol for row in watch_rows])
    created = 0

    for row in watch_rows:
        stock = stock_map.get(row.symbol.upper())
        if stock is None or stock.price is None:
            continue

        current_price = float(stock.price)
        quote_date = (stock.updated_at or _utc_now()).date().isoformat()

        if row.alert_price_up is not None and current_price >= float(row.alert_price_up):
            threshold = float(row.alert_price_up)
            event_key = f"price_up:{row.id}:{threshold:.4f}:{quote_date}"
            created += int(
                _create_notification_if_absent(
                    db=db,
                    user_id=user_id,
                    event_key=event_key,
                    category="price_alert",
                    symbol=row.symbol,
                    title=f"{row.symbol} 触发上破提醒",
                    content=f"现价 {current_price:.2f} ≥ 预警价 {threshold:.2f}，请评估是否执行计划。",
                    payload={"direction": "up", "threshold": threshold, "current_price": round(current_price, 4)},
                )
            )

        if row.alert_price_down is not None and current_price <= float(row.alert_price_down):
            threshold = float(row.alert_price_down)
            event_key = f"price_down:{row.id}:{threshold:.4f}:{quote_date}"
            created += int(
                _create_notification_if_absent(
                    db=db,
                    user_id=user_id,
                    event_key=event_key,
                    category="price_alert",
                    symbol=row.symbol,
                    title=f"{row.symbol} 触发下破提醒",
                    content=f"现价 {current_price:.2f} ≤ 预警价 {threshold:.2f}，建议复核止损纪律。",
                    payload={"direction": "down", "threshold": threshold, "current_price": round(current_price, 4)},
                )
            )

    return created


def _refresh_report_alerts(db: Session, user_id: int) -> int:
    watch_symbols = (
        db.query(UserWatchlistItem.symbol)
        .filter(UserWatchlistItem.user_id == user_id)
        .all()
    )
    position_symbols = (
        db.query(UserPosition.symbol)
        .filter(UserPosition.user_id == user_id)
        .all()
    )

    symbols = [symbol for (symbol,) in watch_symbols] + [symbol for (symbol,) in position_symbols]
    stock_map = _load_stock_map(db, symbols)
    created = 0

    for symbol, stock in stock_map.items():
        report_date = (stock.updated_at or _utc_now()).date().isoformat()
        event_key = f"report:{symbol}:{report_date}"
        created += int(
            _create_notification_if_absent(
                db=db,
                user_id=user_id,
                event_key=event_key,
                category="report_alert",
                symbol=stock.symbol,
                title=f"{stock.name} 财报跟踪提醒",
                content=f"最新财报窗口日期：{report_date}，建议复核营收、利润与现金流变化。",
                payload={"report_date": report_date, "exchange": stock.exchange, "market": stock.market},
            )
        )

    return created


def _refresh_followup_due_alerts(db: Session, user_id: int) -> int:
    today = _today()
    rows = (
        db.query(UserPositionFollowUp)
        .filter(
            UserPositionFollowUp.user_id == user_id,
            UserPositionFollowUp.next_follow_date.is_not(None),
            UserPositionFollowUp.next_follow_date <= today,
            UserPositionFollowUp.status != "closed",
        )
        .order_by(UserPositionFollowUp.next_follow_date.asc(), UserPositionFollowUp.created_at.desc())
        .all()
    )

    created = 0
    for row in rows:
        if not row.next_follow_date:
            continue

        event_key = f"followup_due:{row.id}:{row.next_follow_date}"
        created += int(
            _create_notification_if_absent(
                db=db,
                user_id=user_id,
                event_key=event_key,
                category="followup_due",
                symbol=row.symbol,
                title=f"{row.symbol} 跟进任务已到期",
                content=f"计划跟进日期 {row.next_follow_date} 已到，请尽快完成复盘与决策更新。",
                payload={"follow_up_id": row.id, "next_follow_date": row.next_follow_date},
            )
        )

    return created


def refresh_user_notifications(db: Session, user_id: int) -> NotificationRefreshResponse:
    setting = get_or_create_notification_setting(db=db, user_id=user_id)
    created_by_type: Dict[str, int] = {
        "price_alert": 0,
        "report_alert": 0,
        "followup_due": 0,
        "watch_monitor": 0,
    }

    if setting.enable_price_alert:
        created_by_type["price_alert"] = _refresh_price_alerts(db=db, user_id=user_id)
    if setting.enable_report_alert:
        created_by_type["report_alert"] = _refresh_report_alerts(db=db, user_id=user_id)
    if setting.enable_followup_due_alert:
        created_by_type["followup_due"] = _refresh_followup_due_alerts(db=db, user_id=user_id)
    created_by_type["watch_monitor"] = _refresh_watch_monitor_alerts(db=db, user_id=user_id)

    created_count = sum(created_by_type.values())
    if created_count > 0:
        db.commit()

    return NotificationRefreshResponse(
        created_count=created_count,
        created_by_type={  # type: ignore[arg-type]
            "price_alert": created_by_type["price_alert"],
            "report_alert": created_by_type["report_alert"],
            "followup_due": created_by_type["followup_due"],
            "watch_monitor": created_by_type["watch_monitor"],
        },
    )


def list_user_notifications(
    db: Session,
    user_id: int,
    unread_only: bool = False,
    limit: int = 100,
) -> NotificationListResponse:
    total = db.query(func.count(UserNotification.id)).filter(UserNotification.user_id == user_id).scalar() or 0
    unread_count = (
        db.query(func.count(UserNotification.id))
        .filter(UserNotification.user_id == user_id, UserNotification.is_read.is_(False))
        .scalar()
        or 0
    )

    query = db.query(UserNotification).filter(UserNotification.user_id == user_id)
    if unread_only:
        query = query.filter(UserNotification.is_read.is_(False))

    rows = query.order_by(UserNotification.created_at.desc()).limit(max(1, min(limit, 300))).all()
    items = [_notification_to_schema(row) for row in rows]
    return NotificationListResponse(total=int(total), unread_count=int(unread_count), items=items)


def mark_user_notification_read(db: Session, user_id: int, notification_id: int) -> Optional[NotificationReadResponse]:
    row = db.query(UserNotification).filter(UserNotification.id == notification_id, UserNotification.user_id == user_id).first()
    if row is None:
        return None

    if not row.is_read:
        row.is_read = True
        row.read_at = _utc_now()
        db.add(row)
        db.commit()
        db.refresh(row)

    return NotificationReadResponse(item=_notification_to_schema(row))
