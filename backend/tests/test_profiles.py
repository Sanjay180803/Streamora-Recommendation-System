import pytest

from database import ContinueWatching, SessionLocal, WatchAgain, WatchHistory

HISTORY = [{"title": "Inception", "genres": ["Sci-Fi"], "release_year": 2010}]


# ── Profile management ────────────────────────────────────────────────────────

def test_profiles_list_only_the_callers_profiles(client, alice, bob):
    alice_ids = [p["id"] for p in client.get("/profiles", headers=alice["headers"]).json()["profiles"]]
    bob_ids = [p["id"] for p in client.get("/profiles", headers=bob["headers"]).json()["profiles"]]

    assert alice_ids == [alice["profile_id"]]
    assert bob_ids == [bob["profile_id"]]


def test_profile_limit_is_six(client, register, create_profile):
    headers = register()
    for i in range(6):
        create_profile(headers, name=f"P{i}")

    response = client.post("/profiles/create", json={"name": "Seventh"}, headers=headers)
    assert response.status_code == 400


@pytest.mark.parametrize(
    "payload",
    [
        {"name": ""},
        {"name": "x" * 31},
        {"name": "Ok", "color": "red; background:url(x)"},
        {"name": "Ok", "icon": "x" * 9},
    ],
)
def test_profile_creation_validates_input(client, alice, payload):
    response = client.post("/profiles/create", json=payload, headers=alice["headers"])
    assert response.status_code == 422


def test_profile_rename(client, alice):
    response = client.post(
        "/profiles/rename",
        json={"profile_id": alice["profile_id"], "new_name": "Renamed"},
        headers=alice["headers"],
    )
    assert response.json() == {"status": "ok", "name": "Renamed"}


def test_profile_rename_rejects_duplicate_name(client, alice, create_profile):
    create_profile(alice["headers"], name="Second")

    response = client.post(
        "/profiles/rename",
        json={"profile_id": alice["profile_id"], "new_name": "Second"},
        headers=alice["headers"],
    )
    assert response.status_code == 400


def test_profile_delete_removes_all_profile_data(client, alice):
    pid, headers = alice["profile_id"], alice["headers"]
    client.post("/history/save", json={"profile_id": pid, "history": HISTORY}, headers=headers)
    client.post("/continue-watching/save", json={"profile_id": pid, "items": HISTORY}, headers=headers)
    client.post("/watch-again/save", json={"profile_id": pid, "items": HISTORY}, headers=headers)

    response = client.post("/profiles/delete", json={"profile_id": pid}, headers=headers)

    assert response.status_code == 200
    with SessionLocal() as db:
        for model in (WatchHistory, ContinueWatching, WatchAgain):
            assert db.query(model).filter(model.profile_id == pid).count() == 0


# ── Per-profile lists ─────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "save_path, get_path, field",
    [
        ("/history/save", "/history/{pid}", "history"),
        ("/continue-watching/save", "/continue-watching/{pid}", "items"),
        ("/watch-again/save", "/watch-again/{pid}", "items"),
    ],
)
def test_lists_round_trip_per_profile(client, alice, create_profile, save_path, get_path, field):
    headers, pid = alice["headers"], alice["profile_id"]
    other_pid = create_profile(headers, name="Kids")
    body_key = "history" if field == "history" else "items"

    client.post(save_path, json={"profile_id": pid, body_key: HISTORY}, headers=headers)

    assert client.get(get_path.format(pid=pid), headers=headers).json()[field] == HISTORY
    assert client.get(get_path.format(pid=other_pid), headers=headers).json()[field] == []


def test_history_size_is_capped(client, alice):
    response = client.post(
        "/history/save",
        json={"profile_id": alice["profile_id"], "history": [{"title": "x"}] * 101},
        headers=alice["headers"],
    )
    assert response.status_code == 422


# ── Cross-account isolation ───────────────────────────────────────────────────

@pytest.mark.parametrize(
    "method, path, body",
    [
        ("get", "/history/{pid}", None),
        ("post", "/history/save", {"profile_id": "{pid}", "history": []}),
        ("get", "/continue-watching/{pid}", None),
        ("post", "/continue-watching/save", {"profile_id": "{pid}", "items": []}),
        ("get", "/watch-again/{pid}", None),
        ("post", "/watch-again/save", {"profile_id": "{pid}", "items": []}),
        ("post", "/profiles/rename", {"profile_id": "{pid}", "new_name": "Hijacked"}),
        ("post", "/profiles/delete", {"profile_id": "{pid}"}),
        ("post", "/recommend", {"profile_id": "{pid}", "watch_history": [{"title": "X"}]}),
        ("post", "/feedback", {"profile_id": "{pid}", "movie_id": "m", "signal": -1, "model_variant": "bert4rec"}),
    ],
)
def test_other_accounts_profiles_are_not_found(client, alice, bob, method, path, body):
    """Bob must not read, write, rename or delete anything on Alice's profile."""
    pid = alice["profile_id"]
    client.post("/history/save", json={"profile_id": pid, "history": HISTORY}, headers=alice["headers"])

    kwargs = {}
    if body is not None:
        kwargs["json"] = {k: (v.format(pid=pid) if isinstance(v, str) else v) for k, v in body.items()}
    response = getattr(client, method)(path.format(pid=pid), headers=bob["headers"], **kwargs)

    assert response.status_code == 404
    # Alice's data and profile are untouched
    assert client.get(f"/history/{pid}", headers=alice["headers"]).json()["history"] == HISTORY
    profiles = client.get("/profiles", headers=alice["headers"]).json()["profiles"]
    assert [(p["id"], p["name"]) for p in profiles] == [(pid, "Main")]
