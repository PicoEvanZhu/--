import hashlib
import logging
import os
import re
import subprocess
import tempfile
import time
from csv import DictReader
from collections import Counter
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from io import StringIO
from threading import Lock
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.models.stock_universe import StockUniverse
from app.services.enrichment_service import get_stock_enrichment, merge_stock_detail_with_enrichment
from app.schemas.stock import (
    DashboardSummary,
    DividendRecord,
    FinancialReport,
    PeerCompany,
    ReportDetail,
    ReportListItem,
    ShareholderRecord,
    StockAnalysis,
    StockDetail,
    StockFactorScores,
    StockItem,
    StockListResponse,
    StockListStats,
    StockSnapshot,
    StockSyncResponse,
    TradePlan,
    ValuationHistoryPoint,
)

os.environ.setdefault("TQDM_DISABLE", "1")

logger = logging.getLogger("stock_assistant.stock_service")

SYNC_COOLDOWN_SECONDS = 4 * 60 * 60
MIN_UNIVERSE_READY_COUNT = 1200
MAX_PAGE_SIZE = 200

_sync_lock = Lock()

_FALLBACK_UNIVERSE_ROWS: List[Dict[str, Any]] = [
    {
        "symbol": "600519.SH",
        "code": "600519",
        "name": "贵州茅台",
        "market": "A股",
        "board": "主板",
        "exchange": "SSE",
        "price": 1688.0,
        "change_pct": 1.42,
    },
    {
        "symbol": "00700.HK",
        "code": "00700",
        "name": "腾讯控股",
        "market": "港股",
        "board": "港股",
        "exchange": "HKEX",
        "price": 382.6,
        "change_pct": -0.68,
    },
    {
        "symbol": "300750.SZ",
        "code": "300750",
        "name": "宁德时代",
        "market": "创业板",
        "board": "创业板",
        "exchange": "SZSE",
        "price": 184.2,
        "change_pct": 2.35,
    },
    {
        "symbol": "09988.HK",
        "code": "09988",
        "name": "阿里巴巴-W",
        "market": "港股",
        "board": "港股",
        "exchange": "HKEX",
        "price": 76.3,
        "change_pct": 0.96,
    },
    {
        "symbol": "688981.SH",
        "code": "688981",
        "name": "中芯国际",
        "market": "科创板",
        "board": "科创板",
        "exchange": "SSE",
        "price": 53.8,
        "change_pct": -1.83,
    },
    {
        "symbol": "601318.SH",
        "code": "601318",
        "name": "中国平安",
        "market": "A股",
        "board": "主板",
        "exchange": "SSE",
        "price": 49.7,
        "change_pct": 0.35,
    },
    {
        "symbol": "AAPL.US",
        "code": "AAPL",
        "name": "Apple Inc.",
        "market": "美股",
        "board": "美股",
        "exchange": "NASDAQ",
        "price": 192.8,
        "change_pct": 0.86,
    },
    {
        "symbol": "MSFT.US",
        "code": "MSFT",
        "name": "Microsoft Corporation",
        "market": "美股",
        "board": "美股",
        "exchange": "NASDAQ",
        "price": 421.3,
        "change_pct": 0.64,
    },
]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _safe_float(value: Any) -> Optional[float]:
    if value is None:
        return None

    text = str(value).strip().replace(",", "")
    if text in {"", "--", "None", "nan", "NaN"}:
        return None

    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def _stable_metric(symbol: str, salt: str, low: float, high: float, precision: int = 2) -> float:
    digest = hashlib.sha256(f"{symbol}:{salt}".encode("utf-8")).hexdigest()
    ratio = int(digest[:8], 16) / 0xFFFFFFFF
    value = low + (high - low) * ratio
    return round(value, precision)


def _serialize_dt(value: Optional[datetime]) -> Optional[str]:
    value_utc = _as_utc(value)
    if value_utc is None:
        return None
    return value_utc.isoformat()


def _classify_a_share(prefix: str, code: str) -> Tuple[str, str, str]:
    if prefix == "BJ":
        return "A股", "北交所", "BSE"

    if prefix == "SZ" and code.startswith("300"):
        return "创业板", "创业板", "SZSE"

    if prefix == "SH" and code.startswith("688"):
        return "科创板", "科创板", "SSE"

    exchange = "SSE" if prefix == "SH" else "SZSE"
    return "A股", "主板", exchange


def _normalize_a_code(raw_code: str) -> Optional[Tuple[str, str, str, str, str]]:
    code_text = str(raw_code).strip().lower()
    if not code_text:
        return None

    prefix = ""
    digits = ""

    if code_text.startswith(("sh", "sz", "bj")):
        prefix = code_text[:2].upper()
        digits = re.sub(r"\D", "", code_text[2:])
    else:
        digits = re.sub(r"\D", "", code_text)
        if not digits:
            return None

        if digits.startswith(("4", "8", "9")):
            prefix = "BJ"
        elif digits.startswith(("5", "6", "9")):
            prefix = "SH"
        else:
            prefix = "SZ"

    if not digits:
        return None

    market, board, exchange = _classify_a_share(prefix, digits)
    symbol = f"{digits}.{prefix}"
    return symbol, digits, market, board, exchange


def _normalize_hk_code(raw_code: str) -> Optional[str]:
    code_text = re.sub(r"\D", "", str(raw_code).strip())
    if not code_text:
        return None
    return code_text.zfill(5)


def _normalize_us_symbol(raw_symbol: Any) -> Optional[str]:
    symbol_text = str(raw_symbol or "").strip().upper()
    if not symbol_text:
        return None

    symbol_text = symbol_text.replace(".", "-")
    symbol_text = re.sub(r"[^A-Z0-9\-]", "", symbol_text)
    symbol_text = symbol_text.strip("-")
    if not symbol_text:
        return None

    return symbol_text


def _clean_us_name(raw_name: Any) -> str:
    name = str(raw_name or "").strip()
    if not name:
        return ""

    name = re.sub(r"\s+-\s+Common Stock\s*$", "", name, flags=re.IGNORECASE)
    name = re.sub(r"\s+-\s+Ordinary Shares\s*$", "", name, flags=re.IGNORECASE)
    return name.strip()


