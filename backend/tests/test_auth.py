from datetime import datetime, timedelta, timezone

import jwt
import pytest
from passlib.hash import sha256_crypt

from config import settings
from database import SessionLocal, User
from security import JWT_ALGORITHM
from tests.conftest import PASSWORD


def get_user(email):
    with SessionLocal() as db:
        return db.query(User).filter(User.email == email).first()


def token_for(email, *, secret=None, expires_in=timedelta(minutes=5)):
    now = datetime.now(timezone.utc)
    payload = {"sub": email, "iat": now, "exp": now + expires_in}
    return jwt.encode(payload, secret or settings.jwt_secret, algorithm=JWT_ALGORITHM)


# ── Registration ──────────────────────────────────────────────────────────────

def test_register_returns_token_and_hashes_password(client):
    response = client.post(
        "/auth/register",
        json={"email": "  New@Example.COM ", "name": " New User ", "password": PASSWORD},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["email"] == "new@example.com"
    assert body["name"] == "New User"
    assert body["token_type"] == "bearer"
    assert body["access_token"]

    user = get_user("new@example.com")
    assert user.password_hash.startswith("$argon2")
    assert PASSWORD not in user.password_hash


@pytest.mark.parametrize(
    "payload",
    [
        {"email": "not-an-email", "name": "A", "password": PASSWORD},
        {"email": "a@example.com", "name": "A", "password": "short"},
        {"email": "a@example.com", "name": "A", "password": "x" * 129},
        {"email": "a@example.com", "name": "   ", "password": PASSWORD},
        {"email": "a@example.com", "name": "A" * 51, "password": PASSWORD},
        {"email": "a@example.com", "password": PASSWORD},
    ],
)
def test_register_rejects_invalid_input(client, payload):
    assert client.post("/auth/register", json=payload).status_code == 422


def test_duplicate_email_is_rejected(client, register):
    register("alice@example.com")

    response = client.post(
        "/auth/register",
        json={"email": "ALICE@example.com", "name": "Other", "password": PASSWORD},
    )
    assert response.status_code == 400


# ── Login ─────────────────────────────────────────────────────────────────────

def test_login_returns_token_and_profiles(client, alice):
    response = client.post("/auth/login", json={"email": "alice@example.com", "password": PASSWORD})

    assert response.status_code == 200
    body = response.json()
    assert body["access_token"]
    assert [p["id"] for p in body["profiles"]] == [alice["profile_id"]]


def test_wrong_password_and_unknown_email_get_identical_responses(client, register):
    register("alice@example.com")

    wrong_password = client.post("/auth/login", json={"email": "alice@example.com", "password": "wrong-password"})
    unknown_email = client.post("/auth/login", json={"email": "nobody@example.com", "password": "wrong-password"})

    assert wrong_password.status_code == unknown_email.status_code == 401
    assert wrong_password.json() == unknown_email.json()


def test_legacy_sha256_hash_still_logs_in_and_is_upgraded(client):
    with SessionLocal() as db:
        db.add(User(email="legacy@example.com", name="Legacy", password_hash=sha256_crypt.hash(PASSWORD)))
        db.commit()

    response = client.post("/auth/login", json={"email": "legacy@example.com", "password": PASSWORD})

    assert response.status_code == 200
    assert get_user("legacy@example.com").password_hash.startswith("$argon2")


def test_account_lookup_endpoint_is_gone(client, register):
    register("alice@example.com")
    assert client.get("/auth/check/alice@example.com").status_code == 404


# ── Tokens ────────────────────────────────────────────────────────────────────

def test_me_returns_identity_from_token(client, alice):
    response = client.get("/auth/me", headers=alice["headers"])
    assert response.json() == {"email": "alice@example.com", "name": "Alice"}


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Bearer not-a-jwt"},
        {"Authorization": "Basic YWxpY2U6cGFzcw=="},
        {"Authorization": f"Bearer {token_for('alice@example.com', secret='another-secret-that-is-long-enough-1')}"},
        {"Authorization": f"Bearer {token_for('alice@example.com', expires_in=timedelta(seconds=-1))}"},
        {"Authorization": f"Bearer {token_for('ghost@example.com')}"},
    ],
    ids=["missing", "garbage", "wrong-scheme", "wrong-secret", "expired", "unknown-user"],
)
def test_invalid_tokens_are_rejected(client, alice, headers):
    response = client.get("/auth/me", headers=headers)
    assert response.status_code == 401


def test_token_without_expiry_is_rejected(client, alice):
    token = jwt.encode({"sub": "alice@example.com"}, settings.jwt_secret, algorithm=JWT_ALGORITHM)
    response = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


@pytest.mark.parametrize(
    "method, path, body",
    [
        ("get", "/profiles", None),
        ("post", "/profiles/create", {"name": "X"}),
        ("post", "/profiles/rename", {"profile_id": "p", "new_name": "X"}),
        ("post", "/profiles/delete", {"profile_id": "p"}),
        ("get", "/history/p", None),
        ("post", "/history/save", {"profile_id": "p", "history": []}),
        ("get", "/continue-watching/p", None),
        ("post", "/continue-watching/save", {"profile_id": "p", "items": []}),
        ("get", "/watch-again/p", None),
        ("post", "/watch-again/save", {"profile_id": "p", "items": []}),
        ("post", "/recommend", {"profile_id": "p", "watch_history": [{"title": "X"}]}),
        ("post", "/feedback", {"profile_id": "p", "movie_id": "m", "signal": 1, "model_variant": "bert4rec"}),
        ("get", "/search?q=thriller", None),
        ("get", "/tmdb/movie/popular", None),
    ],
)
def test_protected_routes_require_a_token(client, method, path, body):
    kwargs = {"json": body} if body is not None else {}
    response = getattr(client, method)(path, **kwargs)
    assert response.status_code == 401


def test_public_routes_stay_public(client):
    assert client.get("/health").status_code == 200
    assert client.get("/genres").status_code == 200


# ── CORS ──────────────────────────────────────────────────────────────────────

def test_cors_allows_configured_origin_only(client):
    allowed = client.options(
        "/profiles",
        headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"},
    )
    blocked = client.options(
        "/profiles",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"},
    )

    assert allowed.headers.get("access-control-allow-origin") == "http://localhost:5173"
    assert "access-control-allow-origin" not in blocked.headers
