"""
main.py
FastAPI application entrypoint.

Endpoints:
  GET  /health          — liveness check (Docker healthcheck, monitoring)
  POST /recommend       — get movie recommendations for a watch history
  POST /feedback        — log a thumbs up / thumbs down signal
  GET  /genres          — list all genres in the catalogue

Environment variables (set in .env):
  REDIS_URL             — redis://localhost:6379
  KAFKA_BOOTSTRAP       — localhost:9092
  DATA_DIR              — path to folder containing the three cleaned CSVs
  MODEL_PATH            — path to bert4rec.onnx
  COLD_START_K          — how many items to return for cold-start users (default 10)
  MIN_SEQUENCE_LENGTH   — minimum sequence length before cold-start fallback (default 5)
  MAX_SEQUENCE_LENGTH   — model's max input length (default 50)
"""

import json
import logging
import os
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import redis as redis_lib
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from database import init_db
from auth import router as auth_router
from tmdb import router as tmdb_router

import recommender
from semantic_search import semantic_search
from schemas import (
    FeedbackRequest,
    FeedbackResponse,
    HealthResponse,
    MovieCard,
    RecommendRequest,
    RecommendResponse,
)

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(name)s  %(message)s")
logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# CONFIG  (from environment)
# ─────────────────────────────────────────────────────────────────────────────

DATA_DIR      = os.getenv("DATA_DIR", "../data/output")
MODEL_PATH       = os.getenv("MODEL_PATH", "../data/bert4rec_v3.onnx")
SASREC_PATH      = os.getenv("SASREC_MODEL_PATH", "../data/sasrec_v3.onnx")
REDIS_URL     = os.getenv("REDIS_URL", "redis://localhost:6379")
KAFKA_BOOT    = os.getenv("KAFKA_BOOTSTRAP", "localhost:9092")
COLD_START_K  = int(os.getenv("COLD_START_K", "10"))
CACHE_TTL_SEC = 3600  # cache recommendation results for 1 hour

# ─────────────────────────────────────────────────────────────────────────────
# REDIS CLIENT  (module-level, reconnects automatically)
# ─────────────────────────────────────────────────────────────────────────────

_redis: redis_lib.Redis | None = None


def get_redis() -> redis_lib.Redis | None:
    return _redis


# ─────────────────────────────────────────────────────────────────────────────
# KAFKA PRODUCER  (optional — if Kafka is down, feedback still works via logging)
# ─────────────────────────────────────────────────────────────────────────────

_kafka_producer = None


def _init_kafka():
    global _kafka_producer
    try:
        from kafka import KafkaProducer
        _kafka_producer = KafkaProducer(
            bootstrap_servers=KAFKA_BOOT,
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
            request_timeout_ms=3000,
            retries=3,
        )
        logger.info("Kafka producer connected ✓")
    except Exception as e:
        logger.warning(f"Kafka not available ({e}). Feedback will be logged only.")
        _kafka_producer = None


def _publish_feedback(event: dict):
    """Publish a feedback event to Kafka topic 'user_feedback'. Non-blocking."""
    if _kafka_producer is not None:
        try:
            _kafka_producer.send("user_feedback", event)
        except Exception as e:
            logger.warning(f"Kafka publish failed: {e}")
    # Always log it — Streamlit dashboard can also tail the app log
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
    recommender.load_data(DATA_DIR, MODEL_PATH, SASREC_PATH)
    logger.info(f"Items in catalogue: {recommender.item_count()}")

    # Connect to Redis
    try:
        _redis = redis_lib.from_url(REDIS_URL, decode_responses=True)
        _redis.ping()
        logger.info("Redis connected ✓")
    except Exception as e:
        logger.warning(f"Redis not available ({e}). Caching disabled.")
        _redis = None

    # Connect to Kafka (optional)
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
    title="Netflix Recommendation System",
    version="1.0.0",
    description="BERT4Rec / SASRec recommendation API with A/B testing",
    lifespan=lifespan,
)
app.include_router(auth_router)
app.include_router(tmdb_router)

