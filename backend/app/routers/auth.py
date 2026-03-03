from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.database import get_db
from app.models.user_platform import AppUser
from app.schemas.account import (
    AuthTokenResponse,
    LoginRequest,
    PasswordForgotRequest,
    PasswordForgotResponse,
    PasswordResetRequest,
    PasswordResetResponse,
    RegisterRequest,
    UserPublic,
)
from app.services.auth_service import (
    authenticate_user,
    create_access_token,
    issue_password_reset_code,
    register_user,
    reset_password_with_code,
)

router = APIRouter(prefix="/auth", tags=["auth"])


def _build_auth_response(user: AppUser) -> AuthTokenResponse:
    token, expires_in = create_access_token(user.id)
    return AuthTokenResponse(access_token=token, expires_in=expires_in, user=UserPublic.model_validate(user))


@router.post("/register", response_model=AuthTokenResponse, status_code=status.HTTP_201_CREATED)
def register_endpoint(payload: RegisterRequest, db: Session = Depends(get_db)) -> AuthTokenResponse:
    try:
        user = register_user(
            db=db,
            username=payload.username,
            email=payload.email,
            password=payload.password,
            display_name=payload.display_name,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    return _build_auth_response(user)


@router.post("/login", response_model=AuthTokenResponse)
def login_endpoint(payload: LoginRequest, db: Session = Depends(get_db)) -> AuthTokenResponse:
    user = authenticate_user(db=db, account=payload.account, password=payload.password)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="账号或密码错误")
    return _build_auth_response(user)


@router.post("/password/forgot", response_model=PasswordForgotResponse)
def password_forgot_endpoint(payload: PasswordForgotRequest, db: Session = Depends(get_db)) -> PasswordForgotResponse:
    reset_code, expire_minutes = issue_password_reset_code(db=db, account=payload.account)
    return PasswordForgotResponse(
        message="如账号存在，系统已生成重置验证码。",
        expires_in_minutes=expire_minutes,
        reset_code=reset_code,
    )


@router.post("/password/reset", response_model=PasswordResetResponse)
def password_reset_endpoint(payload: PasswordResetRequest, db: Session = Depends(get_db)) -> PasswordResetResponse:
    success = reset_password_with_code(
        db=db,
        account=payload.account,
        code=payload.code,
        new_password=payload.new_password,
    )
    if not success:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="验证码无效或已过期")
    return PasswordResetResponse(message="密码已重置，请使用新密码登录")


@router.get("/me", response_model=UserPublic)
def me_endpoint(user: AppUser = Depends(get_current_user)) -> UserPublic:
    return UserPublic.model_validate(user)
