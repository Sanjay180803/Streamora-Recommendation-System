"""
watch_party.py
Watch Together: invitations, room membership and the room chat WebSocket.

A room's participants are its creator and every invitee who accepted. Only
participants can read room details or join the chat. The WebSocket cannot
carry an Authorization header from a browser, so the client must send
{"type": "auth", "token": "<access token>"} as its first message.

Each participant plays the trailer independently; only chat and presence are
shared. Playback is not synchronised.
"""

import asyncio
import json
import secrets
import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from database import SessionLocal, User, WatchInvite, WatchRoom, get_db
from security import get_current_user, user_from_token

router = APIRouter()

AUTH_TIMEOUT_SEC = 10
MAX_MESSAGE_BYTES = 4096
MAX_CHAT_LENGTH = 1000

# Application-defined WebSocket close codes (4000-4999 range)
WS_UNAUTHORIZED = 4401
WS_FORBIDDEN = 4403


# ── Room membership ───────────────────────────────────────────────────────────
def is_participant(room: WatchRoom, email: str, db: Session) -> bool:
    if room.created_by == email:
        return True
    return (
        db.query(WatchInvite)
        .filter(
            WatchInvite.room_id == room.room_id,
            WatchInvite.to_email == email,
            WatchInvite.status == "accepted",
        )
        .first()
        is not None
    )


def get_participant_room(room_id: str, user: User, db: Session) -> WatchRoom:
    room = db.query(WatchRoom).filter(WatchRoom.room_id == room_id).first()
    if room is None or not is_participant(room, user.email, db):
        raise HTTPException(status_code=404, detail="Room not found")
    return room


# ── Connection manager ────────────────────────────────────────────────────────
class RoomManager:
    def __init__(self):
        self.rooms: dict[str, list[dict]] = {}

    def add(self, room_id: str, ws: WebSocket, name: str):
        self.rooms.setdefault(room_id, []).append({"ws": ws, "name": name})

    def disconnect(self, room_id: str, ws: WebSocket):
        if room_id in self.rooms:
            self.rooms[room_id] = [p for p in self.rooms[room_id] if p["ws"] is not ws]
            if not self.rooms[room_id]:
                del self.rooms[room_id]

    async def broadcast_all(self, room_id: str, message: dict):
        for participant in list(self.rooms.get(room_id, [])):
            try:
                await participant["ws"].send_json(message)
            except Exception:
                # A socket that cannot be written to is gone; drop it
                self.disconnect(room_id, participant["ws"])

    def room_size(self, room_id: str) -> int:
        return len(self.rooms.get(room_id, []))


manager = RoomManager()


def _now() -> str:
    return datetime.utcnow().isoformat()


# ── Schemas ───────────────────────────────────────────────────────────────────
class InviteRequest(BaseModel):
    to_email: str = Field(max_length=254)
    movie_title: str = Field(min_length=1, max_length=200)
    movie_id: str = Field(min_length=1, max_length=100)


class InviteResponseRequest(BaseModel):
    invite_id: str
    action: Literal["accepted", "declined"]


