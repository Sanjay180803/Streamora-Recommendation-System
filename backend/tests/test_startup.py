"""Application startup (FastAPI lifespan) with and without model artifacts."""

import pytest
from fastapi.testclient import TestClient

import main
import recommender
from tests.fakes import FakeSession, write_catalogue


def settings_with(**overrides):
    return type(main.settings)(**{**main.settings.__dict__, **overrides})


@pytest.fixture(autouse=True)
def _isolated_database(empty_database):
    pass


@pytest.fixture
def artifacts(tmp_path, monkeypatch):
    write_catalogue(tmp_path)
    (tmp_path / "bert4rec_v3.onnx").touch()
    monkeypatch.setattr(recommender.ort, "InferenceSession", lambda path, **kw: FakeSession(path, 2))
    return tmp_path


def test_startup_loads_models_and_runs_without_optional_services(artifacts, monkeypatch):
    monkeypatch.setattr(
        main,
        "settings",
        settings_with(
            data_dir=str(artifacts),
            bert4rec_model_path=str(artifacts / "bert4rec_v3.onnx"),
            sasrec_model_path=str(artifacts / "missing.onnx"),
            redis_url="",
            kafka_bootstrap="",
        ),
    )

    with TestClient(main.app) as client:
        health = client.get("/health").json()
        # startup ran the migrations, so the API works end to end
        registered = client.post(
            "/auth/register",
            json={"email": "s@example.com", "name": "S", "password": "correct-horse-battery"},
        )

    assert health == {"status": "ok", "model_loaded": True, "redis_connected": False, "items_loaded": 13}
    assert registered.status_code == 200


def test_unreachable_redis_degrades_instead_of_failing(artifacts, monkeypatch):
    monkeypatch.setattr(
        main,
        "settings",
        settings_with(
            data_dir=str(artifacts),
            bert4rec_model_path=str(artifacts / "bert4rec_v3.onnx"),
            redis_url="redis://127.0.0.1:1",  # nothing listens on port 1
            kafka_bootstrap="",
        ),
    )

    with TestClient(main.app) as client:
        assert client.get("/health").json()["redis_connected"] is False
    assert main._redis is None


def test_startup_fails_clearly_without_artifacts(tmp_path, monkeypatch):
    monkeypatch.setattr(
        main,
        "settings",
        settings_with(data_dir=str(tmp_path), bert4rec_model_path=str(tmp_path / "bert4rec_v3.onnx")),
    )

    with pytest.raises(FileNotFoundError, match="Missing model/data artifacts"):
        with TestClient(main.app):
            pass
