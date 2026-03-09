from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.database import get_db
from app.models.user_platform import AppUser
from app.schemas.stock import (
    MarketType,
    RecommendationType,
    StockEnrichResponse,
    StockEnrichStatusResponse,
    StockKLineResponse,
    StockAnalysis,
    StockDetail,
    StockQARequest,
    StockQAResponse,
    StockListResponse,
    SectorRotationResponse,
    StockSnapshot,
    StockSyncResponse,
    StockTradeReviewCreate,
    StockTradeReviewItem,
    StockTradeReviewResponse,
    StockTradeReviewUpdate,
)
from app.services.enrichment_service import enrich_stock_universe, get_enrichment_status
from app.services.stock_service import (
    ask_stock_question,
    get_sector_rotation_summary,
    get_stock_analysis,
    get_stock_kline,
    get_stock_detail,
    get_stock_list,
    get_stock_snapshot,
    sync_stock_universe,
)
from app.services.trade_review_service import create_stock_trade_review, get_stock_trade_reviews, update_stock_trade_review

router = APIRouter(prefix="/stocks", tags=["stocks"])


@router.get("", response_model=StockListResponse)
def list_stocks(
    analyzed: Optional[bool] = Query(default=None),
    market: Optional[MarketType] = Query(default=None),
    board: Optional[str] = Query(default=None),
    exchange: Optional[str] = Query(default=None),
    industry: Optional[str] = Query(default=None),
    concept: Optional[str] = Query(default=None),
    tag: Optional[str] = Query(default=None),
    recommendation: Optional[RecommendationType] = Query(default=None),
    dividend_only: Optional[bool] = Query(default=None),
    dividend_years_min: Optional[int] = Query(default=None, ge=1, le=20),
    dividend_yield_min: Optional[float] = Query(default=None, ge=0, le=50),
    ex_dividend_soon: Optional[bool] = Query(default=None),
    market_cap_min: Optional[float] = Query(default=None, ge=0, le=1000000),
    market_cap_max: Optional[float] = Query(default=None, ge=0, le=1000000),
    price_min: Optional[float] = Query(default=None, ge=0, le=1000000),
    price_max: Optional[float] = Query(default=None, ge=0, le=1000000),
    pe_max: Optional[float] = Query(default=None, ge=0, le=500),
    net_profit_min: Optional[float] = Query(default=None, ge=0, le=1000000),
    revenue_min: Optional[float] = Query(default=None, ge=0, le=1000000),
    revenue_growth_min: Optional[float] = Query(default=None, ge=-100, le=300),
    revenue_growth_qoq_min: Optional[float] = Query(default=None, ge=-100, le=300),
    profit_growth_min: Optional[float] = Query(default=None, ge=-100, le=300),
    profit_growth_qoq_min: Optional[float] = Query(default=None, ge=-100, le=300),
    gross_margin_min: Optional[float] = Query(default=None, ge=0, le=100),
    net_margin_min: Optional[float] = Query(default=None, ge=-100, le=100),
    roe_min: Optional[float] = Query(default=None, ge=-100, le=100),
    debt_ratio_max: Optional[float] = Query(default=None, ge=0, le=100),
    exclude_st: Optional[bool] = Query(default=None),
    score_min: Optional[int] = Query(default=None, ge=1, le=99),
    score_max: Optional[int] = Query(default=None, ge=1, le=99),
    change_pct_min: Optional[float] = Query(default=None, ge=-30, le=30),
    change_pct_max: Optional[float] = Query(default=None, ge=-30, le=30),
    prev_limit_up: Optional[bool] = Query(default=None),
    prev_limit_down: Optional[bool] = Query(default=None),
    q: Optional[str] = Query(default=None),
    sort_by: Literal["score", "change_pct", "price", "dividend_years", "dividend_yield"] = Query(default="score"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=10, le=200),
    include_meta: bool = Query(default=True),
    db: Session = Depends(get_db),
) -> StockListResponse:
    return get_stock_list(
        db=db,
        analyzed=analyzed,
        market=market,
        board=board,
        exchange=exchange,
        industry=industry,
        concept=concept,
        tag=tag,
        recommendation=recommendation,
        dividend_only=dividend_only,
        dividend_years_min=dividend_years_min,
        dividend_yield_min=dividend_yield_min,
        ex_dividend_soon=ex_dividend_soon,
        market_cap_min=market_cap_min,
        market_cap_max=market_cap_max,
        price_min=price_min,
        price_max=price_max,
        pe_max=pe_max,
        net_profit_min=net_profit_min,
        revenue_min=revenue_min,
        revenue_growth_min=revenue_growth_min,
        revenue_growth_qoq_min=revenue_growth_qoq_min,
        profit_growth_min=profit_growth_min,
        profit_growth_qoq_min=profit_growth_qoq_min,
        gross_margin_min=gross_margin_min,
        net_margin_min=net_margin_min,
        roe_min=roe_min,
        debt_ratio_max=debt_ratio_max,
        exclude_st=exclude_st,
        score_min=score_min,
        score_max=score_max,
        change_pct_min=change_pct_min,
        change_pct_max=change_pct_max,
        prev_limit_up=prev_limit_up,
        prev_limit_down=prev_limit_down,
        q=q,
        sort_by=sort_by,
        page=page,
        page_size=page_size,
        include_meta=include_meta,
    )


