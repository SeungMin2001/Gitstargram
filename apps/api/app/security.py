import base64
import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from cryptography.fernet import Fernet
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .database import session_scope
from .models import AuthSession, User


COOKIE_NAME = "gitstargram_session"
STATE_COOKIE = "gitstargram_oauth_state"
VERIFIER_COOKIE = "gitstargram_pkce_verifier"


def cipher() -> Fernet:
    secret = settings().session_secret
    if len(secret) < 32:
        raise RuntimeError("SESSION_SECRET must be at least 32 characters")
    key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest())
    return Fernet(key)


def encrypt(value: str) -> str:
    return cipher().encrypt(value.encode()).decode()


def decrypt(value: str) -> str:
    return cipher().decrypt(value.encode()).decode()


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_session() -> tuple[str, str, datetime]:
    token = secrets.token_urlsafe(48)
    return token, token_hash(token), datetime.now(timezone.utc) + timedelta(days=7)


async def current_user(request: Request, db: AsyncSession = Depends(session_scope)) -> User:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Login required")
    query = (
        select(User)
        .join(AuthSession, AuthSession.user_id == User.id)
        .where(AuthSession.token_hash == token_hash(token), AuthSession.expires_at > datetime.now(timezone.utc))
    )
    user = await db.scalar(query)
    if not user:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired")
    return user


def require_same_origin(request: Request) -> None:
    origin = request.headers.get("origin")
    if origin != settings().frontend_url:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Invalid request origin")