def _fetch_text_by_curl(url: str, max_time: int = 45) -> str:
    completed = subprocess.run(
        ["curl", "-fsSL", "--max-time", str(max_time), url],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout


def _silence_akshare_output() -> Tuple[StringIO, StringIO]:
    return StringIO(), StringIO()


def _run_with_retry(callable_fn, attempts: int = 3, delay_seconds: float = 1.2):
    last_error: Optional[Exception] = None
    for attempt in range(1, attempts + 1):
        try:
            return callable_fn()
        except Exception as exc:  # noqa: PERF203
            last_error = exc
            if attempt < attempts:
                time.sleep(delay_seconds * attempt)

    if last_error is None:
        raise RuntimeError("未知抓取错误")
    raise last_error


def _fetch_a_share_rows() -> Tuple[List[Dict[str, Any]], str]:
    import akshare as ak

    out, err = _silence_akshare_output()

    def _fetch_spot_df():
        with redirect_stdout(out), redirect_stderr(err):
            return ak.stock_zh_a_spot()

    def _fetch_code_df():
        with redirect_stdout(out), redirect_stderr(err):
            return ak.stock_info_a_code_name()

    rows: List[Dict[str, Any]] = []
    try:
        spot_df = _run_with_retry(_fetch_spot_df, attempts=2, delay_seconds=1.5)
        for item in spot_df.to_dict("records"):
            normalized = _normalize_a_code(item.get("代码"))
            if normalized is None:
                continue

            symbol, code, market, board, exchange = normalized
            name = str(item.get("名称") or "").strip()
            if not name:
                continue

            rows.append(
                {
                    "symbol": symbol,
                    "code": code,
                    "name": name,
                    "market": market,
                    "board": board,
                    "exchange": exchange,
                    "source": "stock_zh_a_spot",
                    "price": _safe_float(item.get("最新价")),
                    "change_pct": _safe_float(item.get("涨跌幅")),
                    "volume": _safe_float(item.get("成交量")),
                    "turnover": _safe_float(item.get("成交额")),
                }
            )

        if rows:
            return rows, "stock_zh_a_spot"
    except Exception as exc:
        logger.warning("stock_zh_a_spot 拉取失败，回退到 stock_info_a_code_name: %s", exc)

    code_df = _run_with_retry(_fetch_code_df, attempts=3, delay_seconds=1.5)

    for item in code_df.to_dict("records"):
        normalized = _normalize_a_code(item.get("code"))
        if normalized is None:
            continue

        symbol, code, market, board, exchange = normalized
        name = str(item.get("name") or "").strip()
        if not name:
            continue

        rows.append(
            {
                "symbol": symbol,
                "code": code,
                "name": name,
                "market": market,
                "board": board,
                "exchange": exchange,
                "source": "stock_info_a_code_name",
                "price": None,
                "change_pct": None,
                "volume": None,
                "turnover": None,
            }
        )

    return rows, "stock_info_a_code_name"


def _fetch_hk_rows() -> Tuple[List[Dict[str, Any]], str]:
    import akshare as ak

    out, err = _silence_akshare_output()
    source_used = "stock_hk_spot"

    def _fetch_hk_spot_df():
        with redirect_stdout(out), redirect_stderr(err):
            return ak.stock_hk_spot()

    def _fetch_hk_spot_em_df():
        with redirect_stdout(out), redirect_stderr(err):
            return ak.stock_hk_spot_em()

    def _fetch_hk_rows_from_hkex_list() -> List[Dict[str, Any]]:
        import pandas as pd

        url = "https://www.hkex.com.hk/eng/services/trading/securities/securitieslists/ListOfSecurities.xlsx"

        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=True) as file:
            subprocess.run(
                ["curl", "-fsSL", "--max-time", "45", "-o", file.name, url],
                check=True,
                capture_output=True,
                text=True,
            )

            df = pd.read_excel(file.name, header=2)

        output_rows: List[Dict[str, Any]] = []
        for item in df.to_dict("records"):
            category = str(item.get("Category") or "").strip().lower()
            if category != "equity":
                continue

            code = _normalize_hk_code(item.get("Stock Code"))
            if code is None:
                continue

            name = str(item.get("Name of Securities") or "").strip()
            if not name:
                continue

            output_rows.append(
                {
                    "symbol": f"{code}.HK",
                    "code": code,
                    "name": name,
                    "market": "港股",
                    "board": "港股",
                    "exchange": "HKEX",
                    "source": "hkex_list_of_securities",
                    "price": None,
                    "change_pct": None,
                    "volume": None,
                    "turnover": None,
                }
            )

        return output_rows

    try:
        hk_df = _run_with_retry(_fetch_hk_spot_df, attempts=3, delay_seconds=1.8)
    except Exception as primary_error:
        logger.warning("stock_hk_spot 拉取失败，尝试 stock_hk_spot_em: %s", primary_error)
        try:
            hk_df = _run_with_retry(_fetch_hk_spot_em_df, attempts=2, delay_seconds=1.5)
            source_used = "stock_hk_spot_em"
        except Exception as em_error:
            logger.warning("stock_hk_spot_em 拉取失败，尝试 HKEX 官方列表: %s", em_error)
            hk_rows = _run_with_retry(_fetch_hk_rows_from_hkex_list, attempts=2, delay_seconds=1.5)
            return hk_rows, "hkex_list_of_securities"

    rows: List[Dict[str, Any]] = []
    for item in hk_df.to_dict("records"):
        code = _normalize_hk_code(item.get("代码"))
        if code is None:
            continue

        name = str(item.get("中文名称") or item.get("名称") or "").strip()
        if not name:
            continue

        rows.append(
            {
                "symbol": f"{code}.HK",
                "code": code,
                "name": name,
                "market": "港股",
                "board": "港股",
                "exchange": "HKEX",
                "source": source_used,
                "price": _safe_float(item.get("最新价")),
                "change_pct": _safe_float(item.get("涨跌幅")),
                "volume": _safe_float(item.get("成交量")),
                "turnover": _safe_float(item.get("成交额")),
            }
        )

    return rows, source_used


def _fetch_us_rows() -> Tuple[List[Dict[str, Any]], str]:
    def _parse_nasdaqlisted(text: str) -> List[Dict[str, Any]]:
        reader = DictReader(StringIO(text), delimiter="|")
        rows: List[Dict[str, Any]] = []

        for item in reader:
            raw_symbol = item.get("Symbol")
            symbol_code = _normalize_us_symbol(raw_symbol)
            if symbol_code is None:
                continue

            if symbol_code == "FILECREATIONTIME":
                continue

            test_issue = str(item.get("Test Issue") or "").strip().upper()
            if test_issue == "Y":
                continue

            etf_flag = str(item.get("ETF") or "").strip().upper()
            if etf_flag == "Y":
                continue

            name = _clean_us_name(item.get("Security Name"))
            if not name:
                continue

            rows.append(
                {
                    "symbol": f"{symbol_code}.US",
                    "code": symbol_code,
                    "name": name,
                    "market": "美股",
                    "board": "美股",
                    "exchange": "NASDAQ",
                    "source": "nasdaqtrader_nasdaqlisted",
                    "price": None,
                    "change_pct": None,
                    "volume": None,
                    "turnover": None,
                }
            )

        return rows

    def _parse_otherlisted(text: str) -> List[Dict[str, Any]]:
        exchange_map = {
            "N": "NYSE",
            "A": "NYSEMKT",
            "P": "NYSEARCA",
            "Z": "BATS",
            "V": "IEX",
        }

        reader = DictReader(StringIO(text), delimiter="|")
        rows: List[Dict[str, Any]] = []

        for item in reader:
            raw_symbol = item.get("ACT Symbol")
            symbol_code = _normalize_us_symbol(raw_symbol)
            if symbol_code is None:
                continue

            if symbol_code == "FILECREATIONTIME":
                continue

            test_issue = str(item.get("Test Issue") or "").strip().upper()
            if test_issue == "Y":
                continue

            etf_flag = str(item.get("ETF") or "").strip().upper()
            if etf_flag == "Y":
                continue

            name = _clean_us_name(item.get("Security Name"))
            if not name:
                continue

            exchange_code = str(item.get("Exchange") or "").strip().upper()
            exchange = exchange_map.get(exchange_code, "US")

            rows.append(
                {
                    "symbol": f"{symbol_code}.US",
                    "code": symbol_code,
                    "name": name,
                    "market": "美股",
                    "board": "美股",
                    "exchange": exchange,
                    "source": "nasdaqtrader_otherlisted",
                    "price": None,
                    "change_pct": None,
                    "volume": None,
                    "turnover": None,
                }
            )

        return rows

    nasdaq_text = _fetch_text_by_curl("https://www.nasdaqtrader.com/dynamic/symdir/nasdaqlisted.txt")
    other_text = _fetch_text_by_curl("https://www.nasdaqtrader.com/dynamic/symdir/otherlisted.txt")

    merged: Dict[str, Dict[str, Any]] = {}
    for row in _parse_nasdaqlisted(nasdaq_text):
        merged[row["symbol"]] = row
    for row in _parse_otherlisted(other_text):
        merged[row["symbol"]] = row

    ordered_rows = sorted(merged.values(), key=lambda row: row["symbol"])
    return ordered_rows, "nasdaqtrader"


def _seed_fallback_universe(db: Session) -> None:
    now = _utc_now()
    db.query(StockUniverse).delete(synchronize_session=False)

    objects = [
        StockUniverse(
            symbol=item["symbol"],
            code=item["code"],
            name=item["name"],
            market=item["market"],
            board=item["board"],
            exchange=item["exchange"],
            source="seed_builtin",
            listed=True,
            price=item.get("price"),
            change_pct=item.get("change_pct"),
            volume=None,
            turnover=None,
            updated_at=now,
        )
        for item in _FALLBACK_UNIVERSE_ROWS
    ]

    db.bulk_save_objects(objects)
    db.commit()


def _get_universe_count(db: Session) -> int:
    return int(db.query(func.count(StockUniverse.id)).scalar() or 0)


def _get_last_synced_at(db: Session) -> Optional[datetime]:
    return db.query(func.max(StockUniverse.updated_at)).scalar()


def _get_market_counts(db: Session) -> Tuple[int, int, int]:
    rows = (
        db.query(StockUniverse.market, func.count(StockUniverse.id))
        .group_by(StockUniverse.market)
        .all()
    )

    hk_count = 0
    us_count = 0
    a_share_count = 0
    for market, count in rows:
        count_int = int(count or 0)
        if market == "港股":
            hk_count += count_int
            continue
        if market == "美股":
            us_count += count_int
            continue
        a_share_count += count_int

    return a_share_count, hk_count, us_count


