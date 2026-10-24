"""
main.py
FastAPI application entrypoint.

Endpoints:
  GET  /health          — liveness check (Docker healthcheck, monitoring)
  POST /recommend       — get movie recommendations for a profile's watch history
  POST /feedback        — record a thumbs up / thumbs down signal
  GET  /genres          — list all genres in the catalogue
  GET  /search          — semantic search over the catalogue

Configuration is read from the environment by config.py; see backend/.env.example.
"""

import json
import logging
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import redis as redis_lib
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

import recommender
from auth import router as auth_router
from config import settings
from database import User, get_db, init_db
from schemas import (
    FeedbackRequest,
    FeedbackResponse,
    HealthResponse,
    MovieCard,
    RecommendRequest,
    RecommendResponse,
)
from security import get_current_user, get_owned_profile
from semantic_search import semantic_search
from tmdb import router as tmdb_router
from watch_party import router as watch_party_router

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(name)s  %(message)s")
logger = logging.getLogger(__name__)

SERVED_TTL_SEC = 24 * 3600  # how long feedback can be attributed to a served model

# ─────────────────────────────────────────────────────────────────────────────
# REDIS KEYS
#   rec:{profile}:{digest}       cached recommendation response
#   never:{profile}              set of thumbs-down item ids (suppressed)
#   served:{profile}             hash item_id → model variant that served it
#   bandit:{variant}:wins|losses Thompson-sampling counters
# ─────────────────────────────────────────────────────────────────────────────

_redis: redis_lib.Redis | None = None


def get_redis() -> redis_lib.Redis | None:
    return _redis


def _disliked_items(profile_id: str) -> set[str]:
    if _redis is None:
        return set()
    try:
        return set(_redis.smembers(f"never:{profile_id}"))
    except Exception as e:
        logger.warning(f"Redis read error: {e}")
        return set()


def _invalidate_cached_recommendations(profile_id: str) -> None:
    for key in _redis.scan_iter(match=f"rec:{profile_id}:*"):
        _redis.delete(key)


# ─────────────────────────────────────────────────────────────────────────────
# KAFKA PRODUCER  (optional — enabled only when KAFKA_BOOTSTRAP is set)
# Feedback events are published to the 'user_feedback' topic for downstream
# consumers. This repository does not include a consumer.
# ─────────────────────────────────────────────────────────────────────────────

_kafka_producer = None


def _init_kafka():
    global _kafka_producer
    if not settings.kafka_bootstrap:
        logger.info("Kafka disabled (KAFKA_BOOTSTRAP not set)")
        return
    try:
        from kafka import KafkaProducer
        _kafka_producer = KafkaProducer(
            bootstrap_servers=settings.kafka_bootstrap,
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
            request_timeout_ms=3000,
            retries=3,
        )
        logger.info("Kafka producer connected ✓")
    except Exception as e:
        logger.warning(f"Kafka not available ({e}). Feedback will be logged only.")
        _kafka_producer = None


def _publish_feedback(event: dict):
    """Publish a feedback event to Kafka topic 'user_feedback' when enabled."""
    if _kafka_producer is not None:
        try:
            _kafka_producer.send("user_feedback", event)
        except Exception as e:
            logger.warning(f"Kafka publish failed: {e}")
    logger.info(f"FEEDBACK  {json.dumps(event)}")


# ─────────────────────────────────────────────────────────────────────────────
# LIFESPAN  (runs at startup and shutdown)
# ─────────────────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── STARTUP ──────────────────────────────────────────────────────────────
    global _redis

    logger.info("=== Starting up ===")
    init_db()

    # Load data and ONNX model into memory
    recommender.load_data(
        settings.data_dir, settings.bert4rec_model_path, settings.sasrec_model_path
    )
    logger.info(f"Items in catalogue: {recommender.item_count()}")

    # Connect to Redis (optional — caching, dislike suppression and the bandit need it)
    if settings.redis_url:
        try:
            _redis = redis_lib.from_url(settings.redis_url, decode_responses=True)
            _redis.ping()
            logger.info("Redis connected ✓")
        except Exception as e:
            logger.warning(f"Redis not available ({e}). Caching and feedback memory disabled.")
            _redis = None

    _init_kafka()

    logger.info("=== Ready to serve requests ===")

    yield  # FastAPI runs here

    # ── SHUTDOWN ─────────────────────────────────────────────────────────────
    logger.info("Shutting down...")
    if _kafka_producer:
        _kafka_producer.flush()
        _kafka_producer.close()


# ─────────────────────────────────────────────────────────────────────────────
# APP
# ─────────────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Streamora Recommendation API",
    version="1.0.0",
    description="BERT4Rec / SASRec recommendation API with Thompson-sampling model routing",
    lifespan=lifespan,
)
app.include_router(auth_router)
app.include_router(tmdb_router)
app.include_router(watch_party_router)

# CORS — only the configured frontend origins may call this API from a browser
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)


# ─────────────────────────────────────────────────────────────────────────────
# ENDPOINTS
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/health", response_model=HealthResponse)
def health():
    """
    Liveness check.  Docker healthcheck hits this every 30s.
    Returns 200 if the model is loaded and Redis is reachable.
    """
    redis_ok = False
    if _redis:
        try:
            _redis.ping()
            redis_ok = True
        except Exception:
            pass

    return HealthResponse(
        status="ok",
        model_loaded=recommender.is_loaded(),
        redis_connected=redis_ok,
        items_loaded=recommender.item_count(),
    )


