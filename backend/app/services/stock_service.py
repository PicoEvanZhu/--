import hashlib
import json
import logging
import os
import re
import subprocess
import tempfile
import time
from csv import DictReader
from collections import Counter, OrderedDict
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from io import StringIO
from urllib.parse import urlparse
from threading import Lock, Thread
from typing import Any, Dict, List, Optional, Tuple

import requests
from sqlalchemy import func
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.stock_enrichment import StockEnrichment
from app.models.stock_universe import StockUniverse
from app.services.enrichment_service import _to_yfinance_ticker_candidates, build_transient_enrichment_from_row, get_stock_enrichment, is_placeholder_company_website, merge_stock_detail_with_enrichment
from app.services.web_search_service import WebSearchResult, search_web
from app.schemas.stock import (
    DashboardSummary,
    DividendRecord,
    KLinePoint,
    FinancialReport,
    PeerCompany,
    ReportDetail,
    ReportListItem,
    SectorConceptItem,
    SectorRotationResponse,
    ShareholderRecord,
    StockAnalysis,
    StockKLineResponse,
    StockDataQuality,
    StockDetail,
    StockFactorScores,
    StockItem,
    StockListResponse,
    StockListStats,
    StockDividendSummary,
    StockQAResponse,
    StockSnapshot,
    StockSyncResponse,
    TradePlan,
    ValuationHistoryPoint,
)

os.environ.setdefault("TQDM_DISABLE", "1")


@dataclass(frozen=True)
class UniverseRowView:
    symbol: str
    code: str
    name: str
    market: str
    board: str
    exchange: str
    source: str
    listed: bool
    price: Optional[float]
    change_pct: Optional[float]
    volume: Optional[float]
    turnover: Optional[float]
    updated_at: datetime


logger = logging.getLogger("stock_assistant.stock_service")

SYNC_COOLDOWN_SECONDS = 4 * 60 * 60
MIN_UNIVERSE_READY_COUNT = 1200
MAX_PAGE_SIZE = 200

_CONCEPT_RULES: List[Tuple[str, str]] = [
    ("算力", "AI算力"),
    ("人工智能", "AI应用"),
    ("智能", "AI应用"),
    ("芯", "半导体"),
    ("半导体", "半导体"),
    ("存储", "半导体"),
    ("光伏", "光伏"),
    ("风电", "风电"),
    ("锂", "锂电池"),
    ("电池", "锂电池"),
    ("新能源", "新能源车"),
    ("汽车", "新能源车"),
    ("机器人", "机器人"),
    ("自动化", "机器人"),
    ("军工", "军工"),
    ("航空", "军工"),
    ("医药", "创新药"),
    ("生物", "创新药"),
    ("医疗", "医疗器械"),
    ("银行", "银行"),
    ("证券", "券商"),
    ("保险", "保险"),
    ("地产", "地产"),
    ("有色", "有色金属"),
    ("铜", "有色金属"),
    ("黄金", "贵金属"),
    ("煤", "煤炭"),
    ("油", "石油石化"),
    ("天然气", "石油石化"),
    ("通信", "通信设备"),
    ("运营商", "通信设备"),
    ("云", "云计算"),
    ("软件", "云计算"),
    ("消费", "消费"),
    ("食品", "消费"),
    ("酒", "消费"),
]

_ROTATION_STAGES = ["修复", "启动", "加速", "分歧", "降温"]
_BROAD_CONCEPTS = {"美股科技", "顺周期", "港股龙头", "成长股", "硬科技"}
_ROTATION_MIN_SAMPLE_SIZE = 5
_ROTATION_STRONG_SAMPLE_SIZE = 18
_KLINE_LIMIT_BY_PERIOD = {"1mo": 25, "3mo": 70, "6mo": 140, "1y": 260, "5y": 1250}
_KLINE_LIMIT_BY_PERIOD_HOURLY = {"1mo": 160, "3mo": 360, "6mo": 720, "1y": 1200, "5y": 6000}
_DIVIDEND_CACHE_TTL_SECONDS = 12 * 60 * 60
_DIVIDEND_HIGH_YIELD_THRESHOLD = 3.0
_DIVIDEND_SOON_WINDOW_DAYS = 45
_TENCENT_QUOTE_BATCH_SIZE = 60
_DIVIDEND_SUMMARY_QUERY_BATCH_SIZE = 500
_dividend_marker_cache: Dict[str, Any] = {"expires_at": 0.0, "symbols": {}, "report_date": None}
_dividend_marker_lock = Lock()
_dividend_marker_refreshing = False
_stock_item_cache_lock = Lock()
_stock_item_cache_version: Optional[str] = None
_stock_item_cache: Dict[str, StockItem] = {}
_universe_rows_cache_lock = Lock()
_universe_rows_cache_version: Optional[str] = None
_universe_rows_cache_all: List[UniverseRowView] = []
_universe_rows_cache_by_query: Dict[str, List[UniverseRowView]] = {}
_dividend_summary_cache_lock = Lock()
_dividend_summary_cache_version: Optional[str] = None
_dividend_summary_cache_all: Dict[str, Dict[str, Any]] = {}
_stock_list_source_cache_lock = Lock()
_stock_list_source_cache_version: Optional[str] = None
_stock_list_source_cache: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()
_STOCK_LIST_SOURCE_CACHE_MAX = 8
_sector_rotation_cache_lock = Lock()
_sector_rotation_cache_version: Optional[str] = None
_sector_rotation_cache: "OrderedDict[str, SectorRotationResponse]" = OrderedDict()
_SECTOR_ROTATION_CACHE_MAX = 12


def _kline_limit(period: str, interval: str) -> int:
    if interval == "1h":
        return _KLINE_LIMIT_BY_PERIOD_HOURLY.get(period, 360)
    return _KLINE_LIMIT_BY_PERIOD.get(period, 140)


def _build_intraday_timestamps(count: int) -> List[datetime]:
    timestamps: List[datetime] = []
    cursor = _utc_now().replace(minute=0, second=0, microsecond=0)
    while len(timestamps) < count:
        if cursor.weekday() < 5:
            timestamps.append(cursor)
        cursor -= timedelta(hours=1)
    timestamps.reverse()
    return timestamps


def _build_synthetic_kline_points(row: StockUniverse, period: str, interval: str = "1d") -> List[KLinePoint]:
    count = _kline_limit(period=period, interval=interval)
    latest_close = _market_price(row)
    base_vol = float(row.turnover or _stable_metric(row.symbol, "kline_turnover", 50_000_000, 8_000_000_000, 0))
    points: List[KLinePoint] = []
    if interval == "1h":
        trading_days = _build_intraday_timestamps(count)
    else:
        trading_days = []
        cursor = _utc_now()
        while len(trading_days) < count:
            if cursor.weekday() < 5:
                trading_days.append(cursor)
            cursor -= timedelta(days=1)
        trading_days.reverse()

    previous_close = latest_close * max(0.35, 1 - _stable_metric(row.symbol, f"{period}_drift", 0.02, 0.18, 3))
    for index, day in enumerate(trading_days):
        drift = _stable_metric(row.symbol, f"kline_drift_{period}_{index}", -0.028, 0.028, 4)
        spread = _stable_metric(row.symbol, f"kline_spread_{period}_{index}", 0.008, 0.038, 4)
        open_price = max(0.1, previous_close * (1 + drift * 0.35))
        close_price = max(0.1, previous_close * (1 + drift))
        high_price = max(open_price, close_price) * (1 + spread * 0.55)
        low_price = min(open_price, close_price) * max(0.75, 1 - spread * 0.55)
        volume = max(1.0, base_vol * _stable_metric(row.symbol, f"kline_vol_{period}_{index}", 0.42, 1.65, 3))
        points.append(
            KLinePoint(
                date=day.strftime("%Y-%m-%d %H:%M") if interval == "1h" else day.strftime("%Y-%m-%d"),
                open=round(open_price, 2),
                high=round(high_price, 2),
                low=round(low_price, 2),
                close=round(close_price, 2),
                volume=round(volume, 0),
            )
        )
        previous_close = close_price

    if points:
        points[-1] = KLinePoint(
            date=points[-1].date,
            open=points[-1].open,
            high=max(points[-1].high, latest_close),
            low=min(points[-1].low, latest_close),
            close=round(latest_close, 2),
            volume=points[-1].volume,
        )
    return points

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


def _symbol_to_tencent_quote_code(symbol: str) -> Optional[str]:
    normalized = str(symbol or "").strip().upper()
    if not normalized:
        return None

    if "." in normalized:
        code, suffix = normalized.rsplit(".", 1)
        code = code.strip().upper()
        suffix = suffix.strip().upper()
    else:
        code, suffix = normalized, ""

    if suffix == "SH":
        return f"sh{code}"
    if suffix == "SZ":
        return f"sz{code}"
    if suffix == "BJ":
        return f"bj{code}"
    if suffix == "HK":
        digits = re.sub(r"\D", "", code)
        if not digits:
            return None
        return f"hk{digits.zfill(5)}"
    if suffix == "US":
        if not code:
            return None
        return f"us{code}"

    return None


def _fetch_tencent_quote_map(quote_codes: List[str]) -> Dict[str, Dict[str, Optional[float]]]:
    result: Dict[str, Dict[str, Optional[float]]] = {}
    if not quote_codes:
        return result

    deduped_codes = list(dict.fromkeys([code for code in quote_codes if code]))
    for index in range(0, len(deduped_codes), _TENCENT_QUOTE_BATCH_SIZE):
        batch = deduped_codes[index : index + _TENCENT_QUOTE_BATCH_SIZE]
        url = "https://qt.gtimg.cn/q=" + ",".join(batch)
        try:
            response = requests.get(url, timeout=12)
            response.raise_for_status()
            payload = response.content.decode("gbk", errors="ignore")
        except Exception:
            continue

        for segment in payload.split(";"):
            line = segment.strip()
            if not line or '="' not in line or not line.startswith("v_"):
                continue

            key_part, raw_value = line.split('="', 1)
            quote_code = key_part[2:].strip()
            fields = raw_value.rstrip('"').split("~")
            if len(fields) < 5:
                continue

            def _field_float(index_value: int) -> Optional[float]:
                if index_value < 0 or index_value >= len(fields):
                    return None
                return _safe_float(fields[index_value])

            price = _field_float(3)
            previous_close = _field_float(4)
            open_price = _field_float(5)
            volume = _field_float(36) or _field_float(6)
            change_pct: Optional[float] = None
            raw_change_pct = _field_float(32)
            if raw_change_pct is not None:
                change_pct = round(raw_change_pct, 2)
            elif price is not None and previous_close not in {None, 0}:
                change_pct = round((price - previous_close) / previous_close * 100, 2)

            if price is None and change_pct is None and volume is None:
                continue

            amount_wan = _field_float(37)
            amount_yi = round(amount_wan / 10000, 4) if amount_wan is not None else None

            result[quote_code] = {
                "price": price,
                "change_pct": change_pct,
                "volume": volume,
                "open": open_price,
                "high": _field_float(33),
                "low": _field_float(34),
                "turnover_rate": _field_float(38),
                "pe_dynamic": _field_float(52) or _field_float(39),
                "float_market_cap": _field_float(44),
                "market_cap": _field_float(45),
                "pb": _field_float(46),
                "amplitude": _field_float(47),
                "amount_yi": amount_yi,
                "quote_ts": _field_float(30),
            }

    return result


def _fetch_realtime_quote_for_row(row: StockUniverse) -> Optional[Dict[str, Optional[float]]]:
    quote_code = _symbol_to_tencent_quote_code(row.symbol)
    if not quote_code:
        return None
    quote_map = _fetch_tencent_quote_map([quote_code])
    return quote_map.get(quote_code)


def _refresh_existing_universe_quotes(db: Session) -> int:
    rows = db.query(StockUniverse).filter(StockUniverse.listed.is_(True)).all()
    if not rows:
        return 0

    quote_code_to_rows: Dict[str, List[StockUniverse]] = {}
    for row in rows:
        quote_code = _symbol_to_tencent_quote_code(row.symbol)
        if not quote_code:
            continue
        quote_code_to_rows.setdefault(quote_code, []).append(row)

    quote_map = _fetch_tencent_quote_map(list(quote_code_to_rows.keys()))
    if not quote_map:
        return 0

    now = _utc_now()
    updated_count = 0
    for quote_code, quote_payload in quote_map.items():
        targets = quote_code_to_rows.get(quote_code) or []
        if not targets:
            continue

        for row in targets:
            applied = False
            price_value = quote_payload.get("price")
            if price_value is not None:
                row.price = float(price_value)
                applied = True
            change_pct_value = quote_payload.get("change_pct")
            if change_pct_value is not None:
                row.change_pct = float(change_pct_value)
                applied = True
            volume_value = quote_payload.get("volume")
            if volume_value is not None:
                row.volume = float(volume_value)
                applied = True

            if applied:
                row.updated_at = now
                updated_count += 1

    if updated_count > 0:
        db.commit()

    return updated_count


def _touch_existing_universe_timestamp(db: Session) -> int:
    now = _utc_now()
    updated_count = (
        db.query(StockUniverse)
        .filter(StockUniverse.listed.is_(True))
        .update({StockUniverse.updated_at: now}, synchronize_session=False)
    )
    if updated_count > 0:
        db.commit()
    return int(updated_count)