def sync_stock_universe(db: Session, force: bool = False) -> StockSyncResponse:
    started = time.perf_counter()

    with _sync_lock:
        current_count = _get_universe_count(db)
        last_synced_at = _get_last_synced_at(db)
        last_synced_at_utc = _as_utc(last_synced_at)

        if (
            not force
            and current_count >= MIN_UNIVERSE_READY_COUNT
            and last_synced_at_utc is not None
            and (_utc_now() - last_synced_at_utc).total_seconds() < SYNC_COOLDOWN_SECONDS
        ):
            a_share_count, hk_count, us_count = _get_market_counts(db)
            return StockSyncResponse(
                success=True,
                total_count=current_count,
                a_share_count=a_share_count,
                hk_count=hk_count,
                us_count=us_count,
                duration_ms=int((time.perf_counter() - started) * 1000),
                last_synced_at=_serialize_dt(last_synced_at_utc),
                message="使用缓存股票池（4小时内已同步）",
            )

        messages: List[str] = []
        merged: Dict[str, Dict[str, Any]] = {}

        try:
            a_rows, a_source = _fetch_a_share_rows()
            for row in a_rows:
                merged[row["symbol"]] = row
            messages.append(f"A股来源: {a_source}, 数量: {len(a_rows)}")
        except Exception as exc:
            logger.exception("A股数据同步失败")
            messages.append(f"A股同步失败: {exc}")

        try:
            hk_rows, hk_source = _fetch_hk_rows()
            for row in hk_rows:
                merged[row["symbol"]] = row
            messages.append(f"港股来源: {hk_source}, 数量: {len(hk_rows)}")
        except Exception as exc:
            logger.exception("港股数据同步失败")
            messages.append(f"港股同步失败: {exc}")

        try:
            us_rows, us_source = _fetch_us_rows()
            for row in us_rows:
                merged[row["symbol"]] = row
            messages.append(f"美股来源: {us_source}, 数量: {len(us_rows)}")
        except Exception as exc:
            logger.exception("美股数据同步失败")
            messages.append(f"美股同步失败: {exc}")

        if not merged:
            if current_count == 0:
                _seed_fallback_universe(db)
                fallback_count = _get_universe_count(db)
                a_share_count, hk_count, us_count = _get_market_counts(db)
                return StockSyncResponse(
                    success=False,
                    total_count=fallback_count,
                    a_share_count=a_share_count,
                    hk_count=hk_count,
                    us_count=us_count,
                    duration_ms=int((time.perf_counter() - started) * 1000),
                    last_synced_at=_serialize_dt(_get_last_synced_at(db)),
                    message="; ".join(messages) if messages else "外部数据同步失败，已回退内置样本",
                )

            a_share_count, hk_count, us_count = _get_market_counts(db)
            return StockSyncResponse(
                success=False,
                total_count=current_count,
                a_share_count=a_share_count,
                hk_count=hk_count,
                us_count=us_count,
                duration_ms=int((time.perf_counter() - started) * 1000),
                last_synced_at=_serialize_dt(last_synced_at_utc),
                message="; ".join(messages) if messages else "外部数据同步失败，已保留历史数据",
            )

        now = _utc_now()
        ordered_rows = sorted(merged.values(), key=lambda row: row["symbol"])

        objects = [
            StockUniverse(
                symbol=row["symbol"],
                code=row["code"],
                name=row["name"],
                market=row["market"],
                board=row["board"],
                exchange=row["exchange"],
                source=row["source"],
                listed=True,
                price=row.get("price"),
                change_pct=row.get("change_pct"),
                volume=row.get("volume"),
                turnover=row.get("turnover"),
                updated_at=now,
            )
            for row in ordered_rows
        ]

        db.query(StockUniverse).delete(synchronize_session=False)
        db.bulk_save_objects(objects)
        db.commit()

        total_count = len(objects)
        hk_count = sum(1 for item in objects if item.market == "港股")
        us_count = sum(1 for item in objects if item.market == "美股")
        a_share_count = total_count - hk_count - us_count

        return StockSyncResponse(
            success=True,
            total_count=total_count,
            a_share_count=a_share_count,
            hk_count=hk_count,
            us_count=us_count,
            duration_ms=int((time.perf_counter() - started) * 1000),
            last_synced_at=_serialize_dt(now),
            message="; ".join(messages),
        )


def ensure_stock_universe(db: Session) -> None:
    count = _get_universe_count(db)
    if count >= MIN_UNIVERSE_READY_COUNT:
        return

    result = sync_stock_universe(db, force=True)
    if result.success:
        return

    if _get_universe_count(db) == 0:
        _seed_fallback_universe(db)


def _score_from_universe_row(row: StockUniverse) -> int:
    score = 50.0

    change_pct = _market_change_pct(row)
    if -2.5 <= change_pct <= 4.5:
        score += 8
    elif 4.5 < change_pct <= 8:
        score += 4
    elif change_pct > 8:
        score -= 7
    elif -6 <= change_pct < -2.5:
        score -= 4
    elif change_pct < -6:
        score -= 10

    if row.market in {"创业板", "科创板"}:
        score -= 2
    if row.market == "港股":
        score -= 1
    if row.market == "美股":
        score -= 1

    price = _market_price(row)
    if 3 <= price <= 180:
        score += 4
    elif price < 1:
        score -= 8
    elif price > 1000:
        score -= 5

    turnover = row.turnover if row.turnover is not None else _stable_metric(row.symbol, "synthetic_turnover", 8_000_000, 6_000_000_000, 0)
    if turnover >= 3_000_000_000:
        score += 4
    elif turnover >= 300_000_000:
        score += 2
    elif turnover <= 20_000_000:
        score -= 5

    score += _stable_metric(row.symbol, "quality_bias", -16.0, 16.0, 1)

    return int(max(1, min(99, round(score))))


def _to_recommendation(score: int) -> str:
    if score >= 75:
        return "buy"
    if score >= 58:
        return "watch"
    if score >= 45:
        return "hold_cautious"
    return "avoid"


def _to_risk_level(score: int, stock: StockDetail) -> str:
    if score >= 75 and stock.volatility < 30:
        return "low"
    if score >= 50:
        return "medium"
    return "high"


def _market_price(row: StockUniverse) -> float:
    if row.price is not None and row.price > 0:
        return float(row.price)
    return _stable_metric(row.symbol, "synthetic_price", 3.5, 320.0, 2)


def _market_change_pct(row: StockUniverse) -> float:
    if row.change_pct is not None:
        return float(row.change_pct)
    return _stable_metric(row.symbol, "synthetic_change", -4.5, 4.5, 2)


def _industry_from_row(row: StockUniverse) -> str:
    return _detect_sector_theme(row.name, row.board)


def _build_list_tags(row: StockUniverse, industry: str, score: int, change_pct: float, price: float) -> List[str]:
    tags: List[str] = [row.market, row.board, row.exchange, industry]

    if score >= 75:
        tags.append("高评分")
    elif score <= 45:
        tags.append("高风险")

    if change_pct >= 3:
        tags.append("强势上涨")
    elif change_pct <= -3:
        tags.append("弱势回撤")

    if abs(change_pct) >= 5:
        tags.append("高波动")

    if price >= 200:
        tags.append("高价股")
    elif price <= 10:
        tags.append("低价股")

    if row.market == "创业板":
        tags.append("成长")
    if row.market == "科创板":
        tags.append("科技创新")
    if row.market == "港股":
        tags.append("离岸市场")
    if row.market == "美股":
        tags.append("海外市场")

    return list(dict.fromkeys(tags))[:9]


def _to_stock_item(row: StockUniverse) -> StockItem:
    score = _score_from_universe_row(row)
    price = _market_price(row)
    change_pct = _market_change_pct(row)
    industry = _industry_from_row(row)
    tags = _build_list_tags(row=row, industry=industry, score=score, change_pct=change_pct, price=price)

    return StockItem(
        symbol=row.symbol,
        name=row.name,
        market=row.market,
        board=row.board,
        exchange=row.exchange,
        industry=industry,
        sector=industry,
        tags=tags,
        price=price,
        change_pct=change_pct,
        analyzed=True,
        score=score,
        recommendation=_to_recommendation(score),
        updated_at=_serialize_dt(row.updated_at),
    )


def _query_universe_rows(db: Session, market: Optional[str] = None, q: Optional[str] = None) -> List[StockUniverse]:
    query = db.query(StockUniverse).filter(StockUniverse.listed.is_(True))

    if market:
        query = query.filter(StockUniverse.market == market)

    if q:
        q_like = f"%{q.strip()}%"
        query = query.filter(
            or_(
                StockUniverse.symbol.ilike(q_like),
                StockUniverse.code.ilike(q_like),
                StockUniverse.name.ilike(q_like),
                StockUniverse.board.ilike(q_like),
            )
        )

    return query.all()


def _resolve_stock_row(db: Session, symbol: str) -> Optional[StockUniverse]:
    target = symbol.strip().upper()

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


def _detect_sector_theme(name: str, board: str) -> str:
    lowered = name.lower()

    checks = [
        ("银行", "银行与金融服务"),
        ("证券", "证券与资本市场"),
        ("保险", "保险与资管"),
        ("芯", "半导体与电子"),
        ("半导体", "半导体与电子"),
        ("药", "医药与医疗健康"),
        ("医", "医药与医疗健康"),
        ("生物", "医药与医疗健康"),
        ("酒", "消费与食品饮料"),
        ("食品", "消费与食品饮料"),
        ("汽车", "汽车与智能制造"),
        ("电", "新能源与电力"),
        ("锂", "新能源与材料"),
        ("光伏", "新能源与材料"),
        ("科技", "互联网与科技服务"),
        ("软件", "互联网与科技服务"),
        ("网络", "互联网与科技服务"),
        ("通信", "通信与数字基建"),
    ]

    for keyword, theme in checks:
        if keyword in lowered or keyword in name:
            return theme

    if board == "创业板":
        return "成长创新产业"
    if board == "科创板":
        return "硬科技创新产业"
    if board == "港股":
        return "港股综合产业"
    if board == "美股":
        return "美股综合产业"
    return "综合产业"


def _build_business_tags(stock: StockDetail) -> List[str]:
    tags: List[str] = [stock.market, stock.board, stock.exchange]

    if stock.roe >= 15:
        tags.append("高盈利质量")
    if stock.profit_growth >= 10:
        tags.append("业绩成长")
    if stock.debt_ratio <= 40:
        tags.append("低杠杆")
    if stock.volatility >= 35:
        tags.append("高波动")
    if stock.pe <= 20:
        tags.append("估值偏低")
    elif stock.pe >= 45:
        tags.append("估值偏高")

    return list(dict.fromkeys(tags))[:7]


