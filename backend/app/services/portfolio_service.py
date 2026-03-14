import json
from collections import defaultdict
from datetime import datetime, timezone
from typing import Dict, List, Optional, Sequence, Tuple

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.stock_universe import StockUniverse
from app.models.user_platform import UserPosition, UserPositionFollowUp, UserWatchlistItem
from app.schemas.account import (
    PositionAnalysisResponse,
    PositionCreate,
    PositionFollowUpCreate,
    PositionFollowUpItem,
    PositionFollowUpListResponse,
    PositionFollowUpUpdate,
    PositionListResponse,
    PositionSnapshot,
    PositionUpdate,
    WatchlistItem,
    WatchlistItemCreate,
    WatchlistItemUpdate,
    WatchlistListResponse,
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _normalize_symbol(symbol: str) -> str:
    return symbol.strip().upper()


def _parse_json_list(raw: Optional[str]) -> List[str]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []

    if not isinstance(data, list):
        return []
    return [str(item).strip() for item in data if str(item).strip()]


WATCHLIST_MONITOR_INTERVAL_OPTIONS = {1, 5, 10, 15, 30, 60}
DEFAULT_WATCHLIST_MONITOR_FOCUS = ["price_move", "near_alert", "trend_breakout"]


def _normalize_monitor_interval(value: Optional[int]) -> int:
    if value is None:
        return 15
    parsed = int(value)
    return parsed if parsed in WATCHLIST_MONITOR_INTERVAL_OPTIONS else 15


def _normalize_monitor_focus(values: Optional[Sequence[str]]) -> List[str]:
    if values is None:
        return list(DEFAULT_WATCHLIST_MONITOR_FOCUS)
    cleaned = [str(value).strip() for value in values if str(value).strip()]
    if not cleaned:
        return list(DEFAULT_WATCHLIST_MONITOR_FOCUS)
    return list(dict.fromkeys(cleaned))[:8]


def _dump_json_list(values: Sequence[str]) -> str:
    cleaned = [str(value).strip() for value in values if str(value).strip()]
    return json.dumps(cleaned, ensure_ascii=False)


def _resolve_stock_row(db: Session, symbol: str) -> Optional[StockUniverse]:
    target = _normalize_symbol(symbol)
    if not target:
        return None

    row = db.query(StockUniverse).filter(func.upper(StockUniverse.symbol) == target).first()
    if row is not None:
        return row

    clean = "".join(char for char in target if char.isalnum())
    if not clean:
        return None

    if clean.isdigit():
        row = db.query(StockUniverse).filter(StockUniverse.code == clean).first()
        if row is not None:
            return row
        row = db.query(StockUniverse).filter(StockUniverse.code == clean.zfill(5)).first()
        if row is not None:
            return row
    else:
        row = db.query(StockUniverse).filter(func.upper(StockUniverse.code) == clean).first()
        if row is not None:
            return row

    return None


def _load_stock_meta(db: Session, symbols: Sequence[str]) -> Dict[str, Dict[str, object]]:
    if not symbols:
        return {}

    rows = (
        db.query(StockUniverse)
        .filter(func.upper(StockUniverse.symbol).in_([_normalize_symbol(value) for value in symbols]))
        .all()
    )

    output: Dict[str, Dict[str, object]] = {}
    for row in rows:
        output[row.symbol] = {
            "name": row.name,
            "market": row.market,
            "industry": row.board,
            "price": float(row.price) if row.price is not None else 0.0,
            "change_pct": float(row.change_pct) if row.change_pct is not None else 0.0,
        }
    return output


def _watchlist_row_to_schema(row: UserWatchlistItem, meta: Optional[Dict[str, object]]) -> WatchlistItem:
    info = meta or {}
    return WatchlistItem(
        id=row.id,
        symbol=row.symbol,
        name=str(info.get("name") or row.symbol),
        market=str(info.get("market") or "未知"),
        industry=str(info.get("industry") or "未分类"),
        current_price=float(info.get("price") or 0.0),
        change_pct=float(info.get("change_pct") or 0.0),
        group_name=row.group_name,
        tags=_parse_json_list(row.tags_json),
        note=row.note,
        alert_price_up=row.alert_price_up,
        alert_price_down=row.alert_price_down,
        target_position_pct=row.target_position_pct,
        monitor_enabled=row.monitor_enabled,
        monitor_interval_minutes=row.monitor_interval_minutes,
        monitor_focus=_parse_json_list(row.monitor_focus_json),
        monitor_last_checked_at=row.monitor_last_checked_at,
        monitor_last_summary=row.monitor_last_summary,
        monitor_last_signal_level=row.monitor_last_signal_level,
        monitor_last_notified_at=row.monitor_last_notified_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def list_user_watchlist(db: Session, user_id: int) -> WatchlistListResponse:
    rows = db.query(UserWatchlistItem).filter(UserWatchlistItem.user_id == user_id).order_by(UserWatchlistItem.updated_at.desc()).all()
    meta = _load_stock_meta(db, [row.symbol for row in rows])
    items = [_watchlist_row_to_schema(row, meta.get(row.symbol)) for row in rows]
    groups = sorted({item.group_name for item in items})

    return WatchlistListResponse(total=len(items), groups=groups, items=items)


def create_user_watchlist_item(db: Session, user_id: int, payload: WatchlistItemCreate) -> WatchlistItem:
    stock = _resolve_stock_row(db, payload.symbol)
    if stock is None:
        raise ValueError("股票代码不存在，请先检查股票池")

    exists = (
        db.query(UserWatchlistItem)
        .filter(UserWatchlistItem.user_id == user_id, func.upper(UserWatchlistItem.symbol) == stock.symbol.upper())
        .first()
    )
    if exists is not None:
        raise ValueError("该股票已在自选中")

    row = UserWatchlistItem(
        user_id=user_id,
        symbol=stock.symbol,
        group_name=payload.group_name,
        tags_json=_dump_json_list(payload.tags),
        note=payload.note,
        alert_price_up=payload.alert_price_up,
        alert_price_down=payload.alert_price_down,
        target_position_pct=payload.target_position_pct,
        monitor_enabled=payload.monitor_enabled,
        monitor_interval_minutes=_normalize_monitor_interval(payload.monitor_interval_minutes),
        monitor_focus_json=_dump_json_list(_normalize_monitor_focus(payload.monitor_focus)),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _watchlist_row_to_schema(row, _load_stock_meta(db, [row.symbol]).get(row.symbol))


def update_user_watchlist_item(db: Session, user_id: int, item_id: int, payload: WatchlistItemUpdate) -> Optional[WatchlistItem]:
    row = db.query(UserWatchlistItem).filter(UserWatchlistItem.id == item_id, UserWatchlistItem.user_id == user_id).first()
    if row is None:
        return None

    if payload.group_name is not None:
        row.group_name = payload.group_name
    if payload.tags is not None:
        row.tags_json = _dump_json_list(payload.tags)
    if payload.note is not None:
        row.note = payload.note
    if payload.alert_price_up is not None:
        row.alert_price_up = payload.alert_price_up
    if payload.alert_price_down is not None:
        row.alert_price_down = payload.alert_price_down
    if payload.target_position_pct is not None:
        row.target_position_pct = payload.target_position_pct
    if payload.monitor_enabled is not None:
        row.monitor_enabled = payload.monitor_enabled
    if payload.monitor_interval_minutes is not None:
        row.monitor_interval_minutes = _normalize_monitor_interval(payload.monitor_interval_minutes)
    if payload.monitor_focus is not None:
        row.monitor_focus_json = _dump_json_list(_normalize_monitor_focus(payload.monitor_focus))

    db.add(row)
    db.commit()
    db.refresh(row)
    return _watchlist_row_to_schema(row, _load_stock_meta(db, [row.symbol]).get(row.symbol))


def delete_user_watchlist_item(db: Session, user_id: int, item_id: int) -> bool:
    row = db.query(UserWatchlistItem).filter(UserWatchlistItem.id == item_id, UserWatchlistItem.user_id == user_id).first()
    if row is None:
        return False

    db.delete(row)
    db.commit()
    return True


def _load_latest_follow_ups(db: Session, user_id: int) -> Dict[int, UserPositionFollowUp]:
    rows = (
        db.query(UserPositionFollowUp)
        .filter(UserPositionFollowUp.user_id == user_id)
        .order_by(UserPositionFollowUp.created_at.desc())
        .all()
    )
    latest: Dict[int, UserPositionFollowUp] = {}
    for row in rows:
        latest.setdefault(row.position_id, row)
    return latest


def _position_row_to_snapshot(
    row: UserPosition,
    meta: Optional[Dict[str, object]],
    latest_follow_up: Optional[UserPositionFollowUp] = None,
) -> PositionSnapshot:
    info = meta or {}
    current_price = float(info.get("price") or row.cost_price or 0.0)
    quantity = float(row.quantity)
    cost_price = float(row.cost_price)
    cost_value = quantity * cost_price
    market_value = quantity * current_price
    pnl = market_value - cost_value
    pnl_pct = 0.0 if cost_value <= 0 else (pnl / cost_value) * 100

    return PositionSnapshot(
        id=row.id,
        symbol=row.symbol,
        name=str(info.get("name") or row.symbol),
        market=str(info.get("market") or "未知"),
        industry=str(info.get("industry") or "未分类"),
        quantity=round(quantity, 4),
        cost_price=round(cost_price, 4),
        current_price=round(current_price, 4),
        cost_value=round(cost_value, 2),
        market_value=round(market_value, 2),
        pnl=round(pnl, 2),
        pnl_pct=round(pnl_pct, 2),
        weight=0.0,
        stop_loss_price=row.stop_loss_price,
        take_profit_price=row.take_profit_price,
        status=row.status,  # type: ignore[arg-type]
        thesis=row.thesis,
        latest_follow_up_status=(latest_follow_up.status if latest_follow_up else None),  # type: ignore[arg-type]
        latest_follow_up_date=(latest_follow_up.follow_date if latest_follow_up else None),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _attach_weights(items: List[PositionSnapshot]) -> List[PositionSnapshot]:
    total_market_value = sum(item.market_value for item in items)
    if total_market_value <= 0:
        return items

    output: List[PositionSnapshot] = []
    for item in items:
        output.append(item.model_copy(update={"weight": round(item.market_value / total_market_value * 100, 2)}))
    return output


def list_user_positions(db: Session, user_id: int) -> PositionListResponse:
    rows = db.query(UserPosition).filter(UserPosition.user_id == user_id).order_by(UserPosition.updated_at.desc()).all()
    meta = _load_stock_meta(db, [row.symbol for row in rows])
    latest_map = _load_latest_follow_ups(db, user_id)

    snapshots = [_position_row_to_snapshot(row, meta.get(row.symbol), latest_map.get(row.id)) for row in rows]
    snapshots.sort(key=lambda item: item.market_value, reverse=True)
    snapshots = _attach_weights(snapshots)
    return PositionListResponse(total=len(snapshots), items=snapshots)


def create_user_position(db: Session, user_id: int, payload: PositionCreate) -> PositionSnapshot:
    stock = _resolve_stock_row(db, payload.symbol)
    if stock is None:
        raise ValueError("股票代码不存在，请先检查股票池")

    exists = (
        db.query(UserPosition)
        .filter(UserPosition.user_id == user_id, func.upper(UserPosition.symbol) == stock.symbol.upper())
        .first()
    )
    if exists is not None:
        raise ValueError("该股票已在持仓中")

    row = UserPosition(
        user_id=user_id,
        symbol=stock.symbol,
        quantity=payload.quantity,
        cost_price=payload.cost_price,
        stop_loss_price=payload.stop_loss_price,
        take_profit_price=payload.take_profit_price,
        status=payload.status,
        thesis=payload.thesis,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _position_row_to_snapshot(row, _load_stock_meta(db, [row.symbol]).get(row.symbol))


def update_user_position(db: Session, user_id: int, position_id: int, payload: PositionUpdate) -> Optional[PositionSnapshot]:
    row = db.query(UserPosition).filter(UserPosition.id == position_id, UserPosition.user_id == user_id).first()
    if row is None:
        return None

    if payload.quantity is not None:
        row.quantity = payload.quantity
    if payload.cost_price is not None:
        row.cost_price = payload.cost_price
    if payload.stop_loss_price is not None:
        row.stop_loss_price = payload.stop_loss_price
    if payload.take_profit_price is not None:
        row.take_profit_price = payload.take_profit_price
    if payload.status is not None:
        row.status = payload.status
    if payload.thesis is not None:
        row.thesis = payload.thesis

    db.add(row)
    db.commit()
    db.refresh(row)
    return _position_row_to_snapshot(row, _load_stock_meta(db, [row.symbol]).get(row.symbol))


def delete_user_position(db: Session, user_id: int, position_id: int) -> bool:
    row = db.query(UserPosition).filter(UserPosition.id == position_id, UserPosition.user_id == user_id).first()
    if row is None:
        return False

    db.query(UserPositionFollowUp).filter(
        UserPositionFollowUp.user_id == user_id, UserPositionFollowUp.position_id == position_id
    ).delete(synchronize_session=False)
    db.delete(row)
    db.commit()
    return True


def analyze_user_positions(db: Session, user_id: int) -> PositionAnalysisResponse:
    list_response = list_user_positions(db, user_id)
    items = list_response.items

    total_positions = len(items)
    total_cost = round(sum(item.cost_value for item in items), 2)
    total_market_value = round(sum(item.market_value for item in items), 2)
    total_pnl = round(total_market_value - total_cost, 2)
    total_pnl_pct = 0.0 if total_cost <= 0 else round((total_pnl / total_cost) * 100, 2)
    win_count = len([item for item in items if item.pnl > 0])
    loss_count = len([item for item in items if item.pnl < 0])

    sorted_by_value = sorted(items, key=lambda item: item.market_value, reverse=True)
    top3_value = sum(item.market_value for item in sorted_by_value[:3])
    concentration_top3_pct = 0.0 if total_market_value <= 0 else round(top3_value / total_market_value * 100, 2)

    market_values: Dict[str, float] = defaultdict(float)
    industry_values: Dict[str, float] = defaultdict(float)
    for item in items:
        market_values[item.market] += item.market_value
        industry_values[item.industry] += item.market_value

    market_distribution = {
        key: round((value / total_market_value) * 100, 2) if total_market_value > 0 else 0.0
        for key, value in sorted(market_values.items(), key=lambda item: item[1], reverse=True)
    }
    industry_distribution = {
        key: round((value / total_market_value) * 100, 2) if total_market_value > 0 else 0.0
        for key, value in sorted(industry_values.items(), key=lambda item: item[1], reverse=True)
    }

    risk_notes: List[str] = []
    if concentration_top3_pct >= 60:
        risk_notes.append(f"前三大持仓集中度 {concentration_top3_pct:.2f}% 偏高，建议分散风险。")
    if loss_count > win_count and total_positions > 0:
        risk_notes.append("当前亏损持仓数量多于盈利持仓，建议复核止损纪律。")
    if total_pnl_pct <= -10:
        risk_notes.append("组合累计浮亏超过 10%，建议降仓并复盘。")
    if not risk_notes:
        risk_notes.append("组合风险处于可控范围，建议继续按计划跟踪。")

    return PositionAnalysisResponse(
        total_positions=total_positions,
        total_cost=total_cost,
        total_market_value=total_market_value,
        total_pnl=total_pnl,
        total_pnl_pct=total_pnl_pct,
        win_count=win_count,
        loss_count=loss_count,
        concentration_top3_pct=concentration_top3_pct,
        market_distribution=market_distribution,
        industry_distribution=industry_distribution,
        risk_notes=risk_notes,
    )


def _follow_up_row_to_schema(row: UserPositionFollowUp, position_name: str) -> PositionFollowUpItem:
    is_due = bool(row.next_follow_date and row.next_follow_date <= _today() and row.status != "closed")
    return PositionFollowUpItem(
        id=row.id,
        position_id=row.position_id,
        symbol=row.symbol,
        position_name=position_name,
        follow_date=row.follow_date,
        stage=row.stage,  # type: ignore[arg-type]
        status=row.status,  # type: ignore[arg-type]
        summary=row.summary,
        action_items=_parse_json_list(row.action_items_json),
        next_follow_date=row.next_follow_date,
        confidence_score=row.confidence_score,
        discipline_score=row.discipline_score,
        is_due=is_due,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def list_user_follow_ups(
    db: Session,
    user_id: int,
    position_id: Optional[int] = None,
    status: Optional[str] = None,
) -> PositionFollowUpListResponse:
    query = db.query(UserPositionFollowUp).filter(UserPositionFollowUp.user_id == user_id)
    if position_id is not None:
        query = query.filter(UserPositionFollowUp.position_id == position_id)
    if status is not None:
        query = query.filter(UserPositionFollowUp.status == status)

    rows = query.order_by(UserPositionFollowUp.follow_date.desc(), UserPositionFollowUp.created_at.desc()).all()

    positions = db.query(UserPosition).filter(UserPosition.user_id == user_id).all()
    position_name_map: Dict[int, str] = {}
    meta = _load_stock_meta(db, [position.symbol for position in positions])
    for position in positions:
        info = meta.get(position.symbol, {})
        position_name_map[position.id] = str(info.get("name") or position.symbol)

    items = [_follow_up_row_to_schema(row, position_name_map.get(row.position_id, row.symbol)) for row in rows]
    due_count = len([item for item in items if item.is_due])
    return PositionFollowUpListResponse(total=len(items), due_count=due_count, items=items)


def create_user_follow_up(db: Session, user_id: int, payload: PositionFollowUpCreate) -> PositionFollowUpItem:
    position = db.query(UserPosition).filter(UserPosition.id == payload.position_id, UserPosition.user_id == user_id).first()
    if position is None:
        raise ValueError("持仓不存在")

    row = UserPositionFollowUp(
        user_id=user_id,
        position_id=position.id,
        symbol=position.symbol,
        follow_date=payload.follow_date,
        stage=payload.stage,
        status=payload.status,
        summary=payload.summary,
        action_items_json=_dump_json_list(payload.action_items),
        next_follow_date=payload.next_follow_date,
        confidence_score=payload.confidence_score,
        discipline_score=payload.discipline_score,
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    stock = _resolve_stock_row(db, position.symbol)
    position_name = stock.name if stock is not None else position.symbol
    return _follow_up_row_to_schema(row, position_name=position_name)


def update_user_follow_up(
    db: Session,
    user_id: int,
    follow_up_id: int,
    payload: PositionFollowUpUpdate,
) -> Optional[PositionFollowUpItem]:
    row = db.query(UserPositionFollowUp).filter(UserPositionFollowUp.id == follow_up_id, UserPositionFollowUp.user_id == user_id).first()
    if row is None:
        return None

    if payload.follow_date is not None:
        row.follow_date = payload.follow_date
    if payload.stage is not None:
        row.stage = payload.stage
    if payload.status is not None:
        row.status = payload.status
    if payload.summary is not None:
        row.summary = payload.summary
    if payload.action_items is not None:
        row.action_items_json = _dump_json_list(payload.action_items)
    if payload.next_follow_date is not None:
        row.next_follow_date = payload.next_follow_date
    if payload.confidence_score is not None:
        row.confidence_score = payload.confidence_score
    if payload.discipline_score is not None:
        row.discipline_score = payload.discipline_score

    db.add(row)
    db.commit()
    db.refresh(row)

    stock = _resolve_stock_row(db, row.symbol)
    position_name = stock.name if stock is not None else row.symbol
    return _follow_up_row_to_schema(row, position_name=position_name)


def delete_user_follow_up(db: Session, user_id: int, follow_up_id: int) -> bool:
    row = db.query(UserPositionFollowUp).filter(UserPositionFollowUp.id == follow_up_id, UserPositionFollowUp.user_id == user_id).first()
    if row is None:
        return False

    db.delete(row)
    db.commit()
    return True