def _reset_db_connection(db: Session) -> None:
    try:
        db.rollback()
    except Exception:
        db.close()


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

    quote_codes = [f"us{row['code']}" for row in ordered_rows if row.get("code")]
    quote_map = _fetch_tencent_quote_map(quote_codes)
    for row in ordered_rows:
        code = str(row.get("code") or "").strip().upper()
        if not code:
            continue
        quote = quote_map.get(f"us{code}")
        if not quote:
            continue

        price = _safe_float(quote.get("price"))
        if price is not None:
            row["price"] = float(price)

        change_pct = _safe_float(quote.get("change_pct"))
        if change_pct is not None:
            row["change_pct"] = float(change_pct)

        volume = _safe_float(quote.get("volume"))
        if volume is not None:
            row["volume"] = float(volume)

        amount_yi = _safe_float(quote.get("amount_yi"))
        if amount_yi is not None:
            row["turnover"] = float(amount_yi * 100_000_000)

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

        _reset_db_connection(db)

        messages: List[str] = []
        source_success = {"a_share": False, "hk": False, "us": False}
        merged: Dict[str, Dict[str, Any]] = {}

        try:
            a_rows, a_source = _fetch_a_share_rows()
            for row in a_rows:
                merged[row["symbol"]] = row
            messages.append(f"A股来源: {a_source}, 数量: {len(a_rows)}")
            source_success["a_share"] = len(a_rows) > 0
        except Exception as exc:
            logger.exception("A股数据同步失败")
            messages.append(f"A股同步失败: {exc}")

        try:
            hk_rows, hk_source = _fetch_hk_rows()
            for row in hk_rows:
                merged[row["symbol"]] = row
            messages.append(f"港股来源: {hk_source}, 数量: {len(hk_rows)}")
            source_success["hk"] = len(hk_rows) > 0
        except Exception as exc:
            logger.exception("港股数据同步失败")
            messages.append(f"港股同步失败: {exc}")

        try:
            us_rows, us_source = _fetch_us_rows()
            for row in us_rows:
                merged[row["symbol"]] = row
            messages.append(f"美股来源: {us_source}, 数量: {len(us_rows)}")
            source_success["us"] = len(us_rows) > 0
        except Exception as exc:
            logger.exception("美股数据同步失败")
            messages.append(f"美股同步失败: {exc}")

        if not merged:
            refreshed_count = 0
            if current_count > 0:
                refreshed_count = _touch_existing_universe_timestamp(db)
                if refreshed_count > 0:
                    a_share_count, hk_count, us_count = _get_market_counts(db)
                    return StockSyncResponse(
                        success=True,
                        total_count=current_count,
                        a_share_count=a_share_count,
                        hk_count=hk_count,
                        us_count=us_count,
                        duration_ms=int((time.perf_counter() - started) * 1000),
                        last_synced_at=_serialize_dt(_get_last_synced_at(db)),
                        message=(
                            "外部股票列表同步失败，已保留现有股票池并刷新时间戳 "
                            f"{refreshed_count} 只; {'; '.join(messages)}"
                        ),
                    )

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

        if current_count > 0 and len(merged) < int(current_count * 0.8):
            refreshed_count = _touch_existing_universe_timestamp(db)
            if refreshed_count > 0:
                a_share_count, hk_count, us_count = _get_market_counts(db)
                failed_scopes = []
                if not source_success["a_share"]:
                    failed_scopes.append("A股")
                if not source_success["hk"]:
                    failed_scopes.append("港股")
                if not source_success["us"]:
                    failed_scopes.append("美股")
                scope_text = "、".join(failed_scopes) if failed_scopes else "部分市场"
                return StockSyncResponse(
                    success=True,
                    total_count=current_count,
                    a_share_count=a_share_count,
                    hk_count=hk_count,
                    us_count=us_count,
                    duration_ms=int((time.perf_counter() - started) * 1000),
                    last_synced_at=_serialize_dt(_get_last_synced_at(db)),
                    message=(
                        f"{scope_text}列表拉取不完整（新抓取 {len(merged)} / 现有 {current_count}），"
                        f"已保留现有股票池并刷新时间戳 {refreshed_count} 只; {'; '.join(messages)}"
                    ),
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

        try:
            db.query(StockUniverse).delete(synchronize_session=False)
            db.bulk_save_objects(objects)
            db.commit()
        except OperationalError as exc:
            db.rollback()
            logger.exception("股票池写入失败，尝试回退到时间戳刷新策略")
            if current_count > 0:
                refreshed_count = _touch_existing_universe_timestamp(db)
                a_share_count, hk_count, us_count = _get_market_counts(db)
                return StockSyncResponse(
                    success=True,
                    total_count=current_count,
                    a_share_count=a_share_count,
                    hk_count=hk_count,
                    us_count=us_count,
                    duration_ms=int((time.perf_counter() - started) * 1000),
                    last_synced_at=_serialize_dt(_get_last_synced_at(db)),
                    message=(
                        "同步写入时数据库连接中断，已保留现有股票池并刷新时间戳 "
                        f"{refreshed_count} 只; 失败原因: {exc}"
                    ),
                )
            raise

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


def _derive_scoring_factors_from_row(row: StockUniverse) -> Dict[str, float]:
    price = _market_price(row)
    change_pct = _market_change_pct(row)

    factors = {
        "pe": _stable_metric(row.symbol, "pe", 8.0, 58.0, 1),
        "pb": _stable_metric(row.symbol, "pb", 0.8, 8.5, 2),
        "roe": _stable_metric(row.symbol, "roe", 4.0, 34.0, 1),
        "debt_ratio": _stable_metric(row.symbol, "debt", 18.0, 76.0, 1),
        "revenue_growth": _stable_metric(row.symbol, "revenue", -8.0, 28.0, 1),
        "profit_growth": _stable_metric(row.symbol, "profit", -16.0, 36.0, 1),
        "momentum": _stable_metric(row.symbol, "momentum", -10.0, 12.0, 1),
        "volatility": _stable_metric(row.symbol, "volatility", 16.0, 46.0, 1),
        "news_sentiment": _stable_metric(row.symbol, "sentiment", 0.32, 0.76, 2),
    }

    factors["momentum"] = round(max(-15, min(15, factors["momentum"] + change_pct * 0.6)), 1)
    if price < 3:
        factors["volatility"] = min(55.0, factors["volatility"] + 5)

    return factors


def _score_from_factors(
    *,
    roe: float,
    debt_ratio: float,
    revenue_growth: float,
    profit_growth: float,
    pe: float,
    momentum: float,
    volatility: float,
    news_sentiment: float,
) -> int:
    score = 50.0

    if roe >= 20:
        score += 12
    elif roe >= 12:
        score += 8
    elif roe < 8:
        score -= 8

    if debt_ratio <= 35:
        score += 8
    elif debt_ratio <= 50:
        score += 3
    elif debt_ratio > 65:
        score -= 10

    if revenue_growth >= 15:
        score += 8
    elif revenue_growth < 0:
        score -= 8

    if profit_growth >= 15:
        score += 10
    elif profit_growth < 0:
        score -= 10

    if 10 <= pe <= 35:
        score += 6
    elif pe > 55:
        score -= 7

    if momentum > 5:
        score += 6
    elif momentum < -3:
        score -= 6

    if volatility > 36:
        score -= 8
    elif volatility < 22:
        score += 4

    if news_sentiment > 0.6:
        score += 4
    elif news_sentiment < 0.4:
        score -= 4

    return int(max(1, min(99, round(score))))


def _score_from_universe_row(row: StockUniverse) -> int:
    factors = _derive_scoring_factors_from_row(row)
    return _score_from_factors(
        roe=factors["roe"],
        debt_ratio=factors["debt_ratio"],
        revenue_growth=factors["revenue_growth"],
        profit_growth=factors["profit_growth"],
        pe=factors["pe"],
        momentum=factors["momentum"],
        volatility=factors["volatility"],
        news_sentiment=factors["news_sentiment"],
    )


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


def _price_limit_threshold(item: StockItem) -> Optional[float]:
    board_text = str(item.board or "")
    if item.market in {"创业板", "科创板"}:
        return 20.0
    if "北交所" in board_text or item.exchange == "BSE":
        return 30.0
    if item.market == "A股":
        return 5.0 if item.is_st else 10.0
    return None


def _is_prev_limit_up(item: StockItem) -> bool:
    limit_pct = _price_limit_threshold(item)
    if limit_pct is None:
        return False
    tolerance = 0.2 if limit_pct <= 10 else 0.35
    return item.change_pct >= limit_pct - tolerance


def _is_prev_limit_down(item: StockItem) -> bool:
    limit_pct = _price_limit_threshold(item)
    if limit_pct is None:
        return False
    tolerance = 0.2 if limit_pct <= 10 else 0.35
    return item.change_pct <= -(limit_pct - tolerance)


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


def _clamp_int(value: float, low: int, high: int) -> int:
    return max(low, min(high, int(round(value))))


def _freshness_days(value: Optional[datetime]) -> Optional[int]:
    value_utc = _as_utc(value)
    if value_utc is None:
        return None
    return max(0, int((_utc_now() - value_utc).total_seconds() // 86400))


def _build_data_quality(
    row: StockUniverse,
    enrichment: Optional[StockEnrichment],
    realtime_quote: Optional[Dict[str, Optional[float]]] = None,
) -> StockDataQuality:
    realtime_quote = realtime_quote or {}
    updated_at = enrichment.updated_at if enrichment is not None else row.updated_at
    freshness_days = _freshness_days(updated_at)
    is_enriched = enrichment is not None and enrichment.status in {"success", "partial"}
    quote_price = _safe_float(realtime_quote.get("price"))
    quote_pe = _safe_float(realtime_quote.get("pe_dynamic"))
    quote_pb = _safe_float(realtime_quote.get("pb"))
    quote_amount = _safe_float(realtime_quote.get("amount_yi"))
    quote_low = _safe_float(realtime_quote.get("low"))
    quote_high = _safe_float(realtime_quote.get("high"))

    if enrichment is not None:
        coverage_score = round(float(enrichment.coverage_score or 58.0), 1)
        source = enrichment.source or "mixed_web_sources"
        fundamentals_source = "公开页面补齐 + 规则模型校验"
    else:
        coverage_score = 42.0 if row.price is not None else 30.0
        source = row.source or "stock_universe"
        fundamentals_source = "规则模型估算"

    reliability_score = 26 + coverage_score * 0.52
    if row.price is not None and row.price > 0:
        reliability_score += 8
    if quote_price is not None and quote_price > 0:
        reliability_score += 4
    else:
        reliability_score -= 6
    if quote_pe is None and quote_pb is None:
        reliability_score -= 3
    if quote_amount is None:
        reliability_score -= 2
    if is_enriched:
        reliability_score += 7
    if enrichment is not None and enrichment.status == "partial":
        reliability_score -= 6

    if freshness_days is None:
        reliability_score -= 6
    elif freshness_days <= 1:
        reliability_score += 10
    elif freshness_days <= 3:
        reliability_score += 6
    elif freshness_days <= 7:
        reliability_score += 2
    elif freshness_days <= 30:
        reliability_score -= 4
    else:
        reliability_score -= 10

    warnings: List[str] = []
    if enrichment is None:
        warnings.append("公司资料与财报维度仍以规则模型推演为主，建议结合公告原文复核。")
    elif enrichment.status == "partial":
        warnings.append("联网补齐覆盖率有限，部分字段仍由规则模型估算。")

    if quote_price is None or quote_price <= 0:
        warnings.append("实时价格源不可用，当前价格/涨跌幅可能来自缓存或估算。")
    if quote_pe is None and quote_pb is None:
        warnings.append("PE/PB 缺少实时源，估值字段可能由模型补齐。")
    if quote_amount is None:
        warnings.append("成交额相关字段缺少实时源，均值项可能为近似估算。")
    if (quote_low is None or quote_low <= 0) or (quote_high is None or quote_high <= 0):
        warnings.append("日内高低点不可用，支撑/压力位采用近似替代。")

    if freshness_days is not None and freshness_days > 7:
        warnings.append(f"数据距今已 {freshness_days} 天未刷新，短线决策前建议手动复核行情。")
    if row.market == "美股" and enrichment is None:
        warnings.append("当前美股详情偏向基础研究信息整合，事件与公告维度建议二次核验。")

    return StockDataQuality(
        source=source,
        price_source=row.source or "stock_universe",
        fundamentals_source=fundamentals_source,
        coverage_score=coverage_score,
        reliability_score=_clamp_int(reliability_score, 18, 96),
        is_enriched=is_enriched,
        updated_at=_serialize_dt(updated_at),
        freshness_days=freshness_days,
        warnings=warnings,
    )


def _build_analysis_evidence(stock: StockDetail, factor_scores: StockFactorScores) -> List[str]:
    return [
        f"盈利质量：ROE {stock.roe:.1f}% / 负债率 {stock.debt_ratio:.1f}% / 营收增速 {stock.revenue_growth:+.1f}% / 利润增速 {stock.profit_growth:+.1f}%",
        f"估值与交易：PE {stock.pe:.1f} / PB {stock.pb:.2f} / 动量 {stock.momentum:+.1f}% / 波动率 {stock.volatility:.1f}%",
        f"情绪与执行：新闻情绪 {stock.news_sentiment:.2f} / 支撑 {stock.support_price:.2f} / 压力 {stock.resistance_price:.2f}",
        f"数据可信度：{stock.data_quality.reliability_score}/100，覆盖率 {stock.data_quality.coverage_score:.1f}%，来源 {stock.data_quality.source}",
        f"五维得分：基本面 {factor_scores.fundamental} / 估值 {factor_scores.valuation} / 动量 {factor_scores.momentum} / 情绪 {factor_scores.sentiment} / 风控 {factor_scores.risk_control}",
    ]


def _build_suitability_note(risk_level: str, reliability_score: int) -> str:
    if risk_level == "low" and reliability_score >= 70:
        return "更适合稳健到平衡型用户做中线跟踪，仍需控制单票仓位。"
    if risk_level == "medium":
        return "更适合平衡到进取型用户分批观察，等待触发条件确认后再执行。"
    return "当前更适合作为高风险承受用户的观察标的，不适合重仓参与。"


def _detect_concepts(name: str, industry: str, board: str) -> List[str]:
    haystack = f"{name} {industry} {board}".lower()
    concepts: List[str] = []

    for keyword, concept in _CONCEPT_RULES:
        if keyword.lower() in haystack:
            concepts.append(concept)

    if not concepts:
        if board == "创业板":
            concepts.append("成长股")
        elif board == "科创板":
            concepts.append("硬科技")
        elif board == "港股":
            concepts.append("港股龙头")
        elif board == "美股":
            concepts.append("美股科技")
        else:
            concepts.append("顺周期")

    return list(dict.fromkeys(concepts))[:4]


def _parse_dividend_entries(raw_value: Optional[str]) -> List[Dict[str, Any]]:
    if not raw_value:
        return []
    try:
        parsed = json.loads(raw_value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    if not isinstance(parsed, list):
        return []
    return [item for item in parsed if isinstance(item, dict)]



def _candidate_dividend_report_dates() -> List[str]:
    current_year = _utc_now().year
    return [
        f"{current_year - 1}1231",
        f"{current_year - 1}0930",
        f"{current_year - 1}0630",
        f"{current_year - 2}1231",
    ]



def _fetch_a_share_dividend_marker_map() -> Tuple[Dict[str, Dict[str, Any]], Optional[str]]:
    try:
        import akshare as ak
    except Exception:
        return {}, None

    out, err = _silence_akshare_output()
    for report_date in _candidate_dividend_report_dates():
        try:
            with redirect_stdout(out), redirect_stderr(err):
                frame = _run_with_retry(lambda: ak.stock_fhps_em(date=report_date), attempts=2, delay_seconds=1.0)
        except Exception as exc:
            logger.info("a-share dividend marker fetch failed for %s: %s", report_date, exc)
            continue

        if frame is None or getattr(frame, "empty", True):
            continue

        marker_map: Dict[str, Dict[str, Any]] = {}
        for item in frame.to_dict("records"):
            normalized = _normalize_a_code(item.get("代码"))
            if normalized is None:
                continue
            symbol, _, _, _, _ = normalized
            cash_ratio = _safe_float(item.get("现金分红-现金分红比例")) or 0.0
            dividend_yield = _safe_float(item.get("现金分红-股息率")) or 0.0
            if cash_ratio <= 0 and dividend_yield <= 0:
                continue
            ex_dividend_date = _normalize_kline_date(item.get("除权除息日")) if item.get("除权除息日") else None
            normalized_yield = round(dividend_yield * 100, 2) if 0 < dividend_yield <= 1 else round(dividend_yield, 2)
            marker_map[symbol] = {
                "has_dividend": True,
                "dividend_years": 1,
                "latest_dividend_year": report_date[:4],
                "dividend_yield": normalized_yield if normalized_yield > 0 else None,
                "ex_dividend_date": ex_dividend_date,
            }

        if marker_map:
            return marker_map, report_date

    return {}, None



def _refresh_a_share_dividend_marker_cache() -> None:
    global _dividend_marker_refreshing
    now_ts = time.time()
    try:
        marker_map, report_date = _fetch_a_share_dividend_marker_map()
        if marker_map:
            with _dividend_marker_lock:
                _dividend_marker_cache["symbols"] = marker_map
                _dividend_marker_cache["report_date"] = report_date
                _dividend_marker_cache["expires_at"] = now_ts + _DIVIDEND_CACHE_TTL_SECONDS
    finally:
        with _dividend_marker_lock:
            _dividend_marker_refreshing = False


def _get_cached_a_share_dividend_marker_map() -> Dict[str, Dict[str, Any]]:
    global _dividend_marker_refreshing
    now_ts = time.time()
    with _dividend_marker_lock:
        cached_symbols = _dividend_marker_cache.get("symbols") or {}
        expires_at = float(_dividend_marker_cache.get("expires_at") or 0.0)
        if cached_symbols and expires_at > now_ts:
            return dict(cached_symbols)

        if not _dividend_marker_refreshing:
            _dividend_marker_refreshing = True
            Thread(target=_refresh_a_share_dividend_marker_cache, daemon=True).start()

        return dict(cached_symbols)



def _max_optional_date(base_value: Optional[str], incoming_value: Optional[str]) -> Optional[str]:
    base_text = str(base_value or "").strip()
    incoming_text = str(incoming_value or "").strip()
    if base_text and incoming_text:
        return max(base_text, incoming_text)
    return base_text or incoming_text or None



def _merge_dividend_summary(base: Dict[str, Any], incoming: Dict[str, Any]) -> Dict[str, Any]:
    if not incoming:
        return dict(base)

    merged = dict(base)
    merged["has_dividend"] = bool(base.get("has_dividend") or incoming.get("has_dividend"))
    merged["dividend_years"] = max(int(base.get("dividend_years") or 0), int(incoming.get("dividend_years") or 0))

    base_year = str(base.get("latest_dividend_year") or "").strip()
    incoming_year = str(incoming.get("latest_dividend_year") or "").strip()
    merged["latest_dividend_year"] = max(base_year, incoming_year) if base_year and incoming_year else (base_year or incoming_year or None)
    merged["ex_dividend_date"] = _max_optional_date(base.get("ex_dividend_date"), incoming.get("ex_dividend_date"))

    base_yield = _safe_float(base.get("dividend_yield")) or 0.0
    incoming_yield = _safe_float(incoming.get("dividend_yield")) or 0.0
    merged["dividend_yield"] = round(max(base_yield, incoming_yield), 2) if max(base_yield, incoming_yield) > 0 else None

    base_cash_dividend = _safe_float(base.get("cash_dividend_per_share")) or 0.0
    incoming_cash_dividend = _safe_float(incoming.get("cash_dividend_per_share")) or 0.0
    merged["cash_dividend_per_share"] = round(max(base_cash_dividend, incoming_cash_dividend), 4) if max(base_cash_dividend, incoming_cash_dividend) > 0 else None
    return merged



def _load_dividend_summary_map(db: Session, symbols: List[str]) -> Dict[str, Dict[str, Any]]:
    normalized_symbols = [symbol for symbol in dict.fromkeys(symbols) if symbol]
    if not normalized_symbols:
        return {}

    rows: List[Tuple[str, Optional[str]]] = []
    for start in range(0, len(normalized_symbols), _DIVIDEND_SUMMARY_QUERY_BATCH_SIZE):
        symbol_batch = normalized_symbols[start : start + _DIVIDEND_SUMMARY_QUERY_BATCH_SIZE]
        batch_rows = (
            db.query(StockEnrichment.symbol, StockEnrichment.dividend_history_json)
            .filter(StockEnrichment.symbol.in_(symbol_batch), StockEnrichment.dividend_history_json.isnot(None))
            .all()
        )
        rows.extend(batch_rows)

    summary_map: Dict[str, Dict[str, Any]] = {}
    for symbol, raw_value in rows:
        entries = _parse_dividend_entries(raw_value)
        valid_years: List[str] = []
        latest_ex_dividend_date: Optional[str] = None
        latest_cash_dividend = 0.0
        for entry in entries:
            year = str(entry.get("year") or "").strip()
            ex_dividend_date = str(entry.get("ex_dividend_date") or "").strip()
            cash_dividend = _safe_float(entry.get("cash_dividend_per_share")) or 0.0
            payout_ratio = _safe_float(entry.get("payout_ratio")) or 0.0
            if cash_dividend <= 0 and payout_ratio <= 0 and not ex_dividend_date:
                continue
            if not year and ex_dividend_date:
                year = ex_dividend_date[:4]
            if year:
                valid_years.append(year)
            if ex_dividend_date and (latest_ex_dividend_date is None or ex_dividend_date > latest_ex_dividend_date):
                latest_ex_dividend_date = ex_dividend_date
                latest_cash_dividend = cash_dividend

        unique_years = sorted(set(valid_years), reverse=True)
        if not unique_years:
            continue

        summary_map[symbol] = {
            "has_dividend": True,
            "dividend_years": len(unique_years),
            "latest_dividend_year": unique_years[0],
            "ex_dividend_date": latest_ex_dividend_date,
            "cash_dividend_per_share": round(latest_cash_dividend, 4) if latest_cash_dividend > 0 else None,
        }

    a_share_marker_map = _get_cached_a_share_dividend_marker_map()
    for symbol in normalized_symbols:
        marker = a_share_marker_map.get(symbol)
        if not marker:
            continue
        summary_map[symbol] = _merge_dividend_summary(summary_map.get(symbol, {}), marker)

    return summary_map



def _is_ex_dividend_soon(ex_dividend_date: Optional[str]) -> bool:
    date_text = str(ex_dividend_date or "").strip()
    if not date_text:
        return False
    try:
        target_date = datetime.strptime(date_text[:10], "%Y-%m-%d").date()
    except ValueError:
        return False
    current_date = _utc_now().date()
    max_date = current_date + timedelta(days=_DIVIDEND_SOON_WINDOW_DAYS)
    return current_date <= target_date <= max_date



def _to_stock_item(
    row: StockUniverse,
    has_dividend: bool = False,
    dividend_years: int = 0,
    latest_dividend_year: Optional[str] = None,
    dividend_yield: Optional[float] = None,
    ex_dividend_date: Optional[str] = None,
    cash_dividend_per_share: Optional[float] = None,
) -> StockItem:
    score_factors = _derive_scoring_factors_from_row(row)
    score = _score_from_factors(
        roe=score_factors["roe"],
        debt_ratio=score_factors["debt_ratio"],
        revenue_growth=score_factors["revenue_growth"],
        profit_growth=score_factors["profit_growth"],
        pe=score_factors["pe"],
        momentum=score_factors["momentum"],
        volatility=score_factors["volatility"],
        news_sentiment=score_factors["news_sentiment"],
    )
    price = _market_price(row)
    change_pct = _market_change_pct(row)
    market_cap = round(_stable_metric(row.symbol, "market_cap", 120.0, 62000.0, 1), 1)
    pe = round(float(score_factors["pe"]), 1)
    revenue = round(market_cap * _stable_metric(row.symbol, "revenue_scale", 0.35, 2.8, 3), 1)
    net_profit = round(market_cap / pe, 1) if pe > 0 else 0.0
    revenue_growth = round(float(score_factors["revenue_growth"]), 1)
    revenue_growth_qoq = round(_stable_metric(row.symbol, "revenue_growth_qoq", -18.0, 28.0, 1), 1)
    profit_growth = round(float(score_factors["profit_growth"]), 1)
    profit_growth_qoq = round(_stable_metric(row.symbol, "profit_growth_qoq", -25.0, 35.0, 1), 1)
    net_margin = round((net_profit / revenue) * 100, 1) if revenue > 0 else 0.0
    gross_margin = round(min(88.0, max(net_margin + 5.0, net_margin + _stable_metric(row.symbol, "gross_margin_spread", 8.0, 34.0, 1))), 1)
    roe = round(float(score_factors["roe"]), 1)
    debt_ratio = round(float(score_factors["debt_ratio"]), 1)
    industry = _industry_from_row(row)
    concepts = _detect_concepts(name=row.name, industry=industry, board=row.board)
    tags = _build_list_tags(row=row, industry=industry, score=score, change_pct=change_pct, price=price)
    normalized_dividend_yield = _safe_float(dividend_yield)
    if (normalized_dividend_yield is None or normalized_dividend_yield <= 0) and cash_dividend_per_share and price > 0:
        normalized_dividend_yield = round(float(cash_dividend_per_share) / price * 100, 2)
    is_high_dividend = bool(normalized_dividend_yield and normalized_dividend_yield >= _DIVIDEND_HIGH_YIELD_THRESHOLD)
    is_ex_dividend_soon = _is_ex_dividend_soon(ex_dividend_date)
    if has_dividend:
        tags.append("分红股")
        if dividend_years >= 3:
            tags.append("连续分红")
        if is_high_dividend:
            tags.append("高股息")
        if is_ex_dividend_soon:
            tags.append("即将除权")
    tags.extend([f"概念:{item}" for item in concepts])
    is_st = bool(row.name.upper().startswith("ST") or row.name.upper().startswith("*ST"))
    if not is_st and row.market in {"A股", "创业板", "科创板"}:
        is_st = _stable_metric(row.symbol, "st_marker", 0.0, 1.0, 4) < 0.018
    if is_st:
        tags.append("ST")
    tags = list(dict.fromkeys(tags))[:12]

    return StockItem(
        symbol=row.symbol,
        name=row.name,
        market=row.market,
        board=row.board,
        exchange=row.exchange,
        industry=industry,
        sector=industry,
        concepts=concepts,
        tags=tags,
        price=price,
        change_pct=change_pct,
        analyzed=True,
        score=score,
        recommendation=_to_recommendation(score),
        market_cap=market_cap,
        pe=pe,
        net_profit=net_profit,
        revenue=revenue,
        revenue_growth=revenue_growth,
        revenue_growth_qoq=revenue_growth_qoq,
        profit_growth=profit_growth,
        profit_growth_qoq=profit_growth_qoq,
        gross_margin=gross_margin,
        net_margin=net_margin,
        roe=roe,
        debt_ratio=debt_ratio,
        is_st=is_st,
        has_dividend=has_dividend,
        dividend_years=dividend_years,
        latest_dividend_year=latest_dividend_year,
        dividend_yield=round(normalized_dividend_yield, 2) if normalized_dividend_yield and normalized_dividend_yield > 0 else None,
        ex_dividend_date=ex_dividend_date,
        is_high_dividend=is_high_dividend,
        is_ex_dividend_soon=is_ex_dividend_soon,
        updated_at=_serialize_dt(row.updated_at),
    )


def _stock_item_cache_key(
    row: StockUniverse,
    *,
    has_dividend: bool,
    dividend_years: int,
    latest_dividend_year: Optional[str],
    dividend_yield: Optional[float],
    ex_dividend_date: Optional[str],
    cash_dividend_per_share: Optional[float],
) -> str:
    updated_at_text = _serialize_dt(row.updated_at) or ""
    return "|".join(
        [
            row.symbol,
            updated_at_text,
            "1" if has_dividend else "0",
            str(int(dividend_years or 0)),
            str(latest_dividend_year or ""),
            str(_safe_float(dividend_yield) or 0.0),
            str(ex_dividend_date or ""),
            str(_safe_float(cash_dividend_per_share) or 0.0),
        ]
    )


def _kline_date_window(period: str) -> Tuple[str, str]:
    calendar_days = {
        "1mo": 45,
        "3mo": 120,
        "6mo": 240,
        "1y": 420,
        "5y": 1900,
    }
    end_date = _utc_now().date()
    start_date = end_date - timedelta(days=calendar_days.get(period, 240))
    return start_date.strftime("%Y%m%d"), end_date.strftime("%Y%m%d")



def _kline_date_window_iso(period: str) -> Tuple[str, str]:
    start_date, end_date = _kline_date_window(period)
    return f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:8]}", f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:8]}"



def _normalize_kline_date(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        try:
            return value.strftime("%Y-%m-%d")
        except Exception:
            return ""
    if hasattr(value, "strftime"):
        try:
            return value.strftime("%Y-%m-%d")
        except Exception:
            return ""
    text = str(value).strip()
    if text.lower() in {"nat", "nan", "none"}:
        return ""
    return text[:10]



def _eastmoney_secid_for_row(row: StockUniverse) -> Optional[str]:
    code, suffix = _symbol_components(row.symbol)
    if suffix == "SH":
        return f"1.{code}"
    if suffix in {"SZ", "BJ"}:
        return f"0.{code}"
    return None


def _build_kline_points_from_eastmoney_klines(klines: List[str]) -> List[KLinePoint]:
    points: List[KLinePoint] = []
    for item in klines:
        if not isinstance(item, str):
            continue
        parts = item.split(",")
        if len(parts) < 7:
            continue
        open_price = _safe_float(parts[1])
        close_price = _safe_float(parts[2])
        high_price = _safe_float(parts[3])
        low_price = _safe_float(parts[4])
        turnover_amount = _safe_float(parts[6]) or 0.0
        if None in {open_price, high_price, low_price, close_price}:
            continue
        points.append(
            KLinePoint(
                date=str(parts[0]).strip(),
                open=float(open_price),
                high=float(high_price),
                low=float(low_price),
                close=float(close_price),
                volume=float(turnover_amount),
            )
        )
    points.sort(key=lambda item: item.date)
    return points


def _build_kline_points_from_tencent_payload(history: Any, volume_scale: float = 1.0) -> List[KLinePoint]:
    points: List[KLinePoint] = []
    if not history:
        return points

    for item in history:
        if not isinstance(item, (list, tuple)) or len(item) < 6:
            continue

        open_price = _safe_float(item[1])
        close_price = _safe_float(item[2])
        high_price = _safe_float(item[3])
        low_price = _safe_float(item[4])
        raw_volume = (_safe_float(item[5]) or 0.0) * volume_scale
        turnover_wan = _safe_float(item[8]) if len(item) > 8 else None
        if turnover_wan and turnover_wan > 0:
            turnover_amount = turnover_wan * 10_000
        elif close_price and raw_volume > 0:
            turnover_amount = raw_volume * float(close_price)
        else:
            turnover_amount = 0.0
        if None in {open_price, high_price, low_price, close_price}:
            continue

        points.append(
            KLinePoint(
                date=_normalize_kline_date(item[0]),
                open=float(open_price),
                high=float(high_price),
                low=float(low_price),
                close=float(close_price),
                volume=float(turnover_amount),
            )
        )

    points.sort(key=lambda item: item.date)
    return points



def _build_kline_points_from_akshare_frame(history: Any, volume_scale: float = 1.0) -> List[KLinePoint]:
    points: List[KLinePoint] = []
    if history is None or getattr(history, "empty", True):
        return points

    for item in history.to_dict("records"):
        open_price = _safe_float(item.get("开盘"))
        high_price = _safe_float(item.get("最高"))
        low_price = _safe_float(item.get("最低"))
        close_price = _safe_float(item.get("收盘"))
        raw_volume = (_safe_float(item.get("成交量")) or 0.0) * volume_scale
        turnover_amount = _safe_float(item.get("成交额"))
        if not turnover_amount or turnover_amount <= 0:
            turnover_amount = (raw_volume * float(close_price)) if close_price else 0.0
        if None in {open_price, high_price, low_price, close_price}:
            continue
        points.append(
            KLinePoint(
                date=_normalize_kline_date(item.get("日期")),
                open=float(open_price),
                high=float(high_price),
                low=float(low_price),
                close=float(close_price),
                volume=float(turnover_amount),
            )
        )
    return points



def _build_kline_points_from_yfinance_history(history: Any, period: str, interval: str) -> List[KLinePoint]:
    points: List[KLinePoint] = []
    if history is None or getattr(history, "empty", True):
        return points

    history = history.tail(_kline_limit(period=period, interval=interval))
    for idx, item in history.iterrows():
        try:
            open_price = _safe_float(item.get("Open"))
            high_price = _safe_float(item.get("High"))
            low_price = _safe_float(item.get("Low"))
            close_price = _safe_float(item.get("Close"))
            raw_volume = _safe_float(item.get("Volume")) or 0.0
        except Exception:
            continue
        if None in {open_price, high_price, low_price, close_price}:
            continue
        turnover_amount = (raw_volume * float(close_price)) if raw_volume > 0 else 0.0
        date_value = idx.to_pydatetime() if hasattr(idx, "to_pydatetime") else idx
        points.append(
            KLinePoint(
                date=(date_value.strftime("%Y-%m-%d %H:%M") if interval == "1h" and hasattr(date_value, "strftime") else _normalize_kline_date(date_value)),
                open=float(open_price),
                high=float(high_price),
                low=float(low_price),
                close=float(close_price),
                volume=float(turnover_amount),
            )
        )
    return points



def _fetch_kline_history_from_akshare(row: StockUniverse, period: str) -> Tuple[Optional[str], List[KLinePoint]]:
    code, suffix = _symbol_components(row.symbol)
    if suffix not in {"SH", "SZ", "BJ", "HK"}:
        return None, []

    try:
        import akshare as ak
    except Exception:
        return None, []

    start_date, end_date = _kline_date_window(period)
    out, err = _silence_akshare_output()

    history = None
    source = None

    try:
        if suffix in {"SH", "SZ", "BJ"}:
            def _fetch_a_hist():
                with redirect_stdout(out), redirect_stderr(err):
                    return ak.stock_zh_a_hist(symbol=code, period="daily", start_date=start_date, end_date=end_date, adjust="")

            history = _run_with_retry(_fetch_a_hist, attempts=2, delay_seconds=1.0)
            source = "akshare:stock_zh_a_hist"
        elif suffix == "HK":
            def _fetch_hk_hist():
                with redirect_stdout(out), redirect_stderr(err):
                    return ak.stock_hk_hist(symbol=code.zfill(5), period="daily", start_date=start_date, end_date=end_date, adjust="")

            history = _run_with_retry(_fetch_hk_hist, attempts=2, delay_seconds=1.0)
            source = "akshare:stock_hk_hist"
    except Exception as exc:
        logger.info("akshare kline fetch failed for %s: %s", row.symbol, exc)
        history = None

    if history is None or getattr(history, "empty", True):
        return None, []

    history = history.tail(_KLINE_LIMIT_BY_PERIOD[period])
    volume_scale = 100.0 if suffix in {"SH", "SZ", "BJ"} else 1.0
    return source, _build_kline_points_from_akshare_frame(history=history, volume_scale=volume_scale)



def _fetch_kline_history_from_tencent(row: StockUniverse, period: str) -> Tuple[Optional[str], List[KLinePoint]]:
    code, suffix = _symbol_components(row.symbol)
    start_date, end_date = _kline_date_window_iso(period)

    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json,text/plain,*/*",
        "Referer": "https://gu.qq.com/",
    }

    qq_symbol: Optional[str] = None
    url: Optional[str] = None
    params: Dict[str, str] = {}
    volume_scale = 1.0

    if suffix in {"SH", "SZ", "BJ"}:
        qq_symbol = f"{suffix.lower()}{code}"
        url = "https://proxy.finance.qq.com/ifzqgtimg/appstock/app/newfqkline/get"
        params = {
            "_var": f"kline_dayqfq{end_date[:4]}",
            "param": f"{qq_symbol},day,{start_date},{end_date},640,qfq",
            "r": "0.1",
        }
        volume_scale = 100.0
    elif suffix == "HK":
        qq_symbol = f"hk{code.zfill(5)}"
        url = "https://web.ifzq.gtimg.cn/appstock/app/hkfqkline/get"
        params = {
            "_var": "kline_dayqfq",
            "param": f"{qq_symbol},day,{start_date},{end_date},640,qfq",
            "r": "0.1",
        }

    if not qq_symbol or not url:
        return None, []

    try:
        response = _run_with_retry(
            lambda: requests.get(url, params=params, headers=headers, timeout=20),
            attempts=2,
            delay_seconds=1.0,
        )
        response.raise_for_status()
        payload_text = response.text.partition("=")[2].strip()
        if not payload_text:
            return None, []
        data_json = json.loads(payload_text)
    except Exception as exc:
        logger.info("tencent kline fetch failed for %s: %s", row.symbol, exc)
        return None, []

    symbol_payload = ((data_json.get("data") or {}).get(qq_symbol) or {})
    history = symbol_payload.get("qfqday") or symbol_payload.get("day") or symbol_payload.get("hfqday") or []
    points = _build_kline_points_from_tencent_payload(history=history, volume_scale=volume_scale)
    points = [point for point in points if start_date <= point.date <= end_date]
    points = points[-_KLINE_LIMIT_BY_PERIOD[period] :]
    if not points:
        return None, []

    return f"tencent:{qq_symbol}:qfq", points



def _fetch_kline_intraday_from_eastmoney(row: StockUniverse, period: str, interval: str) -> Tuple[Optional[str], List[KLinePoint]]:
    secid = _eastmoney_secid_for_row(row)
    if not secid:
        return None, []

    interval_map = {"1h": "60"}
    klt = interval_map.get(interval)
    if not klt:
        return None, []

    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json,text/plain,*/*",
        "Referer": "https://quote.eastmoney.com/",
    }
    params = {
        "secid": secid,
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
        "klt": klt,
        "fqt": "0",
        "beg": "0",
        "end": "20500101",
        "smplmt": "10000",
        "lmt": "1000000",
    }

    try:
        response = _run_with_retry(
            lambda: requests.get(
                "https://push2his.eastmoney.com/api/qt/stock/kline/get",
                params=params,
                headers=headers,
                timeout=20,
            ),
            attempts=2,
            delay_seconds=1.0,
        )
        response.raise_for_status()
        data_json = response.json()
    except Exception as exc:
        logger.info("eastmoney intraday kline fetch failed for %s: %s", row.symbol, exc)
        return None, []

    klines = ((data_json.get("data") or {}).get("klines") or [])
    points = _build_kline_points_from_eastmoney_klines(klines)
    if not points:
        return None, []

    points = points[-_kline_limit(period=period, interval=interval) :]
    return f"eastmoney:{secid}:klt{klt}", points


def _fetch_kline_history_from_yfinance(symbol: str, period: str, interval: str) -> Tuple[Optional[str], List[KLinePoint]]:
    ticker_candidates = _to_yfinance_ticker_candidates(symbol)
    if not ticker_candidates:
        return None, []

    try:
        import yfinance as yf
    except Exception:
        return None, []

    for ticker in ticker_candidates:
        try:
            history = yf.Ticker(ticker).history(period=period, interval=interval, auto_adjust=False)
        except Exception:
            history = None
        points = _build_kline_points_from_yfinance_history(history=history, period=period, interval=interval)
        if points:
            return f"yfinance:{ticker}", points
    return None, []



def _fetch_kline_points(row: StockUniverse, period: str, interval: str) -> Tuple[str, List[KLinePoint], bool, Optional[str]]:
    code, suffix = _symbol_components(row.symbol)
    del code

    if interval == "1d" and suffix in {"SH", "SZ", "BJ", "HK"}:
        source, points = _fetch_kline_history_from_tencent(row=row, period=period)
        if points:
            return source or row.source or "tencent", points, False, None

        source, points = _fetch_kline_history_from_akshare(row=row, period=period)
        if points:
            return source or row.source or "akshare", points, False, None

    if interval == "1h" and suffix in {"SH", "SZ", "BJ"}:
        source, points = _fetch_kline_intraday_from_eastmoney(row=row, period=period, interval=interval)
        if points:
            return source or row.source or "eastmoney", points, False, None

    source, points = _fetch_kline_history_from_yfinance(row.symbol, period=period, interval=interval)
    if points:
        return source or row.source or "yfinance", points, False, None

    warning = "当前真实历史K线源暂不可用，已临时使用备用估算K线，请勿直接据此交易。"
    return "synthetic_fallback", _build_synthetic_kline_points(row=row, period=period, interval=interval), True, warning



def get_stock_kline(db: Session, symbol: str, period: str = "6mo", interval: str = "1d") -> Optional[StockKLineResponse]:
    ensure_stock_universe(db)

    row = _resolve_stock_row(db, symbol)
    if row is None:
        return None

    normalized_period = period if period in _KLINE_LIMIT_BY_PERIOD else "6mo"
    normalized_interval = interval if interval in {"1d", "1h"} else "1d"
    source, points, is_fallback, warning = _fetch_kline_points(row=row, period=normalized_period, interval=normalized_interval)

    latest_price = points[-1].close if points else _market_price(row)
    change_pct = None
    if len(points) >= 2 and points[0].close != 0:
        change_pct = round((points[-1].close - points[0].close) / points[0].close * 100, 2)
    elif row.change_pct is not None:
        change_pct = round(float(row.change_pct), 2)

    return StockKLineResponse(
        symbol=row.symbol,
        period=normalized_period,
        interval=normalized_interval,
        source=source or row.source or "unavailable",
        points=points,
        latest_price=latest_price,
        change_pct=change_pct,
        is_fallback=is_fallback,
        warning=warning,
    )


def _query_universe_rows(db: Session, market: Optional[str] = None, q: Optional[str] = None) -> List[UniverseRowView]:
    version = _serialize_dt(_get_last_synced_at(db)) or "no_version"
    global _universe_rows_cache_version, _universe_rows_cache_all, _universe_rows_cache_by_query

    with _universe_rows_cache_lock:
        needs_reload = _universe_rows_cache_version != version or not _universe_rows_cache_all

    if needs_reload:
        records = (
            db.query(
                StockUniverse.symbol,
                StockUniverse.code,
                StockUniverse.name,
                StockUniverse.market,
                StockUniverse.board,
                StockUniverse.exchange,
                StockUniverse.source,
                StockUniverse.listed,
                StockUniverse.price,
                StockUniverse.change_pct,
                StockUniverse.volume,
                StockUniverse.turnover,
                StockUniverse.updated_at,
            )
            .filter(StockUniverse.listed.is_(True))
            .all()
        )
        rows = [
            UniverseRowView(
                symbol=symbol,
                code=code,
                name=name,
                market=market_value,
                board=board,
                exchange=exchange,
                source=source,
                listed=listed,
                price=price,
                change_pct=change_pct,
                volume=volume,
                turnover=turnover,
                updated_at=updated_at,
            )
            for symbol, code, name, market_value, board, exchange, source, listed, price, change_pct, volume, turnover, updated_at in records
        ]
        with _universe_rows_cache_lock:
            _universe_rows_cache_version = version
            _universe_rows_cache_all = rows
            _universe_rows_cache_by_query = {}

    market_key = (market or "").strip()
    q_key = (q or "").strip().lower()
    query_key = f"{market_key}|{q_key}"

    with _universe_rows_cache_lock:
        cached_rows = _universe_rows_cache_by_query.get(query_key)
        all_rows = list(_universe_rows_cache_all)
    if cached_rows is not None:
        return list(cached_rows)

    filtered = all_rows
    if market_key:
        filtered = [row for row in filtered if row.market == market_key]

    if q_key:
        filtered = [
            row
            for row in filtered
            if q_key in (row.symbol or "").lower()
            or q_key in (row.code or "").lower()
            or q_key in (row.name or "").lower()
            or q_key in (row.board or "").lower()
        ]

    with _universe_rows_cache_lock:
        _universe_rows_cache_by_query[query_key] = filtered

    return list(filtered)


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
    products_text = "、".join(stock.products_services[:3]) if stock.products_services else "核心产品与服务"
    return (
        f"{stock.name}（{stock.symbol}）属于{stock.market}市场，交易所在{stock.exchange}，总部位于{stock.headquarters}，"
        f"当前归类为{stock.board}，主要围绕“{theme}”赛道展开经营。"
        f"公司当前重点布局 {products_text}，并持续推进产品、渠道与研发能力建设。"
    )


def _split_profile_sentences(*texts: str, limit: int = 4) -> List[str]:
    sentences: List[str] = []
    for raw_text in texts:
        normalized = re.sub(r"\s+", " ", str(raw_text or "")).strip()
        if not normalized:
            continue
        for part in re.split(r"[。；;！!？?\n]+", normalized):
            cleaned = part.strip(" ，,。；;")
            if len(cleaned) < 6:
                continue
            final_text = cleaned if cleaned.endswith(("。", "！", "？")) else f"{cleaned}。"
            if final_text not in sentences:
                sentences.append(final_text)
            if len(sentences) >= limit:
                return sentences
    return sentences


def _build_industry_positioning(stock: StockDetail) -> str:
    theme = _detect_sector_theme(stock.name, stock.board)
    products_text = "、".join(stock.products_services[:3]) if stock.products_services else "核心产品与服务"
    return (
        f"公司当前定位于 {theme} 方向，依托 {stock.market} / {stock.board} 平台，"
        f"围绕 {products_text} 形成业务布局，并以盈利能力、产品迭代和渠道拓展作为经营抓手。"
    )


def _build_business_scope(stock: StockDetail) -> List[str]:
    scope = _split_profile_sentences(stock.main_business, stock.company_intro, limit=3)
    if stock.products_services:
        scope.append(f"核心产品与服务包括：{'、'.join(stock.products_services[:4])}。")

    if not scope:
        theme = _detect_sector_theme(stock.name, stock.board)
        scope = [
            f"公司围绕 {theme} 方向开展主营业务，持续推进核心产品、渠道与服务体系建设。",
            f"经营重心覆盖研发、生产、销售或平台运营等关键环节，并根据市场需求进行产品迭代。",
        ]

    deduped = list(dict.fromkeys(scope))
    return deduped[:4]


def _build_market_coverage(stock: StockDetail) -> List[str]:
    combined_text = f"{stock.company_intro} {stock.main_business}"
    coverage: List[str] = []

    if stock.headquarters and stock.headquarters not in {"未知", "未披露"}:
        coverage.append(stock.headquarters)

    if stock.market in {"A股", "创业板", "科创板"}:
        coverage.extend(["中国内地市场", "重点区域渠道网络", "产业链上下游客户"])
    elif stock.market == "港股":
        coverage.extend(["中国香港资本市场", "中国内地业务", "跨区域经营网络"])
    else:
        coverage.extend(["美国本土市场", "国际客户市场", "全球化业务布局"])

    if any(keyword in combined_text for keyword in ["海外", "全球", "国际"]):
        coverage.append("海外/国际市场")

    return list(dict.fromkeys([item for item in coverage if item]))[:5]


def _build_company_highlights(stock: StockDetail) -> List[str]:
    highlights: List[str] = [
        f"当前总市值约 {stock.market_cap:.1f} 亿，员工规模约 {max(stock.employees, 0):,} 人。",
    ]

    profitability_parts: List[str] = []
    if stock.roe > 0:
        profitability_parts.append(f"ROE {stock.roe:.1f}%")
    if stock.profit_growth != 0:
        profitability_parts.append(f"利润增速 {stock.profit_growth:+.1f}%")
    if stock.revenue_growth != 0:
        profitability_parts.append(f"营收增速 {stock.revenue_growth:+.1f}%")
    if profitability_parts:
        highlights.append(f"经营质量方面，{'，'.join(profitability_parts[:3])}。")

    if stock.products_services:
        highlights.append(f"产品结构方面，当前重点覆盖 {'、'.join(stock.products_services[:4])}。")

    if stock.debt_ratio <= 45:
        highlights.append(f"资产负债率约 {stock.debt_ratio:.1f}%，资本结构相对稳健。")
    elif stock.debt_ratio >= 65:
        highlights.append(f"资产负债率约 {stock.debt_ratio:.1f}%，需持续关注财务杠杆压力。")

    try:
        listed_year = datetime.strptime(stock.listing_date[:10], "%Y-%m-%d").year
        current_year = _utc_now().year
        listed_age = max(0, current_year - listed_year)
        if listed_age > 0:
            highlights.append(f"上市时间为 {stock.listing_date}，至今约 {listed_age} 年，具备一定公开市场经营与披露历史。")
    except ValueError:
        pass

    return list(dict.fromkeys(highlights))[:5]


def _decorate_company_profile(stock: StockDetail) -> StockDetail:
    intro_text = stock.company_intro.strip() or _build_company_intro(stock)
    profile_stock = stock.model_copy(update={"company_intro": intro_text})
    return profile_stock.model_copy(
        update={
            "industry_positioning": _build_industry_positioning(profile_stock),
            "business_scope": _build_business_scope(profile_stock),
            "market_coverage": _build_market_coverage(profile_stock),
            "company_highlights": _build_company_highlights(profile_stock),
        }
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


def _build_stock_detail_from_row(
    row: StockUniverse,
    realtime_quote: Optional[Dict[str, Optional[float]]] = None,
) -> StockDetail:
    realtime_quote = realtime_quote or {}
    quote_price = _safe_float(realtime_quote.get("price"))
    quote_open = _safe_float(realtime_quote.get("open"))
    quote_change_pct = _safe_float(realtime_quote.get("change_pct"))
    if quote_price is not None and quote_price > 0:
        price = float(quote_price)
    elif quote_open is not None and quote_open > 0:
        price = float(quote_open)
    else:
        price = _market_price(row)
    if quote_change_pct is not None:
        change_pct = round(float(quote_change_pct), 2)
    else:
        change_pct = _market_change_pct(row)
    score_factors = _derive_scoring_factors_from_row(row)

    pe_quote = _safe_float(realtime_quote.get("pe_dynamic"))
    pe = round(float(pe_quote), 1) if pe_quote is not None else round(float(score_factors["pe"]), 1)
    pb_quote = _safe_float(realtime_quote.get("pb"))
    pb = round(float(pb_quote), 2) if pb_quote is not None else round(float(score_factors["pb"]), 2)
    roe = score_factors["roe"]
    debt_ratio = score_factors["debt_ratio"]
    revenue_growth = score_factors["revenue_growth"]
    profit_growth = score_factors["profit_growth"]
    momentum = score_factors["momentum"]
    volatility = score_factors["volatility"]
    news_sentiment = score_factors["news_sentiment"]

    if row.market == "港股":
        currency = "HKD"
    elif row.market == "美股":
        currency = "USD"
    else:
        currency = "CNY"
    market_cap_quote = _safe_float(realtime_quote.get("market_cap"))
    if market_cap_quote is not None:
        market_cap = round(max(float(market_cap_quote), 0.0), 2)
    else:
        market_cap = round(_stable_metric(row.symbol, "market_cap", 120.0, 62000.0, 1), 2)
    float_cap_raw = _safe_float(realtime_quote.get("float_market_cap"))
    if float_cap_raw is not None:
        free_float_cap = round(max(float(float_cap_raw), 0.0), 2)
    else:
        free_float_ratio = _stable_metric(row.symbol, "free_float_ratio", 0.35, 0.86, 2)
        free_float_cap = round(market_cap * free_float_ratio, 1)
    turnover_rate_quote = _safe_float(realtime_quote.get("turnover_rate"))
    if turnover_rate_quote is not None:
        turnover_rate = round(max(float(turnover_rate_quote), 0.0), 2)
    else:
        turnover_rate = round(_stable_metric(row.symbol, "turnover_rate", 0.35, 11.5, 2), 2)
    amplitude_quote = _safe_float(realtime_quote.get("amplitude"))
    if amplitude_quote is not None:
        amplitude = round(max(float(amplitude_quote), 0.0), 2)
    else:
        amplitude = round(max(0.8, min(16.0, volatility * 0.28)), 2)

    amount_yi = _safe_float(realtime_quote.get("amount_yi"))
    if amount_yi is not None:
        avg_volume_5d = round(max(float(amount_yi), 0.0), 2)
        if avg_volume_5d > 0:
            avg_volume_20d = round(max(avg_volume_5d, avg_volume_5d * _stable_metric(row.symbol, "vol_ratio", 1.05, 1.75, 2)), 2)
        else:
            avg_volume_20d = 0.0
    else:
        avg_volume_5d = _stable_metric(row.symbol, "avg_vol_5d", 0.08, 65.0, 2)
        avg_volume_20d = round(max(avg_volume_5d, avg_volume_5d * _stable_metric(row.symbol, "vol_ratio", 1.0, 1.9, 2)), 2)

    quote_low = _safe_float(realtime_quote.get("low"))
    quote_high = _safe_float(realtime_quote.get("high"))
    if quote_low is not None:
        support_price = round(quote_low, 2) if quote_low > 0 else round(price, 2)
    else:
        support_gap = max(0.04, min(0.16, volatility / 180))
        support_price = round(price * (1 - support_gap), 2)
    if quote_high is not None:
        resistance_price = round(quote_high, 2) if quote_high > 0 else round(price, 2)
    else:
        resistance_gap = max(0.05, min(0.2, volatility / 160))
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
        industry_positioning="",
        business_scope=[],
        market_coverage=[],
        company_intro="",
        business_tags=[],
        company_highlights=[],
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
        data_quality=_build_data_quality(row=row, enrichment=None, realtime_quote=realtime_quote),
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
        industry_positioning="",
        business_scope=[],
        market_coverage=[],
        company_intro=company_intro,
        business_tags=business_tags,
        company_highlights=[],
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
        data_quality=temp_stock.data_quality,
    )

def _score_stock(stock: StockDetail) -> int:
    return _score_from_factors(
        roe=stock.roe,
        debt_ratio=stock.debt_ratio,
        revenue_growth=stock.revenue_growth,
        profit_growth=stock.profit_growth,
        pe=stock.pe,
        momentum=stock.momentum,
        volatility=stock.volatility,
        news_sentiment=stock.news_sentiment,
    )


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
    confidence = int(max(35, min(95, round(score * 0.66 + factor_scores.risk_control * 0.22 + stock.data_quality.reliability_score * 0.12))))

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
        methodology="规则模型 v2：公开行情 + 财务阈值 + 估值/动量/情绪 + 风控约束综合打分",
        evidence_points=_build_analysis_evidence(stock, factor_scores),
        suitability_note=_build_suitability_note(risk_level, stock.data_quality.reliability_score),
        disclaimer="结论仅供研究辅助，不构成投资建议；若数据覆盖率偏低或更新较久，应以公告与实时行情为准。",
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


def _build_dividend_summary(items: List[StockItem]) -> StockDividendSummary:
    dividend_items = [item for item in items if item.has_dividend]
    latest_year = None
    latest_year_candidates = sorted({str(item.latest_dividend_year) for item in dividend_items if item.latest_dividend_year}, reverse=True)
    if latest_year_candidates:
        latest_year = latest_year_candidates[0]

    return StockDividendSummary(
        total=len(dividend_items),
        continuous_3y_count=len([item for item in dividend_items if item.dividend_years >= 3]),
        high_yield_count=len([item for item in dividend_items if item.is_high_dividend]),
        upcoming_ex_dividend_count=len([item for item in dividend_items if item.is_ex_dividend_soon]),
        latest_year=latest_year,
        by_market=_counter_to_sorted_dict(Counter(item.market for item in dividend_items)),
        by_board=_counter_to_sorted_dict(Counter(item.board for item in dividend_items)),
    )



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
            top_concepts={},
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
    concept_counter = Counter(value for item in items for value in item.concepts)
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
        top_concepts=_counter_to_sorted_dict(concept_counter, limit=12),
        top_tags=_counter_to_sorted_dict(tag_counter, limit=12),
    )


def _build_stock_list_source_cache_key(market: Optional[str], q: Optional[str]) -> str:
    return json.dumps(
        {
            "market": (market or "").strip(),
            "q": (q or "").strip().lower(),
        },
        ensure_ascii=False,
        sort_keys=True,
    )


def _get_stock_list_source(
    db: Session,
    *,
    rows: List[UniverseRowView],
    market: Optional[str],
    q: Optional[str],
    last_synced_at_text: Optional[str],
) -> Dict[str, Any]:
    version = last_synced_at_text or "no_version"
    cache_key = _build_stock_list_source_cache_key(market, q)

    global _stock_list_source_cache_version, _stock_list_source_cache
    with _stock_list_source_cache_lock:
        if _stock_list_source_cache_version != version:
            _stock_list_source_cache_version = version
            _stock_list_source_cache = OrderedDict()

        cached_source = _stock_list_source_cache.get(cache_key)
        if cached_source is not None:
            _stock_list_source_cache.move_to_end(cache_key)
            return cached_source

    global _stock_item_cache_version, _stock_item_cache
    with _stock_item_cache_lock:
        if _stock_item_cache_version != last_synced_at_text:
            _stock_item_cache_version = last_synced_at_text
            _stock_item_cache = {}

    global _dividend_summary_cache_version, _dividend_summary_cache_all
    with _dividend_summary_cache_lock:
        dividend_cache_stale = _dividend_summary_cache_version != last_synced_at_text or not _dividend_summary_cache_all
    if dividend_cache_stale:
        all_symbols = [row.symbol for row in _query_universe_rows(db, market=None, q=None)]
        full_summary = _load_dividend_summary_map(db, all_symbols)
        with _dividend_summary_cache_lock:
            _dividend_summary_cache_version = last_synced_at_text
            _dividend_summary_cache_all = full_summary

    with _dividend_summary_cache_lock:
        cached_summary_all = dict(_dividend_summary_cache_all)

    dividend_summary_map = {row.symbol: cached_summary_all.get(row.symbol, {}) for row in rows}
    items: List[StockItem] = []
    for row in rows:
        summary = dividend_summary_map.get(row.symbol, {})
        has_dividend = bool(summary.get("has_dividend"))
        dividend_years = int(summary.get("dividend_years") or 0)
        latest_dividend_year = summary.get("latest_dividend_year")
        dividend_yield = summary.get("dividend_yield")
        ex_dividend_date = summary.get("ex_dividend_date")
        cash_dividend_per_share = summary.get("cash_dividend_per_share")
        cache_key_for_item = _stock_item_cache_key(
            row,
            has_dividend=has_dividend,
            dividend_years=dividend_years,
            latest_dividend_year=latest_dividend_year,
            dividend_yield=dividend_yield,
            ex_dividend_date=ex_dividend_date,
            cash_dividend_per_share=cash_dividend_per_share,
        )

        with _stock_item_cache_lock:
            cached_item = _stock_item_cache.get(cache_key_for_item)
        if cached_item is not None:
            items.append(cached_item)
            continue

        item = _to_stock_item(
            row,
            has_dividend=has_dividend,
            dividend_years=dividend_years,
            latest_dividend_year=latest_dividend_year,
            dividend_yield=dividend_yield,
            ex_dividend_date=ex_dividend_date,
            cash_dividend_per_share=cash_dividend_per_share,
        )
        with _stock_item_cache_lock:
            _stock_item_cache[cache_key_for_item] = item
        items.append(item)

    recommendation_priority = {
        "buy": 0,
        "watch": 1,
        "hold_cautious": 2,
        "avoid": 3,
    }
    source = {
        "items": items,
        "industries": sorted({item.industry for item in items}),
        "concepts": sorted({value for item in items for value in item.concepts}),
        "tags": sorted({value for item in items for value in item.tags}),
        "boards": sorted({item.board for item in items}),
        "exchanges": sorted({item.exchange for item in items}),
        "recommendations": sorted({item.recommendation for item in items}, key=lambda value: recommendation_priority[value]),
    }

    with _stock_list_source_cache_lock:
        _stock_list_source_cache[cache_key] = source
        _stock_list_source_cache.move_to_end(cache_key)
        while len(_stock_list_source_cache) > _STOCK_LIST_SOURCE_CACHE_MAX:
            _stock_list_source_cache.popitem(last=False)

    return source


def get_stock_list(
    db: Session,
    analyzed: Optional[bool] = None,
    market: Optional[str] = None,
    board: Optional[str] = None,
    exchange: Optional[str] = None,
    industry: Optional[str] = None,
    concept: Optional[str] = None,
    tag: Optional[str] = None,
    recommendation: Optional[str] = None,
    dividend_years_min: Optional[int] = None,
    dividend_yield_min: Optional[float] = None,
    ex_dividend_soon: Optional[bool] = None,
    market_cap_min: Optional[float] = None,
    market_cap_max: Optional[float] = None,
    price_min: Optional[float] = None,
    price_max: Optional[float] = None,
    pe_max: Optional[float] = None,
    net_profit_min: Optional[float] = None,
    revenue_min: Optional[float] = None,
    revenue_growth_min: Optional[float] = None,
    revenue_growth_qoq_min: Optional[float] = None,
    profit_growth_min: Optional[float] = None,
    profit_growth_qoq_min: Optional[float] = None,
    gross_margin_min: Optional[float] = None,
    net_margin_min: Optional[float] = None,
    roe_min: Optional[float] = None,
    debt_ratio_max: Optional[float] = None,
    exclude_st: Optional[bool] = None,
    score_min: Optional[int] = None,
    score_max: Optional[int] = None,
    change_pct_min: Optional[float] = None,
    change_pct_max: Optional[float] = None,
    prev_limit_up: Optional[bool] = None,
    prev_limit_down: Optional[bool] = None,
    dividend_only: Optional[bool] = None,
    q: Optional[str] = None,
    sort_by: str = "score",
    page: int = 1,
    page_size: int = 50,
    include_meta: bool = True,
) -> StockListResponse:
    ensure_stock_universe(db)

    last_synced_at_text = _serialize_dt(_get_last_synced_at(db))
    rows = _query_universe_rows(db, market=market, q=q)
    source = _get_stock_list_source(
        db,
        rows=rows,
        market=market,
        q=q,
        last_synced_at_text=last_synced_at_text,
    )

    items = list(source["items"])
    if analyzed is not None:
        items = [item for item in items if item.analyzed == analyzed]

    industries = list(source["industries"])
    concepts = list(source["concepts"])
    tags = list(source["tags"])
    boards = list(source["boards"])
    exchanges = list(source["exchanges"])
    recommendations = list(source["recommendations"])

    normalized_board = _normalize_filter_text(board)
    if normalized_board:
        items = [item for item in items if item.board.lower() == normalized_board]

    normalized_exchange = _normalize_filter_text(exchange)
    if normalized_exchange:
        items = [item for item in items if item.exchange.lower() == normalized_exchange]

    normalized_industry = _normalize_filter_text(industry)
    if normalized_industry:
        items = [item for item in items if item.industry.lower() == normalized_industry]

    normalized_concept = _normalize_filter_text(concept)
    if normalized_concept:
        items = [item for item in items if any(value.lower() == normalized_concept for value in item.concepts)]

    normalized_tag = _normalize_filter_text(tag)
    if normalized_tag:
        items = [item for item in items if any(value.lower() == normalized_tag for value in item.tags)]

    normalized_recommendation = _normalize_filter_text(recommendation)
    if normalized_recommendation:
        items = [item for item in items if item.recommendation.lower() == normalized_recommendation]

    dividend_summary = _build_dividend_summary(items) if include_meta else None

    if dividend_only:
        items = [item for item in items if item.has_dividend]

    if dividend_years_min is not None:
        items = [item for item in items if item.has_dividend and item.dividend_years >= dividend_years_min]

    if dividend_yield_min is not None:
        items = [item for item in items if (item.dividend_yield or 0) >= dividend_yield_min]

    if ex_dividend_soon:
        items = [item for item in items if item.is_ex_dividend_soon]

    if market_cap_min is not None:
        items = [item for item in items if (item.market_cap or 0) >= market_cap_min]

    if market_cap_max is not None:
        items = [item for item in items if (item.market_cap or 0) <= market_cap_max]

    if price_min is not None:
        items = [item for item in items if item.price >= price_min]

    if price_max is not None:
        items = [item for item in items if item.price <= price_max]

    if pe_max is not None:
        items = [item for item in items if (item.pe or 0) <= pe_max]

    if net_profit_min is not None:
        items = [item for item in items if (item.net_profit or 0) >= net_profit_min]

    if revenue_min is not None:
        items = [item for item in items if (item.revenue or 0) >= revenue_min]

    if revenue_growth_min is not None:
        items = [item for item in items if (item.revenue_growth or 0) >= revenue_growth_min]

    if revenue_growth_qoq_min is not None:
        items = [item for item in items if (item.revenue_growth_qoq or 0) >= revenue_growth_qoq_min]

    if profit_growth_min is not None:
        items = [item for item in items if (item.profit_growth or 0) >= profit_growth_min]

    if profit_growth_qoq_min is not None:
        items = [item for item in items if (item.profit_growth_qoq or 0) >= profit_growth_qoq_min]

    if gross_margin_min is not None:
        items = [item for item in items if (item.gross_margin or 0) >= gross_margin_min]

    if net_margin_min is not None:
        items = [item for item in items if (item.net_margin or 0) >= net_margin_min]

    if roe_min is not None:
        items = [item for item in items if (item.roe or 0) >= roe_min]

    if debt_ratio_max is not None:
        items = [item for item in items if (item.debt_ratio or 0) <= debt_ratio_max]

    if exclude_st:
        items = [item for item in items if not item.is_st]

    if score_min is not None:
        items = [item for item in items if item.score >= score_min]

    if score_max is not None:
        items = [item for item in items if item.score <= score_max]

    if change_pct_min is not None:
        items = [item for item in items if item.change_pct >= change_pct_min]

    if change_pct_max is not None:
        items = [item for item in items if item.change_pct <= change_pct_max]

    if prev_limit_up or prev_limit_down:
        if prev_limit_up and prev_limit_down:
            items = [item for item in items if _is_prev_limit_up(item) or _is_prev_limit_down(item)]
        elif prev_limit_up:
            items = [item for item in items if _is_prev_limit_up(item)]
        elif prev_limit_down:
            items = [item for item in items if _is_prev_limit_down(item)]

    if sort_by == "change_pct":
        items.sort(key=lambda row: row.change_pct, reverse=True)
    elif sort_by == "price":
        items.sort(key=lambda row: row.price, reverse=True)
    elif sort_by == "dividend_years":
        items.sort(key=lambda row: (row.dividend_years, row.score, row.change_pct), reverse=True)
    elif sort_by == "dividend_yield":
        items.sort(key=lambda row: ((row.dividend_yield or 0), row.dividend_years, row.score), reverse=True)
    else:
        items.sort(key=lambda row: row.score, reverse=True)

    stats = _build_stock_list_stats(items) if include_meta else None

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
        industries=industries if include_meta else None,
        concepts=concepts if include_meta else None,
        tags=tags if include_meta else None,
        boards=boards if include_meta else None,
        exchanges=exchanges if include_meta else None,
        recommendations=recommendations if include_meta else None,
        stats=stats,
        dividend_summary=dividend_summary,
        last_synced_at=last_synced_at_text,
    )


