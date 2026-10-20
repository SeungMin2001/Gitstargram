import base64
import hashlib
import secrets
from datetime import datetime, timezone
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .database import session_scope
from .github import GitHubClient, GitHubError, exchange_code, expiry_from_seconds
from .models import AuthSession, GitHubAccount, Interaction, User, UserRepository, utcnow
from .security import COOKIE_NAME, STATE_COOKIE, VERIFIER_COOKIE, current_user, encrypt, new_session, require_same_origin, token_hash
from .sync import enqueue_sync


router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.get("/login")
async def login():
    config = settings()
    if not config.github_client_id or not config.github_client_secret or len(config.session_secret) < 32:
        raise HTTPException(503, "GitHub App credentials are not configured")
    state = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    params = urlencode({
        "client_id": config.github_client_id,
        "redirect_uri": f"{config.backend_url}/api/auth/callback",
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    })
    response = RedirectResponse(f"https://github.com/login/oauth/authorize?{params}")
    response.set_cookie(STATE_COOKIE, state, httponly=True, secure=config.cookie_secure, samesite="lax", max_age=600, path="/api/auth")
    response.set_cookie(VERIFIER_COOKIE, verifier, httponly=True, secure=config.cookie_secure, samesite="lax", max_age=600, path="/api/auth")
    return response


@router.get("/callback")
async def callback(request: Request, code: str | None = None, state: str | None = None, db: AsyncSession = Depends(session_scope)):
    config = settings()
    expected = request.cookies.get(STATE_COOKIE)
    verifier = request.cookies.get(VERIFIER_COOKIE)
    if not code or not state or not expected or not verifier or not secrets.compare_digest(state, expected):
        raise HTTPException(400, "Invalid OAuth state or code")
    try:
        token_data = await exchange_code(code, verifier)
        async with GitHubClient(token_data["access_token"]) as github:
            profile = await github.get("/user")
    except GitHubError as exc:
        raise HTTPException(502, str(exc)) from exc
    user = await db.scalar(select(User).where(User.github_id == profile["id"]))
    if not user:
        user = User(github_id=profile["id"], login=profile["login"], html_url=profile["html_url"])
        db.add(user)
        await db.flush()
    user.login = profile["login"]
    user.name = profile.get("name")
    user.avatar_url = profile.get("avatar_url")
    user.bio = profile.get("bio")
    user.html_url = profile["html_url"]
    user.public_repos = profile.get("public_repos", 0)
    user.followers = profile.get("followers", 0)
    user.following = profile.get("following", 0)
    user.updated_at = utcnow()
    account = await db.get(GitHubAccount, user.id)
    if not account:
        account = GitHubAccount(user_id=user.id, encrypted_token="")
        db.add(account)
    account.encrypted_token = encrypt(token_data["access_token"])
    account.token_expires_at = expiry_from_seconds(token_data.get("expires_in"))
    account.refresh_token = encrypt(token_data["refresh_token"]) if token_data.get("refresh_token") else None
    account.refresh_token_expires_at = expiry_from_seconds(token_data.get("refresh_token_expires_in"))
    account.updated_at = utcnow()
    session_token, hashed, expires_at = new_session()
    db.add(AuthSession(user_id=user.id, token_hash=hashed, expires_at=expires_at))
    await db.commit()
    try:
        await enqueue_sync(db, user.id)
    except RuntimeError:
        pass  # Login remains valid; the sync status endpoint exposes the failure.
    response = RedirectResponse(config.frontend_url, status_code=303)
    response.delete_cookie(STATE_COOKIE, path="/api/auth")
    response.delete_cookie(VERIFIER_COOKIE, path="/api/auth")
    response.set_cookie(COOKIE_NAME, session_token, httponly=True, secure=config.cookie_secure, samesite="lax", max_age=7 * 86400, path="/")
    return response


@router.post("/logout", dependencies=[Depends(require_same_origin)])
async def logout(request: Request, db: AsyncSession = Depends(session_scope)):
    token = request.cookies.get(COOKIE_NAME)
    if token:
        await db.execute(delete(AuthSession).where(AuthSession.token_hash == token_hash(token)))
        await db.commit()
    response = Response(status_code=204)
    response.delete_cookie(COOKIE_NAME, path="/")
    return response


@router.post("/disconnect", dependencies=[Depends(require_same_origin)])
async def disconnect(user: User = Depends(current_user), db: AsyncSession = Depends(session_scope)):
    await db.execute(delete(GitHubAccount).where(GitHubAccount.user_id == user.id))
    await db.execute(delete(UserRepository).where(UserRepository.user_id == user.id))
    await db.execute(delete(Interaction).where(Interaction.user_id == user.id))
    await db.commit()
    return {"status": "disconnected"}


@router.delete("/account", dependencies=[Depends(require_same_origin)])
async def delete_account(user: User = Depends(current_user), db: AsyncSession = Depends(session_scope)):
    await db.delete(user)
    await db.commit()
    response = Response(status_code=204)
    response.delete_cookie(COOKIE_NAME, path="/")
    return response

