"""
config.py
Application settings read from the environment, validated once at startup.
"""

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()

MIN_JWT_SECRET_LENGTH = 32


class ConfigError(RuntimeError):
    """Raised when a required setting is missing or invalid."""


def _int(name: str, default: int, minimum: int = 1) -> int:
    raw = os.getenv(name, str(default))
    try:
        value = int(raw)
    except ValueError:
        raise ConfigError(f"{name} must be an integer, got {raw!r}") from None
    if value < minimum:
        raise ConfigError(f"{name} must be >= {minimum}, got {value}")
    return value


@dataclass(frozen=True)
class Settings:
    jwt_secret: str
    jwt_expire_minutes: int
    cors_origins: list[str]


def load_settings() -> Settings:
    jwt_secret = os.getenv("JWT_SECRET", "")
    if len(jwt_secret) < MIN_JWT_SECRET_LENGTH:
        raise ConfigError(
            f"JWT_SECRET must be set to at least {MIN_JWT_SECRET_LENGTH} characters"
        )

    origins = [
        o.strip()
        for o in os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",")
        if o.strip()
    ]
    if "*" in origins:
        raise ConfigError("CORS_ORIGINS must list explicit origins, not '*'")

    return Settings(
        jwt_secret=jwt_secret,
        jwt_expire_minutes=_int("JWT_EXPIRE_MINUTES", 60),
        cors_origins=origins,
    )


settings = load_settings()
