import json
import logging
import math
import re
import time
from urllib.parse import urlparse
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple, Type, TypeVar

from sqlalchemy import func
from sqlalchemy.exc import OperationalError, PendingRollbackError
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models.stock_enrichment import StockEnrichment
from app.models.stock_universe import StockUniverse
from app.schemas.stock import (
    DividendRecord,
    FinancialReport,
    PeerCompany,
    ShareholderRecord,
    StockDetail,
    StockEnrichResponse,
    StockEnrichStatusResponse,
    ValuationHistoryPoint,
)

logger = logging.getLogger("stock_assistant.enrichment_service")

_YF_CALL_GAP_SECONDS = 0.06
_ENRICH_STALE_SECONDS = 7 * 24 * 60 * 60
_PLACEHOLDER_WEBSITE_DOMAINS = {"www.cninfo.com.cn", "www.hkex.com.hk", "www.nasdaq.com"}

T = TypeVar("T")


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

    if isinstance(value, (int, float)):
        if math.isnan(float(value)):
            return None
        return float(value)

    text = str(value).strip().replace(",", "")
    if text in {"", "--", "None", "nan", "NaN"}:
        return None

    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def _safe_int(value: Any) -> Optional[int]:
    parsed = _safe_float(value)
    if parsed is None:
        return None
    try:
        return int(parsed)
    except (TypeError, ValueError):
        return None


def _first_non_empty_text(*values: Any) -> Optional[str]:
    for value in values:
        text = str(value or "").strip()
        if text and text.lower() not in {"nan", "none", "null", "--"}:
            return text
    return None


def _normalize_url(url: Optional[str]) -> Optional[str]:
    if url is None:
        return None

    text = str(url).strip().strip("'\"；;，,")
    if not text:
        return None

    match = re.search(r'https?://[^\s\'"<>]+', text, flags=re.I)
    if match:
        text = match.group(0)
    else:
        candidate = re.split(r"[\s,，;；]+", text, maxsplit=1)[0].strip()
        if candidate.startswith("//"):
            text = f"https:{candidate}"
        elif candidate.startswith(("http://", "https://")):
            text = candidate
        elif candidate.startswith("www."):
            text = f"https://{candidate}"
        elif re.match(r"^[A-Za-z0-9.-]+\.[A-Za-z]{2,}(/.*)?$", candidate):
            text = f"https://{candidate}"
        else:
            return None

    parsed = urlparse(text)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    if any(char in parsed.netloc for char in [" ", "<", ">", "\"", "'"]):
        return None
    normalized = f"{parsed.scheme}://{parsed.netloc}{parsed.path or ''}"
    if parsed.query:
        normalized = f"{normalized}?{parsed.query}"
    return normalized.rstrip('/')


def _frame_first_record_to_dict(frame: Any) -> Dict[str, Any]:
    if frame is None or getattr(frame, "empty", True):
        return {}
    try:
        record = frame.iloc[0].to_dict()
    except Exception:
        return {}
    output: Dict[str, Any] = {}
    for key, value in record.items():
        text = _first_non_empty_text(value)
        if text is not None:
            output[str(key).strip()] = text
    return output


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _json_loads_list(value: Optional[str]) -> List[Any]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    if isinstance(parsed, list):
        return parsed
    return []


def _parse_model_list(raw: List[Any], model_cls: Type[T]) -> List[T]:
    items: List[T] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        try:
            items.append(model_cls(**entry))
        except Exception:
            continue
    return items


def _split_symbol(symbol: str) -> Tuple[str, str]:
    if "." in symbol:
        code, suffix = symbol.split(".", 1)
        return code, suffix.upper()
    return symbol, ""


def _to_yfinance_ticker(symbol: str) -> Optional[str]:
    code, suffix = _split_symbol(symbol)
    if suffix == "SH":
        return f"{code}.SS"
    if suffix == "SZ":
        return f"{code}.SZ"
    if suffix == "BJ":
        return f"{code}.BJ"
    if suffix == "HK":
        digits = re.sub(r"\D", "", code)
        if not digits:
            return None
        normalized = f"{int(digits):04d}"
        return f"{normalized}.HK"
    if suffix == "US":
        normalized = code.strip().upper()
        return normalized or None
    return None


def _to_yfinance_ticker_candidates(symbol: str) -> List[str]:
    primary = _to_yfinance_ticker(symbol)
    if not primary:
        return []

    code, suffix = _split_symbol(symbol)
    if suffix != "HK":
        return [primary]

    digits = re.sub(r"\D", "", code)
    if not digits:
        return [primary]

    candidates = [primary]
    candidates.append(f"{digits.zfill(5)}.HK")

    deduped: List[str] = []
    for item in candidates:
        if item not in deduped:
            deduped.append(item)
    return deduped