def _sector_rotation_stage(
    avg_change_pct: float,
    relative_change_pct: float,
    breadth_ratio: float,
    buy_watch_ratio: float,
    avg_score: float,
) -> str:
    if relative_change_pct <= -1.2 and breadth_ratio < 0.42:
        return _ROTATION_STAGES[0]
    if relative_change_pct >= -0.2 and breadth_ratio >= 0.45 and buy_watch_ratio >= 0.35:
        return _ROTATION_STAGES[1]
    if relative_change_pct >= 0.8 and breadth_ratio >= 0.58 and avg_score >= 60:
        return _ROTATION_STAGES[2]
    if relative_change_pct >= 0.2 and breadth_ratio >= 0.48 and avg_score >= 55:
        return _ROTATION_STAGES[3]
    return _ROTATION_STAGES[4]



def _rotation_confidence(
    stock_count: int,
    breadth_ratio: float,
    buy_watch_ratio: float,
    avg_score: float,
    is_broad_theme: bool,
) -> int:
    sample_factor = min(1.0, stock_count / _ROTATION_STRONG_SAMPLE_SIZE)
    value = 34 + sample_factor * 28 + breadth_ratio * 15 + buy_watch_ratio * 10 + (avg_score - 55) * 0.45
    if is_broad_theme:
        value -= 10
    if stock_count < _ROTATION_MIN_SAMPLE_SIZE:
        value -= 12
    return _clamp_int(value, 18, 95)