# ── Invite endpoints ──────────────────────────────────────────────────────────
@router.post("/invite")
def send_invite(
    req: InviteRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    to_email = req.to_email.strip().lower()
    if to_email == user.email:
        raise HTTPException(status_code=400, detail="You can't invite yourself")

    recipient = db.query(User).filter(User.email == to_email).first()

    if recipient is not None:
        existing = (
            db.query(WatchInvite)
            .filter(
                WatchInvite.from_email == user.email,
                WatchInvite.to_email == to_email,
                WatchInvite.movie_id == req.movie_id,
                WatchInvite.status == "pending",
            )
            .first()
        )
        if existing:
            return {"status": "ok", "room_id": existing.room_id}

    # The room is created and the response is identical whether or not the
    # recipient has an account, so this endpoint cannot be used to discover
    # which email addresses are registered.
    room = WatchRoom(
        room_id=secrets.token_urlsafe(16),
        movie_id=req.movie_id,
        movie_title=req.movie_title,
        created_by=user.email,
    )
    db.add(room)
    db.flush()  # the invite references the room, so insert the room first
    if recipient is not None:
        db.add(
            WatchInvite(
                id=str(uuid.uuid4()),
                from_email=user.email,
                from_name=user.name,
                to_email=to_email,
                movie_title=req.movie_title,
                movie_id=req.movie_id,
                room_id=room.room_id,
            )
        )
    db.commit()
    return {"status": "ok", "room_id": room.room_id}


@router.get("/invite/pending")
def get_pending_invites(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    invites = (
        db.query(WatchInvite)
        .filter(
            WatchInvite.to_email == user.email,
            WatchInvite.status == "pending",
        )
        .all()
    )
    return {
        "invites": [
            {
                "id": i.id,
                "from_name": i.from_name,
                "from_email": i.from_email,
                "movie_title": i.movie_title,
                "movie_id": i.movie_id,
            }
            for i in invites
        ]
    }


@router.post("/invite/respond")
def respond_invite(
    req: InviteResponseRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    invite = (
        db.query(WatchInvite)
        .filter(
            WatchInvite.id == req.invite_id,
            WatchInvite.to_email == user.email,
        )
        .first()
    )
    if invite is None:
        raise HTTPException(status_code=404, detail="Invite not found")
    if invite.status != "pending":
        raise HTTPException(status_code=409, detail="Invite already answered")

    invite.status = req.action
    db.commit()
    accepted = req.action == "accepted"
    return {
        "status": "ok",
        "room_id": invite.room_id if accepted else None,
        "movie_id": invite.movie_id if accepted else None,
        "movie_title": invite.movie_title if accepted else None,
    }


@router.get("/room/{room_id}")
def get_room(
    room_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    room = get_participant_room(room_id, user, db)
    return {
        "room_id": room.room_id,
        "movie_id": room.movie_id,
        "movie_title": room.movie_title,
        "created_by": room.created_by,
        "participants": manager.room_size(room_id),
    }


# ── Room chat WebSocket ───────────────────────────────────────────────────────
async def _authenticate(ws: WebSocket, room_id: str) -> User | None:
    """Read the auth message and check room membership; close the socket on failure."""
    try:
        raw = await asyncio.wait_for(ws.receive_text(), timeout=AUTH_TIMEOUT_SEC)
        message = json.loads(raw)
        token = message.get("token") if message.get("type") == "auth" else None
    except (TimeoutError, ValueError, AttributeError):
        token = None

    if not isinstance(token, str):
        await ws.close(code=WS_UNAUTHORIZED)
        return None

    with SessionLocal() as db:
        user = user_from_token(token, db)
        if user is None:
            await ws.close(code=WS_UNAUTHORIZED)
            return None
        room = db.query(WatchRoom).filter(WatchRoom.room_id == room_id).first()
        if room is None or not is_participant(room, user.email, db):
            await ws.close(code=WS_FORBIDDEN)
            return None
        db.expunge(user)
        return user


def _parse_chat(raw: str) -> str | None:
    if len(raw.encode()) > MAX_MESSAGE_BYTES:
        return None
    try:
        message = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(message, dict) or message.get("type") != "chat":
        return None
    text = message.get("text")
    if not isinstance(text, str):
        return None
    text = text.strip()
    if not text or len(text) > MAX_CHAT_LENGTH:
        return None
    return text


@router.websocket("/ws/room/{room_id}")
async def websocket_room(room_id: str, ws: WebSocket):
    await ws.accept()
    user = await _authenticate(ws, room_id)
    if user is None:
        return

    name = user.name
    manager.add(room_id, ws, name)
    try:
        await manager.broadcast_all(
            room_id,
            {
                "type": "system",
                "text": f"{name} joined the room",
                "participants": manager.room_size(room_id),
                "timestamp": _now(),
            },
        )
        while True:
            text = _parse_chat(await ws.receive_text())
            if text is None:
                await ws.send_json({"type": "error", "text": "Invalid message"})
                continue
            # Build the outgoing message server-side; clients cannot set the
            # sender, type or any other field.
            await manager.broadcast_all(
                room_id,
                {
                    "type": "chat",
                    "text": text,
                    "sender": name,
                    "timestamp": _now(),
                },
            )
    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(room_id, ws)
        await manager.broadcast_all(
            room_id,
            {
                "type": "system",
                "text": f"{name} left the room",
                "participants": manager.room_size(room_id),
                "timestamp": _now(),
            },
        )
