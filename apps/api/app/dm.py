import asyncio
import json
from collections import defaultdict
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import insert

from .config import settings
from .database import SessionLocal, session_scope
from .models import (
    AuthSession,
    Conversation,
    ConversationMember,
    Message,
    Post,
    Repository,
    User,
    utcnow,
)
from .security import COOKIE_NAME, current_user, require_same_origin, token_hash
from .social import blocked_user_ids, create_notification


router = APIRouter(prefix="/api/dm", tags=["dm"])


class StartConversationInput(BaseModel):
    recipient_user_id: int


class SendMessageInput(BaseModel):
    body: str = Field(min_length=1, max_length=2000)
    shared_repository_id: int | None = None
    shared_post_id: int | None = None
    client_message_id: str | None = Field(default=None, max_length=64)

    @field_validator("body")
    @classmethod
    def nonempty_body(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Message must contain non-whitespace text")
        return value


class ConnectionHub:
    def __init__(self) -> None:
        self._connections: dict[int, set[WebSocket]] = defaultdict(set)

    async def connect(self, user_id: int, ws: WebSocket) -> None:
        await ws.accept()
        self._connections[user_id].add(ws)

    def disconnect(self, user_id: int, ws: WebSocket) -> None:
        self._connections[user_id].discard(ws)

    async def send_to_user(self, user_id: int, event: dict) -> None:
        dead: list[WebSocket] = []
        for ws in list(self._connections.get(user_id, set())):
            try:
                token = ws.cookies.get(COOKIE_NAME)
                async with SessionLocal() as db:
                    active_session = await db.scalar(select(AuthSession.id).where(
                        AuthSession.user_id == user_id,
                        AuthSession.token_hash == token_hash(token or ""),
                        AuthSession.expires_at > datetime.now(timezone.utc),
                    ))
                if active_session is None:
                    await ws.close(code=4401)
                    dead.append(ws)
                    continue
                await ws.send_json(event)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self._connections[user_id].discard(ws)


hub = ConnectionHub()


async def serialize_message(db: AsyncSession, msg: Message) -> dict:
    sender = await db.get(User, msg.sender_id)
    shared_repo = await db.get(Repository, msg.shared_repository_id) if msg.shared_repository_id else None
    shared_post = await db.get(Post, msg.shared_post_id) if msg.shared_post_id else None
    return {
        "id": msg.id,
        "conversation_id": msg.conversation_id,
        "sender": {
            "id": sender.id,
            "login": sender.login,
            "name": sender.name,
            "avatar_url": sender.avatar_url,
        }
        if sender
        else None,
        "body": msg.body,
        "shared_repository": {
            "id": shared_repo.id,
            "full_name": shared_repo.full_name,
            "html_url": shared_repo.html_url,
            "stars": shared_repo.stars,
        }
        if shared_repo and shared_repo.is_public
        else None,
        "shared_post": {
            "id": shared_post.id,
            "title": shared_post.title,
        }
        if shared_post
        else None,
        "client_message_id": msg.client_message_id,
        "created_at": msg.created_at.isoformat(),
    }


async def verify_member(db: AsyncSession, conversation_id: int, user_id: int) -> tuple[ConversationMember, list[int]]:
    members = list(
        await db.scalars(
            select(ConversationMember).where(ConversationMember.conversation_id == conversation_id)
        )
    )
    me_member = next((m for m in members if m.user_id == user_id), None)
    if not me_member:
        raise HTTPException(403, "Not a participant of this conversation")
    blocked = await blocked_user_ids(db, user_id)
    if any(member.user_id in blocked for member in members if member.user_id != user_id):
        raise HTTPException(403, "Messaging unavailable due to block settings")
    return me_member, [m.user_id for m in members]


@router.get("/conversations")
async def list_conversations(user: User = Depends(current_user), db: AsyncSession = Depends(session_scope)):
    blocked = await blocked_user_ids(db, user.id)
    my_memberships = list(
        await db.scalars(select(ConversationMember).where(ConversationMember.user_id == user.id))
    )
    if not my_memberships:
        return {"items": []}
    conv_ids = [m.conversation_id for m in my_memberships]
    read_map = {m.conversation_id: m.last_read_message_id for m in my_memberships}
    convs = list(
        await db.scalars(
            select(Conversation).where(Conversation.id.in_(conv_ids)).order_by(desc(Conversation.updated_at))
        )
    )
    items = []
    for conv in convs:
        peer_member = await db.scalar(
            select(ConversationMember).where(
                ConversationMember.conversation_id == conv.id,
                ConversationMember.user_id != user.id,
            )
        )
        if not peer_member or peer_member.user_id in blocked:
            continue
        peer = await db.get(User, peer_member.user_id)
        if not peer:
            continue
        last_msg = await db.scalar(
            select(Message)
            .where(Message.conversation_id == conv.id)
            .order_by(desc(Message.id))
            .limit(1)
        )
        last_read = read_map.get(conv.id) or 0
        unread_count = int(
            await db.scalar(
                select(func.count())
                .select_from(Message)
                .where(
                    Message.conversation_id == conv.id,
                    Message.sender_id != user.id,
                    Message.id > last_read,
                )
            )
            or 0
        )
        items.append(
            {
                "id": conv.id,
                "peer": {
                    "id": peer.id,
                    "login": peer.login,
                    "name": peer.name,
                    "avatar_url": peer.avatar_url,
                },
                "peer_last_read_message_id": peer_member.last_read_message_id,
                "last_message": await serialize_message(db, last_msg) if last_msg else None,
                "unread_count": unread_count,
                "updated_at": conv.updated_at,
            }
        )
    return {"items": items}


@router.post("/conversations", dependencies=[Depends(require_same_origin)])
async def start_conversation(payload: StartConversationInput, user: User = Depends(current_user), db: AsyncSession = Depends(session_scope)):
    if payload.recipient_user_id == user.id:
        raise HTTPException(422, "Cannot message yourself")
    recipient = await db.get(User, payload.recipient_user_id)
    if not recipient:
        raise HTTPException(404, "Recipient user not found")
    blocked = await blocked_user_ids(db, user.id)
    if recipient.id in blocked:
        raise HTTPException(403, "Cannot message a blocked user")
    my_conv_ids = set(
        await db.scalars(
            select(ConversationMember.conversation_id).where(ConversationMember.user_id == user.id)
        )
    )
    if my_conv_ids:
        existing_conv_id = await db.scalar(
            select(ConversationMember.conversation_id).where(
                ConversationMember.conversation_id.in_(my_conv_ids),
                ConversationMember.user_id == recipient.id,
            )
        )
        if existing_conv_id:
            return {"conversation_id": existing_conv_id}
    conv = Conversation()
    db.add(conv)
    await db.flush()
    db.add(ConversationMember(conversation_id=conv.id, user_id=user.id))
    db.add(ConversationMember(conversation_id=conv.id, user_id=recipient.id))
    await db.commit()
    return {"conversation_id": conv.id}


@router.get("/conversations/{conversation_id}/messages")
async def list_messages(
    conversation_id: int,
    before_id: int | None = Query(default=None),
    limit: int = Query(default=40, ge=1, le=100),
    user: User = Depends(current_user),
    db: AsyncSession = Depends(session_scope),
):
    me_member, member_ids = await verify_member(db, conversation_id, user.id)
    stmt = select(Message).where(Message.conversation_id == conversation_id)
    if before_id is not None:
        stmt = stmt.where(Message.id < before_id)
    rows = list(await db.scalars(stmt.order_by(desc(Message.id)).limit(limit)))
    rows.reverse()
    if rows:
        newest_id = rows[-1].id
        if not me_member.last_read_message_id or me_member.last_read_message_id < newest_id:
            me_member.last_read_message_id = newest_id
            await db.commit()
            for uid in member_ids:
                if uid != user.id:
                    await hub.send_to_user(
                        uid,
                        {
                            "type": "read_receipt",
                            "conversation_id": conversation_id,
                            "reader_user_id": user.id,
                            "last_read_message_id": newest_id,
                        },
                    )
    return {"items": [await serialize_message(db, row) for row in rows]}


@router.post("/conversations/{conversation_id}/messages", dependencies=[Depends(require_same_origin)])
async def send_message(
    conversation_id: int,
    payload: SendMessageInput,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(session_scope),
):
    me_member, member_ids = await verify_member(db, conversation_id, user.id)
    if payload.client_message_id:
        dup = await db.scalar(
            select(Message).where(
                Message.sender_id == user.id,
                Message.client_message_id == payload.client_message_id,
            )
        )
        if dup:
            if (dup.conversation_id != conversation_id or dup.body != payload.body.strip()
                    or dup.shared_repository_id != payload.shared_repository_id
                    or dup.shared_post_id != payload.shared_post_id):
                raise HTTPException(409, "Message key already used for another message")
            return await serialize_message(db, dup)
    if payload.shared_repository_id is not None:
        repo = await db.get(Repository, payload.shared_repository_id)
        if not repo or not repo.is_public:
            raise HTTPException(404, "Shared repository not found")
    if payload.shared_post_id is not None:
        post = await db.get(Post, payload.shared_post_id)
        if not post:
            raise HTTPException(404, "Shared post not found")
    values = dict(
        conversation_id=conversation_id,
        sender_id=user.id,
        body=payload.body.strip(),
        shared_repository_id=payload.shared_repository_id,
        shared_post_id=payload.shared_post_id,
        client_message_id=payload.client_message_id,
    )
    statement = insert(Message).values(**values).on_conflict_do_nothing(
        index_elements=[Message.sender_id, Message.client_message_id]
    ).returning(Message)
    msg = await db.scalar(statement)
    if msg is None:
        # A concurrent retry may have inserted the key after the initial lookup.
        dup = await db.scalar(select(Message).where(
            Message.sender_id == user.id, Message.client_message_id == payload.client_message_id
        ))
        if (dup is None or dup.conversation_id != conversation_id
                or dup.body != payload.body.strip()
                or dup.shared_repository_id != payload.shared_repository_id
                or dup.shared_post_id != payload.shared_post_id):
            raise HTTPException(409, "Message key already used for another message")
        return await serialize_message(db, dup)
    me_member.last_read_message_id = msg.id
    conv = await db.get(Conversation, conversation_id)
    if conv:
        conv.updated_at = utcnow()
    for uid in member_ids:
        if uid != user.id:
            await create_notification(
                db, uid, user.id, "dm", f"@{user.login}님에게서 새 메시지가 도착했습니다.", conversation_id
            )
    await db.commit()
    await db.refresh(msg)
    serialized = await serialize_message(db, msg)
    for uid in member_ids:
        await hub.send_to_user(uid, {"type": "message", "message": serialized})
    return serialized


@router.websocket("/ws")
async def dm_websocket(websocket: WebSocket):
    if websocket.headers.get("origin") != settings().frontend_url:
        await websocket.close(code=4403)
        return
    token = websocket.cookies.get(COOKIE_NAME)
    if not token:
        await websocket.close(code=4401)
        return
    async with SessionLocal() as db:
        user = await db.scalar(
            select(User)
            .join(AuthSession, AuthSession.user_id == User.id)
            .where(
                AuthSession.token_hash == token_hash(token),
                AuthSession.expires_at > datetime.now(timezone.utc),
            )
        )
    if not user:
        await websocket.close(code=4401)
        return
    await hub.connect(user.id, websocket)
    try:
        while True:
            # Recheck idle sockets as well: cookie deletion alone cannot revoke
            # an already established WebSocket after logout or account deletion.
            async with SessionLocal() as db:
                valid_session = await db.scalar(select(AuthSession.id).where(
                    AuthSession.token_hash == token_hash(token),
                    AuthSession.expires_at > datetime.now(timezone.utc),
                ))
            if valid_session is None:
                await websocket.close(code=4401)
                break
            try:
                raw = await asyncio.wait_for(websocket.receive_text(), timeout=30)
            except asyncio.TimeoutError:
                continue
            if len(raw) > 4096:
                await websocket.close(code=4400)
                break
            try:
                data = json.loads(raw)
            except (ValueError, TypeError):
                await websocket.close(code=4400)
                break
            if not isinstance(data, dict):
                await websocket.close(code=4400)
                break
            if data.get("type") == "ping":
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        pass
    finally:
        hub.disconnect(user.id, websocket)