def _build_sector_rotation_cache_key(market: Optional[str], top_n: int) -> str:
    return json.dumps(
        {
            "market": (market or "").strip(),
            "top_n": int(top_n),
        },
        ensure_ascii=False,
        sort_keys=True,
    )


def _get_cached_sector_rotation_summary(
    *,
    market: Optional[str],
    top_n: int,
    last_synced_at_text: Optional[str],
) -> Optional[SectorRotationResponse]:
    version = last_synced_at_text or "no_version"
    cache_key = _build_sector_rotation_cache_key(market, top_n)

    global _sector_rotation_cache_version, _sector_rotation_cache
    with _sector_rotation_cache_lock:
        if _sector_rotation_cache_version != version:
            _sector_rotation_cache_version = version
            _sector_rotation_cache = OrderedDict()

        cached = _sector_rotation_cache.get(cache_key)
        if cached is None:
            return None

        _sector_rotation_cache.move_to_end(cache_key)
        return cached


def _set_cached_sector_rotation_summary(
    *,
    market: Optional[str],
    top_n: int,
    last_synced_at_text: Optional[str],
    response: SectorRotationResponse,
) -> None:
    version = last_synced_at_text or "no_version"
    cache_key = _build_sector_rotation_cache_key(market, top_n)

    global _sector_rotation_cache_version, _sector_rotation_cache
    with _sector_rotation_cache_lock:
        if _sector_rotation_cache_version != version:
            _sector_rotation_cache_version = version
            _sector_rotation_cache = OrderedDict()

        _sector_rotation_cache[cache_key] = response
        _sector_rotation_cache.move_to_end(cache_key)
        while len(_sector_rotation_cache) > _SECTOR_ROTATION_CACHE_MAX:
            _sector_rotation_cache.popitem(last=False)




