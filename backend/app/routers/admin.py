from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.core.auth import require_admin
from app.core.database import get_db
from app.models.user_platform import AppUser
from app.schemas.account import AdminUserListResponse, AdminUserUpdateRequest, UserPublic

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/users", response_model=AdminUserListResponse)
def list_users_endpoint(
    limit: int = Query(default=200, ge=1, le=500),
    q: Optional[str] = Query(default=None, min_length=1, max_length=120),
    _: AppUser = Depends(require_admin),
    db: Session = Depends(get_db),
) -> AdminUserListResponse:
    query = db.query(AppUser)

    keyword = (q or "").strip().lower()
    if keyword:
        like = f"%{keyword}%"
        query = query.filter(
            or_(
                func.lower(AppUser.username).like(like),
                func.lower(AppUser.email).like(like),
                func.lower(func.coalesce(AppUser.display_name, "")).like(like),
            )
        )

    total = query.count()
    rows = query.order_by(AppUser.created_at.desc()).limit(limit).all()
    return AdminUserListResponse(total=total, items=[UserPublic.model_validate(row) for row in rows])


@router.patch("/users/{user_id}", response_model=UserPublic)
def update_user_endpoint(
    user_id: int,
    payload: AdminUserUpdateRequest,
    admin_user: AppUser = Depends(require_admin),
    db: Session = Depends(get_db),
) -> UserPublic:
    target = db.query(AppUser).filter(AppUser.id == user_id).first()
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")

    if payload.role is not None and payload.role != target.role:
        if target.role == "admin" and payload.role != "admin":
            active_admin_count = (
                db.query(func.count(AppUser.id))
                .filter(AppUser.role == "admin", AppUser.is_active.is_(True))
                .scalar()
                or 0
            )
            if int(active_admin_count) <= 1:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="至少需要保留一个可用管理员")
        target.role = payload.role

    if payload.is_active is not None and payload.is_active != target.is_active:
        if target.role == "admin" and not payload.is_active:
            active_admin_count = (
                db.query(func.count(AppUser.id))
                .filter(AppUser.role == "admin", AppUser.is_active.is_(True))
                .scalar()
                or 0
            )
            if int(active_admin_count) <= 1 and target.id == admin_user.id:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="不能禁用最后一个管理员账号")
        target.is_active = payload.is_active

    db.add(target)
    db.commit()
    db.refresh(target)
    return UserPublic.model_validate(target)
