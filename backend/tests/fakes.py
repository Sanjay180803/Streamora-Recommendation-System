"""Test doubles for the recommender's external artifacts (CSVs and ONNX models)."""

from types import SimpleNamespace

import numpy as np
import pandas as pd

N_ITEMS = 12
SEQ_LEN = 50


def item_id(idx: int) -> str:
    return f"item{idx:02d}"


def write_catalogue(data_dir) -> None:
    """Write small item/user feature CSVs with the columns load_data expects.

    Items are "Movie 0".."Movie 11". Popularity decreases with the index, so the
    cold-start order is Movie 0, Movie 1, ... "Movie 3" also appears a second
    time under a less-clicked id to exercise canonical title mapping.
    """
    rows = []
    for idx in range(N_ITEMS):
        rows.append({
            "item_id": item_id(idx),
            "item_idx": idx,
            "title": f"Movie {idx}",
            "release_year": 2000 + idx,
            "click_count": 100,
            "log_popularity": float(N_ITEMS - idx),
            "genre_drama": int(idx % 2 == 0),
            "genre_comedy": int(idx % 2 == 1),
            "genre_science_fiction": int(idx % 3 == 0),
        })
    rows.append({**rows[3], "item_id": "item03-dup", "item_idx": N_ITEMS, "click_count": 1,
                 "log_popularity": 0.0})
    pd.DataFrame(rows).to_csv(data_dir / "item_features_final.csv", index=False)

    pd.DataFrame({
        "user_id": ["u1", "u2", "u3"],
        "user_idx": [0, 1, 2],
        "first_seen": ["2020-01-01"] * 3,
        "last_seen": ["2020-02-01"] * 3,
        "total_clicks": [5, 50, 500],
        "avg_session_minutes": [10.0, 20.0, 30.0],
        "user_engagement_tier": ["low", "mid", "high"],
        "user_preferred_hour_bucket": ["morning", "evening", "night"],
    }).to_csv(data_dir / "user_features_final.csv", index=False)


class FakeSession:
    """Stands in for onnxruntime.InferenceSession.

    Scores each token by its own value, so higher item indices rank first, and
    records every feed so tests can check exactly what the model received.
    """

    def __init__(self, path, token_offset, **_):
        self.path = str(path)
        self.vocab = (N_ITEMS + 1) + token_offset
        self.feeds = []

    def get_inputs(self):
        return [SimpleNamespace(name=n) for n in ("input_ids", "pad_mask", "user_feats")]

    def run(self, _output_names, feed):
        self.feeds.append(feed)
        logits = np.tile(np.arange(self.vocab, dtype=np.float32), (1, SEQ_LEN, 1))
        return [logits]
