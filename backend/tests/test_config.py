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


@pytest.mark.parametrize(
    "name",
    ["JWT_EXPIRE_MINUTES", "MIN_SEQUENCE_LENGTH", "RECOMMENDATION_CACHE_TTL_SEC", "DISLIKE_SUPPRESSION_DAYS"],
)
@pytest.mark.parametrize("value", ["abc", "0", "-5", "1.5"])
def test_invalid_numeric_settings_are_rejected(monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    with pytest.raises(ConfigError, match=name):
        load_settings()


def test_numeric_settings_are_read_from_environment(monkeypatch):
    monkeypatch.setenv("MIN_SEQUENCE_LENGTH", "3")
    monkeypatch.setenv("DISLIKE_SUPPRESSION_DAYS", "7")
    loaded = load_settings()
    assert (loaded.min_sequence_length, loaded.dislike_suppression_days) == (3, 7)


def test_model_paths_default_to_data_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.delenv("MODEL_PATH", raising=False)
    monkeypatch.delenv("SASREC_MODEL_PATH", raising=False)
    loaded = load_settings()
    assert loaded.bert4rec_model_path == str(tmp_path / "bert4rec_v3.onnx")
    assert loaded.sasrec_model_path == str(tmp_path / "sasrec_v3.onnx")


def test_cors_origins_are_parsed(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", "https://a.example, https://b.example ,")
    assert load_settings().cors_origins == ["https://a.example", "https://b.example"]
