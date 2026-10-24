import fakeredis
import numpy as np
import pytest

import recommender
from schemas import WatchItem
from tests.fakes import N_ITEMS, SEQ_LEN, item_id


def history(*indices, extra=()):
    return [WatchItem(title=f"Movie {i}") for i in indices] + [WatchItem(title=t) for t in extra]


def ids(cards):
    return [c.item_id for c in cards]


def recommend(watch_history, *, session="profile-a", top_k=3, exclude=frozenset(), min_len=3, redis=None):
    return recommender.get_recommendations(
        session_id=session,
        watch_history=watch_history,
        top_k=top_k,
        redis_client=redis,
        exclude_item_ids=exclude,
        min_sequence_length=min_len,
    )


def session_routed_to(variant):
    for i in range(100):
        sid = f"profile-{i}"
        if recommender.get_model_variant(sid) == variant:
            return sid
    raise AssertionError(f"no session id routes to {variant}")


# ── Loading ───────────────────────────────────────────────────────────────────

def test_catalogue_loads(catalogue):
    assert recommender.is_loaded()
    assert recommender.item_count() == N_ITEMS + 1
    assert catalogue["bert4rec"] is not None and catalogue["sasrec"] is not None


def test_duplicate_titles_map_to_most_clicked_id(catalogue):
    tokens, unmatched = recommender.build_sequence(history(3), "bert4rec")
    assert unmatched == 0
    assert tokens == [3 + recommender.TOKEN_OFFSET_BERT4REC]


def test_missing_artifacts_fail_with_a_clear_message(tmp_path):
    with pytest.raises(FileNotFoundError) as error:
        recommender.load_data(str(tmp_path), str(tmp_path / "bert4rec_v3.onnx"))

    message = str(error.value)
    for name in ("item_features_final.csv", "user_features_final.csv", "bert4rec_v3.onnx"):
        assert name in message
    assert "docs/artifacts.md" in message


def test_sasrec_model_is_optional(tmp_path, monkeypatch):
    from tests.fakes import FakeSession, write_catalogue

    write_catalogue(tmp_path)
    (tmp_path / "bert4rec.onnx").touch()
    monkeypatch.setattr(recommender.ort, "InferenceSession", lambda path, **kw: FakeSession(path, 2))

    recommender.load_data(str(tmp_path), str(tmp_path / "bert4rec.onnx"), str(tmp_path / "missing.onnx"))

    assert recommender.is_loaded()
    assert recommender._ort_session_sasrec is None


# ── Title mapping ─────────────────────────────────────────────────────────────

def test_only_exact_catalogue_titles_become_tokens(catalogue):
    items = [
        WatchItem(title="movie 1"),
        WatchItem(title="  MOVIE 2  "),
        WatchItem(title="Some TMDB-only Film", genres=["Drama"], release_year=2003),
        WatchItem(title="Movie 22"),
    ]
    tokens, unmatched = recommender.build_sequence(items, "bert4rec")

    offset = recommender.TOKEN_OFFSET_BERT4REC
    assert tokens == [1 + offset, 2 + offset]
    assert unmatched == 2


def test_unknown_titles_never_fill_a_sequence_past_the_cold_start_gate(catalogue):
    result = recommend(history(1, extra=["Unknown A", "Unknown B", "Unknown C"]), min_len=2)

    assert result.cold_start is True
    assert result.model_variant == recommender.POPULARITY_VARIANT
    assert (result.matched_items, result.unmatched_items) == (1, 3)
    assert catalogue["bert4rec"].feeds == []


@pytest.mark.parametrize("variant, offset", [("bert4rec", 2), ("sasrec", 1)])
def test_token_offsets_per_model(catalogue, variant, offset):
    tokens, _ = recommender.build_sequence(history(0, 5), variant)
    assert tokens == [0 + offset, 5 + offset]


def test_sequence_keeps_the_most_recent_items(catalogue, monkeypatch):
    monkeypatch.setattr(recommender, "MAX_SEQ_LEN", 3)
    tokens, _ = recommender.build_sequence(history(1, 2, 3, 4, 5), "bert4rec")
    assert tokens == [3 + 2, 4 + 2, 5 + 2]


# ── Cold start ────────────────────────────────────────────────────────────────

def test_cold_start_returns_popular_unwatched_items(catalogue):
    result = recommend(history(0), top_k=3, min_len=3)

    assert result.cold_start is True
    assert result.model_variant == "popularity"
    assert ids(result.cards) == [item_id(1), item_id(2), item_id(3)]


def test_cold_start_skips_excluded_items(catalogue):
    result = recommend(history(0), top_k=3, exclude={item_id(1), item_id(3)}, min_len=3)
    assert ids(result.cards) == [item_id(2), item_id(4), item_id(5)]