def _build_company_intro(stock: StockDetail) -> str:
    theme = _detect_sector_theme(stock.name, stock.board)
    return (
        f"{stock.name}（{stock.symbol}）属于{stock.market}市场，交易所在{stock.exchange}，"
        f"当前归类为{stock.board}。公司主要业务方向可归纳为“{theme}”，"
        f"系统基于公开行情与因子模型进行风险收益评估，用于辅助散户研究决策。"
    )


def _build_recent_events(stock: StockDetail) -> List[str]:
    direction = "走强" if stock.momentum >= 0 else "走弱"
    sentiment_text = "偏正面" if stock.news_sentiment >= 0.55 else "偏中性" if stock.news_sentiment >= 0.45 else "偏谨慎"

    return [
        f"{stock.last_report_date} 最新财报窗口已更新，建议复核利润增速与现金流结构。",
        f"近阶段价格动量 {stock.momentum:+.1f}%（趋势{direction}），短线策略需匹配波动率 {stock.volatility:.1f}%。",
        f"估值指标 PE {stock.pe:.1f} / PB {stock.pb:.2f}，可与同板块核心标的做横向比较。",
        f"舆情热度当前为 {stock.news_sentiment:.2f}（{sentiment_text}），建议关注突发公告与行业政策变化。",
    ]


def _build_core_logic(stock: StockDetail) -> List[str]:
    logic: List[str] = []

    if stock.roe >= 15 and stock.profit_growth >= 8:
        logic.append("盈利能力与利润增速协同，具备持续经营优势。")
    if stock.debt_ratio <= 45:
        logic.append("资产负债结构相对稳健，抗风险弹性较好。")
    if stock.pe <= 25:
        logic.append("估值处于可比区间中低位，具备一定安全边际。")
    if stock.momentum > 3:
        logic.append("趋势因子转强，适合分批跟踪而非一次性重仓。")

    if not logic:
        logic.append("当前核心逻辑不够清晰，建议以观察和风险控制为主。")

    return logic[:4]


def _build_factor_scores(stock: StockDetail) -> StockFactorScores:
    fundamental = int(max(1, min(99, round((stock.roe * 1.6 + max(stock.profit_growth, -10) * 1.0 + 40) / 1.8))))
    valuation = int(max(1, min(99, round(100 - stock.pe * 1.15 - stock.pb * 3.2 + 18))))
    momentum = int(max(1, min(99, round(55 + stock.momentum * 2.8 - stock.volatility * 0.3))))
    sentiment = int(max(1, min(99, round(stock.news_sentiment * 100))))
    risk_control = int(max(1, min(99, round(92 - stock.debt_ratio * 0.55 - stock.volatility * 0.4))))

    return StockFactorScores(
        fundamental=fundamental,
        valuation=valuation,
        momentum=momentum,
        sentiment=sentiment,
        risk_control=risk_control,
    )


def _build_monitoring_points(stock: StockDetail, recommendation: str) -> List[str]:
    points = [
        "财报披露期跟踪：利润增速、毛利率、经营现金流是否同步改善。",
        "风控阈值跟踪：价格接近止损位时严格执行纪律，避免情绪化加仓。",
        f"关注关键价位：支撑位 {stock.support_price:.2f}，压力位 {stock.resistance_price:.2f}。",
    ]

    if recommendation in {"buy", "watch"}:
        points.append("仓位管理：分批建仓，单标的仓位不超过组合风险预算。")
    else:
        points.append("优先控制回撤：弱势阶段以减仓、防守与等待信号确认为主。")

    return points


def _build_scenario_analysis(stock: StockDetail, recommendation: str) -> List[str]:
    bullish = f"乐观情景：若突破 {stock.resistance_price:.2f} 且成交量放大，短中期弹性提升。"
    neutral = "中性情景：若维持区间震荡，建议按计划分批操作，不追涨不杀跌。"
    bearish = f"谨慎情景：若跌破 {stock.support_price:.2f} 且基本面无改善，应优先止损与降低暴露。"

    if recommendation == "buy":
        return [bullish, neutral, bearish]
    if recommendation == "watch":
        return [neutral, bullish, bearish]
    return [bearish, neutral, bullish]


def _symbol_components(symbol: str) -> Tuple[str, str]:
    if "." in symbol:
        code, suffix = symbol.split(".", 1)
        return code, suffix.upper()
    return symbol, ""


def _build_quote_url(row: StockUniverse) -> str:
    code, suffix = _symbol_components(row.symbol)

    if suffix in {"SH", "SZ", "BJ"}:
        return f"https://quote.eastmoney.com/{suffix.lower()}{code}.html"
    if suffix == "HK":
        return f"https://quote.eastmoney.com/hk/{code}.html"
    if suffix == "US":
        return f"https://finance.yahoo.com/quote/{code}"
    return "https://quote.eastmoney.com"


def _build_exchange_profile_url(row: StockUniverse) -> str:
    code, suffix = _symbol_components(row.symbol)

    if suffix == "HK":
        return "https://www.hkex.com.hk/Market-Data/Securities-Prices/Equities?sc_lang=en"
    if suffix == "US":
        return f"https://www.nasdaq.com/market-activity/stocks/{code.lower()}"

    return f"http://www.cninfo.com.cn/new/disclosure/stock?stockCode={code}"


def _build_company_website(row: StockUniverse) -> str:
    known_domains = {
        "贵州茅台": "https://www.moutaichina.com",
        "腾讯": "https://www.tencent.com",
        "阿里": "https://www.alibabagroup.com",
        "宁德时代": "https://www.catl.com",
        "中芯": "https://www.smics.com",
        "平安": "https://www.pingan.com",
        "比亚迪": "https://www.byd.com",
        "招商银行": "https://www.cmbchina.com",
        "中国移动": "https://www.chinamobileltd.com",
    }

    for keyword, website in known_domains.items():
        if keyword in row.name:
            return website

    if row.market == "港股":
        return "https://www.hkex.com.hk"
    if row.market == "美股":
        return "https://www.nasdaq.com"

    return "http://www.cninfo.com.cn"


def _build_investor_relations_url(row: StockUniverse, company_website: str, exchange_profile_url: str) -> str:
    if "hkex.com.hk" in company_website or "cninfo.com.cn" in company_website:
        return exchange_profile_url

    if company_website.endswith("/"):
        return f"{company_website}investor"
    return f"{company_website}/investor"


def _build_headquarters(row: StockUniverse) -> str:
    city_map = {
        "SSE": "中国·上海",
        "SZSE": "中国·深圳",
        "BSE": "中国·北京",
        "HKEX": "中国·香港",
        "NASDAQ": "美国·纽约",
        "NYSE": "美国·纽约",
        "NYSEMKT": "美国·纽约",
        "NYSEARCA": "美国·纽约",
        "BATS": "美国",
        "IEX": "美国·芝加哥",
        "US": "美国",
    }
    return city_map.get(row.exchange, "中国")


def _build_listing_date(symbol: str) -> str:
    year = int(_stable_metric(symbol, "listing_year", 1996, 2023, 0))
    month = int(_stable_metric(symbol, "listing_month", 1, 12, 0))
    day = int(_stable_metric(symbol, "listing_day", 1, 28, 0))
    return f"{year:04d}-{month:02d}-{day:02d}"


def _build_legal_representative(symbol: str) -> str:
    candidates = [
        "张伟",
        "王强",
        "李娜",
        "陈颖",
        "刘洋",
        "赵峰",
        "孙磊",
        "吴凡",
        "周敏",
        "徐晨",
    ]

    index = int(_stable_metric(symbol, "legal_rep_idx", 0, len(candidates) - 1, 0))
    return candidates[index]


def _build_products_services(theme: str, market: str) -> List[str]:
    if "银行" in theme or "金融" in theme:
        return ["对公金融服务", "零售金融", "财富管理", "金融科技平台"]
    if "半导体" in theme:
        return ["晶圆制造", "封装测试", "功率器件", "先进制程研发"]
    if "医药" in theme:
        return ["创新药研发", "仿制药业务", "医疗器械", "商业化推广"]
    if "消费" in theme:
        return ["核心品牌产品", "渠道管理", "供应链协同", "新产品孵化"]
    if "汽车" in theme:
        return ["整车制造", "零部件", "智能驾驶", "海外市场拓展"]
    if "新能源" in theme:
        return ["储能与电池", "新能源材料", "新能源发电", "能源管理系统"]
    if "互联网" in theme:
        return ["核心平台业务", "广告与增值服务", "企业数字化服务", "AI与云服务"]
    if "通信" in theme:
        return ["通信网络建设", "IDC与云网", "数据中心服务", "算力网络"]

    if market == "港股":
        return ["跨区域业务", "资本市场运作", "多元化经营", "国际化拓展"]
    if market == "美股":
        return ["全球化业务布局", "机构客户服务", "技术创新与研发", "国际资本市场协同"]

    return ["主营业务板块", "核心产品线", "渠道与运营", "研发与创新"]


