from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.database import get_db
from app.models.user_platform import AppUser
from app.schemas.account import (
    FollowUpStatus,
    NotificationListResponse,
    NotificationReadResponse,
    NotificationRefreshResponse,
    NotificationSetting,
    NotificationSettingUpdate,
    PositionAnalysisResponse,
    PositionCreate,
    PositionFollowUpCreate,
    PositionFollowUpItem,
    PositionFollowUpListResponse,
    PositionFollowUpUpdate,
    PositionListResponse,
    PositionSnapshot,
    PositionUpdate,
    WatchlistItem,
    WatchlistItemCreate,
    WatchlistItemUpdate,
    WatchlistListResponse,
)
from app.services.portfolio_service import (
    analyze_user_positions,
    create_user_follow_up,
    create_user_position,
    create_user_watchlist_item,
    delete_user_follow_up,
    delete_user_position,
    delete_user_watchlist_item,
    list_user_follow_ups,
    list_user_positions,
    list_user_watchlist,
    update_user_follow_up,
    update_user_position,
    update_user_watchlist_item,
)
from app.services.notification_service import (
    get_user_notification_setting,
    list_user_notifications,
    mark_user_notification_read,
    refresh_user_notifications,
    update_user_notification_setting,
)

router = APIRouter(prefix="/me", tags=["me"])


@router.get("/watchlist", response_model=WatchlistListResponse)
def list_watchlist_endpoint(
    user: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> WatchlistListResponse:
    return list_user_watchlist(db=db, user_id=user.id)


@router.post("/watchlist", response_model=WatchlistItem, status_code=status.HTTP_201_CREATED)
def create_watchlist_endpoint(
    payload: WatchlistItemCreate,
    user: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> WatchlistItem:
    try:
        return create_user_watchlist_item(db=db, user_id=user.id, payload=payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.patch("/watchlist/{item_id}", response_model=WatchlistItem)
def update_watchlist_endpoint(
    item_id: int,
    payload: WatchlistItemUpdate,
    user: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> WatchlistItem:
    item = update_user_watchlist_item(db=db, user_id=user.id, item_id=item_id, payload=payload)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="自选项不存在")
    return item


@router.delete("/watchlist/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_watchlist_endpoint(
    item_id: int,
    user: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    deleted = delete_user_watchlist_item(db=db, user_id=user.id, item_id=item_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="自选项不存在")


@router.get("/positions", response_model=PositionListResponse)
def list_positions_endpoint(
    user: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PositionListResponse:
    return list_user_positions(db=db, user_id=user.id)


@router.post("/positions", response_model=PositionSnapshot, status_code=status.HTTP_201_CREATED)
def create_position_endpoint(
    payload: PositionCreate,
    user: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PositionSnapshot:
    try:
        return create_user_position(db=db, user_id=user.id, payload=payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.patch("/positions/{position_id}", response_model=PositionSnapshot)
def update_position_endpoint(
    position_id: int,
    payload: PositionUpdate,
    user: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PositionSnapshot:
    position = update_user_position(db=db, user_id=user.id, position_id=position_id, payload=payload)
    if position is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="持仓不存在")
    return position


@router.delete("/positions/{position_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_position_endpoint(
    position_id: int,
    user: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    deleted = delete_user_position(db=db, user_id=user.id, position_id=position_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="持仓不存在")


@router.get("/positions/analysis", response_model=PositionAnalysisResponse)
def analyze_positions_endpoint(
    user: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PositionAnalysisResponse:
    return analyze_user_positions(db=db, user_id=user.id)


@router.get("/followups", response_model=PositionFollowUpListResponse)
def list_followups_endpoint(
    position_id: Optional[int] = Query(default=None, ge=1),
    follow_up_status: Optional[FollowUpStatus] = Query(default=None, alias="status"),
    user: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PositionFollowUpListResponse:
    return list_user_follow_ups(db=db, user_id=user.id, position_id=position_id, status=follow_up_status)


@router.post("/followups", response_model=PositionFollowUpItem, status_code=status.HTTP_201_CREATED)
def create_followup_endpoint(
    payload: PositionFollowUpCreate,
    user: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PositionFollowUpItem:
    try:
        return create_user_follow_up(db=db, user_id=user.id, payload=payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.patch("/followups/{follow_up_id}", response_model=PositionFollowUpItem)
def update_followup_endpoint(
    follow_up_id: int,
    payload: PositionFollowUpUpdate,
    user: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PositionFollowUpItem:
    follow_up = update_user_follow_up(db=db, user_id=user.id, follow_up_id=follow_up_id, payload=payload)
    if follow_up is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="跟进记录不存在")
    return follow_up


@router.delete("/followups/{follow_up_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_followup_endpoint(
    follow_up_id: int,
    user: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    deleted = delete_user_follow_up(db=db, user_id=user.id, follow_up_id=follow_up_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="跟进记录不存在")


@router.get("/notification-settings", response_model=NotificationSetting)
def get_notification_settings_endpoint(
    user: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> NotificationSetting:
    return get_user_notification_setting(db=db, user_id=user.id)


@router.patch("/notification-settings", response_model=NotificationSetting)
def update_notification_settings_endpoint(
    payload: NotificationSettingUpdate,
    user: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> NotificationSetting:
    return update_user_notification_setting(db=db, user_id=user.id, payload=payload)


@router.post("/notifications/refresh", response_model=NotificationRefreshResponse)
def refresh_notifications_endpoint(
    user: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> NotificationRefreshResponse:
    return refresh_user_notifications(db=db, user_id=user.id)


@router.get("/notifications", response_model=NotificationListResponse)
def list_notifications_endpoint(
    unread_only: bool = Query(default=False),
    limit: int = Query(default=100, ge=1, le=300),
    user: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> NotificationListResponse:
    return list_user_notifications(db=db, user_id=user.id, unread_only=unread_only, limit=limit)


@router.post("/notifications/{notification_id}/read", response_model=NotificationReadResponse)
def mark_notification_read_endpoint(
    notification_id: int,
    user: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> NotificationReadResponse:
    result = mark_user_notification_read(db=db, user_id=user.id, notification_id=notification_id)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="通知不存在")
    return result