def _frame_has_data(value: Any) -> bool:
    if value is None:
        return False
    empty_attr = getattr(value, "empty", None)
    if empty_attr is None:
        return bool(value)
    return not bool(empty_attr)


def _quote_url(symbol: str) -> str:
    code, suffix = _split_symbol(symbol)
    if suffix in {"SH", "SZ", "BJ"}:
        return f"https://quote.eastmoney.com/{suffix.lower()}{code}.html"
    if suffix == "HK":
        return f"https://quote.eastmoney.com/hk/{code}.html"
    if suffix == "US":
        return f"https://finance.yahoo.com/quote/{code}"
    return "https://quote.eastmoney.com"


def _exchange_profile_url(symbol: str) -> str:
    code, suffix = _split_symbol(symbol)
    if suffix == "HK":
        return "https://www.hkex.com.hk/Market-Data/Securities-Prices/Equities?sc_lang=en"
    if suffix == "US":
        return f"https://www.nasdaq.com/market-activity/stocks/{code.lower()}"
    return f"http://www.cninfo.com.cn/new/disclosure/stock?stockCode={code}"


def _default_headquarters(exchange: str) -> str:
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
    return city_map.get(exchange, "中国")


def _parse_date_like(value: Any) -> Optional[str]:
    if value is None:
        return None

    text = str(value).strip()
    if not text:
        return None

    text = text.replace("/", "-").replace(".", "-")
    if re.fullmatch(r"\d{8}", text):
        return f"{text[:4]}-{text[4:6]}-{text[6:8]}"
    if re.fullmatch(r"\d{4}-\d{1,2}-\d{1,2}", text):
        yyyy, mm, dd = text.split("-")
        return f"{int(yyyy):04d}-{int(mm):02d}-{int(dd):02d}"

    return text


def _to_yi(amount: Optional[float]) -> Optional[float]:
    if amount is None:
        return None

    value = float(amount)
    if abs(value) >= 1_000_000:
        return round(value / 100_000_000, 2)

    return round(value, 2)


def _df_get_value(dataframe, labels: List[str], column) -> Optional[float]:
    if dataframe is None:
        return None
    try:
        index_values = list(dataframe.index)
    except Exception:
        return None

    for label in labels:
        if label in index_values:
            try:
                return _safe_float(dataframe.at[label, column])
            except Exception:
                continue

    return None


def _build_financial_reports_from_yf(
    financials,
    balance_sheet,
    cashflow,
    dividends,
    current_close: Optional[float],
    report_url: str,
) -> List[Dict[str, Any]]:
    if financials is None:
        return []

    try:
        if financials.empty:
            return []
        columns = list(financials.columns)
    except Exception:
        return []

    records: List[Dict[str, Any]] = []

    for col in columns[:6]:
        year = str(getattr(col, "year", "")) or str(col)[:4]
        if len(year) < 4:
            continue

        revenue = _df_get_value(financials, ["Total Revenue", "Revenue"], col)
        net_profit = _df_get_value(financials, ["Net Income", "Net Income Common Stockholders"], col)
        gross_profit = _df_get_value(financials, ["Gross Profit"], col)
        equity = _df_get_value(balance_sheet, ["Stockholders Equity", "Total Equity Gross Minority Interest", "Total Equity"], col)
        total_assets = _df_get_value(balance_sheet, ["Total Assets"], col)
        total_debt = _df_get_value(balance_sheet, ["Total Debt", "Total Liabilities Net Minority Interest"], col)
        operating_cashflow = _df_get_value(cashflow, ["Operating Cash Flow", "Total Cash From Operating Activities"], col)
        eps = _df_get_value(financials, ["Diluted EPS", "Basic EPS"], col)

        gross_margin = None
        net_margin = None
        roe = None
        debt_ratio = None

        if revenue and abs(revenue) > 1:
            if gross_profit is not None:
                gross_margin = round(gross_profit / revenue * 100, 2)
            if net_profit is not None:
                net_margin = round(net_profit / revenue * 100, 2)

        if net_profit is not None and equity and abs(equity) > 1:
            roe = round(net_profit / equity * 100, 2)

        if total_debt is not None and total_assets and abs(total_assets) > 1:
            debt_ratio = round(total_debt / total_assets * 100, 2)

        dividend_yield = None
        if current_close and current_close > 0 and dividends is not None:
            try:
                annual_div = float(dividends[dividends.index.year == int(year)].sum())
                dividend_yield = round(annual_div / current_close * 100, 2)
            except Exception:
                dividend_yield = None

        if revenue is None and net_profit is None and eps is None:
            continue

        records.append(
            {
                "year": year,
                "revenue": _to_yi(revenue) or 0.0,
                "net_profit": _to_yi(net_profit) or 0.0,
                "gross_margin": gross_margin or 0.0,
                "net_margin": net_margin or 0.0,
                "roe": roe or 0.0,
                "debt_ratio": debt_ratio or 0.0,
                "operating_cashflow": _to_yi(operating_cashflow) or 0.0,
                "eps": round(eps, 3) if eps is not None else 0.0,
                "dividend_yield": dividend_yield or 0.0,
                "report_url": f"{report_url}#year={year}",
            }
        )

    records.sort(key=lambda item: item["year"], reverse=True)
    return records


