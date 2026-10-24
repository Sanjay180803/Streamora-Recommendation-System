import sys
from types import ModuleType

import numpy as np
import pandas as pd
import pytest

import semantic_search
from tests.fakes import write_catalogue

VOCAB = ["drama", "comedy", "science", "fiction", "movie", "0", "1", "2", "3", "4", "5"]


class FakeSentenceTransformer:
    """Bag-of-words embedding over a tiny vocabulary — deterministic and offline."""

    instances = []

    def __init__(self, name):
        self.name = name
        FakeSentenceTransformer.instances.append(self)

    def encode(self, texts, normalize_embeddings=True, convert_to_numpy=True, **_):
        vectors = np.array(
            [[float(word in text.lower().split()) for word in VOCAB] for text in texts],
            dtype=np.float32,
        )
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        return vectors / np.where(norms == 0, 1, norms)


@pytest.fixture
def search_index(tmp_path, monkeypatch):
    fake_module = ModuleType("sentence_transformers")
    fake_module.SentenceTransformer = FakeSentenceTransformer
    monkeypatch.setitem(sys.modules, "sentence_transformers", fake_module)
    monkeypatch.setattr(semantic_search, "_search_model", None)
    monkeypatch.setattr(semantic_search, "_item_embeddings", None)

    write_catalogue(tmp_path)
    semantic_search.load_search_index(pd.read_csv(tmp_path / "item_features_final.csv"))


def test_search_returns_empty_before_index_is_built(monkeypatch):
    monkeypatch.setattr(semantic_search, "_search_model", None)
    assert semantic_search.semantic_search("drama") == []


def test_index_embeds_title_year_and_genres(search_index):
    assert FakeSentenceTransformer.instances[-1].name == "all-MiniLM-L6-v2"
    assert semantic_search._item_embeddings.shape == (13, len(VOCAB))


def test_results_are_ranked_by_similarity(search_index):
    results = semantic_search.semantic_search("comedy", top_k=4)

    assert len(results) == 4
    assert all("Comedy" in r["genres"] for r in results)
    scores = [r["score"] for r in results]
    assert scores == sorted(scores, reverse=True)


def test_genre_words_match_without_title_overlap(search_index):
    [top] = semantic_search.semantic_search("science fiction", top_k=1)
    assert "Science Fiction" in top["genres"]


def test_search_endpoint_requires_auth_and_maps_results_to_catalogue(client, catalogue, search_index, alice):
    assert client.get("/search?q=comedy").status_code == 401

    body = client.get("/search?q=comedy&top_k=3", headers=alice["headers"]).json()

    assert len(body["results"]) == 3
    assert all({"item_id", "title", "similarity_score"} <= set(r) for r in body["results"])


@pytest.mark.parametrize("top_k, expected", [(0, 1), (-5, 1), (100, 13)])
def test_search_endpoint_clamps_top_k(client, catalogue, search_index, alice, top_k, expected):
    body = client.get(f"/search?q=movie&top_k={top_k}", headers=alice["headers"]).json()
    assert len(body["results"]) == min(expected, 20)


def test_short_queries_return_nothing(client, alice):
    assert client.get("/search?q=a", headers=alice["headers"]).json()["results"] == []
