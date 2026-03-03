import json
from typing import Optional

from sqlalchemy.orm import Session

from app.models.feedback import Feedback
from app.schemas.feedback import FeedbackCreate, FeedbackStatus


def create_feedback(db: Session, payload: FeedbackCreate) -> Feedback:
    feedback = Feedback(
        user_id=payload.user_id,
        page=payload.page,
        type=payload.type,
        scope=payload.scope,
        content=payload.content,
        contact=payload.contact,
        screenshot_url=payload.screenshot_url,
        meta_json=json.dumps(payload.meta_json, ensure_ascii=False) if payload.meta_json else None,
        status="new",
    )
    db.add(feedback)
    db.commit()
    db.refresh(feedback)
    return feedback


def list_feedbacks(
    db: Session,
    limit: int = 100,
    status: Optional[FeedbackStatus] = None,
    feedback_type: Optional[str] = None,
    scope: Optional[str] = None,
) -> list[Feedback]:
    query = db.query(Feedback)

    if status:
        query = query.filter(Feedback.status == status)
    if feedback_type:
        query = query.filter(Feedback.type == feedback_type)
    if scope:
        query = query.filter(Feedback.scope == scope)

    return query.order_by(Feedback.created_at.desc()).limit(limit).all()


def update_feedback_status(db: Session, feedback_id: int, status: FeedbackStatus) -> Optional[Feedback]:
    feedback = db.query(Feedback).filter(Feedback.id == feedback_id).first()
    if feedback is None:
        return None

    feedback.status = status
    db.add(feedback)
    db.commit()
    db.refresh(feedback)
    return feedback