def _build_valuation_history_from_yf(history, info: Dict[str, Any]) -> List[Dict[str, Any]]:
    if history is None:
        return []

    try:
        if history.empty:
            return []
        close_series = history["Close"].dropna()
    except Exception:
        return []

    if close_series.empty:
        return []

    try:
        yearly_close = close_series.groupby(close_series.index.year).last()
    except Exception:
        return []

    if yearly_close.empty:
        return []

    yearly_close = yearly_close.tail(6)

    current_close = _safe_float(close_series.iloc[-1]) or 0.0
    current_pe = _safe_float(info.get("trailingPE")) or _safe_float(info.get("forwardPE")) or 18.0
    current_pb = _safe_float(info.get("priceToBook")) or 2.2
    current_market_cap = _safe_float(info.get("marketCap"))

    rows: List[Dict[str, Any]] = []
    for year, close in yearly_close.items():
        close_value = _safe_float(close)
        if close_value is None or close_value <= 0:
            continue

        ratio = close_value / current_close if current_close > 0 else 1.0
        pe = round(max(3.0, current_pe * ratio), 2)
        pb = round(max(0.3, current_pb * ratio), 2)

        market_cap_yi = None
        if current_market_cap is not None:
            market_cap_yi = _to_yi(current_market_cap * ratio)

        rows.append(
            {
                "year": str(year),
                "pe": pe,
                "pb": pb,
                "market_cap": market_cap_yi if market_cap_yi is not None else 0.0,
            }
        )

    rows.sort(key=lambda item: item["year"], reverse=True)
    return rows


def _build_dividend_history_from_yf(dividends) -> List[Dict[str, Any]]:
    if dividends is None:
        return []

    try:
        if dividends.empty:
            return []
        grouped = dividends.groupby(dividends.index.year)
    except Exception:
        return []

    records: List[Dict[str, Any]] = []
    years = sorted(grouped.groups.keys(), reverse=True)[:5]

    for year in years:
        try:
            series = grouped.get_group(year)
            total_div = float(series.sum())
            ex_date = str(series.index.max().date())
        except Exception:
            continue

        records.append(
            {
                "year": str(year),
                "cash_dividend_per_share": round(total_div, 4),
                "payout_ratio": 0.0,
                "ex_dividend_date": ex_date,
            }
        )

    return records


def _build_shareholders_from_yf(institutional_holders, major_holders) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []

    if institutional_holders is not None:
        try:
            if not institutional_holders.empty:
                for _, row in institutional_holders.head(8).iterrows():
                    name = str(row.get("Holder") or "").strip()
                    ratio_raw = row.get("% Out")
                    ratio = _safe_float(ratio_raw)
                    if ratio is None:
                        ratio = _safe_float(str(ratio_raw).replace("%", ""))
                    if not name:
                        continue
                    records.append(
                        {
                            "name": name,
                            "holder_type": "机构投资者",
                            "holding_ratio": round(ratio or 0.0, 2),
                            "change_yoy": 0.0,
                        }
                    )
        except Exception:
            pass

    if not records and major_holders is not None:
        try:
            if not major_holders.empty:
                for _, row in major_holders.iterrows():
                    ratio_text = str(row.iloc[0])
                    ratio = _safe_float(ratio_text.replace("%", ""))
                    label = str(row.iloc[1])
                    if ratio is None or not label:
                        continue
                    records.append(
                        {
                            "name": label,
                            "holder_type": "股东结构",
                            "holding_ratio": round(ratio, 2),
                            "change_yoy": 0.0,
                        }
                    )
        except Exception:
            pass

    return records[:8]


def _build_news_from_yf(news_items: List[Dict[str, Any]]) -> List[str]:
    rows: List[str] = []
    for item in news_items[:8]:
        title = str(item.get("title") or "").strip()
        publisher = str(item.get("publisher") or item.get("source") or "").strip()
        if not title:
            continue
        if publisher:
            rows.append(f"{title}（来源：{publisher}）")
        else:
            rows.append(title)
    return rows


