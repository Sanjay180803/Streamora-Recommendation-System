import json

import pytest
from starlette.websockets import WebSocketDisconnect

from database import SessionLocal, WatchInvite
from watch_party import MAX_CHAT_LENGTH, WS_FORBIDDEN, WS_UNAUTHORIZED, manager

MOVIE = {"movie_title": "Inception", "movie_id": "tmdb_27205"}


def token(headers):
    return headers["Authorization"].removeprefix("Bearer ")


def invite(client, headers, to_email, **overrides):
    return client.post("/invite", json={"to_email": to_email, **MOVIE, **overrides}, headers=headers)


def pending(client, headers):
    return client.get("/invite/pending", headers=headers).json()["invites"]


@pytest.fixture
def accepted_room(client, alice, bob):
    """A room created by Alice that Bob has joined."""
    room_id = invite(client, alice["headers"], "bob@example.com").json()["room_id"]
    invite_id = pending(client, bob["headers"])[0]["id"]
    client.post("/invite/respond", json={"invite_id": invite_id, "action": "accepted"}, headers=bob["headers"])
    return room_id


def connect(client, room_id, headers=None, auth_message=None):
    ws = client.websocket_connect(f"/ws/room/{room_id}")
    session = ws.__enter__()
    if auth_message is None and headers is not None:
        auth_message = {"type": "auth", "token": token(headers)}
    if auth_message is not None:
        session.send_text(auth_message if isinstance(auth_message, str) else json.dumps(auth_message))
    return ws, session


# ── Invitations ───────────────────────────────────────────────────────────────

def test_invite_uses_sender_identity_from_token(client, alice, bob):
    response = invite(client, alice["headers"], "BOB@example.com", from_email="mallory@example.com", from_name="Mallory")

    assert response.status_code == 200
    [received] = pending(client, bob["headers"])
    assert received["from_email"] == "alice@example.com"
    assert received["from_name"] == "Alice"


def test_invite_to_unknown_email_looks_identical(client, alice, bob):
    known = invite(client, alice["headers"], "bob@example.com")
    unknown = invite(client, alice["headers"], "nobody@example.com")

    assert known.status_code == unknown.status_code == 200
    assert known.json().keys() == unknown.json().keys()
    with SessionLocal() as db:
        assert db.query(WatchInvite).filter(WatchInvite.to_email == "nobody@example.com").count() == 0


def test_cannot_invite_yourself(client, alice):
    assert invite(client, alice["headers"], "alice@example.com").status_code == 400


def test_repeat_invite_reuses_pending_room(client, alice, bob):
    first = invite(client, alice["headers"], "bob@example.com").json()["room_id"]
    second = invite(client, alice["headers"], "bob@example.com").json()["room_id"]

    assert first == second
    assert len(pending(client, bob["headers"])) == 1


def test_room_ids_are_not_guessable(client, alice, bob):
    room_id = invite(client, alice["headers"], "bob@example.com").json()["room_id"]
    assert len(room_id) >= 20


def test_pending_invites_are_only_visible_to_the_invitee(client, alice, bob, register):
    invite(client, alice["headers"], "bob@example.com")
    carol = register("carol@example.com", "Carol")

    assert len(pending(client, bob["headers"])) == 1
    assert pending(client, alice["headers"]) == []
    assert pending(client, carol) == []


def test_only_the_invitee_can_respond(client, alice, bob, register):
    invite(client, alice["headers"], "bob@example.com")
    invite_id = pending(client, bob["headers"])[0]["id"]
    carol = register("carol@example.com", "Carol")

    for headers in (alice["headers"], carol):
        response = client.post("/invite/respond", json={"invite_id": invite_id, "action": "accepted"}, headers=headers)
        assert response.status_code == 404

    assert len(pending(client, bob["headers"])) == 1


@pytest.mark.parametrize("action", ["approved", "", "pending", "ACCEPTED"])
def test_invalid_response_action_is_rejected(client, alice, bob, action):
    invite(client, alice["headers"], "bob@example.com")
    invite_id = pending(client, bob["headers"])[0]["id"]

    response = client.post("/invite/respond", json={"invite_id": invite_id, "action": action}, headers=bob["headers"])
    assert response.status_code == 422


def test_invite_can_only_be_answered_once(client, alice, bob):
    invite(client, alice["headers"], "bob@example.com")
    invite_id = pending(client, bob["headers"])[0]["id"]

    first = client.post("/invite/respond", json={"invite_id": invite_id, "action": "declined"}, headers=bob["headers"])
    second = client.post("/invite/respond", json={"invite_id": invite_id, "action": "accepted"}, headers=bob["headers"])

    assert first.status_code == 200
    assert first.json()["room_id"] is None
    assert second.status_code == 409


def test_invite_endpoints_require_auth(client):
    assert client.post("/invite", json={"to_email": "a@example.com", **MOVIE}).status_code == 401
    assert client.get("/invite/pending").status_code == 401
    assert client.post("/invite/respond", json={"invite_id": "x", "action": "accepted"}).status_code == 401
    assert client.get("/room/anything").status_code == 401


