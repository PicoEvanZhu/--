import json
import re
from datetime import datetime, timezone
from typing import List, Optional, Tuple

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.stock_universe import StockUniverse
from app.models.trade_review import TradeReview
from app.models.user_platform import AppUser
from app.schemas.stock import (
    StockTradeReviewCreate,
    StockTradeReviewItem,
    StockTradeReviewResponse,
    StockTradeReviewSummary,
    StockTradeReviewUpdate,
)
from app.services.stock_service import get_stock_detail

ACTION_DIRECTION = {
    "buy": 1,
    "add": 1,
    "sell": -1,
    "reduce": -1,
    "observe": 0,
}


def _as_utc(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _serialize_datetime(value: Optional[datetime]) -> str:
    value_utc = _as_utc(value)
    if value_utc is None:
        return ""
    return value_utc.isoformat()


def _normalize_date(value: Optional[str], required: bool = False) -> Optional[str]:
    text = (value or "").strip()
    if not text:
        if required:
            raise ValueError("日期不能为空")
        return None

    candidate = text[:10]

    try:
        datetime.strptime(candidate, "%Y-%m-%d")
        return candidate
    except ValueError:
        pass

    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("日期格式应为 YYYY-MM-DD") from exc

    return parsed.strftime("%Y-%m-%d")


def _clean_text(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    text = value.strip()
    return text or None


def _normalize_follow_up_items(items: Optional[List[str]]) -> List[str]:
    if not items:
        return []

    normalized: List[str] = []
    for item in items:
        text = str(item).strip()
        if text:
            normalized.append(text)

    return list(dict.fromkeys(normalized))


def _resolve_stock_row(db: Session, symbol: str) -> Optional[StockUniverse]:
    target = symbol.strip().upper()
    if not target:
        return None

    row = db.query(StockUniverse).filter(func.upper(StockUniverse.symbol) == target).first()
    if row is not None:
        return row

    clean = re.sub(r"[^0-9A-Z]", "", target)

    if clean.startswith(("SH", "SZ", "BJ")) and len(clean) > 2:
        code = clean[2:]
        suffix = clean[:2]
        row = (
            db.query(StockUniverse)
            .filter(StockUniverse.code == code)
            .filter(func.upper(StockUniverse.symbol).like(f"%.{suffix}"))
            .first()
        )
        if row is not None:
            return row

    if clean.isdigit():
        row = db.query(StockUniverse).filter(StockUniverse.code == clean.zfill(5)).first()
        if row is not None:
            return row

        row = db.query(StockUniverse).filter(StockUniverse.code == clean).first()
        if row is not None:
            return row
    elif clean:
        row = db.query(StockUniverse).filter(func.upper(StockUniverse.code) == clean).first()
        if row is not None:
            return row

    return None


def _floating_pnl(action: str, entry_price: Optional[float], quantity: Optional[float], current_price: Optional[float]) -> Tuple[Optional[float], Optional[float]]:
    if current_price is None or entry_price is None or quantity is None:
        return None, None

    if entry_price <= 0 or quantity <= 0:
        return None, None

    direction = ACTION_DIRECTION.get(action, 0)
    if direction == 0:
        return None, None

    pnl = round(direction * (current_price - entry_price) * quantity, 2)
    pnl_pct = round(direction * ((current_price / entry_price) - 1) * 100, 2)
    return pnl, pnl_pct


def _resolve_current_price(db: Session, symbol: str, fallback_price: Optional[float]) -> Optional[float]:
    if fallback_price is not None:
        return float(fallback_price)

    detail = get_stock_detail(db=db, symbol=symbol)
    if detail is None:
        return None

    return float(detail.price)


def _to_review_item(
    review: TradeReview,
    current_price: Optional[float],
    owner_user_id: Optional[int] = None,
    owner_username: Optional[str] = None,
) -> StockTradeReviewItem:
    try:
        parsed_items = json.loads(review.follow_up_items_json or "[]")
    except json.JSONDecodeError:
        parsed_items = []

    follow_up_items = _normalize_follow_up_items(parsed_items)
    pnl, pnl_pct = _floating_pnl(
        action=review.action,
        entry_price=review.price,
        quantity=review.quantity,
        current_price=current_price,
    )

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    is_due = bool(review.next_review_date and review.follow_up_status != "closed" and review.next_review_date <= today)

    return StockTradeReviewItem(
        id=review.id,
        symbol=review.symbol,
        owner_user_id=owner_user_id,
        owner_username=owner_username,
        trade_date=review.trade_date,
        action=review.action,
        price=review.price,
        quantity=review.quantity,
        thesis=review.thesis,
        execution_notes=review.execution_notes,
        outcome_review=review.outcome_review,
        lessons_learned=review.lessons_learned,
        follow_up_items=follow_up_items,
        follow_up_status=review.follow_up_status,
        next_review_date=review.next_review_date,
        confidence_score=review.confidence_score,
        discipline_score=review.discipline_score,
        created_at=_serialize_datetime(review.created_at),
        updated_at=_serialize_datetime(review.updated_at),
        floating_pnl=pnl,
        floating_pnl_pct=pnl_pct,
        is_follow_up_due=is_due,
    )


def _build_summary(items: List[StockTradeReviewItem]) -> StockTradeReviewSummary:
    confidence_scores = [item.confidence_score for item in items if item.confidence_score is not None]
    discipline_scores = [item.discipline_score for item in items if item.discipline_score is not None]
    pnl_values = [item.floating_pnl for item in items if item.floating_pnl is not None]
    pnl_pct_values = [item.floating_pnl_pct for item in items if item.floating_pnl_pct is not None]

    return StockTradeReviewSummary(
        total_reviews=len(items),
        open_follow_ups=len([item for item in items if item.follow_up_status == "open"]),
        in_progress_follow_ups=len([item for item in items if item.follow_up_status == "in_progress"]),
        closed_follow_ups=len([item for item in items if item.follow_up_status == "closed"]),
        due_follow_ups=len([item for item in items if item.is_follow_up_due]),
        avg_confidence_score=round(sum(confidence_scores) / len(confidence_scores), 1) if confidence_scores else 0.0,
        avg_discipline_score=round(sum(discipline_scores) / len(discipline_scores), 1) if discipline_scores else 0.0,
        net_floating_pnl=round(sum(pnl_values), 2) if pnl_values else 0.0,
        net_floating_pnl_pct=round(sum(pnl_pct_values) / len(pnl_pct_values), 2) if pnl_pct_values else 0.0,
    )


def _validate_trade_payload(action: str, price: Optional[float], quantity: Optional[float], thesis: str) -> None:
    if not thesis.strip():
        raise ValueError("交易逻辑不能为空")

    if action != "observe":
        if price is None or quantity is None:
            raise ValueError("买入/卖出/加减仓记录必须填写成交价和数量")

    if price is not None and price <= 0:
        raise ValueError("成交价必须大于 0")

    if quantity is not None and quantity <= 0:
        raise ValueError("数量必须大于 0")


def get_stock_trade_reviews(
    db: Session,
    symbol: str,
    user_id: int,
    include_all: bool = False,
) -> Optional[StockTradeReviewResponse]:
    stock_row = _resolve_stock_row(db, symbol)
    if stock_row is None:
        return None

    current_price = _resolve_current_price(db=db, symbol=stock_row.symbol, fallback_price=stock_row.price)

    query = db.query(TradeReview).filter(TradeReview.symbol == stock_row.symbol)
    if not include_all:
        query = query.filter(TradeReview.user_id == user_id)

    rows = query.order_by(TradeReview.trade_date.desc(), TradeReview.created_at.desc(), TradeReview.id.desc()).all()

    owner_name_map = {}
    if include_all:
        owner_ids = sorted({int(row.user_id) for row in rows if row.user_id is not None})
        if owner_ids:
            users = db.query(AppUser).filter(AppUser.id.in_(owner_ids)).all()
            owner_name_map = {item.id: item.username for item in users}

    items = [
        _to_review_item(
            row,
            current_price=current_price,
            owner_user_id=row.user_id if include_all else None,
            owner_username=owner_name_map.get(int(row.user_id)) if include_all and row.user_id is not None else None,
        )
        for row in rows
    ]
    summary = _build_summary(items)

    return StockTradeReviewResponse(
        symbol=stock_row.symbol,
        current_price=current_price,
        items=items,
        summary=summary,
    )


def create_stock_trade_review(db: Session, symbol: str, payload: StockTradeReviewCreate, user_id: int) -> Optional[StockTradeReviewItem]:
    stock_row = _resolve_stock_row(db, symbol)
    if stock_row is None:
        return None

    _validate_trade_payload(action=payload.action, price=payload.price, quantity=payload.quantity, thesis=payload.thesis)

    review = TradeReview(
        symbol=stock_row.symbol,
        user_id=user_id,
        trade_date=_normalize_date(payload.trade_date, required=True) or "",
        action=payload.action,
        price=payload.price,
        quantity=payload.quantity,
        thesis=payload.thesis.strip(),
        execution_notes=_clean_text(payload.execution_notes),
        outcome_review=_clean_text(payload.outcome_review),
        lessons_learned=_clean_text(payload.lessons_learned),
        follow_up_items_json=json.dumps(_normalize_follow_up_items(payload.follow_up_items), ensure_ascii=False),
        follow_up_status=payload.follow_up_status,
        next_review_date=_normalize_date(payload.next_review_date),
        confidence_score=payload.confidence_score,
        discipline_score=payload.discipline_score,
    )

    db.add(review)
    db.commit()
    db.refresh(review)

    current_price = _resolve_current_price(db=db, symbol=stock_row.symbol, fallback_price=stock_row.price)
    return _to_review_item(review, current_price=current_price)


def update_stock_trade_review(
    db: Session,
    symbol: str,
    review_id: int,
    payload: StockTradeReviewUpdate,
    user_id: int,
    can_manage_all: bool = False,
) -> Optional[StockTradeReviewItem]:
    stock_row = _resolve_stock_row(db, symbol)
    if stock_row is None:
        return None

    query = db.query(TradeReview).filter(TradeReview.id == review_id, TradeReview.symbol == stock_row.symbol)
    if not can_manage_all:
        query = query.filter(TradeReview.user_id == user_id)

    review = query.first()
    if review is None:
        return None

    data = payload.model_dump(exclude_unset=True)

    action = data.get("action", review.action)
    price = data.get("price", review.price)
    quantity = data.get("quantity", review.quantity)
    thesis = data.get("thesis", review.thesis)

    if thesis is None:
        thesis = review.thesis

    _validate_trade_payload(action=action, price=price, quantity=quantity, thesis=thesis)

    if "trade_date" in data and data["trade_date"] is not None:
        review.trade_date = _normalize_date(data["trade_date"], required=True) or review.trade_date
    if "action" in data and data["action"] is not None:
        review.action = data["action"]
    if "price" in data:
        review.price = data["price"]
    if "quantity" in data:
        review.quantity = data["quantity"]
    if "thesis" in data and data["thesis"] is not None:
        review.thesis = data["thesis"].strip()
    if "execution_notes" in data:
        review.execution_notes = _clean_text(data["execution_notes"])
    if "outcome_review" in data:
        review.outcome_review = _clean_text(data["outcome_review"])
    if "lessons_learned" in data:
        review.lessons_learned = _clean_text(data["lessons_learned"])
    if "follow_up_items" in data:
        review.follow_up_items_json = json.dumps(
            _normalize_follow_up_items(data["follow_up_items"]),
            ensure_ascii=False,
        )
    if "follow_up_status" in data and data["follow_up_status"] is not None:
        review.follow_up_status = data["follow_up_status"]
    if "next_review_date" in data:
        review.next_review_date = _normalize_date(data["next_review_date"])
    if "confidence_score" in data:
        review.confidence_score = data["confidence_score"]
    if "discipline_score" in data:
        review.discipline_score = data["discipline_score"]

    db.add(review)
    db.commit()
    db.refresh(review)

    current_price = _resolve_current_price(db=db, symbol=stock_row.symbol, fallback_price=stock_row.price)
    return _to_review_item(review, current_price=current_price)
