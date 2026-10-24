import pytest

from config import ConfigError, load_settings


@pytest.mark.parametrize("secret", [None, "", "too-short"])
def test_missing_or_short_jwt_secret_is_rejected(monkeypatch, secret):
    if secret is None:
        monkeypatch.delenv("JWT_SECRET", raising=False)
    else:
        monkeypatch.setenv("JWT_SECRET", secret)

    with pytest.raises(ConfigError, match="JWT_SECRET"):
        load_settings()


def test_wildcard_cors_is_rejected(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", "*")
    with pytest.raises(ConfigError, match="CORS_ORIGINS"):
        load_settings()


@pytest.mark.parametrize("value", ["abc", "0", "-5"])
def test_invalid_token_lifetime_is_rejected(monkeypatch, value):
    monkeypatch.setenv("JWT_EXPIRE_MINUTES", value)
    with pytest.raises(ConfigError, match="JWT_EXPIRE_MINUTES"):
        load_settings()


def test_cors_origins_are_parsed(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", "https://a.example, https://b.example ,")
    assert load_settings().cors_origins == ["https://a.example", "https://b.example"]
