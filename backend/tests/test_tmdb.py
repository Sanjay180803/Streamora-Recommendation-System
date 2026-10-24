import httpx
import pytest

import tmdb


@pytest.fixture
def upstream(monkeypatch):
    """Route the proxy's outgoing requests to an in-process fake TMDB."""
    calls = []
    state = {"status": 200}

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(state["status"], json={"results": [{"path": request.url.path}]})

    real_client = httpx.AsyncClient

    def client_factory(**kwargs):
        return real_client(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(tmdb.httpx, "AsyncClient", client_factory)
    monkeypatch.setenv("TMDB_TOKEN", "server-side-token")
    monkeypatch.setattr(tmdb, "_cache", {})
    return {"calls": calls, "state": state}


def test_proxy_requires_login(client, upstream):
    assert client.get("/tmdb/movie/popular").status_code == 401
    assert upstream["calls"] == []


@pytest.mark.parametrize(
    "path",
    [
        "search/movie",
        "search/tv",
        "movie/popular",
        "movie/now_playing",
        "movie/top_rated",
        "tv/popular",
        "tv/on_the_air",
        "tv/top_rated",
        "trending/all/week",
        "movie/27205/videos",
        "tv/1399/videos",
    ],
)
def test_allowed_endpoints_are_forwarded_with_server_token(client, alice, upstream, path):
    response = client.get(f"/tmdb/{path}", headers=alice["headers"])

    assert response.status_code == 200
    [request] = upstream["calls"]
    assert request.url.path == f"/3/{path}"
    assert request.headers["authorization"] == "Bearer server-side-token"


@pytest.mark.parametrize(
    "path",
    [
        "account/1",
        "movie/27205/credits",
        "discover/movie",
        "movie/abc/videos",
        "movie/../account",
        "authentication",
    ],
)
def test_other_endpoints_are_rejected(client, alice, upstream, path):
    assert client.get(f"/tmdb/{path}", headers=alice["headers"]).status_code == 404
    assert upstream["calls"] == []


def test_only_known_query_parameters_are_forwarded(client, alice, upstream):
    client.get("/tmdb/search/movie?query=heat&page=2&api_key=attacker&session_id=x", headers=alice["headers"])

    [request] = upstream["calls"]
    assert dict(request.url.params) == {"query": "heat", "page": "2"}


def test_missing_token_returns_503(client, alice, upstream, monkeypatch):
    monkeypatch.delenv("TMDB_TOKEN")
    assert client.get("/tmdb/movie/popular", headers=alice["headers"]).status_code == 503
    assert upstream["calls"] == []


def test_upstream_errors_are_not_passed_through(client, alice, upstream):
    upstream["state"]["status"] = 401
    response = client.get("/tmdb/movie/popular", headers=alice["headers"])

    assert response.status_code == 502
    assert response.json() == {"detail": "TMDB request failed"}


def test_responses_are_cached(client, alice, upstream):
    for _ in range(3):
        client.get("/tmdb/movie/popular?page=1", headers=alice["headers"])
    client.get("/tmdb/movie/popular?page=2", headers=alice["headers"])

    assert len(upstream["calls"]) == 2
