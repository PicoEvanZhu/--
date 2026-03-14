import logging
from threading import Thread
from time import perf_counter, sleep

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import inspect, text

from app import models as _models  # noqa: F401
from app.core.config import get_settings
from app.core.database import Base, SessionLocal, engine
from app.routers.admin import router as admin_router
from app.routers.auth import router as auth_router
from app.routers.dashboard import router as dashboard_router
from app.routers.feedback import router as feedback_router
from app.routers.health import router as health_router
from app.routers.me import router as me_router
from app.routers.reports import router as reports_router
from app.services.notification_service import run_watch_monitor_cycle
from app.services.main_force_service import run_main_force_schedule
from app.services.stock_service import get_sector_rotation_summary, get_stock_list
from app.routers.stocks import router as stocks_router

settings = get_settings()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("stock_assistant")

app = FastAPI(title=settings.app_name)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_log_middleware(request: Request, call_next):
    started = perf_counter()
    response = await call_next(request)
    elapsed_ms = (perf_counter() - started) * 1000

    logger.info(
        "%s %s -> %s (%.2fms)",
        request.method,
        request.url.path,
        response.status_code,
        elapsed_ms,
    )
    return response


Base.metadata.create_all(bind=engine)


def _apply_runtime_migrations() -> None:
    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())

    with engine.begin() as connection:
        if "trade_reviews" in table_names:
            columns = {column["name"] for column in inspector.get_columns("trade_reviews")}
            indexes = {index["name"] for index in inspector.get_indexes("trade_reviews")}
            if "user_id" not in columns:
                connection.execute(text("ALTER TABLE trade_reviews ADD COLUMN user_id INTEGER"))
            if "idx_trade_reviews_user_symbol" not in indexes:
                connection.execute(text("CREATE INDEX idx_trade_reviews_user_symbol ON trade_reviews(user_id, symbol)"))

        if "user_watchlist_items" in table_names:
            columns = {column["name"] for column in inspector.get_columns("user_watchlist_items")}
            if "monitor_enabled" not in columns:
                connection.execute(text("ALTER TABLE user_watchlist_items ADD COLUMN monitor_enabled BOOLEAN NOT NULL DEFAULT 0"))
            if "monitor_interval_minutes" not in columns:
                connection.execute(text("ALTER TABLE user_watchlist_items ADD COLUMN monitor_interval_minutes INTEGER NOT NULL DEFAULT 15"))
            if "monitor_focus_json" not in columns:
                connection.execute(text("ALTER TABLE user_watchlist_items ADD COLUMN monitor_focus_json TEXT"))
            if "monitor_last_checked_at" not in columns:
                connection.execute(text("ALTER TABLE user_watchlist_items ADD COLUMN monitor_last_checked_at DATETIME"))
            if "monitor_last_summary" not in columns:
                connection.execute(text("ALTER TABLE user_watchlist_items ADD COLUMN monitor_last_summary TEXT"))
            if "monitor_last_signal_level" not in columns:
                connection.execute(text("ALTER TABLE user_watchlist_items ADD COLUMN monitor_last_signal_level VARCHAR(16)"))
            if "monitor_last_notified_at" not in columns:
                connection.execute(text("ALTER TABLE user_watchlist_items ADD COLUMN monitor_last_notified_at DATETIME"))

        if "user_notification_settings" in table_names:
            columns = {column["name"] for column in inspector.get_columns("user_notification_settings")}
            if "enable_watch_monitor_alert" not in columns:
                connection.execute(text("ALTER TABLE user_notification_settings ADD COLUMN enable_watch_monitor_alert BOOLEAN NOT NULL DEFAULT 1"))


_apply_runtime_migrations()


def _warm_runtime_caches() -> None:
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))

        db = SessionLocal()
        try:
            get_stock_list(db=db, page=1, page_size=20)
            get_sector_rotation_summary(db=db, top_n=8)
        finally:
            db.close()
        logger.info("runtime caches warmed")
    except Exception as exc:
        logger.warning("runtime warmup skipped: %s", exc)


def _watch_monitor_loop() -> None:
    while True:
        try:
            db = SessionLocal()
            try:
                created = run_watch_monitor_cycle(db=db)
                if created > 0:
                    logger.info("watch monitor cycle created %s notifications", created)
            finally:
                db.close()
        except Exception as exc:
            logger.warning("watch monitor cycle skipped: %s", exc)
        sleep(60)


def _main_force_loop() -> None:
    while True:
        try:
            db = SessionLocal()
            try:
                ran = run_main_force_schedule(db=db)
                if ran:
                    logger.info("main force scan completed")
            finally:
                db.close()
        except Exception as exc:
            logger.warning("main force scan skipped: %s", exc)
        sleep(60)


@app.on_event("startup")
def _schedule_runtime_warmup() -> None:
    Thread(target=_warm_runtime_caches, daemon=True).start()
    Thread(target=_watch_monitor_loop, daemon=True).start()
    Thread(target=_main_force_loop, daemon=True).start()


app.include_router(health_router, prefix=settings.api_prefix)
app.include_router(auth_router, prefix=settings.api_prefix)
app.include_router(admin_router, prefix=settings.api_prefix)
app.include_router(feedback_router, prefix=settings.api_prefix)
app.include_router(stocks_router, prefix=settings.api_prefix)
app.include_router(reports_router, prefix=settings.api_prefix)
app.include_router(dashboard_router, prefix=settings.api_prefix)
app.include_router(me_router, prefix=settings.api_prefix)
