import json
from datetime import datetime, timezone
from typing import Dict, List, Optional, Sequence

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.stock_universe import StockUniverse
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
    }

    if setting.enable_price_alert:
        created_by_type["price_alert"] = _refresh_price_alerts(db=db, user_id=user_id)
    if setting.enable_report_alert:
        created_by_type["report_alert"] = _refresh_report_alerts(db=db, user_id=user_id)
    if setting.enable_followup_due_alert:
        created_by_type["followup_due"] = _refresh_followup_due_alerts(db=db, user_id=user_id)

    created_count = sum(created_by_type.values())
    if created_count > 0:
        db.commit()

    return NotificationRefreshResponse(
        created_count=created_count,
        created_by_type={  # type: ignore[arg-type]
            "price_alert": created_by_type["price_alert"],
            "report_alert": created_by_type["report_alert"],
            "followup_due": created_by_type["followup_due"],
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