def _build_products_services(info: Dict[str, Any], fallback_industry: str) -> List[str]:
    sector = str(info.get("sector") or "").strip()
    industry = str(info.get("industry") or "").strip()

    entries = [item for item in [sector, industry, fallback_industry] if item]

    if not entries:
        entries = ["核心产品线", "市场渠道", "研发创新", "数字化运营"]

    deduped = list(dict.fromkeys(entries))
    while len(deduped) < 4:
        deduped.append(["运营体系", "客户生态", "供应链协同", "资本运营"][len(deduped) % 4])

    return deduped[:6]


def _build_key_risks(info: Dict[str, Any], pe_value: Optional[float], beta: Optional[float]) -> List[str]:
    risks: List[str] = []

    if pe_value is not None and pe_value >= 40:
        risks.append("估值水平偏高，若业绩兑现偏弱，估值回撤压力较大。")
    if beta is not None and beta >= 1.4:
        risks.append("Beta 偏高，市场波动加剧时，股价弹性与回撤可能同步放大。")

    debt_to_equity = _safe_float(info.get("debtToEquity"))
    if debt_to_equity is not None and debt_to_equity > 120:
        risks.append("资本结构偏激进，需跟踪融资成本和偿债能力变化。")

    revenue_growth = _safe_float(info.get("revenueGrowth"))
    if revenue_growth is not None and revenue_growth < 0:
        risks.append("收入增速转负，建议重点关注订单、价格和成本端的修复节奏。")

    if not risks:
        risks.append("暂无单一重大风险暴露，但仍需持续关注政策、行业景气和流动性变化。")

    return risks[:5]


def _build_catalyst_events(info: Dict[str, Any]) -> List[str]:
    events = [
        "财报披露窗口：关注收入质量、利润弹性与经营现金流改善。",
        "行业政策/监管变化：观察景气度、价格机制与需求端变化。",
    ]

    target_price = _safe_float(info.get("targetMeanPrice"))
    current_price = _safe_float(info.get("currentPrice"))
    if target_price is not None and current_price and current_price > 0:
        spread = (target_price - current_price) / current_price * 100
        events.append(f"卖方一致预期相对现价偏离 {spread:+.1f}%，情绪与预期修正可能带来波动。")

    return events[:4]


def _extract_akshare_info(row: StockUniverse) -> Dict[str, Any]:
    try:
        import akshare as ak
    except Exception as exc:
        logger.debug("akshare import failed for %s: %s", row.symbol, exc)
        return {}

    output: Dict[str, Any] = {}

    if row.market == "港股":
        try:
            hk_profile = ak.stock_hk_company_profile_em(symbol=str(row.code).zfill(5))
            output.update(_frame_first_record_to_dict(hk_profile))
        except Exception as exc:
            logger.debug("akshare hk company profile failed for %s: %s", row.symbol, exc)
        return output

    if row.market == "美股":
        return {}

    try:
        cninfo_profile = ak.stock_profile_cninfo(symbol=row.code)
        output.update(_frame_first_record_to_dict(cninfo_profile))
    except Exception as exc:
        logger.debug("akshare cninfo profile failed for %s: %s", row.symbol, exc)

    try:
        df = ak.stock_individual_info_em(symbol=row.code)
        if df is not None and not df.empty:
            columns = list(df.columns)
            key_column = columns[0]
            value_column = columns[1] if len(columns) > 1 else columns[0]
            for item in df.to_dict("records"):
                key = str(item.get(key_column) or "").strip()
                value = _first_non_empty_text(item.get(value_column))
                if key and value is not None and key not in output:
                    output[key] = value
    except Exception as exc:
        logger.debug("akshare stock individual info failed for %s: %s", row.symbol, exc)

    return output


