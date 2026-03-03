#!/usr/bin/env python3

from pathlib import Path
import os
import sys


ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT / "backend"
os.chdir(BACKEND_DIR)

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app import models as _models  # noqa: E402,F401
from app.core.database import Base, SessionLocal, engine  # noqa: E402
from app.services.stock_service import sync_stock_universe  # noqa: E402


def main() -> int:
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        result = sync_stock_universe(db=db, force=True)
        print("success:", result.success)
        print("total_count:", result.total_count)
        print("a_share_count:", result.a_share_count)
        print("hk_count:", result.hk_count)
        print("duration_ms:", result.duration_ms)
        print("last_synced_at:", result.last_synced_at)
        print("message:", result.message)
        return 0 if result.success else 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
