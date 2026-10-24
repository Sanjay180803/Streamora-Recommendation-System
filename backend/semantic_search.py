"""
semantic_search.py
Semantic search module for the recommendation system.
Loads sentence-transformers model at startup, pre-computes embeddings
for all 9,387 catalogue items, serves cosine similarity search.

Add to recommender.py globals and load_data(), then wire up in main.py.
"""

import logging

import numpy as np

logger = logging.getLogger("recommender")

# ── Globals ───────────────────────────────────────────────────────────────────
_search_model = None  # SentenceTransformer, imported lazily (pulls in PyTorch)
_item_embeddings: np.ndarray | None = None   # shape: [N, 384]
_item_search_index: list[dict] | None = None  # [{item_idx, item_id, title, genres, release_year}]


def load_search_index(item_features_df) -> None:
    """
    Call once at startup after item features are loaded.
    Builds text descriptions for all catalogue items and computes embeddings.
    """
    global _search_model, _item_embeddings, _item_search_index

    from sentence_transformers import SentenceTransformer

    logger.info("Loading semantic search model (all-MiniLM-L6-v2)...")
    _search_model = SentenceTransformer("all-MiniLM-L6-v2")
    logger.info("  Search model loaded ✓")

    # Build text descriptions: "Title (year) - Genre1 Genre2 Genre3"
    genre_cols = [c for c in item_features_df.columns if c.startswith("genre_")]
    descriptions = []
    index = []

    for _, row in item_features_df.iterrows():
        genres = [
            col.replace("genre_", "").replace("_", " ").title()
            for col in genre_cols if row[col] == 1
        ]
        year = int(row["release_year"]) if "release_year" in row and row["release_year"] == row["release_year"] else ""
        title = str(row["title"]) if "title" in row else ""
        genre_str = " ".join(genres) if genres else "Drama"
        desc = f"{title} {year} {genre_str}".strip()
        descriptions.append(desc)
        index.append({
            "item_idx":    int(row["item_idx"]),
            "item_id":     str(row["item_id"]),
            "title":       title,
            "genres":      genres,
            "release_year": int(year) if year else None,
        })

    logger.info(f"  Computing embeddings for {len(descriptions)} items...")
    _item_embeddings = _search_model.encode(
        descriptions,
        batch_size=256,
        show_progress_bar=False,
        normalize_embeddings=True,   # L2 normalised → dot product = cosine similarity
        convert_to_numpy=True,
    )
    _item_search_index = index
    logger.info(f"  Embeddings shape: {_item_embeddings.shape} ✓")


def semantic_search(query: str, top_k: int = 10) -> list[dict]:
    """
    Search catalogue by semantic similarity.
    Returns list of {item_idx, item_id, title, genres, release_year, score}.
    """
    if _search_model is None or _item_embeddings is None:
        return []

    # Embed the query
    query_emb = _search_model.encode(
        [query],
        normalize_embeddings=True,
        convert_to_numpy=True,
    )  # shape: [1, 384]

    # Cosine similarity (dot product since both are L2 normalised)
    scores = (_item_embeddings @ query_emb.T).squeeze()  # shape: [N]

    # Get top-K indices
    top_indices = np.argsort(scores)[::-1][:top_k]

    results = []
    for idx in top_indices:
        item = _item_search_index[idx].copy()
        item["score"] = float(scores[idx])
        results.append(item)

    return results