def _extract_yfinance_payload(row: StockUniverse) -> Dict[str, Any]:
    ticker_candidates = _to_yfinance_ticker_candidates(row.symbol)
    if not ticker_candidates:
        return {}

    try:
        import yfinance as yf

        best_payload: Dict[str, Any] = {}

        for ticker in ticker_candidates:
            obj = yf.Ticker(ticker)

            info: Dict[str, Any] = {}
            history = None

            try:
                info = obj.get_info() or {}
            except Exception:
                try:
                    info = obj.info or {}
                except Exception:
                    info = {}

            try:
                history = obj.history(period="10y", interval="1d", auto_adjust=False)
            except Exception:
                history = None

            payload = {
                "ticker": ticker,
                "info": info,
                "history": history,
                "financials": None,
                "balance_sheet": None,
                "cashflow": None,
                "dividends": None,
                "news_items": [],
                "major_holders": None,
                "institutional_holders": None,
            }

            has_core_info = bool(
                info.get("longName")
                or info.get("shortName")
                or info.get("website")
                or info.get("sector")
                or info.get("industry")
            )
            has_history = _frame_has_data(history)

            if not best_payload:
                best_payload = payload

            if not has_core_info and not has_history:
                continue

            try:
                payload["financials"] = obj.financials
            except Exception:
                payload["financials"] = None

            try:
                payload["balance_sheet"] = obj.balance_sheet
            except Exception:
                payload["balance_sheet"] = None

            try:
                payload["cashflow"] = obj.cashflow
            except Exception:
                payload["cashflow"] = None

            try:
                payload["dividends"] = obj.dividends
            except Exception:
                payload["dividends"] = None

            try:
                news_raw = obj.news
                if isinstance(news_raw, list):
                    payload["news_items"] = [item for item in news_raw if isinstance(item, dict)]
            except Exception:
                payload["news_items"] = []

            try:
                payload["major_holders"] = obj.major_holders
            except Exception:
                payload["major_holders"] = None

            try:
                payload["institutional_holders"] = obj.institutional_holders
            except Exception:
                payload["institutional_holders"] = None

            return payload

        return best_payload
    except Exception as exc:
        logger.debug("yfinance fetch failed for %s: %s", row.symbol, exc)
        return {}


def _build_enrichment_payload(row: StockUniverse) -> Dict[str, Any]:
    y_payload = _extract_yfinance_payload(row)
    ak_info = _extract_akshare_info(row)

    info = y_payload.get("info") if y_payload else {}
    if not isinstance(info, dict):
        info = {}

    company_name = _first_non_empty_text(info.get("longName"), info.get("shortName"), ak_info.get("公司名称")) or ""
    if company_name:
        company_full_name = company_name
    elif row.market == "港股":
        company_full_name = f"{row.name}有限公司"
    elif row.market == "美股":
        company_full_name = row.name if row.name.lower().endswith(("inc.", "corp.", "corporation", "plc", "ltd.")) else f"{row.name} Inc."
    else:
        company_full_name = f"{row.name}股份有限公司"
    english_name = _first_non_empty_text(info.get("longName"), info.get("shortName"), ak_info.get("英文名称")) or f"{row.name} Holdings"

    listing_date = _parse_date_like(info.get("firstTradeDateEpochUtc"))
    if listing_date and str(listing_date).isdigit() and len(str(listing_date)) >= 10:
        try:
            listing_date = datetime.fromtimestamp(int(listing_date), tz=timezone.utc).date().isoformat()
        except Exception:
            listing_date = None

    if not listing_date:
        listing_date = _parse_date_like(_first_non_empty_text(ak_info.get("上市时间"), ak_info.get("上市日期"), ak_info.get("公司成立日期")))

    company_website = _normalize_url(_first_non_empty_text(
        info.get("website"),
        ak_info.get("官方网站"),
        ak_info.get("公司网址"),
        ak_info.get("官网"),
        ak_info.get("公司网站"),
    ))
    if not company_website:
        if row.market == "港股":
            company_website = "https://www.hkex.com.hk"
        elif row.market == "美股":
            company_website = "https://www.nasdaq.com"
        else:
            company_website = "http://www.cninfo.com.cn"

    exchange_profile_url = _exchange_profile_url(row.symbol)
    quote_url = _quote_url(row.symbol)

    investor_relations_url = _normalize_url(_first_non_empty_text(info.get("irWebsite")))
    if not investor_relations_url:
        if company_website.endswith("/"):
            investor_relations_url = f"{company_website}investor"
        else:
            investor_relations_url = f"{company_website}/investor"

    city = _first_non_empty_text(info.get("city")) or ""
    country = _first_non_empty_text(info.get("country")) or ""
    headquarters = _first_non_empty_text(
        ak_info.get("办公地址"),
        ak_info.get("注册地址"),
        ak_info.get("注册地"),
        "·".join([part for part in [country, city] if part]) if (country or city) else None,
    ) or _default_headquarters(row.exchange)

    legal_representative = _first_non_empty_text(ak_info.get("法人代表"), ak_info.get("董事长")) or "未披露"
    employees = _safe_int(info.get("fullTimeEmployees")) or _safe_int(ak_info.get("员工人数"))

    long_business_summary = _first_non_empty_text(info.get("longBusinessSummary")) or ""
    main_business = _first_non_empty_text(long_business_summary[:280] if long_business_summary else None, ak_info.get("主营业务"), ak_info.get("经营范围"), ak_info.get("公司介绍")) or f"{row.name} 主要从事相关业务。"
    company_intro = _first_non_empty_text(long_business_summary[:500] if long_business_summary else None, ak_info.get("机构简介"), ak_info.get("公司介绍"), ak_info.get("经营范围")) or f"{row.name} 主要从事相关业务，当前归属于 {row.board} / {row.exchange}。"

    fallback_industry = _first_non_empty_text(ak_info.get("所属行业"), ak_info.get("行业"), row.board) or row.board
    products_services = _build_products_services(info=info, fallback_industry=fallback_industry)

    history = y_payload.get("history") if y_payload else None
    financials = y_payload.get("financials") if y_payload else None
    balance_sheet = y_payload.get("balance_sheet") if y_payload else None
    cashflow = y_payload.get("cashflow") if y_payload else None
    dividends = y_payload.get("dividends") if y_payload else None
    news_items = y_payload.get("news_items") if y_payload else []
    major_holders = y_payload.get("major_holders") if y_payload else None
    institutional_holders = y_payload.get("institutional_holders") if y_payload else None

    current_close = _safe_float(info.get("currentPrice"))

    financial_reports = _build_financial_reports_from_yf(
        financials=financials,
        balance_sheet=balance_sheet,
        cashflow=cashflow,
        dividends=dividends,
        current_close=current_close,
        report_url=exchange_profile_url,
    )
    valuation_history = _build_valuation_history_from_yf(history=history, info=info)
    dividend_history = _build_dividend_history_from_yf(dividends=dividends)
    shareholder_structure = _build_shareholders_from_yf(
        institutional_holders=institutional_holders,
        major_holders=major_holders,
    )

    news_highlights = _build_news_from_yf(news_items)

    pe_value = _safe_float(info.get("trailingPE")) or _safe_float(info.get("forwardPE"))
    beta = _safe_float(info.get("beta"))
    key_risks = _build_key_risks(info=info, pe_value=pe_value, beta=beta)
    catalyst_events = _build_catalyst_events(info=info)

    peer_companies: List[Dict[str, Any]] = []

    coverage_parts = [
        bool(company_website),
        bool(main_business),
        bool(products_services),
        bool(financial_reports),
        bool(valuation_history),
        bool(dividend_history),
        bool(shareholder_structure),
        bool(news_highlights),
    ]
    coverage_score = round(sum(1 for value in coverage_parts if value) / len(coverage_parts) * 100, 1)

    status = "success" if coverage_score >= 70 else "partial"

    return {
        "source": "yfinance+akshare",
        "status": status,
        "coverage_score": coverage_score,
        "company_full_name": company_full_name,
        "english_name": english_name,
        "listing_date": listing_date,
        "company_website": company_website,
        "investor_relations_url": investor_relations_url,
        "exchange_profile_url": exchange_profile_url,
        "quote_url": quote_url,
        "headquarters": headquarters,
        "legal_representative": legal_representative,
        "employees": employees,
        "main_business": main_business,
        "company_intro": company_intro,
        "products_services_json": _json_dumps(products_services),
        "key_risks_json": _json_dumps(key_risks),
        "catalyst_events_json": _json_dumps(catalyst_events),
        "news_highlights_json": _json_dumps(news_highlights),
        "financial_reports_json": _json_dumps(financial_reports),
        "valuation_history_json": _json_dumps(valuation_history),
        "dividend_history_json": _json_dumps(dividend_history),
        "shareholder_structure_json": _json_dumps(shareholder_structure),
        "peer_companies_json": _json_dumps(peer_companies),
        "raw_payload_json": _json_dumps(
            {
                "ticker": y_payload.get("ticker") if y_payload else None,
                "info_keys": sorted(list(info.keys()))[:80],
                "akshare_keys": sorted(list(ak_info.keys()))[:80],
                "news_count": len(news_items),
            }
        ),
        "updated_at": _utc_now(),
    }