# CORS — allow the React frontend (and localhost dev) to call this API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
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
def recommend(req: RecommendRequest):
    """
    Main recommendation endpoint.

    Flow:
      1. Check Redis cache — if hit, return immediately (~1ms)
      2. Determine A/B model variant from session_id hash
      3. Build token sequence from watch_history titles
      4. If sequence too short → cold-start popularity fallback
      5. Else → run ONNX inference
      6. Write result to Redis cache (TTL = 1 hour)
      7. Return recommendations + metadata

    Request body:
      { "watch_history": ["Movie Title 1", ...], "session_id": "uuid", "top_k": 10 }
    """
    t_start = time.perf_counter()

    # ── 1. Cache check ────────────────────────────────────────────────────────
    cache_key = recommender.make_cache_key(req.session_id, req.watch_history, req.top_k)
    cache_hit = False

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
                    recommendations=[MovieCard(**m) for m in data["recommendations"]],
                    model_variant=data["model_variant"],
                    cache_hit=True,
                    cold_start=data["cold_start"],
                )
        except Exception as e:
            logger.warning(f"Redis read error: {e}")

    # ── 2–5. Inference ────────────────────────────────────────────────────────
    try:
        cards, model_variant, cold_start = recommender.get_recommendations(
            session_id=req.session_id,
            watch_history=req.watch_history,
            top_k=req.top_k,
            redis_client=_redis,
        )
    except Exception as e:
        logger.error(f"Inference error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Inference failed. See server logs.")

    # ── Option A: Filter hard negatives ──────────────────────────────────────
    if _redis and cards:
        try:
            never_key = f"never:{req.session_id}"
            never_set = _redis.smembers(never_key)
            if never_set:
                never_ids = {m.decode() if isinstance(m, bytes) else m for m in never_set}
                before = len(cards)
                cards = [c for c in cards if c.item_id not in never_ids]
                if len(cards) < before:
                    logger.info(f"  Hard negative filter: removed {before - len(cards)} disliked movies")
        except Exception as e:
            logger.warning(f"Hard negative filter error: {e}")

    # ── 6. Write to cache ─────────────────────────────────────────────────────
    if _redis and cards:
        try:
            payload = json.dumps({
                "recommendations": [c.model_dump() for c in cards],
                "model_variant": model_variant,
                "cold_start": cold_start,
            })
            _redis.setex(cache_key, CACHE_TTL_SEC, payload)
        except Exception as e:
            logger.warning(f"Redis write error: {e}")

    latency_ms = 1000 * (time.perf_counter() - t_start)
    logger.info(
        f"Cache MISS  variant={model_variant}  cold_start={cold_start}  "
        f"n_results={len(cards)}  latency={latency_ms:.1f}ms"
    )

    return RecommendResponse(
        recommendations=cards,
        model_variant=model_variant,
        cache_hit=False,
        cold_start=cold_start,
    )


@app.post("/feedback", response_model=FeedbackResponse)
def feedback(req: FeedbackRequest):
    """
    Log a thumbs up (signal=1) or thumbs down (signal=-1).

    The event is published to Kafka topic 'user_feedback' so the
    Streamlit A/B dashboard can consume it in real time.
    If Kafka is unavailable, the event is logged to stdout instead.

    Request body:
      { "session_id": "uuid", "movie_id": "e847f14da5",
        "signal": 1, "model_variant": "bert4rec" }
    """
    event = {
        "session_id":    req.session_id,
        "movie_id":      req.movie_id,
        "signal":        req.signal,
        "model_variant": req.model_variant,
        "timestamp":     datetime.now(timezone.utc).isoformat(),
    }
    _publish_feedback(event)
    return FeedbackResponse(status="ok")


@app.get("/genres", response_model=dict)
def genres():
    """
    Return the list of all genres in the item catalogue.
    The React frontend uses this to populate the genre filter dropdown.
    """
    # Extract genre names from the MovieCard genre lists
    all_genres: set[str] = set()
    from recommender import _idx_to_card
    for card in _idx_to_card.values():
        all_genres.update(card.genres)
    return {"genres": sorted(all_genres)}


@app.get("/search")
async def search(q: str, top_k: int = 10):
    """
    Semantic search over the catalogue.
    Returns catalogue movies most similar to the query by meaning.
    Example: /search?q=dark+psychological+thriller
    """
    if not q or len(q.strip()) < 2:
        return {"results": [], "query": q}
    
    results = semantic_search(q.strip(), top_k=min(top_k, 20))
    
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