def get_sector_rotation_summary(db: Session, market: Optional[str] = None, top_n: int = 8) -> SectorRotationResponse:
    ensure_stock_universe(db)

    normalized_top_n = max(1, min(int(top_n), 15))
    last_synced_at_text = _serialize_dt(_get_last_synced_at(db))
    cached_response = _get_cached_sector_rotation_summary(
        market=market,
        top_n=normalized_top_n,
        last_synced_at_text=last_synced_at_text,
    )
    if cached_response is not None:
        return cached_response

    rows = _query_universe_rows(db, market=market)
    source = _get_stock_list_source(
        db,
        rows=rows,
        market=market,
        q=None,
        last_synced_at_text=last_synced_at_text,
    )
    items = list(source["items"])
    benchmark_change_pct = round(sum(item.change_pct for item in items) / len(items), 2) if items else 0.0
    concept_buckets: Dict[str, List[StockItem]] = {}
    for item in items:
        for concept in item.concepts:
            concept_buckets.setdefault(concept, []).append(item)

    concept_views: List[SectorConceptItem] = []
    for concept_name, group in concept_buckets.items():
        stock_count = len(group)
        if stock_count == 0:
            continue

        avg_change_pct = round(sum(value.change_pct for value in group) / stock_count, 2)
        relative_change_pct = round(avg_change_pct - benchmark_change_pct, 2)
        avg_score = round(sum(value.score for value in group) / stock_count, 1)
        buy_watch_count = sum(1 for value in group if value.recommendation in {"buy", "watch"})
        buy_watch_ratio = round(buy_watch_count / stock_count, 3)
        positive_count = sum(1 for value in group if value.change_pct >= 0)
        breadth_ratio = round(positive_count / stock_count, 3)
        leaders = sorted(group, key=lambda row: (row.score, row.change_pct), reverse=True)[:3]
        leader_avg_score = round(sum(value.score for value in leaders) / len(leaders), 1)
        leading_symbols = [value.symbol for value in leaders]
        is_broad_theme = concept_name in _BROAD_CONCEPTS
        confidence = _rotation_confidence(
            stock_count=stock_count,
            breadth_ratio=breadth_ratio,
            buy_watch_ratio=buy_watch_ratio,
            avg_score=avg_score,
            is_broad_theme=is_broad_theme,
        )

        heat_score = 44 + relative_change_pct * 8.8 + breadth_ratio * 21 + buy_watch_ratio * 26 + (avg_score - 55) * 0.8
        heat_score += (leader_avg_score - 55) * 0.18
        if is_broad_theme:
            heat_score -= 8
        if stock_count < _ROTATION_MIN_SAMPLE_SIZE:
            heat_score -= 14
        heat_score = round(max(0.0, min(100.0, heat_score)), 1)

        warnings: List[str] = []
        if stock_count < _ROTATION_MIN_SAMPLE_SIZE:
            warnings.append(f"样本数仅 {stock_count}，容易被个股波动放大。")
        if is_broad_theme:
            warnings.append("该概念粒度较粗，更适合作为观察方向，不宜直接用于交易触发。")
        if breadth_ratio < 0.45:
            warnings.append("板块内部上涨家数占比偏低，扩散性仍待确认。")

        concept_views.append(
            SectorConceptItem(
                name=concept_name,
                stock_count=stock_count,
                avg_change_pct=avg_change_pct,
                relative_change_pct=relative_change_pct,
                avg_score=avg_score,
                buy_watch_ratio=buy_watch_ratio,
                breadth_ratio=breadth_ratio,
                leader_avg_score=leader_avg_score,
                heat_score=heat_score,
                confidence=confidence,
                is_broad_theme=is_broad_theme,
                leading_symbols=leading_symbols,
                rotation_stage=_sector_rotation_stage(
                    avg_change_pct=avg_change_pct,
                    relative_change_pct=relative_change_pct,
                    breadth_ratio=breadth_ratio,
                    buy_watch_ratio=buy_watch_ratio,
                    avg_score=avg_score,
                ),
                warnings=warnings,
            )
        )

    concept_views.sort(key=lambda value: (value.confidence, value.heat_score, value.relative_change_pct, value.avg_score), reverse=True)
    eligible_views = [
        value
        for value in concept_views
        if value.stock_count >= _ROTATION_MIN_SAMPLE_SIZE and (not value.is_broad_theme or value.confidence >= 68)
    ]
    ranked_views = eligible_views or concept_views
    current_hot = ranked_views[:normalized_top_n]

    next_potential: Optional[SectorConceptItem] = None
    for candidate in ranked_views:
        if candidate.rotation_stage in {"启动", "修复"} and candidate.relative_change_pct >= -0.3 and candidate.confidence >= 58:
            next_potential = candidate
            break
    if next_potential is None and current_hot:
        next_potential = current_hot[0]

    rotation_path = [value.name for value in current_hot[:5]]
    reasoning: List[str] = []
    risk_warnings: List[str] = []
    if next_potential is not None:
        reasoning = [
            f"{next_potential.name} 当前阶段为“{next_potential.rotation_stage}”，样本数 {next_potential.stock_count}，轮动置信度 {next_potential.confidence}/100。",
            f"相对全市场平均涨跌幅强 {next_potential.relative_change_pct:+.2f}%，板块内上涨占比 {next_potential.breadth_ratio * 100:.1f}%，扩散性开始改善。",
            f"平均评分 {next_potential.avg_score:.1f}、买入/观察占比 {next_potential.buy_watch_ratio * 100:.1f}%，龙头得分均值 {next_potential.leader_avg_score:.1f}。",
        ]
        if next_potential.warnings:
            reasoning.extend([f"注意：{warning}" for warning in next_potential.warnings[:2]])

    if current_hot:
        risk_warnings.append(f"当前最热方向为 {current_hot[0].name}，若板块扩散率下降或龙头掉队，容易转入高位分歧。")
    risk_warnings.append("轮动模型已加入样本门槛与广谱概念降权，但仍属于启发式研究工具，不构成投资建议。")

    response = SectorRotationResponse(
        generated_at=datetime.now(timezone.utc).isoformat(),
        market_scope=market or "全市场",
        benchmark_change_pct=benchmark_change_pct,
        methodology=[
            "先按概念板块聚合，再计算相对全市场涨跌幅、上涨家数占比、买入/观察占比、龙头均分。",
            "默认弱化样本数过少或概念粒度过粗的板块，避免单只股票主导结论。",
            "下一潜力板块优先选择处于“修复/启动”阶段且置信度达标的方向。",
        ],
        sample_policy=f"默认优先展示样本数 >= {_ROTATION_MIN_SAMPLE_SIZE} 的概念板块；广谱概念会被降权处理。",
        total_sectors=len(concept_views),
        current_hot_sectors=current_hot,
        next_potential_sector=next_potential,
        rotation_path=rotation_path,
        reasoning=reasoning,
        risk_warnings=risk_warnings,
    )
    _set_cached_sector_rotation_summary(
        market=market,
        top_n=normalized_top_n,
        last_synced_at_text=last_synced_at_text,
        response=response,
    )
    return response


