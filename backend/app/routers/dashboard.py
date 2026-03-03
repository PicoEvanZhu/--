from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.stock import DashboardSummary
from app.services.stock_service import get_dashboard_summary

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/summary", response_model=DashboardSummary)
def get_dashboard_summary_endpoint(db: Session = Depends(get_db)) -> DashboardSummary:
    return get_dashboard_summary(db=db)