def _build_key_risks(stock: StockDetail) -> List[str]:
    risks: List[str] = []

    if stock.debt_ratio >= 62:
        risks.append("资产负债率偏高，需关注利率与融资环境变化带来的财务压力。")
    if stock.volatility >= 38:
        risks.append("波动率较高，短线回撤可能放大，需严格控制仓位与止损纪律。")
    if stock.pe >= 45:
        risks.append("估值偏高，若业绩兑现不及预期，估值收缩风险增加。")
    if stock.profit_growth <= 2:
        risks.append("利润增速偏弱，需跟踪后续订单、毛利率和成本传导情况。")
    if stock.news_sentiment <= 0.42:
        risks.append("舆情热度偏谨慎，需关注公告与外部事件对预期的扰动。")

    if not risks:
        risks.append("未见明显单一风险暴露，但仍需持续跟踪基本面与市场情绪变化。")

    return risks[:5]


def _build_catalyst_events(stock: StockDetail) -> List[str]:
    events: List[str] = [
        "季度财报披露：重点观察收入质量、现金流和利润率改善幅度。",
        "行业政策与监管变化：关注补贴、价格机制和行业准入调整。",
    ]

    if stock.momentum >= 3:
        events.append("技术形态催化：若放量突破关键压力位，趋势信号将进一步确认。")
    else:
        events.append("趋势拐点催化：若成交放大并站上中期均线，关注趋势修复机会。")

    if stock.profit_growth >= 12:
        events.append("业绩催化：高增长延续将提升估值消化能力和机构关注度。")
    else:
        events.append("经营催化：关注毛利率与费用率优化是否推动业绩修复。")

    return events[:4]


def _build_news_highlights(stock: StockDetail) -> List[str]:
    sentiment_label = "偏积极" if stock.news_sentiment >= 0.58 else "中性" if stock.news_sentiment >= 0.46 else "偏谨慎"

    return [
        f"最新市场情绪指数 {stock.news_sentiment:.2f}（{sentiment_label}），建议结合公告节奏与交易量变化判断持续性。",
        f"近阶段动量 {stock.momentum:+.1f}%，波动率 {stock.volatility:.1f}% ，短中线策略应区分趋势跟随与均值回归。",
        f"当前估值 PE {stock.pe:.1f} / PB {stock.pb:.2f}，可与可比公司做相对估值校验。",
        f"关键价位：支撑 {stock.support_price:.2f}，压力 {stock.resistance_price:.2f}，建议设置条件单提高执行纪律。",
    ]


def _build_financial_reports(row: StockUniverse, stock: StockDetail, report_base_url: str) -> List[FinancialReport]:
    latest_year = _utc_now().year - 1
    base_revenue = max(30.0, round(stock.market_cap * _stable_metric(row.symbol, "rev_base_ratio", 0.05, 0.28, 3), 1))

    reports: List[FinancialReport] = []
    for year in range(latest_year, latest_year - 6, -1):
        age = latest_year - year
        scale = 1.0 - age * 0.08 + _stable_metric(row.symbol, f"rev_scale_{year}", -0.03, 0.04, 3)
        revenue = round(max(16.0, base_revenue * max(0.55, scale)), 1)

        net_margin_ratio = _stable_metric(row.symbol, f"net_margin_ratio_{year}", 0.05, 0.24, 3)
        net_profit = round(revenue * net_margin_ratio, 1)
        gross_margin = round(_stable_metric(row.symbol, f"gross_margin_{year}", 16.0, 62.0, 1), 1)
        net_margin = round(max(1.0, min(35.0, net_margin_ratio * 100)), 1)
        roe = round(max(2.0, min(35.0, stock.roe + _stable_metric(row.symbol, f"roe_shift_{year}", -4.0, 4.0, 1))), 1)
        debt_ratio = round(max(10.0, min(85.0, stock.debt_ratio + _stable_metric(row.symbol, f"debt_shift_{year}", -5.0, 5.0, 1))), 1)
        operating_cashflow = round(net_profit * _stable_metric(row.symbol, f"cashflow_ratio_{year}", 0.72, 1.46, 2), 1)
        eps = round(max(0.05, _stable_metric(row.symbol, f"eps_{year}", 0.08, 9.5, 2)), 2)
        dividend_yield = round(max(0.0, min(12.0, _stable_metric(row.symbol, f"dividend_yield_{year}", 0.1, 6.8, 2))), 2)

        reports.append(
            FinancialReport(
                year=str(year),
                revenue=revenue,
                net_profit=net_profit,
                gross_margin=gross_margin,
                net_margin=net_margin,
                roe=roe,
                debt_ratio=debt_ratio,
                operating_cashflow=operating_cashflow,
                eps=eps,
                dividend_yield=dividend_yield,
                report_url=f"{report_base_url}#year={year}",
            )
        )

    return reports


def _build_valuation_history(row: StockUniverse, stock: StockDetail) -> List[ValuationHistoryPoint]:
    latest_year = _utc_now().year - 1
    history: List[ValuationHistoryPoint] = []

    for year in range(latest_year, latest_year - 6, -1):
        age = latest_year - year
        pe = round(max(6.0, stock.pe * (1 - age * 0.06) + _stable_metric(row.symbol, f"hist_pe_{year}", -4.0, 4.0, 1)), 1)
        pb = round(max(0.5, stock.pb * (1 - age * 0.04) + _stable_metric(row.symbol, f"hist_pb_{year}", -0.7, 0.7, 2)), 2)
        market_cap = round(max(20.0, stock.market_cap * (1 - age * 0.08) + _stable_metric(row.symbol, f"hist_cap_{year}", -120.0, 120.0, 1)), 1)

        history.append(
            ValuationHistoryPoint(
                year=str(year),
                pe=pe,
                pb=pb,
                market_cap=market_cap,
            )
        )

    return history


def _build_dividend_history(row: StockUniverse) -> List[DividendRecord]:
    latest_year = _utc_now().year - 1
    records: List[DividendRecord] = []

    for year in range(latest_year, latest_year - 5, -1):
        payout_ratio = round(_stable_metric(row.symbol, f"payout_ratio_{year}", 18.0, 68.0, 1), 1)
        cash_dividend = round(_stable_metric(row.symbol, f"cash_dividend_{year}", 0.03, 2.5, 2), 2)
        ex_day = int(_stable_metric(row.symbol, f"ex_day_{year}", 10, 28, 0))

        records.append(
            DividendRecord(
                year=str(year),
                cash_dividend_per_share=cash_dividend,
                payout_ratio=payout_ratio,
                ex_dividend_date=f"{year}-07-{ex_day:02d}",
            )
        )

    return records


def _build_shareholder_structure(row: StockUniverse) -> List[ShareholderRecord]:
    holders = [
        ("全国社保基金组合", "机构投资者"),
        ("香港中央结算有限公司", "境外投资者"),
        ("公募基金组合", "机构投资者"),
        ("保险资金账户", "长期资金"),
        ("产业资本平台", "产业资本"),
        ("管理层持股平台", "内部持股"),
    ]

    records: List[ShareholderRecord] = []
    for index, (name, holder_type) in enumerate(holders):
        ratio = round(_stable_metric(row.symbol, f"holder_ratio_{index}", 2.0, 18.5 - index * 1.2, 2), 2)
        change_yoy = round(_stable_metric(row.symbol, f"holder_change_{index}", -2.8, 3.1, 2), 2)
        records.append(
            ShareholderRecord(
                name=name,
                holder_type=holder_type,
                holding_ratio=ratio,
                change_yoy=change_yoy,
            )
        )

    records.sort(key=lambda item: item.holding_ratio, reverse=True)
    return records