def get_stock_enrichment(db: Session, symbol: str) -> Optional[StockEnrichment]:
    return db.query(StockEnrichment).filter(StockEnrichment.symbol == symbol).first()


def is_placeholder_company_website(url: Optional[str]) -> bool:
    normalized = _normalize_url(url)
    if not normalized:
        return True
    return urlparse(normalized).netloc.lower() in _PLACEHOLDER_WEBSITE_DOMAINS


def build_transient_enrichment_from_row(row: StockUniverse) -> Optional[StockEnrichment]:
    try:
        payload = _build_enrichment_payload(row)
    except Exception as exc:
        logger.debug("build transient enrichment failed for %s: %s", row.symbol, exc)
        return None

    if not payload:
        return None

    return StockEnrichment(
        symbol=row.symbol,
        source=payload.get("source") or "mixed_web_sources",
        status=payload.get("status") or "partial",
        coverage_score=payload.get("coverage_score"),
        company_full_name=payload.get("company_full_name"),
        english_name=payload.get("english_name"),
        listing_date=payload.get("listing_date"),
        company_website=payload.get("company_website"),
        investor_relations_url=payload.get("investor_relations_url"),
        exchange_profile_url=payload.get("exchange_profile_url"),
        quote_url=payload.get("quote_url"),
        headquarters=payload.get("headquarters"),
        legal_representative=payload.get("legal_representative"),
        employees=payload.get("employees"),
        main_business=payload.get("main_business"),
        company_intro=payload.get("company_intro"),
        products_services_json=payload.get("products_services_json"),
        key_risks_json=payload.get("key_risks_json"),
        catalyst_events_json=payload.get("catalyst_events_json"),
        news_highlights_json=payload.get("news_highlights_json"),
        financial_reports_json=payload.get("financial_reports_json"),
        valuation_history_json=payload.get("valuation_history_json"),
        dividend_history_json=payload.get("dividend_history_json"),
        shareholder_structure_json=payload.get("shareholder_structure_json"),
        peer_companies_json=payload.get("peer_companies_json"),
        raw_payload_json=payload.get("raw_payload_json"),
        updated_at=payload.get("updated_at") or _utc_now(),
    )


