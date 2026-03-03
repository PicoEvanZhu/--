import logging
from time import perf_counter

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import inspect, text

from app import models as _models  # noqa: F401
from app.core.config import get_settings
from app.core.database import Base, engine
from app.routers.admin import router as admin_router
from app.routers.auth import router as auth_router
from app.routers.dashboard import router as dashboard_router
from app.routers.feedback import router as feedback_router
from app.routers.health import router as health_router
from app.routers.me import router as me_router
from app.routers.reports import router as reports_router
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
    if "trade_reviews" not in inspector.get_table_names():
        return

    columns = {column["name"] for column in inspector.get_columns("trade_reviews")}
    with engine.begin() as connection:
        if "user_id" not in columns:
            connection.execute(text("ALTER TABLE trade_reviews ADD COLUMN user_id INTEGER"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS idx_trade_reviews_user_symbol ON trade_reviews(user_id, symbol)"))


_apply_runtime_migrations()

app.include_router(health_router, prefix=settings.api_prefix)
app.include_router(auth_router, prefix=settings.api_prefix)
app.include_router(admin_router, prefix=settings.api_prefix)
app.include_router(feedback_router, prefix=settings.api_prefix)
app.include_router(stocks_router, prefix=settings.api_prefix)
app.include_router(reports_router, prefix=settings.api_prefix)
app.include_router(dashboard_router, prefix=settings.api_prefix)
app.include_router(me_router, prefix=settings.api_prefix)