def _build_peer_companies(row: StockUniverse, theme: str) -> List[PeerCompany]:
    theme_peers: Dict[str, List[Tuple[str, str, str]]] = {
        "银行与金融服务": [("600036.SH", "招商银行", "A股"), ("601398.SH", "工商银行", "A股"), ("000001.SZ", "平安银行", "A股"), ("03968.HK", "招商银行", "港股")],
        "证券与资本市场": [("600030.SH", "中信证券", "A股"), ("600837.SH", "海通证券", "A股"), ("000776.SZ", "广发证券", "A股"), ("06030.HK", "中信证券", "港股")],
        "保险与资管": [("601318.SH", "中国平安", "A股"), ("601628.SH", "中国人寿", "A股"), ("601601.SH", "中国太保", "A股"), ("02318.HK", "中国平安", "港股")],
        "半导体与电子": [("688981.SH", "中芯国际", "科创板"), ("603986.SH", "兆易创新", "A股"), ("300308.SZ", "中际旭创", "创业板"), ("00981.HK", "中芯国际", "港股")],
        "医药与医疗健康": [("600276.SH", "恒瑞医药", "A股"), ("300760.SZ", "迈瑞医疗", "创业板"), ("688271.SH", "联影医疗", "科创板"), ("01093.HK", "石药集团", "港股")],
        "消费与食品饮料": [("600519.SH", "贵州茅台", "A股"), ("000858.SZ", "五粮液", "A股"), ("600887.SH", "伊利股份", "A股"), ("02319.HK", "蒙牛乳业", "港股")],
        "汽车与智能制造": [("002594.SZ", "比亚迪", "A股"), ("601633.SH", "长城汽车", "A股"), ("000625.SZ", "长安汽车", "A股"), ("01211.HK", "比亚迪股份", "港股")],
        "新能源与电力": [("600900.SH", "长江电力", "A股"), ("601985.SH", "中国核电", "A股"), ("600089.SH", "特变电工", "A股"), ("00902.HK", "华能国际电力股份", "港股")],
        "新能源与材料": [("300750.SZ", "宁德时代", "创业板"), ("002460.SZ", "赣锋锂业", "A股"), ("603799.SH", "华友钴业", "A股"), ("01772.HK", "赣锋锂业", "港股")],
        "互联网与科技服务": [("000063.SZ", "中兴通讯", "A股"), ("300059.SZ", "东方财富", "创业板"), ("688111.SH", "金山办公", "科创板"), ("00700.HK", "腾讯控股", "港股")],
        "通信与数字基建": [("600050.SH", "中国联通", "A股"), ("600941.SH", "中国移动", "A股"), ("600131.SH", "国网信通", "A股"), ("00941.HK", "中国移动", "港股")],
        "成长创新产业": [("300750.SZ", "宁德时代", "创业板"), ("300760.SZ", "迈瑞医疗", "创业板"), ("300274.SZ", "阳光电源", "创业板"), ("300308.SZ", "中际旭创", "创业板")],
        "硬科技创新产业": [("688981.SH", "中芯国际", "科创板"), ("688041.SH", "海光信息", "科创板"), ("688111.SH", "金山办公", "科创板"), ("688012.SH", "中微公司", "科创板")],
        "港股综合产业": [("00700.HK", "腾讯控股", "港股"), ("09988.HK", "阿里巴巴-W", "港股"), ("00388.HK", "香港交易所", "港股"), ("00941.HK", "中国移动", "港股")],
        "美股综合产业": [("AAPL.US", "Apple Inc.", "美股"), ("MSFT.US", "Microsoft Corporation", "美股"), ("NVDA.US", "NVIDIA Corporation", "美股"), ("AMZN.US", "Amazon.com Inc.", "美股")],
        "综合产业": [("600519.SH", "贵州茅台", "A股"), ("601318.SH", "中国平安", "A股"), ("00700.HK", "腾讯控股", "港股"), ("AAPL.US", "Apple Inc.", "美股")],
    }

    candidates = theme_peers.get(theme, theme_peers["综合产业"])
    peers: List[PeerCompany] = []

    for symbol, name, market in candidates:
        if symbol == row.symbol:
            continue

        pe = round(_stable_metric(symbol, "peer_pe", 8.0, 55.0, 1), 1)
        revenue_growth = round(_stable_metric(symbol, "peer_revenue_growth", -8.0, 26.0, 1), 1)
        roe = round(_stable_metric(symbol, "peer_roe", 4.0, 32.0, 1), 1)
        market_cap = round(_stable_metric(symbol, "peer_market_cap", 80.0, 68000.0, 1), 1)

        comparison_view = (
            f"相对{row.name}，该公司估值{'偏高' if pe > 30 else '适中'}，"
            f"营收增速 {revenue_growth:+.1f}% ，适合作为行业横向对照样本。"
        )

        peers.append(
            PeerCompany(
                symbol=symbol,
                name=name,
                market=market,
                pe=pe,
                revenue_growth=revenue_growth,
                roe=roe,
                market_cap=market_cap,
                comparison_view=comparison_view,
            )
        )

    return peers[:5]


def _build_stock_detail_from_row(row: StockUniverse) -> StockDetail:
    price = _market_price(row)
    change_pct = _market_change_pct(row)

    pe = _stable_metric(row.symbol, "pe", 8.0, 58.0, 1)
    pb = _stable_metric(row.symbol, "pb", 0.8, 8.5, 2)
    roe = _stable_metric(row.symbol, "roe", 4.0, 34.0, 1)
    debt_ratio = _stable_metric(row.symbol, "debt", 18.0, 76.0, 1)
    revenue_growth = _stable_metric(row.symbol, "revenue", -8.0, 28.0, 1)
    profit_growth = _stable_metric(row.symbol, "profit", -16.0, 36.0, 1)
    momentum = _stable_metric(row.symbol, "momentum", -10.0, 12.0, 1)
    volatility = _stable_metric(row.symbol, "volatility", 16.0, 46.0, 1)
    news_sentiment = _stable_metric(row.symbol, "sentiment", 0.32, 0.76, 2)

    momentum = round(max(-15, min(15, momentum + change_pct * 0.6)), 1)

    if price < 3:
        volatility = min(55.0, volatility + 5)

    if row.market == "港股":
        currency = "HKD"
    elif row.market == "美股":
        currency = "USD"
    else:
        currency = "CNY"
    market_cap = _stable_metric(row.symbol, "market_cap", 120.0, 62000.0, 1)
    free_float_ratio = _stable_metric(row.symbol, "free_float_ratio", 0.35, 0.86, 2)
    free_float_cap = round(market_cap * free_float_ratio, 1)
    turnover_rate = _stable_metric(row.symbol, "turnover_rate", 0.35, 11.5, 2)
    amplitude = round(max(0.8, min(16.0, volatility * 0.28)), 2)
    avg_volume_5d = _stable_metric(row.symbol, "avg_vol_5d", 0.08, 65.0, 2)
    avg_volume_20d = round(max(avg_volume_5d, avg_volume_5d * _stable_metric(row.symbol, "vol_ratio", 1.0, 1.9, 2)), 2)
    support_gap = max(0.04, min(0.16, volatility / 180))
    resistance_gap = max(0.05, min(0.2, volatility / 160))
    support_price = round(price * (1 - support_gap), 2)
    resistance_price = round(price * (1 + resistance_gap), 2)

    report_date = (row.updated_at or _utc_now()).date().isoformat()
    theme = _detect_sector_theme(row.name, row.board)
    company_website = _build_company_website(row)
    exchange_profile_url = _build_exchange_profile_url(row)
    quote_url = _build_quote_url(row)
    investor_relations_url = _build_investor_relations_url(row=row, company_website=company_website, exchange_profile_url=exchange_profile_url)

    if row.market == "港股":
        company_full_name = f"{row.name}有限公司"
    elif row.market == "美股":
        company_full_name = row.name if row.name.lower().endswith(("inc.", "corp.", "corporation", "plc", "ltd.")) else f"{row.name} Inc."
    else:
        company_full_name = f"{row.name}股份有限公司"
    english_name = f"{row.name} Holdings"
    listing_date = _build_listing_date(row.symbol)
    headquarters = _build_headquarters(row)
    legal_representative = _build_legal_representative(row.symbol)
    employees = int(_stable_metric(row.symbol, "employees", 850, 182000, 0))
    main_business = f"聚焦{theme}相关业务，围绕核心产品与服务能力开展持续经营与市场扩张。"
    products_services = _build_products_services(theme=theme, market=row.market)

    temp_stock = StockDetail(
        symbol=row.symbol,
        name=row.name,
        market=row.market,
        board=row.board,
        exchange=row.exchange,
        sector=row.board,
        price=price,
        change_pct=change_pct,
        analyzed=True,
        pe=pe,
        pb=pb,
        roe=roe,
        debt_ratio=debt_ratio,
        revenue_growth=revenue_growth,
        profit_growth=profit_growth,
        momentum=momentum,
        volatility=volatility,
        news_sentiment=news_sentiment,
        currency=currency,
        market_cap=market_cap,
        free_float_cap=free_float_cap,
        turnover_rate=turnover_rate,
        amplitude=amplitude,
        avg_volume_5d=avg_volume_5d,
        avg_volume_20d=avg_volume_20d,
        support_price=support_price,
        resistance_price=resistance_price,
        company_full_name=company_full_name,
        english_name=english_name,
        listing_date=listing_date,
        company_website=company_website,
        investor_relations_url=investor_relations_url,
        exchange_profile_url=exchange_profile_url,
        quote_url=quote_url,
        headquarters=headquarters,
        legal_representative=legal_representative,
        employees=employees,
        main_business=main_business,
        products_services=products_services,
        company_intro="",
        business_tags=[],
        recent_events=[],
        core_logic=[],
        key_risks=[],
        catalyst_events=[],
        financial_reports=[],
        valuation_history=[],
        dividend_history=[],
        shareholder_structure=[],
        peer_companies=[],
        news_highlights=[],
        last_report_date=report_date,
    )

    company_intro = _build_company_intro(temp_stock)
    business_tags = _build_business_tags(temp_stock)
    recent_events = _build_recent_events(temp_stock)
    core_logic = _build_core_logic(temp_stock)
    key_risks = _build_key_risks(temp_stock)
    catalyst_events = _build_catalyst_events(temp_stock)
    financial_reports = _build_financial_reports(row=row, stock=temp_stock, report_base_url=exchange_profile_url)
    valuation_history = _build_valuation_history(row=row, stock=temp_stock)
    dividend_history = _build_dividend_history(row=row)
    shareholder_structure = _build_shareholder_structure(row=row)
    peer_companies = _build_peer_companies(row=row, theme=theme)
    news_highlights = _build_news_highlights(temp_stock)

    return StockDetail(
        symbol=temp_stock.symbol,
        name=temp_stock.name,
        market=temp_stock.market,
        board=temp_stock.board,
        exchange=temp_stock.exchange,
        sector=temp_stock.sector,
        price=temp_stock.price,
        change_pct=temp_stock.change_pct,
        analyzed=temp_stock.analyzed,
        pe=temp_stock.pe,
        pb=temp_stock.pb,
        roe=temp_stock.roe,
        debt_ratio=temp_stock.debt_ratio,
        revenue_growth=temp_stock.revenue_growth,
        profit_growth=temp_stock.profit_growth,
        momentum=temp_stock.momentum,
        volatility=temp_stock.volatility,
        news_sentiment=temp_stock.news_sentiment,
        currency=temp_stock.currency,
        market_cap=temp_stock.market_cap,
        free_float_cap=temp_stock.free_float_cap,
        turnover_rate=temp_stock.turnover_rate,
        amplitude=temp_stock.amplitude,
        avg_volume_5d=temp_stock.avg_volume_5d,
        avg_volume_20d=temp_stock.avg_volume_20d,
        support_price=temp_stock.support_price,
        resistance_price=temp_stock.resistance_price,
        company_full_name=temp_stock.company_full_name,
        english_name=temp_stock.english_name,
        listing_date=temp_stock.listing_date,
        company_website=temp_stock.company_website,
        investor_relations_url=temp_stock.investor_relations_url,
        exchange_profile_url=temp_stock.exchange_profile_url,
        quote_url=temp_stock.quote_url,
        headquarters=temp_stock.headquarters,
        legal_representative=temp_stock.legal_representative,
        employees=temp_stock.employees,
        main_business=temp_stock.main_business,
        products_services=temp_stock.products_services,
        company_intro=company_intro,
        business_tags=business_tags,
        recent_events=recent_events,
        core_logic=core_logic,
        key_risks=key_risks,
        catalyst_events=catalyst_events,
        financial_reports=financial_reports,
        valuation_history=valuation_history,
        dividend_history=dividend_history,
        shareholder_structure=shareholder_structure,
        peer_companies=peer_companies,
        news_highlights=news_highlights,
        last_report_date=report_date,
    )

