import secrets
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import func, select
from starlette.websockets import WebSocketDisconnect

from app.config import settings
from app import dm
from app.dm import SendMessageInput, list_messages, send_message, verify_member
from app.main import app
from app.models import Block, Conversation, ConversationMember, Message, User


async def participants(db):
    suffix = uuid4().hex[:12]
    users = [User(github_id=secrets.randbits(52), login=f"fixture_{suffix}_{i}",
                  html_url="https://github.com") for i in range(3)]
    db.add_all(users)
    await db.flush()
    conversations = [Conversation(), Conversation()]
    db.add_all(conversations)
    await db.flush()
    for conversation in conversations:
        for user in users[:2]:
            db.add(ConversationMember(conversation_id=conversation.id, user_id=user.id))
    await db.flush()
    return users, conversations


def test_websocket_rejects_foreign_origin_before_authentication():
    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect) as exc:
            with client.websocket_connect("/api/dm/ws", headers={"origin": "https://untrusted.invalid"}):
                pass
        assert exc.value.code == 4403


def test_websocket_requires_session_on_allowed_origin():
    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect) as exc:
            with client.websocket_connect("/api/dm/ws", headers={"origin": settings().frontend_url}):
                pass
        assert exc.value.code == 4401


def test_message_rejects_whitespace_only_text():
    with pytest.raises(ValidationError):
        SendMessageInput(body="  \n\t ")


class FakeSession:
    def __init__(self, value):
        self.value = value

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def scalar(self, statement):
        return self.value


def test_websocket_closes_when_session_is_revoked(monkeypatch):
    responses = iter([SimpleNamespace(id=7), None])
    monkeypatch.setattr(dm, "SessionLocal", lambda: FakeSession(next(responses)))
    with TestClient(app) as client:
        client.cookies.set("gitstargram_session", "unit-test-session")
        with client.websocket_connect("/api/dm/ws", headers={"origin": settings().frontend_url}) as ws:
            with pytest.raises(WebSocketDisconnect) as exc:
                ws.receive_json()
            assert exc.value.code == 4401


@pytest.mark.asyncio
async def test_delivery_checks_revoked_session_before_sending(monkeypatch):
    monkeypatch.setattr(dm, "SessionLocal", lambda: FakeSession(None))
    socket = AsyncMock()
    socket.cookies = {"gitstargram_session": "unit-test-session"}
    connection_hub = dm.ConnectionHub()
    connection_hub._connections[7].add(socket)
    await connection_hub.send_to_user(7, {"type": "message", "body": "private"})
    socket.send_json.assert_not_awaited()
    socket.close.assert_awaited_once_with(code=4401)
    assert not connection_hub._connections[7]


@pytest.mark.asyncio
async def test_dm_membership_and_both_block_directions(isolated_db):
    db = isolated_db
    users, conversations = await participants(db)
    sender, recipient, outsider = users
    conversation = conversations[0]
    with pytest.raises(HTTPException) as exc:
        await verify_member(db, conversation.id, outsider.id)
    assert exc.value.status_code == 403
    block = Block(blocker_id=recipient.id, blocked_id=sender.id)
    db.add(block)
    await db.flush()
    for viewer in (sender, recipient):
        with pytest.raises(HTTPException) as exc:
            await list_messages(conversation.id, before_id=None, limit=40, user=viewer, db=db)
        assert exc.value.status_code == 403
        with pytest.raises(HTTPException) as exc:
            await send_message(conversation.id, SendMessageInput(body="blocked"), user=viewer, db=db)
        assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_message_retry_returns_same_message_and_rejects_key_reuse(isolated_db):
    db = isolated_db
    users, conversations = await participants(db)
    sender = users[0]
    payload = SendMessageInput(body="first message", client_message_id=uuid4().hex)
    first = await send_message(conversations[0].id, payload, user=sender, db=db)
    retry = await send_message(conversations[0].id, payload, user=sender, db=db)
    assert first["id"] == retry["id"]
    assert await db.scalar(select(func.count()).select_from(Message).where(
        Message.sender_id == sender.id, Message.client_message_id == payload.client_message_id
    )) == 1
    for conversation, body in ((conversations[1], payload.body), (conversations[0], "changed body")):
        with pytest.raises(HTTPException) as exc:
            await send_message(conversation.id, SendMessageInput(
                body=body, client_message_id=payload.client_message_id
            ), user=sender, db=db)
        assert exc.value.status_code == 409