def get_stock_detail(db: Session, symbol: str) -> Optional[StockDetail]:
    ensure_stock_universe(db)

    row = _resolve_stock_row(db, symbol)
    if row is None:
        return None

    realtime_quote = _fetch_realtime_quote_for_row(row)
    base_detail = _build_stock_detail_from_row(row, realtime_quote=realtime_quote)
    enrichment = get_stock_enrichment(db=db, symbol=row.symbol)
    detail = base_detail if enrichment is None else merge_stock_detail_with_enrichment(base_detail=base_detail, enrichment=enrichment)

    if enrichment is None or is_placeholder_company_website(detail.company_website):
        transient_enrichment = build_transient_enrichment_from_row(row)
        if transient_enrichment is not None:
            detail = merge_stock_detail_with_enrichment(base_detail=detail, enrichment=transient_enrichment)

    detail = _decorate_company_profile(detail)

    return detail.model_copy(update={"data_quality": _build_data_quality(row=row, enrichment=enrichment, realtime_quote=realtime_quote)})


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


def _qa_recommendation_label(value: str) -> str:
    mapping = {
        "buy": "关注买入",
        "watch": "继续观察",
        "hold_cautious": "谨慎持有",
        "avoid": "暂时回避",
    }
    return mapping.get(value, value)


