# Architecture

## Components

| Component | Code | Role |
|---|---|---|
| Frontend | `frontend/` (React 19, Vite) | UI; holds the access token; calls the API and the TMDB proxy |
| API | `backend/main.py` (FastAPI) | Recommendations, feedback, search, health |
| Accounts | `backend/auth.py`, `backend/security.py` | Registration, login, JWTs, profiles and per-profile lists |
| Watch Together | `backend/watch_party.py` | Invites, room membership, chat WebSocket |
| Recommender | `backend/recommender.py` | Title mapping, model routing, ONNX inference, cold start |
| Search | `backend/semantic_search.py` | MiniLM embeddings of title + year + genres, cosine ranking |
| TMDB proxy | `backend/tmdb.py` | Allowlisted pass-through holding the TMDB token |
| Persistence | `backend/database.py`, `backend/migrations/` | SQLAlchemy models, Alembic migrations |
| Configuration | `backend/config.py` | Environment settings, validated at import |

## Request flows

### Recommendation (`POST /recommend`)

1. Authenticate the bearer token; check the profile belongs to the caller.
2. Return the cached response if Redis has one for this profile, ordered
   history and `top_k`.
3. Choose a model: stable MD5 split on the profile id, or Thompson sampling
   once ten or more feedback events exist. SASRec falls back to BERT4Rec if its
   model file is absent.
4. Map history titles to catalogue items by exact (case-insensitive) title.
   Unmatched titles are counted and ignored.
5. Fewer than `MIN_SEQUENCE_LENGTH` matches → most popular items, excluding
   watched and disliked ones; `model_variant = "popularity"`.
6. Otherwise left-pad the token sequence to 50, run the ONNX model, mask PAD,
   MASK (BERT4Rec), watched and disliked items, and take the top-k.
7. Record which model served each item (`served:{profile}`), cache the response.

### Feedback (`POST /feedback`)

1. Authenticate; check profile ownership.
2. Look up the model that served the item; increment its `wins` or `losses`
   once, then forget the item so repeated clicks do not count.
3. Thumbs down: add the item to `never:{profile}` and refresh its expiry.
4. Invalidate the profile's cached recommendations.
5. Log the event and publish it to Kafka topic `user_feedback` if enabled.

### Watch Together

1. `POST /invite` creates a room (128-bit random id). An invite row is created
   only if the recipient exists; the response is identical either way.
2. The recipient lists `GET /invite/pending` and answers once with
   `accepted` or `declined`.
3. Participants (creator + accepted invitees) connect to `/ws/room/{id}` and
   send `{"type": "auth", "token": ...}` first. Invalid tokens close with 4401,
   non-participants with 4403.
4. Chat messages are validated and rebuilt server-side (`type`, `text`,
   `sender`, `timestamp`); join/leave notices carry the participant count.

## Data model

```
users (email PK)
 ├── profiles (id PK, user_email FK) ── max 6 per user
 │     ├── watch_history     (profile_id FK, unique)  JSON list
 │     ├── continue_watching (profile_id FK, unique)  JSON list
 │     └── watch_again       (profile_id FK, unique)  JSON list
 ├── watch_rooms (room_id PK, created_by FK)
 └── watch_invites (from_email FK, to_email FK, room_id FK, status)
```

All foreign keys cascade on delete. Migrations run at startup
(`database.init_db`); a database created by the pre-migration schema is
stamped at the baseline only if its tables and columns match exactly.

## Redis keys

| Key | Type | Lifetime | Purpose |
|---|---|---|---|
| `rec:{profile}:{digest}` | string | `RECOMMENDATION_CACHE_TTL_SEC` | Cached `/recommend` response |
| `served:{profile}` | hash item → model | 24 h | Attributes feedback to a model |
| `never:{profile}` | set | `DISLIKE_SUPPRESSION_DAYS` since last dislike | Suppressed items |
| `bandit:{model}:wins` / `:losses` | counter | permanent | Thompson-sampling statistics |

Without Redis the API still works, but nothing is cached, dislikes are not
remembered and routing stays on the hash split.

## Configuration

See `backend/.env.example` (local) and `.env.example` (Docker Compose).
Required: `JWT_SECRET` (32+ characters). Validated at startup: CORS origins
(no wildcard) and all numeric settings.

## Deployment shape

`docker-compose.yml` runs `frontend` (nginx, port 80), `backend` (uvicorn,
port 8000) and `redis` (internal only), plus `zookeeper` and `kafka` under the
`kafka` profile. Model artifacts are mounted read-only from `./data`; the
database is on the `streamora-db` volume; the MiniLM model is baked into the
backend image.
