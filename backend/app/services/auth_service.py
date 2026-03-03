import base64
import hashlib
import hmac
import json
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.user_platform import AppUser, PasswordResetToken

PBKDF2_ITERATIONS = 390000
HASH_ALGO = "sha256"
_admin_seed_done = False


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("utf-8").rstrip("=")


def _b64url_decode(raw: str) -> bytes:
    padded = raw + "=" * ((4 - len(raw) % 4) % 4)
    return base64.urlsafe_b64decode(padded.encode("utf-8"))


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(HASH_ALGO, password.encode("utf-8"), salt.encode("utf-8"), PBKDF2_ITERATIONS).hex()
    return f"pbkdf2_{HASH_ALGO}${PBKDF2_ITERATIONS}${salt}${digest}"


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        method, iter_text, salt, digest = stored_hash.split("$", maxsplit=3)
    except ValueError:
        return False

    if not method.startswith("pbkdf2_"):
        return False

    algo = method.replace("pbkdf2_", "", 1)
    try:
        iterations = int(iter_text)
    except ValueError:
        return False

    computed = hashlib.pbkdf2_hmac(algo, password.encode("utf-8"), salt.encode("utf-8"), iterations).hex()
    return hmac.compare_digest(computed, digest)


def _hash_reset_code(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def _sign_token(message: str, secret: str) -> str:
    signature = hmac.new(secret.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).digest()
    return _b64url_encode(signature)


def create_access_token(user_id: int) -> Tuple[str, int]:
    settings = get_settings()
    expires_in = max(30, int(settings.auth_token_expire_minutes)) * 60
    expire_at = int(datetime.now(timezone.utc).timestamp()) + expires_in

    header = {"alg": "HS256", "typ": "JWT"}
    payload = {"sub": str(user_id), "exp": expire_at}

    header_encoded = _b64url_encode(json.dumps(header, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
    payload_encoded = _b64url_encode(json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
    signing_input = f"{header_encoded}.{payload_encoded}"
    signature = _sign_token(signing_input, settings.auth_secret)
    token = f"{signing_input}.{signature}"
    return token, expires_in


def parse_access_token(token: str) -> Optional[int]:
    settings = get_settings()

    try:
        header_encoded, payload_encoded, signature = token.split(".", maxsplit=2)
    except ValueError:
        return None

    signing_input = f"{header_encoded}.{payload_encoded}"
    expected_signature = _sign_token(signing_input, settings.auth_secret)
    if not hmac.compare_digest(signature, expected_signature):
        return None

    try:
        payload = json.loads(_b64url_decode(payload_encoded))
    except Exception:
        return None

    exp = payload.get("exp")
    sub = payload.get("sub")

    if not isinstance(exp, int):
        return None
    if datetime.now(timezone.utc).timestamp() >= exp:
        return None

    try:
        return int(sub)
    except (TypeError, ValueError):
        return None


def find_user_by_account(db: Session, account: str) -> Optional[AppUser]:
    normalized = account.strip().lower()
    if not normalized:
        return None

    return (
        db.query(AppUser)
        .filter(
            or_(
                func.lower(AppUser.username) == normalized,
                func.lower(AppUser.email) == normalized,
            )
        )
        .first()
    )


def ensure_admin_seeded(db: Session) -> None:
    global _admin_seed_done
    if _admin_seed_done:
        return

    settings = get_settings()
    admin_username = settings.bootstrap_admin_username.strip() or "tianyuyezi"
    admin_password = settings.bootstrap_admin_password if len(settings.bootstrap_admin_password) >= 8 else "88888888"
    admin_email = settings.bootstrap_admin_email.strip().lower() or f"{admin_username}@stock-assistant.local"

    admin_user = db.query(AppUser).filter(func.lower(AppUser.username) == admin_username.lower()).first()
    changed = False

    if admin_user is None:
        email_owner = db.query(AppUser).filter(func.lower(AppUser.email) == admin_email).first()
        if email_owner is not None:
            admin_email = f"{admin_username}_{int(utc_now().timestamp())}@stock-assistant.local"

        admin_user = AppUser(
            username=admin_username,
            email=admin_email,
            display_name="系统管理员",
            password_hash=hash_password(admin_password),
            role="admin",
            is_active=True,
        )
        db.add(admin_user)
        changed = True
    else:
        if admin_user.role != "admin":
            admin_user.role = "admin"
            changed = True
        if not admin_user.is_active:
            admin_user.is_active = True
            changed = True
        if not verify_password(admin_password, admin_user.password_hash):
            admin_user.password_hash = hash_password(admin_password)
            changed = True

    if changed:
        db.commit()

    admin_exists = db.query(AppUser.id).filter(AppUser.role == "admin").first() is not None
    if not admin_exists:
        first_user = db.query(AppUser).order_by(AppUser.id.asc()).first()
        if first_user is not None:
            first_user.role = "admin"
            db.add(first_user)
            db.commit()

    _admin_seed_done = True


def register_user(
    db: Session,
    username: str,
    email: str,
    password: str,
    display_name: Optional[str] = None,
) -> AppUser:
    ensure_admin_seeded(db)

    username_normalized = username.strip()
    email_normalized = email.strip().lower()

    existing = (
        db.query(AppUser)
        .filter(or_(func.lower(AppUser.username) == username_normalized.lower(), func.lower(AppUser.email) == email_normalized))
        .first()
    )
    if existing is not None:
        raise ValueError("用户名或邮箱已存在")

    user_count = db.query(func.count(AppUser.id)).scalar() or 0
    role = "admin" if int(user_count) == 0 else "user"

    user = AppUser(
        username=username_normalized,
        email=email_normalized,
        display_name=display_name.strip() if display_name else None,
        password_hash=hash_password(password),
        role=role,
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def authenticate_user(db: Session, account: str, password: str) -> Optional[AppUser]:
    ensure_admin_seeded(db)

    user = find_user_by_account(db, account)
    if user is None:
        return None
    if not user.is_active:
        return None
    if not verify_password(password, user.password_hash):
        return None

    user.last_login_at = utc_now()
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def issue_password_reset_code(db: Session, account: str) -> Tuple[Optional[str], int]:
    settings = get_settings()
    expire_minutes = max(5, int(settings.password_reset_code_expire_minutes))

    user = find_user_by_account(db, account)
    if user is None or not user.is_active:
        return None, expire_minutes

    now = utc_now()

    db.query(PasswordResetToken).filter(
        PasswordResetToken.user_id == user.id,
        PasswordResetToken.used_at.is_(None),
    ).update({PasswordResetToken.used_at: now}, synchronize_session=False)

    reset_code = f"{secrets.randbelow(1_000_000):06d}"
    token = PasswordResetToken(
        user_id=user.id,
        code_hash=_hash_reset_code(reset_code),
        expires_at=now + timedelta(minutes=expire_minutes),
    )

    db.add(token)
    db.commit()
    return reset_code, expire_minutes


def reset_password_with_code(db: Session, account: str, code: str, new_password: str) -> bool:
    user = find_user_by_account(db, account)
    if user is None or not user.is_active:
        return False

    now = utc_now()
    code_hash = _hash_reset_code(code.strip())

    token = (
        db.query(PasswordResetToken)
        .filter(
            PasswordResetToken.user_id == user.id,
            PasswordResetToken.code_hash == code_hash,
            PasswordResetToken.used_at.is_(None),
            PasswordResetToken.expires_at >= now,
        )
        .order_by(PasswordResetToken.created_at.desc())
        .first()
    )
    if token is None:
        return False

    user.password_hash = hash_password(new_password)
    token.used_at = now

    db.query(PasswordResetToken).filter(
        PasswordResetToken.user_id == user.id,
        PasswordResetToken.used_at.is_(None),
    ).update({PasswordResetToken.used_at: now}, synchronize_session=False)

    db.add(user)
    db.add(token)
    db.commit()
    return True
