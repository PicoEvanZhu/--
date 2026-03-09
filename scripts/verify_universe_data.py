#!/usr/bin/env python3

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple


ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT / "backend"
os.chdir(BACKEND_DIR)

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app import models as _models  # noqa: E402,F401
from app.core.database import Base, SessionLocal, engine  # noqa: E402
from app.models.stock_enrichment import StockEnrichment  # noqa: E402
from app.models.stock_universe import StockUniverse  # noqa: E402
from app.services.enrichment_service import merge_stock_detail_with_enrichment, is_placeholder_company_website  # noqa: E402
from app.services.stock_service import _build_analysis_from_detail, _build_stock_detail_from_row, _decorate_company_profile, get_stock_analysis, get_stock_detail  # noqa: E402


REQUIRED_URL_FIELDS = ["company_website", "investor_relations_url", "exchange_profile_url", "quote_url"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="全量股票数据校验（结构完整性 + 业务一致性）")
    parser.add_argument("--market", choices=["A股", "港股", "创业板", "科创板"], default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--output-json", default=str(ROOT / ".run" / "verification_summary.json"))
    parser.add_argument("--output-csv", default=str(ROOT / ".run" / "verification_issues.csv"))
    parser.add_argument("--fast", action="store_true", help="使用数据库快照快速审计，不逐股联网拉实时行情")
    return parser.parse_args()


def _is_url(value: Optional[str]) -> bool:
    if not value:
        return False
    text = value.strip().lower()
    return text.startswith("http://") or text.startswith("https://")


def _score_from_issue_count(critical: int, warning: int) -> float:
    score = 100 - critical * 12 - warning * 3
    if score < 0:
        return 0.0
    return float(score)


def _validate_symbol(
    symbol: str,
    detail,
    analysis,
    enrichment: Optional[StockEnrichment],
) -> List[Tuple[str, str]]:
    issues: List[Tuple[str, str]] = []

    if detail is None:
        issues.append(("critical", "detail_missing"))
        return issues

    if analysis is None:
        issues.append(("critical", "analysis_missing"))
        return issues

    if detail.price <= 0:
        issues.append(("critical", "price_invalid"))

    if detail.support_price > 0 and detail.resistance_price > 0 and detail.support_price >= detail.resistance_price:
        issues.append(("warning", "support_not_below_resistance"))

    if not detail.company_full_name.strip():
        issues.append(("warning", "company_full_name_empty"))

    if len(detail.company_intro.strip()) < 20:
        issues.append(("warning", "company_intro_too_short"))

    if len(getattr(detail, "industry_positioning", "").strip()) < 12:
        issues.append(("warning", "industry_positioning_too_short"))

    if len(getattr(detail, "business_scope", []) or []) < 1:
        issues.append(("warning", "business_scope_missing"))

    if len(getattr(detail, "market_coverage", []) or []) < 1:
        issues.append(("warning", "market_coverage_missing"))

    if len(getattr(detail, "company_highlights", []) or []) < 1:
        issues.append(("warning", "company_highlights_missing"))

    for field in REQUIRED_URL_FIELDS:
        value = getattr(detail, field, None)
        if not _is_url(value):
            issues.append(("warning", f"url_invalid_{field}"))

    if is_placeholder_company_website(getattr(detail, "company_website", None)):
        issues.append(("warning", "company_website_placeholder"))

    if len(detail.financial_reports) < 3:
        issues.append(("warning", "financial_reports_insufficient"))

    if len(detail.valuation_history) < 3:
        issues.append(("warning", "valuation_history_insufficient"))

    if len(detail.dividend_history) < 1:
        issues.append(("warning", "dividend_history_missing"))

    if len(detail.shareholder_structure) < 1:
        issues.append(("warning", "shareholder_structure_missing"))

    if len(detail.key_risks) < 1:
        issues.append(("warning", "key_risks_missing"))

    if len(detail.catalyst_events) < 1:
        issues.append(("warning", "catalyst_events_missing"))

    if len(detail.news_highlights) < 1:
        issues.append(("warning", "news_highlights_missing"))

    if not (0 <= analysis.score <= 100):
        issues.append(("critical", "analysis_score_out_of_range"))

    factor_values = [
        analysis.factor_scores.fundamental,
        analysis.factor_scores.valuation,
        analysis.factor_scores.momentum,
        analysis.factor_scores.sentiment,
        analysis.factor_scores.risk_control,
    ]
    if any(value < 0 or value > 100 for value in factor_values):
        issues.append(("critical", "factor_score_out_of_range"))

    if analysis.recommendation not in {"buy", "watch", "hold_cautious", "avoid"}:
        issues.append(("critical", "recommendation_invalid"))

    if enrichment is None:
        issues.append(("warning", "enrichment_missing"))
    else:
        if enrichment.coverage_score is None or enrichment.coverage_score < 60:
            issues.append(("warning", "enrichment_coverage_low"))

        if enrichment.status not in {"success", "partial"}:
            issues.append(("warning", "enrichment_status_not_success"))

    return issues


def _build_fast_snapshot(row: StockUniverse, enrichment: Optional[StockEnrichment]):
    detail = _build_stock_detail_from_row(row)
    if enrichment is not None:
        detail = merge_stock_detail_with_enrichment(base_detail=detail, enrichment=enrichment)
    detail = _decorate_company_profile(detail)
    analysis = _build_analysis_from_detail(detail)
    return detail, analysis


def main() -> int:
    args = parse_args()

    Base.metadata.create_all(bind=engine)
    output_json_path = Path(args.output_json)
    output_csv_path = Path(args.output_csv)
    output_json_path.parent.mkdir(parents=True, exist_ok=True)
    output_csv_path.parent.mkdir(parents=True, exist_ok=True)

    db = SessionLocal()
    try:
        query = db.query(StockUniverse).filter(StockUniverse.listed.is_(True))
        if args.market:
            query = query.filter(StockUniverse.market == args.market)

        rows = query.order_by(StockUniverse.symbol.asc()).all()
        if args.limit:
            rows = rows[: max(0, args.limit)]

        issue_counter: Counter[str] = Counter()
        severity_counter: Counter[str] = Counter()
        market_counter: Dict[str, Counter[str]] = defaultdict(Counter)

        detail_missing = 0
        analysis_missing = 0
        passed_count = 0
        warning_only_count = 0
        failed_count = 0
        scores: List[float] = []
        issue_rows: List[Dict[str, str]] = []

        enrichment_map = {item.symbol: item for item in db.query(StockEnrichment).all()} if args.fast else {}

        for row in rows:
            enrichment = enrichment_map.get(row.symbol) if args.fast else db.query(StockEnrichment).filter(StockEnrichment.symbol == row.symbol).first()
            if args.fast:
                detail, analysis = _build_fast_snapshot(row=row, enrichment=enrichment)
            else:
                detail = get_stock_detail(db=db, symbol=row.symbol)
                analysis = get_stock_analysis(db=db, symbol=row.symbol)

            issues = _validate_symbol(
                symbol=row.symbol,
                detail=detail,
                analysis=analysis,
                enrichment=enrichment,
            )

            critical_count = len([1 for severity, _ in issues if severity == "critical"])
            warning_count = len([1 for severity, _ in issues if severity == "warning"])
            score = _score_from_issue_count(critical=critical_count, warning=warning_count)
            scores.append(score)

            if not issues:
                passed_count += 1
            elif critical_count == 0:
                warning_only_count += 1
            else:
                failed_count += 1

            if detail is None:
                detail_missing += 1
            if analysis is None:
                analysis_missing += 1

            for severity, code in issues:
                issue_counter[code] += 1
                severity_counter[severity] += 1
                market_counter[row.market][code] += 1
                issue_rows.append(
                    {
                        "symbol": row.symbol,
                        "name": row.name,
                        "market": row.market,
                        "severity": severity,
                        "issue_code": code,
                    }
                )

        total = len(rows)
        avg_score = round(sum(scores) / len(scores), 2) if scores else 0.0

        summary = {
            "mode": "fast" if args.fast else "live",
            "total": total,
            "passed": passed_count,
            "warning_only": warning_only_count,
            "failed": failed_count,
            "detail_missing": detail_missing,
            "analysis_missing": analysis_missing,
            "avg_quality_score": avg_score,
            "pass_rate": round((passed_count / total * 100), 2) if total else 0.0,
            "issue_count_by_severity": dict(severity_counter),
            "top_issues": issue_counter.most_common(20),
            "market_issue_snapshot": {
                market: counter.most_common(8)
                for market, counter in market_counter.items()
            },
        }

        with output_json_path.open("w", encoding="utf-8") as fp:
            json.dump(summary, fp, ensure_ascii=False, indent=2)

        with output_csv_path.open("w", encoding="utf-8", newline="") as fp:
            writer = csv.DictWriter(
                fp,
                fieldnames=["symbol", "name", "market", "severity", "issue_code"],
            )
            writer.writeheader()
            writer.writerows(issue_rows)

        print("verification_total:", total)
        print("verification_passed:", passed_count)
        print("verification_warning_only:", warning_only_count)
        print("verification_failed:", failed_count)
        print("verification_avg_quality_score:", avg_score)
        print("summary_json:", str(output_json_path))
        print("issues_csv:", str(output_csv_path))

        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())