def _qa_risk_label(value: str) -> str:
    mapping = {
        "low": "低风险",
        "medium": "中风险",
        "high": "高风险",
    }
    return mapping.get(value, value)


def _contains_cjk(text: str) -> bool:
    return any("一" <= char <= "鿿" for char in str(text or ""))


def _qa_last_user_topic(history: Optional[List[Dict[str, str]]]) -> Optional[str]:
    if not history:
        return None
    for item in reversed(history):
        if not isinstance(item, dict):
            continue
        if str(item.get("role") or "") != "user":
            continue
        content = str(item.get("content") or "").strip()
        if not content:
            continue
        topic = _qa_topic(content)
        if topic != "summary":
            return topic
    return None


def _qa_preferred_products(detail: StockDetail) -> List[str]:
    products = [item for item in detail.products_services if _contains_cjk(item)]
    if products:
        return products[:3]
    tags = [item for item in detail.business_tags if _contains_cjk(item) and item not in {detail.market, detail.board, detail.exchange}]
    if tags:
        return tags[:3]
    return ["核心产品与服务"]


def _qa_preferred_business_scope(detail: StockDetail) -> List[str]:
    scope: List[str] = []
    for item in detail.business_scope:
        if not _contains_cjk(item):
            continue
        if item.startswith("核心产品与服务包括："):
            continue
        scope.append(item)
    if scope:
        return scope[:2]
    if _contains_cjk(detail.main_business):
        return [detail.main_business]
    return [
        f"公司围绕 {detail.sector} 方向开展主营业务，并持续推进产品、渠道与服务体系建设。",
        f"当前重点观察盈利能力、产品迭代、市场拓展与经营执行效率。",
    ]


def _qa_company_summary(detail: StockDetail) -> str:
    business_scope = "；".join(_qa_preferred_business_scope(detail))
    market_scope = "、".join(detail.market_coverage[:3]) if detail.market_coverage else detail.market
    product_scope = "、".join(_qa_preferred_products(detail))
    positioning_text = f"公司当前主要定位在 {detail.sector} 方向，处于 {detail.market} / {detail.board} 板块。"
    return (
        f"{detail.name} 当前可概括为：{positioning_text}"
        f"业务上重点围绕 {product_scope} 展开，主要覆盖 {market_scope}。"
        f"进一步看，{business_scope}"
    )


def _qa_company_references(detail: StockDetail) -> List[str]:
    references: List[str] = []
    if detail.company_website:
        references.append(f"官网：{detail.company_website}")
    if detail.investor_relations_url:
        references.append(f"投资者关系：{detail.investor_relations_url}")
    if detail.exchange_profile_url:
        references.append(f"交易所资料：{detail.exchange_profile_url}")
    return references


def _qa_should_use_web_search(question: str) -> bool:
    return bool(str(question or "").strip())


def _qa_build_search_query(detail: StockDetail, question: str, topic: str) -> str:
    base = f"{detail.name} {detail.symbol}"
    if topic == "company":
        return f"{base} 官网 主营业务 公司介绍 {question}"
    if topic == "valuation":
        return f"{base} 估值 市盈率 财报 {question}"
    if topic == "fundamental":
        return f"{base} 财报 营收 利润 业绩 {question}"
    if topic == "dividend":
        return f"{base} 分红 派息 除权 公告 {question}"
    if topic == "event":
        return f"{base} 最新 公告 新闻 财报 {question}"
    if topic == "risk":
        return f"{base} 风险 公告 新闻 问询 {question}"
    if topic == "trading":
        return f"{base} 板块 新闻 公告 走势 {question}"
    return f"{base} 最新 新闻 公告 {question}"


def _qa_rank_web_search_results(detail: StockDetail, question: str, results: List[WebSearchResult]) -> List[WebSearchResult]:
    official_domain = urlparse(detail.company_website).netloc.lower().replace("www.", "") if detail.company_website else ""
    website_requested = any(keyword in question for keyword in ["官网", "网址", "网站"])
    latest_requested = any(keyword in question for keyword in ["最新", "最近", "今天", "公告", "新闻", "财报"])

    def score(result: WebSearchResult) -> int:
        value = 0
        domain = urlparse(result.url).netloc.lower().replace("www.", "")
        joined = f"{result.title} {result.snippet}"
        if official_domain and official_domain and official_domain in domain:
            value += 20
        if detail.name in joined:
            value += 8
        if website_requested and any(keyword in joined for keyword in ["官网", "官方网站"]):
            value += 10
        if latest_requested and any(keyword in joined for keyword in ["公告", "财报", "新闻", "季报", "年报", "中报"]):
            value += 8
        if detail.symbol.split(".")[0] in joined:
            value += 4
        return value

    return sorted(results, key=score, reverse=True)


def _qa_merge_web_search(
    *,
    question: str,
    topic: str,
    detail: StockDetail,
    answer: str,
    bullets: List[str],
    references: List[str],
    confidence: int,
    search_results: List[WebSearchResult],
) -> Tuple[str, List[str], List[str], int]:
    if not search_results:
        if any(keyword in question for keyword in ["最新", "最近", "今天", "公告", "新闻", "财报", "官网", "网站", "网址"]):
            bullets.append("本次未检索到稳定的联网结果，建议稍后重试或换更具体的问题。")
            confidence = max(35, confidence - 8)
        return answer, bullets, references, confidence

    ranked_results = _qa_rank_web_search_results(detail, question, search_results)
    top_results = ranked_results[: min(3, len(ranked_results))]
    top_result = top_results[0]

    if topic == "company" and any(keyword in question for keyword in ["官网", "网址", "网站"]):
        answer = f"{answer} 联网检索结果也指向：{top_result.title}（{top_result.url}）。"
    elif topic in {"event", "summary", "risk", "fundamental", "valuation", "dividend", "trading"}:
        answer = f"{answer} 我已联网补充检索到近端网页信息，可结合下方检索依据交叉验证。"

    for item in top_results:
        snippet = item.snippet or "未返回摘要"
        bullets.append(f"联网检索：{item.title} —— {snippet}")
        references.append(f"联网检索：{item.title} | {item.url}")

    confidence = min(95, confidence + 3)
    return answer, bullets, references, confidence


