#!/usr/bin/env python3

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT / "backend"
os.chdir(BACKEND_DIR)

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app import models as _models  # noqa: E402,F401
from app.core.database import Base, SessionLocal, engine  # noqa: E402
from app.services.enrichment_service import enrich_stock_universe, get_enrichment_status  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="全量股票详情补齐（逐股联网抓取）")
    parser.add_argument("--market", choices=["A股", "港股", "创业板", "科创板"], default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--sleep-ms", type=int, default=120)
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        before = get_enrichment_status(db=db)
        print("[before] coverage_rate:", before.coverage_rate, "enriched_count:", before.enriched_count)

        result = enrich_stock_universe(
            db=db,
            market=args.market,
            limit=args.limit,
            force=args.force,
            sleep_ms=args.sleep_ms,
        )

        after = get_enrichment_status(db=db)

        print("success:", result.success)
        print("total_universe:", result.total)
        print("processed:", result.processed)
        print("success_count:", result.success_count)
        print("failed_count:", result.failed_count)
        print("skipped_count:", result.skipped_count)
        print("duration_ms:", result.duration_ms)
        print("message:", result.message)
        print("[after] coverage_rate:", after.coverage_rate, "enriched_count:", after.enriched_count)
        print("[after] latest_enriched_at:", after.latest_enriched_at)

        return 0 if result.success else 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