@pytest.mark.parametrize("min_len, cold", [(1, False), (2, False), (3, True)])
def test_threshold_is_configurable(catalogue, min_len, cold):
    # 2 matched titles + 1 unknown title
    result = recommend(history(4, 5, extra=["Unknown"]), min_len=min_len)
    assert result.cold_start is cold


def test_threshold_counts_matched_titles_only(catalogue):
    at_threshold = recommend(history(1, 2, 3), min_len=3)
    below = recommend(history(1, 2, extra=["Unknown"]), min_len=3)

    assert at_threshold.cold_start is False
    assert below.cold_start is True


# ── Inference ─────────────────────────────────────────────────────────────────

def test_inference_input_is_left_padded_with_mask_and_neutral_user_features(catalogue):
    sid = session_routed_to("bert4rec")
    recommend(history(1, 2, 3), session=sid)

    [feed] = catalogue["bert4rec"].feeds
    input_ids = feed["input_ids"]
    assert input_ids.shape == (1, SEQ_LEN) and input_ids.dtype == np.int64
    assert input_ids[0, :-3].tolist() == [0] * (SEQ_LEN - 3)
    assert input_ids[0, -3:].tolist() == [3, 4, 5]
    assert feed["pad_mask"].tolist() == (input_ids != 0).tolist()
    assert feed["user_feats"].shape[0] == 1
    assert not feed["user_feats"].any(), "inference uses a zero (population-mean) user vector"


def test_inference_ranks_by_model_scores_and_excludes_watched_and_rejected(catalogue):
    sid = session_routed_to("bert4rec")
    result = recommend(history(11, 9, 8), session=sid, top_k=3, exclude={item_id(10)})

    # The fake model prefers higher indices: 12 (dup id), 11, 10, 9 ... minus excluded
    assert result.cold_start is False
    assert result.model_variant == "bert4rec"
    assert ids(result.cards) == ["item03-dup", item_id(7), item_id(6)]


def test_sasrec_requests_use_the_sasrec_model_and_offset(catalogue):
    sid = session_routed_to("sasrec")
    result = recommend(history(1, 2, 3), session=sid)

    assert result.model_variant == "sasrec"
    assert catalogue["bert4rec"].feeds == []
    [feed] = catalogue["sasrec"].feeds
    assert feed["input_ids"][0, -3:].tolist() == [2, 3, 4]


def test_missing_sasrec_model_falls_back_to_bert4rec_offsets(catalogue, monkeypatch):
    monkeypatch.setattr(recommender, "_ort_session_sasrec", None)
    sid = session_routed_to("sasrec")

    result = recommend(history(1, 2, 3), session=sid)

    assert result.model_variant == "bert4rec"
    [feed] = catalogue["bert4rec"].feeds
    assert feed["input_ids"][0, -3:].tolist() == [3, 4, 5]


def test_top_k_is_respected(catalogue):
    assert len(recommend(history(1, 2, 3), top_k=5).cards) == 5


# ── Model routing ─────────────────────────────────────────────────────────────

def test_routing_without_feedback_is_a_stable_hash_split():
    variants = {recommender.get_model_variant(f"profile-{i}") for i in range(50)}
    assert variants == {"bert4rec", "sasrec"}
    assert recommender.get_model_variant("profile-1") == recommender.get_model_variant("profile-1")


def test_routing_ignores_bandit_until_ten_feedback_events():
    redis = fakeredis.FakeRedis(decode_responses=True)
    redis.set("bandit:sasrec:wins", 9)
    sid = session_routed_to("bert4rec")
    assert all(recommender.get_model_variant(sid, redis) == "bert4rec" for _ in range(20))


def test_thompson_sampling_favours_the_winning_model():
    redis = fakeredis.FakeRedis(decode_responses=True)
    redis.set("bandit:sasrec:wins", 200)
    redis.set("bandit:bert4rec:losses", 200)
    np.random.seed(0)

    picks = [recommender.get_model_variant("any", redis) for _ in range(200)]
    assert picks.count("sasrec") > 190


# ── Cache key ─────────────────────────────────────────────────────────────────

def test_cache_key_depends_on_profile_order_and_k():
    base = recommender.make_cache_key("p1", history(1, 2), 10)

    assert base == recommender.make_cache_key("p1", history(1, 2), 10)
    assert base != recommender.make_cache_key("p2", history(1, 2), 10)
    assert base != recommender.make_cache_key("p1", history(2, 1), 10)
    assert base != recommender.make_cache_key("p1", history(1, 2), 5)
