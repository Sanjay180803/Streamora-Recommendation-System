import pytest

import main
import recommender
from config import settings

WARM_HISTORY = [{"title": f"Movie {i}"} for i in (1, 2, 3, 4, 5)]
COLD_HISTORY = [{"title": "Movie 1"}]


def recommend(client, profile, watch_history=WARM_HISTORY, top_k=3):
    response = client.post(
        "/recommend",
        json={"profile_id": profile["profile_id"], "watch_history": watch_history, "top_k": top_k},
        headers=profile["headers"],
    )
    assert response.status_code == 200, response.text
    return response.json()


def feedback(client, profile, movie_id, signal):
    return client.post(
        "/feedback",
        json={"profile_id": profile["profile_id"], "movie_id": movie_id, "signal": signal},
        headers=profile["headers"],
    )


def rec_ids(body):
    return [m["item_id"] for m in body["recommendations"]]


def bandit(redis, variant, outcome):
    return int(redis.get(f"bandit:{variant}:{outcome}") or 0)


# ── /recommend ────────────────────────────────────────────────────────────────


def test_recommend_reports_mapping_coverage(client, catalogue, alice):
    history = WARM_HISTORY + [{"title": "TMDB-only film"}]
    body = recommend(client, alice, watch_history=history)

    assert body["cold_start"] is False
    assert body["model_variant"] in recommender.MODEL_VARIANTS
    assert (body["matched_items"], body["unmatched_items"]) == (5, 1)


def test_cold_start_is_labelled_popularity(client, catalogue, alice):
    body = recommend(client, alice, watch_history=COLD_HISTORY)

    assert body["cold_start"] is True
    assert body["model_variant"] == "popularity"


def test_cold_start_threshold_comes_from_settings(client, catalogue, alice, monkeypatch):
    monkeypatch.setattr(main, "settings", type(settings)(**{**settings.__dict__, "min_sequence_length": 1}))
    assert recommend(client, alice, watch_history=COLD_HISTORY)["cold_start"] is False


def test_second_request_is_served_from_cache(client, catalogue, alice, fake_redis):
    first = recommend(client, alice)
    second = recommend(client, alice)

    assert first["cache_hit"] is False
    assert second["cache_hit"] is True
    assert rec_ids(first) == rec_ids(second)


def test_served_items_are_attributed_to_the_model(client, catalogue, alice, fake_redis):
    body = recommend(client, alice)

    served = fake_redis.hgetall(f"served:{alice['profile_id']}")
    assert served == {item: body["model_variant"] for item in rec_ids(body)}
    assert 0 < fake_redis.ttl(f"served:{alice['profile_id']}") <= main.SERVED_TTL_SEC


def test_cold_start_items_are_not_attributed(client, catalogue, alice, fake_redis):
    recommend(client, alice, watch_history=COLD_HISTORY)
    assert fake_redis.hgetall(f"served:{alice['profile_id']}") == {}


# ── /feedback: suppression ────────────────────────────────────────────────────


def test_thumbs_down_suppresses_item_in_future_recommendations(client, catalogue, alice, fake_redis):
    first = recommend(client, alice)
    disliked = rec_ids(first)[0]

    assert feedback(client, alice, disliked, -1).status_code == 200
    second = recommend(client, alice)

    assert second["cache_hit"] is False, "feedback must invalidate the cached list"
    assert disliked not in rec_ids(second)
    assert len(rec_ids(second)) == 3


def test_thumbs_down_also_applies_to_cold_start(client, catalogue, alice, fake_redis):
    popular = rec_ids(recommend(client, alice, watch_history=COLD_HISTORY))[0]
    feedback(client, alice, popular, -1)

    assert popular not in rec_ids(recommend(client, alice, watch_history=COLD_HISTORY))


def test_suppression_expires_after_configured_period(client, catalogue, alice, fake_redis):
    feedback(client, alice, "item07", -1)

    ttl = fake_redis.ttl(f"never:{alice['profile_id']}")
    assert settings.dislike_suppression_days * 86400 - 5 < ttl <= settings.dislike_suppression_days * 86400


def test_suppression_is_per_profile(client, catalogue, alice, bob, fake_redis):
    disliked = rec_ids(recommend(client, alice))[0]
    feedback(client, alice, disliked, -1)

    assert disliked in rec_ids(recommend(client, bob))


def test_thumbs_up_does_not_suppress(client, catalogue, alice, fake_redis):
    liked = rec_ids(recommend(client, alice))[0]
    feedback(client, alice, liked, 1)

    assert liked in rec_ids(recommend(client, alice))


# ── /feedback: bandit ─────────────────────────────────────────────────────────


@pytest.mark.parametrize("signal, outcome", [(1, "wins"), (-1, "losses")])
def test_feedback_credits_the_model_that_served_the_item(
    client, catalogue, alice, fake_redis, signal, outcome
):
    body = recommend(client, alice)
    variant = body["model_variant"]

    feedback(client, alice, rec_ids(body)[0], signal)

    assert bandit(fake_redis, variant, outcome) == 1
    other = "sasrec" if variant == "bert4rec" else "bert4rec"
    assert bandit(fake_redis, other, "wins") == bandit(fake_redis, other, "losses") == 0


def test_each_served_item_counts_once(client, catalogue, alice, fake_redis):
    body = recommend(client, alice)
    item = rec_ids(body)[0]

    for _ in range(5):
        feedback(client, alice, item, 1)

    assert bandit(fake_redis, body["model_variant"], "wins") == 1


def test_client_cannot_choose_the_credited_model(client, catalogue, alice, fake_redis):
    body = recommend(client, alice)
    claimed = "sasrec" if body["model_variant"] == "bert4rec" else "bert4rec"

    client.post(
        "/feedback",
        json={
            "profile_id": alice["profile_id"],
            "movie_id": rec_ids(body)[0],
            "signal": 1,
            "model_variant": claimed,
        },
        headers=alice["headers"],
    )

    assert bandit(fake_redis, claimed, "wins") == 0
    assert bandit(fake_redis, body["model_variant"], "wins") == 1


def test_feedback_on_items_never_served_does_not_touch_the_bandit(client, catalogue, alice, fake_redis):
    feedback(client, alice, "item09", 1)
    assert fake_redis.keys("bandit:*") == []


# ── /feedback: validation and degraded mode ──────────────────────────────────


@pytest.mark.parametrize(
    "payload",
    [
        {"movie_id": "item01", "signal": 0},
        {"movie_id": "item01", "signal": 2},
        {"movie_id": "", "signal": 1},
        {"movie_id": "x" * 101, "signal": 1},
        {"signal": 1},
    ],
)
def test_invalid_feedback_is_rejected(client, alice, payload):
    response = client.post(
        "/feedback", json={"profile_id": alice["profile_id"], **payload}, headers=alice["headers"]
    )
    assert response.status_code == 422


def test_feedback_without_redis_still_succeeds(client, catalogue, alice, monkeypatch):
    monkeypatch.setattr(main, "_redis", None)
    assert feedback(client, alice, "item01", -1).json() == {"status": "ok"}


def test_feedback_event_records_server_side_variant(client, catalogue, alice, fake_redis, monkeypatch):
    events = []
    monkeypatch.setattr(main, "_publish_feedback", events.append)
    body = recommend(client, alice)

    feedback(client, alice, rec_ids(body)[0], 1)

    [event] = events
    assert event["profile_id"] == alice["profile_id"]
    assert event["model_variant"] == body["model_variant"]
    assert "email" not in event