def _qa_topic(question: str) -> str:
    text = question.lower().strip()
    if any(keyword in text for keyword in ["估值", "市盈率", "pe", "pb", "高估", "低估", "贵", "便宜", "市值"]):
        return "valuation"
    if any(keyword in text for keyword in ["营收", "收入", "利润", "增长", "毛利", "净利", "roe", "业绩", "财报"]):
        return "fundamental"
    if any(keyword in text for keyword in ["风险", "负债", "波动", "回撤", "不确定", "下跌", "雷"]):
        return "risk"
    if any(keyword in text for keyword in ["买", "卖", "加仓", "减仓", "仓位", "止损", "止盈", "进场", "交易", "短线", "长期"]):
        return "trading"
    if any(keyword in text for keyword in ["分红", "股息", "派息", "除权"]):
        return "dividend"
    if any(keyword in text for keyword in ["官网", "网址", "网站", "主营", "公司", "业务", "产品", "介绍", "赛道", "做什么"]):
        return "company"
    if any(keyword in text for keyword in ["事件", "催化", "公告", "进展", "跟踪"]):
        return "event"
    return "summary"


def _qa_build_response(
    *,
    question: str,
    detail: StockDetail,
    analysis: StockAnalysis,
    history: Optional[List[Dict[str, str]]] = None,
) -> StockQAResponse:
    topic = _qa_topic(question)
    recommendation_label = _qa_recommendation_label(analysis.recommendation)
    risk_label = _qa_risk_label(analysis.risk_level)

    peer_pe_values = [item.pe for item in detail.peer_companies if item.pe > 0]
    peer_pe_avg = round(sum(peer_pe_values) / len(peer_pe_values), 1) if peer_pe_values else None

    lead_prefix = ""
    if history:
        normalized_history = [str(item.get("content", "")).strip() for item in history if isinstance(item, dict)]
        normalized_history = [item for item in normalized_history if item]
        if normalized_history and question.strip().startswith(("那", "再", "还", "然后", "这个", "它", "那它")):
            lead_prefix = "结合你上一轮问题，"
            last_topic = _qa_last_user_topic(history)
            if topic == "summary" and last_topic is not None:
                topic = last_topic

    answer = (
        f"{lead_prefix}{detail.name} 当前模型评分 {analysis.score}/99，建议“{recommendation_label}”，风险等级“{risk_label}”。"
        "如需可执行决策，请优先结合仓位约束与止损纪律。"
    )
    bullets: List[str] = [
        f"综合结论：{analysis.summary}",
        f"交易计划参考：入场 {analysis.trade_plan.entry_range}，止损 {analysis.trade_plan.stop_loss}，止盈 {analysis.trade_plan.take_profit}。",
        f"数据可信度：{detail.data_quality.reliability_score}/100（覆盖率 {detail.data_quality.coverage_score:.1f}%）。",
    ]
    follow_ups = [
        "这只股票未来30-60天最关键的跟踪指标是什么？",
        "如果我要分批建仓，仓位和止损怎么设置更稳妥？",
        "相比同行，它最大的优势和短板分别是什么？",
    ]

    if topic == "valuation":
        if detail.pe <= 18 and detail.roe >= 12:
            valuation_view = "估值偏低到合理"
        elif detail.pe <= 35:
            valuation_view = "估值大致中性"
        else:
            valuation_view = "估值偏高"
        peer_text = f"同行平均PE约 {peer_pe_avg:.1f}" if peer_pe_avg is not None else "同行PE样本不足"
        answer = (
            f"{lead_prefix}从估值角度看，{detail.name} 当前 PE {detail.pe:.1f}、PB {detail.pb:.2f}，属于“{valuation_view}”。"
            f"{peer_text}，结合 ROE {detail.roe:.1f}% 与利润增速 {detail.profit_growth:+.1f}%，建议把估值和盈利趋势一起看。"
        )
        bullets = [
            f"估值位置：PE {detail.pe:.1f} / PB {detail.pb:.2f} / 总市值约 {detail.market_cap:.1f} 亿。",
            f"盈利支撑：ROE {detail.roe:.1f}%、营收增速 {detail.revenue_growth:+.1f}%、利润增速 {detail.profit_growth:+.1f}%。",
            f"相对比较：{peer_text}。",
        ]
        follow_ups = [
            "当前估值对应的安全边际大概有多少？",
            "如果盈利不及预期，估值可能压缩到什么区间？",
            "和最接近的同行相比，应该看哪些估值差异？",
        ]
    elif topic == "fundamental":
        answer = (
            f"{lead_prefix}从基本面看，{detail.name} 目前营收增速 {detail.revenue_growth:+.1f}%，利润增速 {detail.profit_growth:+.1f}%，"
            f"ROE {detail.roe:.1f}%，资产负债率 {detail.debt_ratio:.1f}%。整体盈利质量处于"
            f"{'较强' if detail.roe >= 15 and detail.profit_growth >= 10 else '中等'}水平。"
        )
        bullets = [
            f"增长：营收 {detail.revenue_growth:+.1f}% / 利润 {detail.profit_growth:+.1f}%。",
            f"质量：ROE {detail.roe:.1f}% / 负债率 {detail.debt_ratio:.1f}%。",
            f"现金流与报表：最近财报日 {detail.last_report_date}，建议重点看经营现金流与毛利率变化。",
        ]
        follow_ups = [
            "最近三年财报里，哪一项指标改善最明显？",
            "盈利增速能否持续，主要看哪两个先行指标？",
            "这只股票的财报风险点有哪些？",
        ]
    elif topic == "risk":
        answer = (
            f"{lead_prefix}风险维度上，{detail.name} 波动率 {detail.volatility:.1f}%、资产负债率 {detail.debt_ratio:.1f}%，"
            f"模型风险等级为“{risk_label}”。若短线交易，建议优先执行 {analysis.trade_plan.stop_loss} 的止损纪律。"
        )
        bullets = [
            f"价格风险：当前支撑位 {detail.support_price:.2f}，压力位 {detail.resistance_price:.2f}。",
            f"经营风险：{detail.key_risks[0] if detail.key_risks else '需重点跟踪订单、现金流与行业景气波动。'}",
            f"执行建议：单票仓位控制 + 预设止损，避免高波动阶段放大回撤。",
        ]
        follow_ups = [
            "如果跌破支撑位，下一步该怎么处理仓位？",
            "这只股票最需要防范的黑天鹅是什么？",
            "怎么设置更稳健的止损和止盈比？",
        ]
    elif topic == "trading":
        answer = (
            f"{lead_prefix}交易上可参考模型计划：入场区间 {analysis.trade_plan.entry_range}，止损 {analysis.trade_plan.stop_loss}，"
            f"第一目标 {analysis.trade_plan.take_profit}。当前建议“{recommendation_label}”，更适合分批执行而非一次性重仓。"
        )
        bullets = [
            f"位置判断：支撑 {detail.support_price:.2f} / 压力 {detail.resistance_price:.2f} / 动量 {detail.momentum:+.1f}%。",
            f"仓位建议：{analysis.trade_plan.position_advice}",
            "执行纪律：先定义失败条件，再定义盈利目标，避免情绪化加减仓。",
        ]
        follow_ups = [
            "给我一个分三笔建仓的执行方案。",
            "短线和中线分别应该看哪些触发信号？",
            "如果放量突破压力位，怎样调整止盈策略？",
        ]
    elif topic == "dividend":
        has_dividend_records = len(detail.dividend_history) > 0
        latest_dividend = detail.dividend_history[0] if has_dividend_records else None
        if latest_dividend is not None and detail.price > 0:
            est_yield = latest_dividend.cash_dividend_per_share / detail.price * 100
            answer = (
                f"{lead_prefix}{detail.name} 存在分红记录，最近每股分红约 {latest_dividend.cash_dividend_per_share:.2f} 元，"
                f"按当前价格粗算股息率约 {est_yield:.2f}%。分红策略可作为防守因子，但仍需结合盈利与现金流稳定性。"
            )
            bullets = [
                f"最近分红：{latest_dividend.year}，每股分红 {latest_dividend.cash_dividend_per_share:.2f} 元。",
                f"最近除权日：{latest_dividend.ex_dividend_date}",
                "观察重点：分红率变化、经营现金流质量、未来利润增速是否支持持续分红。",
            ]
        else:
            answer = f"{lead_prefix}{detail.name} 当前分红历史样本较少，暂不建议只凭股息逻辑交易，优先看盈利增长与估值匹配度。"
            bullets = [
                "分红数据覆盖不足，需结合公司公告进一步核验。",
                f"当前替代观察：ROE {detail.roe:.1f}%、利润增速 {detail.profit_growth:+.1f}%、负债率 {detail.debt_ratio:.1f}%。",
                "可先将分红作为加分项，而不是单一决策依据。",
            ]
        follow_ups = [
            "它的分红可持续性如何判断？",
            "分红率上升是利好还是透支未来增长？",
            "除权前后适合怎样做交易计划？",
        ]
    elif topic == "event":
        answer = (
            f"{lead_prefix}{detail.name} 当前更值得跟踪的事件主要集中在财报、分红/回购、行业政策和订单进展。"
            f"结合当前模型，最近优先看：{detail.recent_events[0] if detail.recent_events else '财报与经营进展'}。"
        )
        bullets = [
            f"近期事件：{detail.recent_events[0] if detail.recent_events else '建议优先跟踪财报披露、重大合同和政策变化。'}",
            f"潜在催化：{detail.catalyst_events[0] if detail.catalyst_events else '关注业绩兑现、产品放量和行业景气回升。'}",
            f"风险提醒：{detail.key_risks[0] if detail.key_risks else '若财报、订单或政策低于预期，短期波动会明显放大。'}",
        ]
        follow_ups = [
            "未来1-2个季度最重要的催化剂是什么？",
            "哪些公告出现时需要提高警惕？",
            "如果事件兑现不及预期，股价通常先看什么指标？",
        ]
    elif topic == "company":
        website_requested = any(keyword in question for keyword in ["官网", "网址", "网站"])
        answer = _qa_company_summary(detail)
        if website_requested and detail.company_website:
            answer = f"{lead_prefix}{answer} 官方网站是 {detail.company_website}。"
        else:
            answer = f"{lead_prefix}{answer}"
        bullets = [
            f"公司定位：公司当前主要定位在 {detail.sector} 方向，处于 {detail.market} / {detail.board} 板块。",
            f"业务范围：{_qa_preferred_business_scope(detail)[0]}",
            f"覆盖市场：{'、'.join(detail.market_coverage[:4]) if detail.market_coverage else detail.market}",
            f"公司亮点：{detail.company_highlights[0] if detail.company_highlights else '建议继续结合盈利质量、产品迭代和行业地位一起看。'}",
            f"重点产品/服务：{'、'.join(_qa_preferred_products(detail))}",
        ]
        if detail.company_website:
            bullets.append(f"官网：{detail.company_website}")
        follow_ups = [
            "这家公司核心竞争壁垒是什么？",
            "它的主营业务里哪一块最值得重点跟踪？",
            "和同行比，它最大的优势和劣势是什么？",
        ]

    confidence_raw = round(analysis.confidence * 0.65 + detail.data_quality.reliability_score * 0.35)
    if len(question.strip()) <= 4:
        confidence_raw -= 8
    if topic == "dividend" and not detail.dividend_history:
        confidence_raw -= 10
    confidence = max(35, min(95, int(confidence_raw)))

    references = [
        f"评分 {analysis.score}/99，建议 {recommendation_label}，风险 {risk_label}",
        f"当前价 {detail.price:.2f} {detail.currency}，涨跌幅 {detail.change_pct:+.2f}%",
        f"PE {detail.pe:.1f} / PB {detail.pb:.2f} / ROE {detail.roe:.1f}% / 负债率 {detail.debt_ratio:.1f}%",
        f"营收增速 {detail.revenue_growth:+.1f}% / 利润增速 {detail.profit_growth:+.1f}%",
        f"支撑 {detail.support_price:.2f} / 压力 {detail.resistance_price:.2f} / 最近财报 {detail.last_report_date}",
    ] + _qa_company_references(detail)

    search_used = False
    search_query = None
    search_result_count = 0
    settings = get_settings()
    if settings.qa_enable_web_search and _qa_should_use_web_search(question):
        search_query = _qa_build_search_query(detail, question, topic)
        try:
            search_results = search_web(
                search_query,
                max_results=settings.qa_web_search_max_results,
                timeout=settings.qa_web_search_timeout_seconds,
            )
        except Exception as exc:
            logger.info("qa web search failed for %s: %s", detail.symbol, exc)
            search_results = []

        search_result_count = len(search_results)
        if search_results:
            search_used = True
        answer, bullets, references, confidence = _qa_merge_web_search(
            question=question,
            topic=topic,
            detail=detail,
            answer=answer,
            bullets=bullets,
            references=references,
            confidence=confidence,
            search_results=search_results,
        )

    disclaimer = "该问答基于当前平台数据自动生成，仅供研究参考，不构成投资建议。"
    if search_used:
        disclaimer = "该问答已联网检索公开网页并结合平台数据生成，仅供研究参考，不构成投资建议；对新闻、公告、官网等信息请以原始页面为准。"

    return StockQAResponse(
        symbol=detail.symbol,
        question=question.strip(),
        answer=answer,
        confidence=confidence,
        bullets=bullets,
        references=references,
        follow_up_questions=follow_ups,
        disclaimer=disclaimer,
        generated_at=_utc_now().isoformat(),
        search_used=search_used,
        search_query=search_query,
        search_result_count=search_result_count,
    )


def ask_stock_question(
    db: Session,
    symbol: str,
    question: str,
    history: Optional[List[Dict[str, str]]] = None,
) -> Optional[StockQAResponse]:
    snapshot = get_stock_snapshot(db, symbol)
    if snapshot is None:
        return None
    return _qa_build_response(question=question, detail=snapshot.detail, analysis=snapshot.analysis, history=history)


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
