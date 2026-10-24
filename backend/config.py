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
    data_dir: str
    bert4rec_model_path: str
    sasrec_model_path: str
    redis_url: str            # empty string disables Redis
    kafka_bootstrap: str      # empty string disables Kafka
    min_sequence_length: int  # matched titles needed before using a model
    recommendation_cache_ttl_sec: int
    dislike_suppression_days: int


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

    data_dir = os.getenv("DATA_DIR", "../data")

    return Settings(
        jwt_secret=jwt_secret,
        jwt_expire_minutes=_int("JWT_EXPIRE_MINUTES", 60),
        cors_origins=origins,
        data_dir=data_dir,
        bert4rec_model_path=os.getenv("MODEL_PATH", os.path.join(data_dir, "bert4rec_v3.onnx")),
        sasrec_model_path=os.getenv("SASREC_MODEL_PATH", os.path.join(data_dir, "sasrec_v3.onnx")),
        redis_url=os.getenv("REDIS_URL", "redis://localhost:6379"),
        kafka_bootstrap=os.getenv("KAFKA_BOOTSTRAP", ""),
        min_sequence_length=_int("MIN_SEQUENCE_LENGTH", 5),
        recommendation_cache_ttl_sec=_int("RECOMMENDATION_CACHE_TTL_SEC", 3600),
        dislike_suppression_days=_int("DISLIKE_SUPPRESSION_DAYS", 30),
    )


settings = load_settings()