@app.post("/recommend", response_model=RecommendResponse)
def recommend(
    req: RecommendRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Main recommendation endpoint.

    Flow:
      1. Check Redis cache — if hit, return immediately
      2. Choose a model variant (Thompson sampling once enough feedback exists)
      3. Map watch-history titles to catalogue items (exact matches only)
      4. Too few matches → cold-start popularity fallback
      5. Else → ONNX inference, excluding watched and thumbs-down items
      6. Remember which model served each item, then cache the response

    Request body:
      { "watch_history": [{"title": "Movie Title 1"}, ...], "profile_id": "uuid", "top_k": 10 }
    """
    t_start = time.perf_counter()
    get_owned_profile(req.profile_id, user, db)

    # ── 1. Cache check ────────────────────────────────────────────────────────
    cache_key = recommender.make_cache_key(req.profile_id, req.watch_history, req.top_k)

    if _redis:
        try:
            cached = _redis.get(cache_key)
            if cached:
                data = json.loads(cached)
                logger.info(
                    f"Cache HIT  key={cache_key[:20]}...  "
                    f"latency={1000*(time.perf_counter()-t_start):.1f}ms"
                )
                return RecommendResponse(
                    **{**data, "recommendations": [MovieCard(**m) for m in data["recommendations"]]},
                    cache_hit=True,
                )
        except Exception as e:
            logger.warning(f"Redis read error: {e}")

    # ── 2–5. Inference ────────────────────────────────────────────────────────
    try:
        result = recommender.get_recommendations(
            session_id=req.profile_id,
            watch_history=req.watch_history,
            top_k=req.top_k,
            redis_client=_redis,
            exclude_item_ids=_disliked_items(req.profile_id),
            min_sequence_length=settings.min_sequence_length,
        )
    except Exception as e:
        logger.error(f"Inference error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Inference failed. See server logs.")

    response = RecommendResponse(
        recommendations=result.cards,
        model_variant=result.model_variant,
        cache_hit=False,
        cold_start=result.cold_start,
        matched_items=result.matched_items,
        unmatched_items=result.unmatched_items,
    )

    # ── 6. Attribution + cache ────────────────────────────────────────────────
    if _redis and result.cards:
        try:
            if result.model_variant in recommender.MODEL_VARIANTS:
                served_key = f"served:{req.profile_id}"
                _redis.hset(served_key, mapping={c.item_id: result.model_variant for c in result.cards})
                _redis.expire(served_key, SERVED_TTL_SEC)
            _redis.setex(
                cache_key,
                settings.recommendation_cache_ttl_sec,
                response.model_dump_json(exclude={"cache_hit"}),
            )
        except Exception as e:
            logger.warning(f"Redis write error: {e}")

    latency_ms = 1000 * (time.perf_counter() - t_start)
    logger.info(
        f"Cache MISS  variant={result.model_variant}  cold_start={result.cold_start}  "
        f"matched={result.matched_items}  unmatched={result.unmatched_items}  "
        f"n_results={len(result.cards)}  latency={latency_ms:.1f}ms"
    )
    return response


@app.post("/feedback", response_model=FeedbackResponse)
def feedback(
    req: FeedbackRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Record a thumbs up (signal=1) or thumbs down (signal=-1).

    With Redis available:
      - The model that served the item (recorded by /recommend) gets a win or a
        loss for Thompson sampling. Each served item counts at most once.
      - Thumbs down adds the item to the profile's suppression set for
        DISLIKE_SUPPRESSION_DAYS (refreshed on every new dislike).
      - Cached recommendations for the profile are invalidated.

    The event is also logged and, when Kafka is enabled, published to the
    'user_feedback' topic.
    """
    get_owned_profile(req.profile_id, user, db)
    variant = None

    if _redis:
        try:
            served_key = f"served:{req.profile_id}"
            variant = _redis.hget(served_key, req.movie_id)
            if variant in recommender.MODEL_VARIANTS:
                outcome = "wins" if req.signal == 1 else "losses"
                _redis.incr(f"bandit:{variant}:{outcome}")
                _redis.hdel(served_key, req.movie_id)

            if req.signal == -1:
                never_key = f"never:{req.profile_id}"
                _redis.sadd(never_key, req.movie_id)
                _redis.expire(never_key, settings.dislike_suppression_days * 24 * 3600)

            _invalidate_cached_recommendations(req.profile_id)
        except Exception as e:
            logger.warning(f"Redis feedback error: {e}")

    _publish_feedback({
        "profile_id":    req.profile_id,
        "movie_id":      req.movie_id,
        "signal":        req.signal,
        "model_variant": variant,
        "timestamp":     datetime.now(timezone.utc).isoformat(),
    })
    return FeedbackResponse(status="ok")


@app.get("/genres", response_model=dict)
def genres():
    """
    Return the list of all genres in the item catalogue.
    The React frontend uses this to populate the genre filter dropdown.
    """
    all_genres: set[str] = set()
    for card in recommender._idx_to_card.values():
        all_genres.update(card.genres)
    return {"genres": sorted(all_genres)}


@app.get("/search")
def search(q: str, top_k: int = 10, user: User = Depends(get_current_user)):
    """
    Semantic search over the catalogue.
    Returns catalogue movies most similar to the query by meaning.
    Example: /search?q=dark+psychological+thriller
    """
    if not q or len(q.strip()) < 2:
        return {"results": [], "query": q}

    results = semantic_search(q.strip()[:200], top_k=max(1, min(top_k, 20)))

    # Convert to MovieCard format
    cards = []
    for r in results:
        card = recommender._idx_to_card.get(r["item_idx"])
        if card:
            cards.append({
                "item_id":     card.item_id,
                "item_idx":    card.item_idx,
                "title":       card.title,
                "release_year": card.release_year,
                "genres":      card.genres,
                "log_popularity": card.log_popularity,
                "similarity_score": round(r["score"], 3),
            })

    return {"results": cards, "query": q}
