from pydantic import BaseModel, Field
from typing import Optional

# ─────────────────────────────────────────────────────────────────────────────
# REQUEST MODELS  (what the frontend sends to FastAPI)
# ─────────────────────────────────────────────────────────────────────────────

class WatchItem(BaseModel):
    """One item in the user's watch history."""
    title: str
    genres: list[str] = Field(default_factory=list)   # e.g. ["Action", "Drama"]
    release_year: Optional[int] = None


class RecommendRequest(BaseModel):
    """
    Sent by the React frontend when a user wants recommendations.
    watch_history: list of WatchItem — each has title + genres so unknown titles
                   can be matched by genre similarity against the catalogue.
    profile_id:    profile the recommendations are for — must belong to the caller;
                   used for A/B routing and caching
    top_k:         how many recommendations to return (default 10)
    """
    watch_history: list[WatchItem] = Field(..., min_length=1, max_length=100)
    profile_id: str
    top_k: int = Field(default=10, ge=1, le=50)


class FeedbackRequest(BaseModel):
    """
    Sent when the user clicks thumbs up (signal=1) or thumbs down (signal=-1).
    profile_id:    profile giving the feedback — must belong to the caller
    movie_id:      the item_id string of the movie being rated (e.g. 'e847f14da5')
    signal:        1 = thumbs up, -1 = thumbs down
    model_variant: which model served this recommendation ('bert4rec' or 'sasrec')
    """
    profile_id: str
    movie_id: str
    signal: int = Field(..., ge=-1, le=1)
    model_variant: str


# ─────────────────────────────────────────────────────────────────────────────
# RESPONSE MODELS  (what FastAPI sends back to the frontend)
# ─────────────────────────────────────────────────────────────────────────────

class MovieCard(BaseModel):
    """
    One recommended movie — everything the frontend needs to render a card.
    """
    item_id: str
    item_idx: int
    title: str
    release_year: Optional[int]
    genres: list[str]            # e.g. ["Action", "Drama"]
    log_popularity: float        # used by frontend to show a popularity indicator if needed


class RecommendResponse(BaseModel):
    """
    Returned by POST /recommend.
    recommendations: ordered list of MovieCard (highest-ranked first)
    model_variant:   which model was used — frontend logs this for A/B tracking
    cache_hit:       True if result came from Redis (for debugging / latency display)
    cold_start:      True if user had too few interactions and got popularity fallback
    """
    recommendations: list[MovieCard]
    model_variant: str
    cache_hit: bool
    cold_start: bool


class FeedbackResponse(BaseModel):
    """
    Returned by POST /feedback.  Simple acknowledgement.
    """
    status: str = "ok"


class HealthResponse(BaseModel):
    """
    Returned by GET /health.  Used by Docker healthcheck and monitoring.
    """
    status: str
    model_loaded: bool
    redis_connected: bool
    items_loaded: int