@router.get("/sectors/rotation", response_model=SectorRotationResponse)
def get_sector_rotation_endpoint(
    market: Optional[MarketType] = Query(default=None),
    top_n: int = Query(default=8, ge=3, le=15),
    db: Session = Depends(get_db),
) -> SectorRotationResponse:
    return get_sector_rotation_summary(db=db, market=market, top_n=top_n)


@router.post("/sync", response_model=StockSyncResponse)
def sync_stocks(
    force: bool = Query(default=False),
    db: Session = Depends(get_db),
) -> StockSyncResponse:
    return sync_stock_universe(db=db, force=force)


@router.post("/enrich", response_model=StockEnrichResponse)
def enrich_stocks(
    force: bool = Query(default=False),
    market: Optional[MarketType] = Query(default=None),
    limit: Optional[int] = Query(default=None, ge=1, le=10000),
    sleep_ms: int = Query(default=120, ge=0, le=3000),
    db: Session = Depends(get_db),
) -> StockEnrichResponse:
    return enrich_stock_universe(
        db=db,
        force=force,
        market=market,
        limit=limit,
        sleep_ms=sleep_ms,
    )


@router.get("/enrich/status", response_model=StockEnrichStatusResponse)
def get_enrich_status(db: Session = Depends(get_db)) -> StockEnrichStatusResponse:
    return get_enrichment_status(db=db)


@router.get("/{symbol}/reviews", response_model=StockTradeReviewResponse)
def get_stock_trade_reviews_endpoint(
    symbol: str,
    user: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> StockTradeReviewResponse:
    response = get_stock_trade_reviews(db=db, symbol=symbol, user_id=user.id, include_all=(user.role == "admin"))
    if response is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="股票不存在")
    return response


@router.post("/{symbol}/reviews", response_model=StockTradeReviewItem, status_code=status.HTTP_201_CREATED)
def create_stock_trade_review_endpoint(
    symbol: str,
    payload: StockTradeReviewCreate,
    user: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> StockTradeReviewItem:
    try:
        response = create_stock_trade_review(db=db, symbol=symbol, payload=payload, user_id=user.id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    if response is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="股票不存在")
    return response


@router.patch("/{symbol}/reviews/{review_id}", response_model=StockTradeReviewItem)
def update_stock_trade_review_endpoint(
    symbol: str,
    review_id: int,
    payload: StockTradeReviewUpdate,
    user: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> StockTradeReviewItem:
    try:
        response = update_stock_trade_review(
            db=db,
            symbol=symbol,
            review_id=review_id,
            payload=payload,
            user_id=user.id,
            can_manage_all=(user.role == "admin"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    if response is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="股票或复盘记录不存在")
    return response


@router.get("/{symbol}/kline", response_model=StockKLineResponse)
def get_stock_kline_endpoint(
    symbol: str,
    period: Literal["1mo", "3mo", "6mo", "1y", "5y"] = Query(default="6mo"),
    interval: Literal["1d", "1h"] = Query(default="1d"),
    db: Session = Depends(get_db),
) -> StockKLineResponse:
    response = get_stock_kline(db=db, symbol=symbol, period=period, interval=interval)
    if response is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="股票不存在")
    return response


@router.post("/{symbol}/qa", response_model=StockQAResponse)
def ask_stock_question_endpoint(
    symbol: str,
    payload: StockQARequest,
    db: Session = Depends(get_db),
) -> StockQAResponse:
    response = ask_stock_question(db=db, symbol=symbol, question=payload.question, history=[item.model_dump() for item in payload.history])
    if response is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="股票不存在")
    return response


@router.get("/{symbol}", response_model=StockDetail)
def get_stock_detail_endpoint(symbol: str, db: Session = Depends(get_db)) -> StockDetail:
    stock = get_stock_detail(db=db, symbol=symbol)
    if stock is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="股票不存在")
    return stock


@router.get("/{symbol}/analysis", response_model=StockAnalysis)
def get_stock_analysis_endpoint(symbol: str, db: Session = Depends(get_db)) -> StockAnalysis:
    analysis = get_stock_analysis(db=db, symbol=symbol)
    if analysis is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="股票不存在")
    return analysis


@router.get("/{symbol}/snapshot", response_model=StockSnapshot)
def get_stock_snapshot_endpoint(symbol: str, db: Session = Depends(get_db)) -> StockSnapshot:
    snapshot = get_stock_snapshot(db=db, symbol=symbol)
    if snapshot is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="股票不存在")
    return snapshot
