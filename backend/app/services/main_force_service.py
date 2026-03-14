from __future__ import annotations

import json
import math
from threading import Thread
from types import SimpleNamespace
from datetime import datetime, timezone
from typing import List, Optional, Tuple

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.main_force import MainForceJob, MainForceScan, MainForceSetting
from app.schemas.stock import MainForceCandidate, MainForceMetrics, MainForceScanResponse, MainForceSignalLevel, MainForceStage
from app.services.llm_service import chat_completion
from app.services.stock_service import _market_change_pct, _market_price, _query_universe_rows, get_stock_kline
from app.services.web_search_service import search_web


def _utc_now_text() -> str:
    return datetime.now(timezone.utc).isoformat()


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _linear_slope(values: List[float]) -> float:
    if len(values) < 2:
        return 0.0
    n = len(values)
    xs = list(range(n))
    mean_x = (n - 1) / 2
    mean_y = sum(values) / n
    num = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, values))
    den = sum((x - mean_x) ** 2 for x in xs) or 1.0
    return num / den


def _stddev(values: List[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    var = sum((value - mean) ** 2 for value in values) / (len(values) - 1)
    return math.sqrt(max(var, 0.0))


def _build_metrics(prices: List[float], opens: List[float], volumes: List[float]) -> Optional[MainForceMetrics]:
    if len(prices) < 60:
        return None

    closes_20 = prices[-20:]
    closes_60 = prices[-60:]
    volumes_20 = volumes[-20:]
    opens_20 = opens[-20:]

    min_20, max_20 = min(closes_20), max(closes_20)
    min_60, max_60 = min(closes_60), max(closes_60)
    range_20 = (max_20 - min_20) / max(min_20, 0.01)
    range_60 = (max_60 - min_60) / max(min_60, 0.01)
    range_squeeze = range_20 / max(range_60, 0.01)

    returns_20 = [(closes_20[i] - closes_20[i - 1]) / max(closes_20[i - 1], 0.01) for i in range(1, len(closes_20))]
    returns_60 = [(closes_60[i] - closes_60[i - 1]) / max(closes_60[i - 1], 0.01) for i in range(1, len(closes_60))]
    vol_20 = _stddev(returns_20)
    vol_60 = _stddev(returns_60)
    vol_squeeze = vol_20 / max(vol_60, 0.0001)

    obv = [0.0]
    for i in range(1, len(prices)):
        if prices[i] > prices[i - 1]:
            obv.append(obv[-1] + volumes[i])
        elif prices[i] < prices[i - 1]:
            obv.append(obv[-1] - volumes[i])
        else:
            obv.append(obv[-1])
    obv_20 = obv[-20:]
    obv_slope = _linear_slope(obv_20)
    obv_slope_norm = obv_slope / (abs(obv_20[0]) + 1.0)

    up_volume = sum(vol for vol, close, open_ in zip(volumes_20, closes_20, opens_20) if close >= open_)
    total_volume = sum(volumes_20) or 1.0
    up_volume_ratio = up_volume / total_volume

    close_slope = _linear_slope(closes_60)
    close_slope_norm = close_slope / (sum(closes_60) / len(closes_60))

    drawdown_60 = (closes_60[-1] - max_60) / max(max_60, 0.01)

    return MainForceMetrics(
        range_20=round(range_20, 4),
        range_60=round(range_60, 4),
        range_squeeze=round(range_squeeze, 4),
        vol_20=round(vol_20, 6),
        vol_60=round(vol_60, 6),
        vol_squeeze=round(vol_squeeze, 4),
        obv_slope_20=round(obv_slope_norm, 6),
        up_volume_ratio_20=round(up_volume_ratio, 4),
        close_slope_60=round(close_slope_norm, 6),
        drawdown_60=round(drawdown_60, 4),
    )


def _score_and_stage(metrics: MainForceMetrics, settings) -> Tuple[int, MainForceStage, str]:
    score = 50

    if metrics.vol_squeeze < 0.8:
        score += 6
    if metrics.vol_squeeze < 0.6:
        score += 6
    if metrics.range_squeeze < 0.7:
        score += 6
    if metrics.range_squeeze < 0.55:
        score += 4

    if metrics.obv_slope_20 > 0.02:
        score += 8
    elif metrics.obv_slope_20 < -0.02:
        score -= 8

    if metrics.up_volume_ratio_20 >= 0.55:
        score += 6
    elif metrics.up_volume_ratio_20 <= 0.45:
        score -= 6

    if -0.003 <= metrics.close_slope_60 <= 0.006:
        score += 6
    elif metrics.close_slope_60 < -0.01:
        score -= 6
    elif metrics.close_slope_60 > 0.02:
        score += 4

    if metrics.drawdown_60 < -0.35:
        score -= 6

    score = int(max(1, min(99, round(score))))

    stage: MainForceStage = "neutral"
    if (
        score >= settings.main_force_accumulation_score_min
        and metrics.vol_squeeze < settings.main_force_accumulation_vol_squeeze_max
        and metrics.range_squeeze < settings.main_force_accumulation_range_squeeze_max
        and metrics.obv_slope_20 > 0
    ):
        stage = "accumulation"
    elif metrics.close_slope_60 > settings.main_force_markup_close_slope_min and metrics.up_volume_ratio_20 > settings.main_force_markup_up_volume_ratio_min:
        stage = "markup"
    elif metrics.close_slope_60 < settings.main_force_distribution_close_slope_max and metrics.obv_slope_20 < settings.main_force_distribution_obv_slope_max:
        stage = "distribution"
    elif metrics.close_slope_60 < settings.main_force_pullback_close_slope_max and metrics.obv_slope_20 > settings.main_force_pullback_obv_slope_min:
        stage = "pullback"

    reason_parts = []
    if metrics.range_squeeze < 0.7:
        reason_parts.append("区间收敛")
    if metrics.vol_squeeze < 0.7:
        reason_parts.append("波动收缩")
    if metrics.obv_slope_20 > 0:
        reason_parts.append("OBV 上行")
    if metrics.up_volume_ratio_20 >= 0.55:
        reason_parts.append("资金偏多")
    if not reason_parts:
        reason_parts.append("信号中性")

    reason = " / ".join(reason_parts)
    return score, stage, reason


def _signal_level(metrics: MainForceMetrics, score: int, stage: MainForceStage, settings) -> MainForceSignalLevel:
    if (
        stage == "accumulation"
        and score >= settings.main_force_signal_high_score_min
        and metrics.vol_squeeze < settings.main_force_signal_high_vol_squeeze_max
        and metrics.range_squeeze < settings.main_force_signal_high_range_squeeze_max
        and metrics.obv_slope_20 > settings.main_force_signal_high_obv_slope_min
    ):
        return "high"
    if (
        score >= settings.main_force_signal_medium_score_min
        and metrics.vol_squeeze < settings.main_force_signal_medium_vol_squeeze_max
        and metrics.range_squeeze < settings.main_force_signal_medium_range_squeeze_max
        and metrics.obv_slope_20 >= settings.main_force_signal_medium_obv_slope_min
    ):
        return "medium"
    return "low"


def _sentiment_score(text: str) -> Tuple[int, int, int]:
    positive_terms = [
        "利好",
        "上调",
        "增持",
        "回购",
        "业绩增长",
        "创新高",
        "签约",
        "中标",
        "扩产",
        "涨停",
        "资金流入",
        "净流入",
        "获批",
        "重组",
        "收购",
        "战略合作",
        "景气度",
    ]
    negative_terms = [
        "利空",
        "下调",
        "减持",
        "亏损",
        "罚款",
        "调查",
        "被立案",
        "诉讼",
        "业绩下滑",
        "下修",
        "退市",
        "风险",
        "暴雷",
        "限售解禁",
        "资金流出",
        "净流出",
        "跌停",
        "质押",
        "减产",
    ]
    pos = sum(text.count(term) for term in positive_terms)
    neg = sum(text.count(term) for term in negative_terms)
    score = max(0, min(100, 50 + (pos - neg) * 5))
    return score, pos, neg


def _fetch_sentiment(symbol: str, name: str) -> Tuple[Optional[float], Optional[str], int]:
    settings = get_settings()
    query = f"{name} {symbol} 资金 流入 主力"
    try:
        results = search_web(
            query,
            max_results=settings.qa_web_search_max_results,
            timeout=settings.qa_web_search_timeout_seconds,
        )
    except Exception:
        return None, None, 0

    if not results:
        return None, None, 0

    merged = " ".join(f"{item.title} {item.snippet}" for item in results)
    score, _, _ = _sentiment_score(merged)
    summary = "；".join([item.title for item in results[:3] if item.title])
    return float(score), summary or None, len(results)


def _signal_rank(level: MainForceSignalLevel) -> int:
    if level == "high":
        return 2
    if level == "medium":
        return 1
    return 0


def _default_main_force_config(settings) -> dict:
    return {
        "main_force_accumulation_score_min": settings.main_force_accumulation_score_min,
        "main_force_accumulation_vol_squeeze_max": settings.main_force_accumulation_vol_squeeze_max,
        "main_force_accumulation_range_squeeze_max": settings.main_force_accumulation_range_squeeze_max,
        "main_force_markup_close_slope_min": settings.main_force_markup_close_slope_min,
        "main_force_markup_up_volume_ratio_min": settings.main_force_markup_up_volume_ratio_min,
        "main_force_distribution_close_slope_max": settings.main_force_distribution_close_slope_max,
        "main_force_distribution_obv_slope_max": settings.main_force_distribution_obv_slope_max,
        "main_force_pullback_close_slope_max": settings.main_force_pullback_close_slope_max,
        "main_force_pullback_obv_slope_min": settings.main_force_pullback_obv_slope_min,
        "main_force_signal_high_score_min": settings.main_force_signal_high_score_min,
        "main_force_signal_medium_score_min": settings.main_force_signal_medium_score_min,
        "main_force_signal_high_vol_squeeze_max": settings.main_force_signal_high_vol_squeeze_max,
        "main_force_signal_medium_vol_squeeze_max": settings.main_force_signal_medium_vol_squeeze_max,
        "main_force_signal_high_range_squeeze_max": settings.main_force_signal_high_range_squeeze_max,
        "main_force_signal_medium_range_squeeze_max": settings.main_force_signal_medium_range_squeeze_max,
        "main_force_signal_high_obv_slope_min": settings.main_force_signal_high_obv_slope_min,
        "main_force_signal_medium_obv_slope_min": settings.main_force_signal_medium_obv_slope_min,
        "main_force_sentiment_high": settings.main_force_sentiment_high,
        "main_force_sentiment_low": settings.main_force_sentiment_low,
        "main_force_sentiment_boost_step": settings.main_force_sentiment_boost_step,
        "main_force_sentiment_boost_weight": settings.main_force_sentiment_boost_weight,
        "main_force_scan_limit": settings.main_force_scan_limit,
        "main_force_scan_top_n": settings.main_force_scan_top_n,
        "main_force_scan_with_llm": settings.main_force_scan_with_llm,
        "main_force_scan_llm_top_n": settings.main_force_scan_llm_top_n,
        "main_force_scan_with_web": settings.main_force_scan_with_web,
        "main_force_scan_sentiment_top_n": settings.main_force_scan_sentiment_top_n,
    }


def _load_setting_overrides(row: Optional[MainForceSetting]) -> dict:
    if row is None or not row.overrides_json:
        return {}
    try:
        value = json.loads(row.overrides_json)
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def _merge_config(defaults: dict, overrides: dict) -> dict:
    merged = dict(defaults)
    for key, value in overrides.items():
        if key in defaults:
            merged[key] = value
    return merged


def get_or_create_main_force_setting(db: Session) -> MainForceSetting:
    row = db.query(MainForceSetting).first()
    if row is not None:
        return row
    row = MainForceSetting()
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def get_main_force_setting_payload(db: Session) -> dict:
    settings = get_settings()
    defaults = _default_main_force_config(settings)
    row = get_or_create_main_force_setting(db)
    overrides = _load_setting_overrides(row)
    effective = _merge_config(defaults, overrides)
    return {
        "enabled": row.enabled,
        "scan_interval_minutes": row.scan_interval_minutes,
        "overrides": overrides,
        "effective": effective,
        "last_run_at": row.last_run_at.isoformat() if row.last_run_at else None,
    }


def update_main_force_setting(db: Session, payload: dict) -> dict:
    settings = get_settings()
    defaults = _default_main_force_config(settings)
    row = get_or_create_main_force_setting(db)

    if "enabled" in payload and payload["enabled"] is not None:
        row.enabled = bool(payload["enabled"])
    if "scan_interval_minutes" in payload and payload["scan_interval_minutes"] is not None:
        row.scan_interval_minutes = int(payload["scan_interval_minutes"])

    overrides = _load_setting_overrides(row)
    update_overrides = payload.get("overrides") or {}
    if isinstance(update_overrides, dict):
        for key, value in update_overrides.items():
            if key not in defaults:
                continue
            if value is None:
                overrides.pop(key, None)
            else:
                overrides[key] = value

    row.overrides_json = json.dumps(overrides, ensure_ascii=False)
    db.add(row)
    db.commit()
    db.refresh(row)

    effective = _merge_config(defaults, overrides)
    return {
        "enabled": row.enabled,
        "scan_interval_minutes": row.scan_interval_minutes,
        "overrides": overrides,
        "effective": effective,
        "last_run_at": row.last_run_at.isoformat() if row.last_run_at else None,
    }


def _persist_scan(db: Session, response: MainForceScanResponse, config: dict) -> None:
    candidates_json = json.dumps([item.model_dump() for item in response.candidates], ensure_ascii=False)
    config_json = json.dumps(config, ensure_ascii=False)
    row = MainForceScan(
        generated_at=datetime.fromisoformat(response.generated_at),
        total_scanned=response.total_scanned,
        candidates_json=candidates_json,
        config_json=config_json,
    )
    db.add(row)
    db.commit()


def get_latest_scan(db: Session) -> Optional[MainForceScanResponse]:
    row = db.query(MainForceScan).order_by(MainForceScan.generated_at.desc()).first()
    if row is None:
        return None
    try:
        candidates_raw = json.loads(row.candidates_json)
    except Exception:
        candidates_raw = []
    candidates = [MainForceCandidate(**item) for item in candidates_raw if isinstance(item, dict)]
    return MainForceScanResponse(
        generated_at=row.generated_at.isoformat(),
        total_scanned=row.total_scanned,
        candidates=candidates,
    )


def run_main_force_schedule(db: Session) -> bool:
    setting = get_or_create_main_force_setting(db)
    if not setting.enabled:
        return False
    interval_minutes = max(5, int(setting.scan_interval_minutes or 0))
    now = _utc_now()
    if setting.last_run_at:
        delta = now - setting.last_run_at
        if delta.total_seconds() < interval_minutes * 60:
            return False
    scan_main_force_candidates(db=db, use_settings=True, persist=True)
    setting.last_run_at = now
    db.add(setting)
    db.commit()
    return True


def _llm_summary(
    symbol: str,
    name: str,
    metrics: MainForceMetrics,
    stage: MainForceStage,
    sentiment_score: Optional[float],
    sentiment_summary: Optional[str],
) -> Optional[str]:
    content = (
        "你是量价结构分析助手。根据指标判断是否处于主力吸筹/建仓阶段，"
        "输出三行：阶段判断、理由、风险提示。不要给交易建议。\n"
        f"标的: {name}({symbol})\n"
        f"阶段预判: {stage}\n"
        f"指标: range_squeeze={metrics.range_squeeze}, vol_squeeze={metrics.vol_squeeze}, "
        f"obv_slope_20={metrics.obv_slope_20}, up_volume_ratio_20={metrics.up_volume_ratio_20}, "
        f"close_slope_60={metrics.close_slope_60}, drawdown_60={metrics.drawdown_60}. "
        f"舆情评分: {sentiment_score if sentiment_score is not None else 'N/A'}. "
        f"新闻摘要: {sentiment_summary or 'N/A'}."
    )
    messages = [
        {"role": "system", "content": "你是资深市场结构研究员，输出简洁客观结论。"},
        {"role": "user", "content": content},
    ]
    try:
        return chat_completion(messages)
    except Exception:
        return None


def scan_main_force_candidates(
    db: Session,
    market: Optional[str] = None,
    limit: Optional[int] = None,
    top_n: Optional[int] = None,
    with_llm: Optional[bool] = None,
    llm_top_n: Optional[int] = None,
    with_web: Optional[bool] = None,
    sentiment_top_n: Optional[int] = None,
    use_settings: bool = True,
    persist: bool = True,
) -> MainForceScanResponse:
    base_settings = get_settings()
    defaults = _default_main_force_config(base_settings)
    overrides = _load_setting_overrides(get_or_create_main_force_setting(db)) if use_settings else {}
    effective = _merge_config(defaults, overrides)
    config = SimpleNamespace(**effective)

    limit = int(limit if limit is not None else config.main_force_scan_limit)
    top_n = int(top_n if top_n is not None else config.main_force_scan_top_n)
    with_llm = bool(with_llm if with_llm is not None else config.main_force_scan_with_llm)
    llm_top_n = int(llm_top_n if llm_top_n is not None else config.main_force_scan_llm_top_n)
    with_web = bool(with_web if with_web is not None else config.main_force_scan_with_web)
    sentiment_top_n = int(sentiment_top_n if sentiment_top_n is not None else config.main_force_scan_sentiment_top_n)
    rows = _query_universe_rows(db, market=None, q=None)
    market_set = {"A股", "创业板", "科创板"} if not market or market == "A股" else {market}

    filtered = [
        row
        for row in rows
        if row.market in market_set
        and row.listed
        and not row.name.upper().startswith("ST")
        and not row.name.upper().startswith("*ST")
    ]

    filtered.sort(key=lambda item: float(item.turnover or 0.0), reverse=True)
    filtered = filtered[: max(1, limit)]

    candidates: List[MainForceCandidate] = []
    for row in filtered:
        kline = get_stock_kline(db=db, symbol=row.symbol, period="6mo", interval="1d")
        if not kline or not kline.points:
            continue
        points = kline.points
        prices = [point.close for point in points]
        opens = [point.open for point in points]
        volumes = [point.volume for point in points]

        metrics = _build_metrics(prices, opens, volumes)
        if metrics is None:
            continue

        score, stage, reason = _score_and_stage(metrics, config)
        signal_level = _signal_level(metrics, score, stage, config)
        price = _market_price(row)
        change_pct = _market_change_pct(row)
        candidates.append(
            MainForceCandidate(
                symbol=row.symbol,
                name=row.name,
                market=row.market,  # type: ignore[arg-type]
                price=price,
                change_pct=change_pct,
                score=score,
                stage=stage,
                signal_level=signal_level,
                reason=reason,
                metrics=metrics,
            )
        )

    candidates.sort(key=lambda item: item.score, reverse=True)

    if with_web:
        for candidate in candidates[: max(0, sentiment_top_n)]:
            sentiment_score, sentiment_summary, sentiment_sources = _fetch_sentiment(candidate.symbol, candidate.name)
            if sentiment_score is not None:
                boost_step = max(1, config.main_force_sentiment_boost_step)
                boost_weight = max(0, config.main_force_sentiment_boost_weight)
                sentiment_boost = int(round((sentiment_score - 50) / boost_step)) * boost_weight
                candidate.score = int(max(1, min(99, candidate.score + sentiment_boost)))
            candidate.sentiment_score = sentiment_score
            candidate.sentiment_summary = sentiment_summary
            candidate.sentiment_sources = sentiment_sources
            if sentiment_score is not None:
                if sentiment_score >= config.main_force_sentiment_high:
                    candidate.reason = f"{candidate.reason} / 舆情偏多"
                elif sentiment_score <= config.main_force_sentiment_low:
                    candidate.reason = f"{candidate.reason} / 舆情偏空"
                if sentiment_score <= config.main_force_sentiment_low:
                    candidate.signal_level = "low"
                elif sentiment_score >= config.main_force_sentiment_high and candidate.signal_level == "medium":
                    candidate.signal_level = "high"

    candidates.sort(key=lambda item: item.score, reverse=True)
    candidates = candidates[: max(1, top_n)]

    if with_llm:
        for idx, candidate in enumerate(candidates[: max(0, llm_top_n)]):
            candidate.llm_summary = _llm_summary(
                candidate.symbol,
                candidate.name,
                candidate.metrics,
                candidate.stage,
                candidate.sentiment_score,
                candidate.sentiment_summary,
            )

    response = MainForceScanResponse(
        generated_at=_utc_now_text(),
        total_scanned=len(filtered),
        candidates=candidates,
    )
    if persist:
        config_used = dict(effective)
        config_used.update(
            {
                "scan_market": market or "A股",
                "scan_limit": limit,
                "scan_top_n": top_n,
                "scan_with_llm": with_llm,
                "scan_llm_top_n": llm_top_n,
                "scan_with_web": with_web,
                "scan_sentiment_top_n": sentiment_top_n,
            }
        )
        _persist_scan(db, response, config_used)
    return response
