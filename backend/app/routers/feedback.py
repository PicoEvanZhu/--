from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from app.core.auth import require_admin
from app.core.database import get_db
from app.models.user_platform import AppUser
from app.schemas.feedback import (
    FeedbackCreate,
    FeedbackCreateResponse,
    FeedbackListItem,
    FeedbackScope,
    FeedbackStatus,
    FeedbackStatusUpdate,
    FeedbackType,
)
from app.services.feedback_service import create_feedback, list_feedbacks, update_feedback_status
from app.services.rate_limit_service import RateLimitExceeded, assert_feedback_rate_limit

router = APIRouter(prefix="/feedbacks", tags=["feedbacks"])


def _resolve_identity(request: Request, payload: FeedbackCreate) -> str:
    meta = payload.meta_json or {}
    device_id = str(meta.get("device_id") or "")
    user_id = payload.user_id or ""

    forwarded_for = request.headers.get("x-forwarded-for", "")
    if forwarded_for:
        ip = forwarded_for.split(",")[0].strip()
    else:
        ip = request.client.host if request.client else "unknown"

    identity_parts = [ip]
    if device_id:
        identity_parts.append(device_id)
    if user_id:
        identity_parts.append(user_id)

    return "|".join(identity_parts)


@router.post("", response_model=FeedbackCreateResponse, status_code=status.HTTP_201_CREATED)
def create_feedback_endpoint(
    payload: FeedbackCreate,
    request: Request,
    db: Session = Depends(get_db),
) -> FeedbackCreateResponse:
    identity = _resolve_identity(request, payload)

    try:
        assert_feedback_rate_limit(identity)
    except RateLimitExceeded as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=exc.message,
            headers={"Retry-After": str(exc.retry_after)},
        )

    feedback = create_feedback(db, payload)
    return FeedbackCreateResponse(feedback_id=feedback.id)


@router.get("", response_model=list[FeedbackListItem])
def list_feedbacks_endpoint(
    limit: int = Query(default=100, ge=1, le=500),
    status: Optional[FeedbackStatus] = Query(default=None),
    feedback_type: Optional[FeedbackType] = Query(default=None, alias="type"),
    scope: Optional[FeedbackScope] = Query(default=None),
    _: AppUser = Depends(require_admin),
    db: Session = Depends(get_db),
) -> list[FeedbackListItem]:
    return list_feedbacks(db=db, limit=limit, status=status, feedback_type=feedback_type, scope=scope)


@router.patch("/{feedback_id}/status", response_model=FeedbackListItem)
def update_feedback_status_endpoint(
    feedback_id: int,
    payload: FeedbackStatusUpdate,
    _: AppUser = Depends(require_admin),
    db: Session = Depends(get_db),
) -> FeedbackListItem:
    feedback = update_feedback_status(db, feedback_id=feedback_id, status=payload.status)
    if feedback is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="反馈不存在")
    return feedback