def enrich_single_stock(
    db: Session,
    row: StockUniverse,
    force: bool = False,
) -> Tuple[str, float]:
    db.rollback()
    existing = get_stock_enrichment(db, row.symbol)

    if existing is not None and not force:
        updated_at = _as_utc(existing.updated_at)
        if updated_at is not None and (_utc_now() - updated_at).total_seconds() < _ENRICH_STALE_SECONDS:
            return "skipped", existing.coverage_score or 0.0

    payload = _build_enrichment_payload(row)
    status = payload.get("status") or "partial"
    coverage_score = payload.get("coverage_score") or 0.0
    updated_at = payload.get("updated_at") or _utc_now()

    insert_payload = {
        "symbol": row.symbol,
        "source": payload.get("source") or "mixed_web_sources",
        "status": status,
        "coverage_score": coverage_score,
        "company_full_name": payload.get("company_full_name"),
        "english_name": payload.get("english_name"),
        "listing_date": payload.get("listing_date"),
        "company_website": payload.get("company_website"),
        "investor_relations_url": payload.get("investor_relations_url"),
        "exchange_profile_url": payload.get("exchange_profile_url"),
        "quote_url": payload.get("quote_url"),
        "headquarters": payload.get("headquarters"),
        "legal_representative": payload.get("legal_representative"),
        "employees": payload.get("employees"),
        "main_business": payload.get("main_business"),
        "company_intro": payload.get("company_intro"),
        "products_services_json": payload.get("products_services_json"),
        "key_risks_json": payload.get("key_risks_json"),
        "catalyst_events_json": payload.get("catalyst_events_json"),
        "news_highlights_json": payload.get("news_highlights_json"),
        "financial_reports_json": payload.get("financial_reports_json"),
        "valuation_history_json": payload.get("valuation_history_json"),
        "dividend_history_json": payload.get("dividend_history_json"),
        "shareholder_structure_json": payload.get("shareholder_structure_json"),
        "peer_companies_json": payload.get("peer_companies_json"),
        "raw_payload_json": payload.get("raw_payload_json"),
        "updated_at": updated_at,
    }

    if existing is None:
        db.add(StockEnrichment(**insert_payload))
        db.commit()
        time.sleep(_YF_CALL_GAP_SECONDS)
        return status, coverage_score

    update_payload = dict(insert_payload)
    update_payload.pop("symbol", None)
    db.query(StockEnrichment).filter(StockEnrichment.id == existing.id).update(update_payload)
    db.commit()

    time.sleep(_YF_CALL_GAP_SECONDS)
    return status, coverage_score