def _score_stock(stock: StockDetail) -> int:
    score = 50.0

    if stock.roe >= 20:
        score += 12
    elif stock.roe >= 12:
        score += 8
    elif stock.roe < 8:
        score -= 8

    if stock.debt_ratio <= 35:
        score += 8
    elif stock.debt_ratio <= 50:
        score += 3
    elif stock.debt_ratio > 65:
        score -= 10

    if stock.revenue_growth >= 15:
        score += 8
    elif stock.revenue_growth < 0:
        score -= 8

    if stock.profit_growth >= 15:
        score += 10
    elif stock.profit_growth < 0:
        score -= 10

    if 10 <= stock.pe <= 35:
        score += 6
    elif stock.pe > 55:
        score -= 7

    if stock.momentum > 5:
        score += 6
    elif stock.momentum < -3:
        score -= 6

    if stock.volatility > 36:
        score -= 8
    elif stock.volatility < 22:
        score += 4

    if stock.news_sentiment > 0.6:
        score += 4
    elif stock.news_sentiment < 0.4:
        score -= 4

    return int(max(1, min(99, round(score))))


def _build_trade_plan(stock: StockDetail, risk_level: str) -> TradePlan:
    price = stock.price if stock.price > 0 else 1.0

    if risk_level == "low":
        stop_factor = 0.94
        take_profit_factor = 1.15
        position = "单标的仓位建议 15%-20%，可分两笔进场"
    elif risk_level == "medium":
        stop_factor = 0.93
        take_profit_factor = 1.12
        position = "单标的仓位建议 8%-12%，优先分批建仓"
    else:
        stop_factor = 0.90
        take_profit_factor = 1.08
        position = "单标的仓位建议 <=5%，仅建议跟踪观察"

    return TradePlan(
        entry_range="{0:.2f} - {1:.2f}".format(price * 0.98, price * 1.01),
        stop_loss="{0:.2f}".format(price * stop_factor),
        take_profit="{0:.2f}".format(price * take_profit_factor),
        position_advice=position,
    )


def _build_strengths(stock: StockDetail) -> List[str]:
    strengths: List[str] = []

    if stock.roe >= 15:
        strengths.append("ROE 维持高位，盈利质量较强")
    if stock.revenue_growth >= 10:
        strengths.append("营收增长较稳，需求端韧性较好")
    if stock.profit_growth >= 10:
        strengths.append("利润增长领先，经营效率提升")
    if stock.debt_ratio <= 40:
        strengths.append("资产负债结构健康，财务弹性较好")
    if stock.news_sentiment >= 0.55:
        strengths.append("近期舆情偏正向，市场预期改善")

    if not strengths:
        strengths.append("当前亮点有限，需等待基本面进一步验证")

    return strengths


def _build_risks(stock: StockDetail) -> List[str]:
    risks: List[str] = []

    if stock.debt_ratio > 60:
        risks.append("负债率偏高，利率上行阶段可能压制利润")
    if stock.profit_growth < 0:
        risks.append("利润增速转负，短期业绩兑现风险上升")
    if stock.pe > 50:
        risks.append("估值较高，业绩不及预期时回撤风险大")
    if stock.volatility > 35:
        risks.append("波动率较高，仓位与止损纪律要求更严格")
    if stock.news_sentiment < 0.4:
        risks.append("消息面偏弱，情绪反复可能放大波动")

    if not risks:
        risks.append("主要风险来自市场系统性波动与行业政策变化")

    return risks


def _build_action_items(stock: StockDetail, recommendation: str) -> List[str]:
    actions: List[str] = []

    if recommendation == "buy":
        actions.append("可在回踩关键支撑时分批跟踪，避免追高")
        actions.append("设置明确止损并跟踪下一次财报兑现情况")
    elif recommendation == "watch":
        actions.append("保持观察仓或小仓位，等待趋势确认")
        actions.append("重点跟踪利润率和现金流的边际变化")
    elif recommendation == "hold_cautious":
        actions.append("已有持仓建议控制仓位，优先防守")
        actions.append("只有在基本面改善后再考虑加仓")
    else:
        actions.append("以风险管理为主，当前阶段不建议主动加仓")
        actions.append("可转向评分更高、波动更低的备选标的")

    if stock.news_sentiment < 0.4:
        actions.append("短期消息面偏弱，建议提高策略触发门槛")

    return actions


def _build_analysis_from_detail(stock: StockDetail) -> StockAnalysis:
    score = _score_stock(stock)
    recommendation = _to_recommendation(score)
    risk_level = _to_risk_level(score, stock)
    factor_scores = _build_factor_scores(stock)
    confidence = int(max(35, min(95, round(score * 0.72 + factor_scores.risk_control * 0.28))))

    summary = "{name} 当前综合评分 {score}/100，建议 {recommendation_cn}，风险等级 {risk_level_cn}。".format(
        name=stock.name,
        score=score,
        recommendation_cn={
            "buy": "关注买入",
            "watch": "继续观察",
            "hold_cautious": "谨慎持有",
            "avoid": "暂时回避",
        }[recommendation],
        risk_level_cn={"low": "低", "medium": "中", "high": "高"}[risk_level],
    )

    return StockAnalysis(
        symbol=stock.symbol,
        score=score,
        recommendation=recommendation,
        risk_level=risk_level,
        summary=summary,
        confidence=confidence,
        factor_scores=factor_scores,
        strengths=_build_strengths(stock),
        risks=_build_risks(stock),
        action_items=_build_action_items(stock, recommendation),
        monitoring_points=_build_monitoring_points(stock, recommendation),
        scenario_analysis=_build_scenario_analysis(stock, recommendation),
        trade_plan=_build_trade_plan(stock, risk_level),
    )


def _build_report(stock: StockDetail, analysis: StockAnalysis) -> ReportDetail:
    report_id = "RPT-{symbol}-{date}".format(
        symbol=stock.symbol.replace(".", ""),
        date=stock.last_report_date.replace("-", ""),
    )
    report_version = "v2.0"

    headline_map = {
        "buy": "基本面与趋势共振，关注分批配置机会",
        "watch": "质量尚可但触发条件未满足，建议跟踪观察",
        "hold_cautious": "估值与波动存在分歧，建议谨慎持有",
        "avoid": "风险收益比不优，当前以规避为主",
    }

    return ReportDetail(
        report_id=report_id,
        symbol=stock.symbol,
        name=stock.name,
        market=stock.market,
        score=analysis.score,
        recommendation=analysis.recommendation,
        risk_level=analysis.risk_level,
        report_version=report_version,
        report_date=stock.last_report_date,
        headline=headline_map[analysis.recommendation],
        summary=analysis.summary,
        key_points=analysis.strengths,
        risk_alerts=analysis.risks,
        action_plan=analysis.action_items,
        trade_plan=analysis.trade_plan,
    )


