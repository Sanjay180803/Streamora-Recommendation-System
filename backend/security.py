"""
security.py
Password hashing, JWT access tokens and the current-user dependency.

Every protected route derives the caller's identity from the bearer token;
no route trusts an email address supplied in the URL or request body.
"""

from datetime import UTC, datetime, timedelta

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from config import settings
from database import Profile, User, get_db

JWT_ALGORITHM = "HS256"

# argon2 for new hashes; sha256_crypt is still accepted for accounts created
# before the switch and is transparently upgraded on their next login.
pwd_context = CryptContext(schemes=["argon2", "sha256_crypt"], deprecated="auto")

_bearer = HTTPBearer(auto_error=False)

_UNAUTHORIZED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Not authenticated",
    headers={"WWW-Authenticate": "Bearer"},
)


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def create_access_token(email: str) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": email,
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_expire_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=JWT_ALGORITHM)


def user_from_token(token: str, db: Session) -> User | None:
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[JWT_ALGORITHM],
            options={"require": ["sub", "exp"]},
        )
    except jwt.PyJWTError:
        return None
    return db.query(User).filter(User.email == payload["sub"]).first()


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise _UNAUTHORIZED
    user = user_from_token(credentials.credentials, db)
    if user is None:
        raise _UNAUTHORIZED
    return user


def get_owned_profile(profile_id: str, user: User, db: Session) -> Profile:
    """Return the profile if it belongs to the user; otherwise 404 (not 403),
    so callers cannot probe which profile ids exist on other accounts."""
    profile = (
        db.query(Profile)
        .filter(Profile.id == profile_id, Profile.user_email == user.email)
        .first()
    )
    if profile is None:
        raise HTTPException(status_code=404, detail="Profile not found")
    return profile
