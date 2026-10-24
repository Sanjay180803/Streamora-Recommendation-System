import os
import shutil
import tempfile

import pytest

# The application reads its configuration at import time, so the test
# environment has to be in place before any backend module is imported.
_DATA_DIR = tempfile.mkdtemp(prefix="streamora-tests-")
os.environ.update(
    JWT_SECRET="test-only-secret-that-is-long-enough-123",
    JWT_EXPIRE_MINUTES="60",
    CORS_ORIGINS="http://localhost:5173",
    DATA_DIR=_DATA_DIR,
)
os.environ.pop("TMDB_TOKEN", None)

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
from database import Base, engine  # noqa: E402

PASSWORD = "correct-horse-battery"


def pytest_sessionfinish(session, exitstatus):
    engine.dispose()
    shutil.rmtree(_DATA_DIR, ignore_errors=True)


@pytest.fixture
def client():
    # The lifespan (model loading, Redis, Kafka) is deliberately not run;
    # tests that need recommender state set it up explicitly.
    Base.metadata.create_all(engine)
    yield TestClient(main.app)
    Base.metadata.drop_all(engine)


@pytest.fixture
def register(client):
    """Register an account and return its auth headers."""

    def _register(email="alice@example.com", name="Alice", password=PASSWORD):
        response = client.post(
            "/auth/register",
            json={"email": email, "name": name, "password": password},
        )
        assert response.status_code == 200, response.text
        return {"Authorization": f"Bearer {response.json()['access_token']}"}

    return _register


@pytest.fixture
def create_profile(client):
    def _create(headers, name="Main"):
        response = client.post("/profiles/create", json={"name": name}, headers=headers)
        assert response.status_code == 200, response.text
        return response.json()["id"]

    return _create


@pytest.fixture
def alice(register, create_profile):
    headers = register("alice@example.com", "Alice")
    return {"headers": headers, "profile_id": create_profile(headers)}


@pytest.fixture
def bob(register, create_profile):
    headers = register("bob@example.com", "Bob")
    return {"headers": headers, "profile_id": create_profile(headers)}