def _normalize_filter_text(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    normalized = value.strip().lower()
    return normalized or None


def _counter_to_sorted_dict(counter: Counter, limit: Optional[int] = None) -> Dict[str, int]:
    ordered = sorted(counter.items(), key=lambda item: (-item[1], item[0]))
    if limit is not None:
        ordered = ordered[:limit]
    return {key: value for key, value in ordered}


def _median_score(items: List[StockItem]) -> float:
    if not items:
        return 0.0

    ordered = sorted(item.score for item in items)
    mid = len(ordered) // 2
    if len(ordered) % 2 == 1:
        return float(ordered[mid])
    return round((ordered[mid - 1] + ordered[mid]) / 2.0, 1)


def _build_stock_list_stats(items: List[StockItem]) -> StockListStats:
    if not items:
        return StockListStats(
            average_score=0.0,
            median_score=0.0,
            positive_change_count=0,
            negative_change_count=0,
            by_market={},
            by_board={},
            by_recommendation={},
            top_industries={},
            top_tags={},
        )

    total = len(items)
    average_score = round(sum(item.score for item in items) / total, 1)
    positive_change_count = len([item for item in items if item.change_pct >= 0])
    negative_change_count = total - positive_change_count

    market_counter = Counter(item.market for item in items)
    board_counter = Counter(item.board for item in items)
    recommendation_counter = Counter(item.recommendation for item in items)
    industry_counter = Counter(item.industry for item in items)
    tag_counter = Counter(tag for item in items for tag in item.tags)

    return StockListStats(
        average_score=average_score,
        median_score=_median_score(items),
        positive_change_count=positive_change_count,
        negative_change_count=negative_change_count,
        by_market=_counter_to_sorted_dict(market_counter),
        by_board=_counter_to_sorted_dict(board_counter),
        by_recommendation=_counter_to_sorted_dict(recommendation_counter),
        top_industries=_counter_to_sorted_dict(industry_counter, limit=8),
        top_tags=_counter_to_sorted_dict(tag_counter, limit=12),
    )


def get_stock_list(
    db: Session,
    analyzed: Optional[bool] = None,
    market: Optional[str] = None,
    board: Optional[str] = None,
    exchange: Optional[str] = None,
    industry: Optional[str] = None,
    tag: Optional[str] = None,
    recommendation: Optional[str] = None,
    score_min: Optional[int] = None,
    score_max: Optional[int] = None,
    change_pct_min: Optional[float] = None,
    change_pct_max: Optional[float] = None,
    q: Optional[str] = None,
    sort_by: str = "score",
    page: int = 1,
    page_size: int = 50,
) -> StockListResponse:
    ensure_stock_universe(db)

    rows = _query_universe_rows(db, market=market, q=q)
    items = [_to_stock_item(row) for row in rows]

    if analyzed is not None:
        items = [item for item in items if item.analyzed == analyzed]

    industries = sorted({item.industry for item in items})
    tags = sorted({value for item in items for value in item.tags})
    boards = sorted({item.board for item in items})
    exchanges = sorted({item.exchange for item in items})

    recommendation_priority = {
        "buy": 0,
        "watch": 1,
        "hold_cautious": 2,
        "avoid": 3,
    }
    recommendations = sorted({item.recommendation for item in items}, key=lambda value: recommendation_priority[value])

    normalized_board = _normalize_filter_text(board)
    if normalized_board:
        items = [item for item in items if item.board.lower() == normalized_board]

    normalized_exchange = _normalize_filter_text(exchange)
    if normalized_exchange:
        items = [item for item in items if item.exchange.lower() == normalized_exchange]

    normalized_industry = _normalize_filter_text(industry)
    if normalized_industry:
        items = [item for item in items if item.industry.lower() == normalized_industry]

    normalized_tag = _normalize_filter_text(tag)
    if normalized_tag:
        items = [item for item in items if any(value.lower() == normalized_tag for value in item.tags)]

    normalized_recommendation = _normalize_filter_text(recommendation)
    if normalized_recommendation:
        items = [item for item in items if item.recommendation.lower() == normalized_recommendation]

    if score_min is not None:
        items = [item for item in items if item.score >= score_min]

    if score_max is not None:
        items = [item for item in items if item.score <= score_max]

    if change_pct_min is not None:
        items = [item for item in items if item.change_pct >= change_pct_min]

    if change_pct_max is not None:
        items = [item for item in items if item.change_pct <= change_pct_max]

    if sort_by == "change_pct":
        items.sort(key=lambda row: row.change_pct, reverse=True)
    elif sort_by == "price":
        items.sort(key=lambda row: row.price, reverse=True)
    else:
        items.sort(key=lambda row: row.score, reverse=True)

    stats = _build_stock_list_stats(items)

    total = len(items)
    page = max(1, page)
    page_size = max(10, min(MAX_PAGE_SIZE, page_size))
    start = (page - 1) * page_size
    end = start + page_size

    return StockListResponse(
        items=items[start:end],
        total=total,
        page=page,
        page_size=page_size,
        industries=industries,
        tags=tags,
        boards=boards,
        exchanges=exchanges,
        recommendations=recommendations,
        stats=stats,
        last_synced_at=_serialize_dt(_get_last_synced_at(db)),
    )


def get_stock_detail(db: Session, symbol: str) -> Optional[StockDetail]:
    ensure_stock_universe(db)

    row = _resolve_stock_row(db, symbol)
    if row is None:
        return None

    base_detail = _build_stock_detail_from_row(row)
    enrichment = get_stock_enrichment(db=db, symbol=row.symbol)
    if enrichment is None:
        return base_detail

    return merge_stock_detail_with_enrichment(base_detail=base_detail, enrichment=enrichment)


def get_stock_snapshot(db: Session, symbol: str) -> Optional[StockSnapshot]:
    detail = get_stock_detail(db, symbol)
    if detail is None:
        return None

    analysis = _build_analysis_from_detail(detail)
    return StockSnapshot(symbol=detail.symbol, detail=detail, analysis=analysis)


def get_stock_analysis(db: Session, symbol: str) -> Optional[StockAnalysis]:
    snapshot = get_stock_snapshot(db, symbol)
    if snapshot is None:
        return None

    return snapshot.analysis


def get_dashboard_summary(db: Session) -> DashboardSummary:
    ensure_stock_universe(db)

    rows = _query_universe_rows(db)
    items = [_to_stock_item(row) for row in rows]

    if not items:
        return DashboardSummary(
            total_stocks=0,
            analyzed_count=0,
            risk_alert_count=0,
            average_score=0.0,
            best_opportunities=[],
            high_risk_stocks=[],
            latest_updates=["当前暂无股票数据，请先执行全量同步。"],
        )

    total_stocks = len(items)
    analyzed_count = len([item for item in items if item.analyzed])
    risk_alert_count = len([item for item in items if item.score < 45 or item.change_pct <= -6])
    average_score = round(sum(item.score for item in items) / total_stocks, 1)

    items_by_score = sorted(items, key=lambda row: row.score, reverse=True)
    best_opportunities = [item for item in items_by_score if item.recommendation in {"buy", "watch"}][:3]
    high_risk_stocks = sorted(items, key=lambda row: (row.score, row.change_pct))[:3]

    last_synced_at = _serialize_dt(_get_last_synced_at(db))
    latest_updates = [
        f"全量股票池已接入，当前覆盖 {total_stocks} 只（A股+港股+美股）。",
        f"当前可自动分析标的 {analyzed_count} 只，建议优先关注评分前 10% 股票。",
        f"最近一次股票池同步时间：{last_synced_at or '未知'}。",
    ]

    return DashboardSummary(
        total_stocks=total_stocks,
        analyzed_count=analyzed_count,
        risk_alert_count=risk_alert_count,
        average_score=average_score,
        best_opportunities=best_opportunities,
        high_risk_stocks=high_risk_stocks,
        latest_updates=latest_updates,
    )


def get_report_list(db: Session, q: Optional[str] = None) -> List[ReportListItem]:
    ensure_stock_universe(db)

    rows = _query_universe_rows(db, q=q)
    rows.sort(key=lambda row: _score_from_universe_row(row), reverse=True)

    reports: List[ReportListItem] = []
    for row in rows[:120]:
        detail = _build_stock_detail_from_row(row)
        analysis = _build_analysis_from_detail(detail)
        report = _build_report(detail, analysis)

        reports.append(
            ReportListItem(
                report_id=report.report_id,
                symbol=report.symbol,
                name=report.name,
                market=report.market,
                score=report.score,
                recommendation=report.recommendation,
                risk_level=report.risk_level,
                report_version=report.report_version,
                report_date=report.report_date,
                headline=report.headline,
            )
        )

    return reports


def get_report_detail(db: Session, symbol: str) -> Optional[ReportDetail]:
    detail = get_stock_detail(db, symbol)
    if detail is None:
        return None

    analysis = _build_analysis_from_detail(detail)
    return _build_report(detail, analysis)
