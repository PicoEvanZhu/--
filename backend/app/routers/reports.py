from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.stock import ReportDetail, ReportListItem
from app.services.stock_service import get_report_detail, get_report_list

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("", response_model=list[ReportListItem])
def list_reports(
    q: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
) -> list[ReportListItem]:
    return get_report_list(db=db, q=q)


@router.get("/{symbol}", response_model=ReportDetail)
def get_report(symbol: str, db: Session = Depends(get_db)) -> ReportDetail:
    report = get_report_detail(db=db, symbol=symbol)
    if report is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="报告不存在")
    return report