def enrich_stock_universe(
    db: Session,
    market: Optional[str] = None,
    limit: Optional[int] = None,
    force: bool = False,
    sleep_ms: int = 120,
) -> StockEnrichResponse:
    started = time.perf_counter()

    query = db.query(StockUniverse).filter(StockUniverse.listed.is_(True))
    if market:
        query = query.filter(StockUniverse.market == market)

    rows = query.order_by(StockUniverse.symbol.asc()).all()
    row_ids = [row.id for row in rows]
    total = len(row_ids)

    if limit is not None:
        row_ids = row_ids[: max(0, limit)]

    processed = 0
    success_count = 0
    failed_count = 0
    skipped_count = 0

    def _new_session() -> Session:
        try:
            db.close()
        except Exception:
            pass
        return SessionLocal()

    for row_id in row_ids:
        processed += 1
        for attempt in range(2):
            try:
                if attempt == 0:
                    db.rollback()
                row = db.query(StockUniverse).filter(StockUniverse.id == row_id).first()
                if row is None:
                    failed_count += 1
                    logger.exception("enrich failed for id=%s: stock not found", row_id)
                    break

                status, coverage = enrich_single_stock(db=db, row=row, force=force)
                if status == "skipped":
                    skipped_count += 1
                elif status == "success":
                    success_count += 1
                else:
                    success_count += 1

                if processed % 50 == 0:
                    logger.info("enrich progress %s/%s symbol=%s coverage=%s", processed, len(row_ids), row.symbol, coverage)
                break
            except (OperationalError, PendingRollbackError) as exc:
                logger.exception("enrich db error for id=%s (attempt %s): %s", row_id, attempt + 1, exc)
                db = _new_session()
                if attempt == 1:
                    failed_count += 1
            except Exception as exc:
                failed_count += 1
                logger.exception("enrich failed for id=%s: %s", row_id, exc)
                db = _new_session()
                break

        if sleep_ms > 0:
            time.sleep(sleep_ms / 1000.0)

    duration_ms = int((time.perf_counter() - started) * 1000)

    success = failed_count == 0
    return StockEnrichResponse(
        success=success,
        total=total,
        processed=processed,
        success_count=success_count,
        failed_count=failed_count,
        skipped_count=skipped_count,
        duration_ms=duration_ms,
        message="全量详情补齐完成" if success else "补齐任务完成，部分股票抓取失败",
    )


def get_enrichment_status(db: Session) -> StockEnrichStatusResponse:
    total_universe = int(db.query(func.count(StockUniverse.id)).filter(StockUniverse.listed.is_(True)).scalar() or 0)

    enriched_query = db.query(StockEnrichment)
    enriched_count = int(enriched_query.count())
    success_count = int(enriched_query.filter(StockEnrichment.status.in_(["success", "partial"])) .count())
    failed_count = int(enriched_query.filter(StockEnrichment.status == "failed").count())
    latest_enriched_at = db.query(func.max(StockEnrichment.updated_at)).scalar()

    coverage_rate = 0.0
    if total_universe > 0:
        coverage_rate = round(enriched_count / total_universe * 100, 2)

    latest_text = None
    latest_utc = _as_utc(latest_enriched_at)
    if latest_utc is not None:
        latest_text = latest_utc.isoformat()

    return StockEnrichStatusResponse(
        total_universe=total_universe,
        enriched_count=enriched_count,
        success_count=success_count,
        failed_count=failed_count,
        coverage_rate=coverage_rate,
        latest_enriched_at=latest_text,
    )


def merge_stock_detail_with_enrichment(base_detail: StockDetail, enrichment: StockEnrichment) -> StockDetail:
    updates: Dict[str, Any] = {}

    for field in [
        "company_full_name",
        "english_name",
        "listing_date",
        "company_website",
        "investor_relations_url",
        "exchange_profile_url",
        "quote_url",
        "headquarters",
        "legal_representative",
        "main_business",
        "company_intro",
    ]:
        value = getattr(enrichment, field)
        if value:
            updates[field] = value

    if enrichment.employees and enrichment.employees > 0:
        updates["employees"] = enrichment.employees

    products_services = _json_loads_list(enrichment.products_services_json)
    if products_services:
        updates["products_services"] = [str(item) for item in products_services if str(item).strip()][:8]

    key_risks = _json_loads_list(enrichment.key_risks_json)
    if key_risks:
        updates["key_risks"] = [str(item) for item in key_risks if str(item).strip()][:8]

    catalyst_events = _json_loads_list(enrichment.catalyst_events_json)
    if catalyst_events:
        updates["catalyst_events"] = [str(item) for item in catalyst_events if str(item).strip()][:8]

    news_highlights = _json_loads_list(enrichment.news_highlights_json)
    if news_highlights:
        updates["news_highlights"] = [str(item) for item in news_highlights if str(item).strip()][:10]

    financial_reports = _parse_model_list(_json_loads_list(enrichment.financial_reports_json), FinancialReport)
    if financial_reports:
        updates["financial_reports"] = financial_reports

    valuation_history = _parse_model_list(_json_loads_list(enrichment.valuation_history_json), ValuationHistoryPoint)
    if valuation_history:
        updates["valuation_history"] = valuation_history

    dividend_history = _parse_model_list(_json_loads_list(enrichment.dividend_history_json), DividendRecord)
    if dividend_history:
        updates["dividend_history"] = dividend_history

    shareholder_structure = _parse_model_list(_json_loads_list(enrichment.shareholder_structure_json), ShareholderRecord)
    if shareholder_structure:
        updates["shareholder_structure"] = shareholder_structure

    peer_companies = _parse_model_list(_json_loads_list(enrichment.peer_companies_json), PeerCompany)
    if peer_companies:
        updates["peer_companies"] = peer_companies

    if not updates:
        return base_detail

    return base_detail.model_copy(update=updates)