# ── Room membership ───────────────────────────────────────────────────────────

def test_room_details_visible_to_participants_only(client, alice, bob, register, accepted_room):
    carol = register("carol@example.com", "Carol")

    assert client.get(f"/room/{accepted_room}", headers=alice["headers"]).status_code == 200
    assert client.get(f"/room/{accepted_room}", headers=bob["headers"]).status_code == 200
    assert client.get(f"/room/{accepted_room}", headers=carol).status_code == 404


def test_invitee_is_not_a_participant_until_accepting(client, alice, bob):
    room_id = invite(client, alice["headers"], "bob@example.com").json()["room_id"]
    assert client.get(f"/room/{room_id}", headers=bob["headers"]).status_code == 404


def test_declining_does_not_grant_access(client, alice, bob):
    room_id = invite(client, alice["headers"], "bob@example.com").json()["room_id"]
    invite_id = pending(client, bob["headers"])[0]["id"]
    client.post("/invite/respond", json={"invite_id": invite_id, "action": "declined"}, headers=bob["headers"])

    assert client.get(f"/room/{room_id}", headers=bob["headers"]).status_code == 404


# ── WebSocket ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "auth_message",
    [
        "not json",
        {"type": "chat", "text": "hi"},
        {"type": "auth"},
        {"type": "auth", "token": 123},
        {"type": "auth", "token": "not-a-jwt"},
        ["auth", "token"],
    ],
)
def test_websocket_rejects_unauthenticated_clients(client, accepted_room, auth_message):
    ws, session = connect(client, accepted_room, auth_message=auth_message)
    with pytest.raises(WebSocketDisconnect) as closed:
        session.receive_text()
    assert closed.value.code == WS_UNAUTHORIZED
    ws.__exit__(None, None, None)
    assert manager.room_size(accepted_room) == 0


def test_websocket_rejects_non_participants(client, register, accepted_room):
    carol = register("carol@example.com", "Carol")
    ws, session = connect(client, accepted_room, carol)

    with pytest.raises(WebSocketDisconnect) as closed:
        session.receive_text()
    assert closed.value.code == WS_FORBIDDEN
    ws.__exit__(None, None, None)


def test_websocket_rejects_unknown_room(client, alice):
    ws, session = connect(client, "no-such-room", alice["headers"])
    with pytest.raises(WebSocketDisconnect) as closed:
        session.receive_text()
    assert closed.value.code == WS_FORBIDDEN
    ws.__exit__(None, None, None)


def test_participants_can_chat_with_server_assigned_sender(client, alice, bob, accepted_room):
    alice_ws, alice_session = connect(client, accepted_room, alice["headers"])
    joined = alice_session.receive_json()
    assert joined["type"] == "system" and joined["participants"] == 1

    bob_ws, bob_session = connect(client, accepted_room, bob["headers"])
    assert alice_session.receive_json()["text"] == "Bob joined the room"
    assert bob_session.receive_json()["participants"] == 2

    bob_session.send_text(json.dumps({"type": "chat", "text": " hello ", "sender": "Alice", "type2": "x"}))
    for session in (alice_session, bob_session):
        message = session.receive_json()
        assert message["type"] == "chat"
        assert message["text"] == "hello"
        assert message["sender"] == "Bob"
        assert set(message) == {"type", "text", "sender", "timestamp"}

    bob_ws.__exit__(None, None, None)
    left = alice_session.receive_json()
    assert left["text"] == "Bob left the room"
    assert left["participants"] == 1
    alice_ws.__exit__(None, None, None)


@pytest.mark.parametrize(
    "message",
    [
        "not json",
        json.dumps({"type": "system", "text": "Alice left the room"}),
        json.dumps({"type": "chat"}),
        json.dumps({"type": "chat", "text": "   "}),
        json.dumps({"type": "chat", "text": "x" * (MAX_CHAT_LENGTH + 1)}),
        json.dumps({"type": "chat", "text": 42}),
        json.dumps([1, 2, 3]),
    ],
)
def test_invalid_chat_messages_are_rejected_without_dropping_the_socket(client, alice, accepted_room, message):
    ws, session = connect(client, accepted_room, alice["headers"])
    session.receive_json()  # join notice

    session.send_text(message)
    assert session.receive_json() == {"type": "error", "text": "Invalid message"}

    session.send_text(json.dumps({"type": "chat", "text": "still here"}))
    assert session.receive_json()["text"] == "still here"
    ws.__exit__(None, None, None)


def test_disconnect_cleans_up_room(client, alice, accepted_room):
    ws, session = connect(client, accepted_room, alice["headers"])
    session.receive_json()
    assert manager.room_size(accepted_room) == 1

    ws.__exit__(None, None, None)
    assert manager.room_size(accepted_room) == 0
    assert accepted_room not in manager.rooms
