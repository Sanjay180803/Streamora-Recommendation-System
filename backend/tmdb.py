"""
tmdb.py
Server-side proxy for the TMDB API.

The TMDB read token lives only in the backend environment (TMDB_TOKEN), so it is
never bundled into the browser JavaScript. Only the endpoints and query
parameters the frontend actually uses are forwarded; everything else is rejected
so the proxy cannot be used as a general-purpose TMDB client.
"""

import os
import re
import time

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request

from security import get_current_user

router = APIRouter(
    prefix="/tmdb",
    tags=["tmdb"],
    dependencies=[Depends(get_current_user)],
)

TMDB_BASE_URL = "https://api.themoviedb.org/3"
CACHE_TTL_SEC = 600
CACHE_MAX_ENTRIES = 1000

ALLOWED_PATHS = [
    re.compile(p)
    for p in (
        r"search/(movie|tv)",
        r"movie/(popular|now_playing|top_rated)",
        r"tv/(popular|on_the_air|top_rated)",
        r"trending/all/week",
        r"(movie|tv)/\d{1,10}/videos",
    )
]
ALLOWED_PARAMS = {"query", "year", "language", "page"}

_cache: dict[tuple, tuple[float, dict]] = {}


def _is_allowed(path: str) -> bool:
    return any(pattern.fullmatch(path) for pattern in ALLOWED_PATHS)


async def _fetch(path: str, params: dict) -> dict:
    token = os.getenv("TMDB_TOKEN")
    if not token:
        raise HTTPException(status_code=503, detail="TMDB integration is not configured")

    async with httpx.AsyncClient(base_url=TMDB_BASE_URL, timeout=10) as client:
        response = await client.get(
            f"/{path}",
            params=params,
            headers={"Authorization": f"Bearer {token}"},
        )
    if response.status_code != 200:
        raise HTTPException(status_code=502, detail="TMDB request failed")
    return response.json()


@router.get("/{path:path}")
async def proxy(path: str, request: Request):
    if not _is_allowed(path):
        raise HTTPException(status_code=404, detail="Unsupported TMDB endpoint")

    params = {k: v for k, v in request.query_params.items() if k in ALLOWED_PARAMS}
    key = (path, tuple(sorted(params.items())))

    cached = _cache.get(key)
    if cached and cached[0] > time.monotonic():
        return cached[1]

    data = await _fetch(path, params)
    if len(_cache) >= CACHE_MAX_ENTRIES:
        _cache.clear()
    _cache[key] = (time.monotonic() + CACHE_TTL_SEC, data)
    return data
