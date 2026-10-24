# Streamora

[![CI](https://github.com/Sanjay180803/Streamora-Recommendation-System/actions/workflows/ci.yml/badge.svg?branch=version2)](https://github.com/Sanjay180803/Streamora-Recommendation-System/actions/workflows/ci.yml)

A full-stack streaming catalogue with sequential recommendations (BERT4Rec and
SASRec served through ONNX Runtime), multi-profile accounts, semantic search
and Watch Together chat rooms.

> **This is a maintained fork** of the team project
> [RP-1106/Streamora-Recommendation-System](https://github.com/RP-1106/Streamora-Recommendation-System).
> See [Contributions](#contributions) for what the original team built and what
> changed in this fork.

**Demo video:** [youtu.be/6JtSAc9Zq68](https://youtu.be/6JtSAc9Zq68) (recorded on the original project)

## Features

- **Sequential recommendations.** A profile's watch history is mapped to
  catalogue items and scored by BERT4Rec or SASRec (ONNX Runtime, CPU).
  Only titles that exactly match the catalogue are used; the API reports how
  many history titles matched.
- **Cold start.** With fewer than `MIN_SEQUENCE_LENGTH` matched titles (default
  5), the API returns the most popular unwatched catalogue titles and labels the
  response `popularity`.
- **Model routing.** Requests are split between the two models by a stable hash
  of the profile id. Once at least ten feedback events exist, Thompson sampling
  over each model's thumbs-up/thumbs-down record chooses the model.
- **Feedback.** 👍 / 👎 are credited to the model that served the item (once per
  item). 👎 also suppresses the title for that profile for 30 days
  (`DISLIKE_SUPPRESSION_DAYS`). Feedback memory requires Redis.
- **Semantic search** with `all-MiniLM-L6-v2` sentence embeddings over each
  title's name, year and genres (no plot text, so matches are driven by genre
  and title words).
- **Profiles.** Up to six per account, each with its own history, Continue
  Watching and Watch Again lists.
- **Watch Together.** Invite another account to a room with a shared live chat
  over WebSockets. Each participant plays the trailer independently; playback
  is **not** synchronised.
- **TMDB integration** for posters, trailers and browse rows, through a backend
  proxy so the API token never reaches the browser.

## Architecture

```
React (Vite) ──HTTPS/JSON + JWT──▶ FastAPI ──▶ ONNX Runtime (BERT4Rec, SASRec)
     │                               ├──▶ sentence-transformers (MiniLM)
     └──────── WebSocket ───────────▶├──▶ SQLite / SQLAlchemy + Alembic
                                     ├──▶ Redis (cache, feedback, bandit) — optional
                                     ├──▶ Kafka (feedback events) — optional
                                     └──▶ TMDB API (server-side proxy)
```

Details: [docs/architecture.md](docs/architecture.md).

## Tech stack

**Frontend:** React 19, Vite, React Router, Axios ·
**Backend:** Python 3.11, FastAPI, SQLAlchemy, Alembic, PyJWT, argon2 ·
**ML/search:** ONNX Runtime, sentence-transformers (PyTorch CPU) ·
**Infrastructure:** Redis, Kafka (optional), Docker Compose, nginx ·
**Quality:** pytest, ruff, ESLint, GitHub Actions, gitleaks ·
**External API:** TMDB

## Model evaluation

The original team reported these results for models trained on Netflix UK
interaction data (9,387 items, 110,065 users).

> **Not reproducible from this repository.** The training and evaluation code,
> the dataset split and the trained artifacts are not in git. The numbers below
> are as reported by the original authors. What is and is not verified, and what
> is needed to reproduce them, is in
> [docs/model-verification.md](docs/model-verification.md).

| Metric | BERT4Rec (val) | BERT4Rec (test) | SASRec (val) | SASRec (test) |
|---|---|---|---|---|
| HR@5 | 0.1409 | 0.1074 | 0.1951 | 0.1637 |
| HR@10 | 0.1937 | 0.1549 | 0.2565 | 0.2206 |
| HR@20 | 0.2555 | 0.2153 | 0.3285 | 0.2868 |
| NDCG@5 | 0.0996 | 0.0734 | 0.1424 | 0.1181 |
| NDCG@10 | 0.1166 | 0.0888 | 0.1622 | 0.1365 |
| NDCG@20 | 0.1322 | 0.1040 | 0.1803 | 0.1531 |
| MRR | 0.1025 | 0.0782 | 0.1432 | 0.1201 |

## Running it

### Model and data artifacts (required)

The trained models and feature tables are **not stored in git**. Obtain them
from the original team and place them in `data/`; the list and a checker are in
[docs/artifacts.md](docs/artifacts.md):

```bash
python scripts/check_artifacts.py
```

Without them the backend exits at startup with a list of the missing files. The
test suite does not need them.

### Local development

Prerequisites: Python 3.11, Node.js 22 (or 20.19+).

```bash
git clone https://github.com/Sanjay180803/Streamora-Recommendation-System
cd Streamora-Recommendation-System

# Backend
cd backend
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install torch==2.5.1 --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt
cp .env.example .env                 # set JWT_SECRET (32+ chars) and TMDB_TOKEN
uvicorn main:app --reload --port 8000   # runs database migrations on startup

# Frontend (new terminal)
cd frontend
npm ci
npm run dev                          # http://localhost:5173
```

Redis is optional locally (`REDIS_URL=` disables caching and feedback memory).

### Docker Compose

```bash
cp .env.example .env                 # set JWT_SECRET and TMDB_TOKEN
docker compose up --build            # frontend: http://localhost, API: http://localhost:8000
```

`./data` is mounted read-only into the backend; the SQLite database lives in
the `streamora-db` volume. Redis is internal to the Compose network. Kafka is
optional: `docker compose --profile kafka up --build` with
`KAFKA_BOOTSTRAP=kafka:9092` in `.env`.

### Deploying to a single server (e.g. AWS EC2)

1. Ubuntu 24.04, t3.medium or larger, 30 GB disk. Allow inbound 22 (your IP
   only), 80 and 8000.
2. Install Docker: `curl -fsSL https://get.docker.com | sh`, then
   `sudo usermod -aG docker ubuntu && newgrp docker`.
3. Clone the repository and copy the artifacts into `data/`.
4. Create `.env` with `JWT_SECRET`, `TMDB_TOKEN`,
   `CORS_ORIGINS=http://<public-ip>` and
   `VITE_API_BASE_URL=http://<public-ip>:8000`.
   The API URL is compiled into the frontend, so set it before building.
5. `docker compose up -d --build`

Serve over HTTPS (for example with a reverse proxy) before handling real
accounts: access tokens are sent with every request.

## Testing

```bash
cd backend
pip install -r requirements.txt -r requirements-dev.txt
pytest --cov=. --cov-report=term-missing   # 208 tests, 95% line coverage
ruff check . && ruff format --check .

cd ../frontend
npm run lint && npm run build
```

The backend tests need no models, Redis or network: they use a small generated
catalogue, a fake ONNX session, fakeredis and a fake sentence encoder. They
cover authentication and token validation, cross-account isolation, Watch
Together authorization and the WebSocket protocol, cold start and inference
inputs, feedback suppression and bandit attribution, semantic search, the TMDB
proxy, migrations (including upgrading a pre-migration database) and startup
configuration. CI also builds both Docker images and scans the files for
secrets.

## Security notes

- Passwords are hashed with argon2; access tokens are HS256 JWTs that expire
  after `JWT_EXPIRE_MINUTES` (default 60). The frontend keeps the token in
  `localStorage`.
- Every account, profile, history and room route derives the user from the
  token and returns 404 for another account's resources.
- CORS is limited to `CORS_ORIGINS`; the app refuses to start without a
  `JWT_SECRET` of at least 32 characters.
- A TMDB read token was committed in this project's history before this fork's
  hardening. It is no longer used by the code and must be revoked by its owner.

## Known limitations

- Training, evaluation and ONNX export code are not included; metrics are not
  reproducible here.
- BERT4Rec inference reads logits at the last history position without
  appending a mask token. This may not match how the model was trained; it is
  documented in [docs/model-verification.md](docs/model-verification.md) and
  deliberately left unchanged until verified.
- Inference uses a zero (population-mean) user-feature vector; per-user
  features are loaded but not used.
- Watch Together shares chat only, not playback.
- Kafka feedback events have no consumer in this repository.
- SQLite suits a single server; use `DATABASE_URL` for another database.

## Contributions

**Original project** ([upstream](https://github.com/RP-1106/Streamora-Recommendation-System), team project).
Commits by RP-1106, Rhea Pandita, Themozhi and Sanjay Balasubramaniam built the
FastAPI service with BERT4Rec/SASRec ONNX inference, the React frontend,
profiles, semantic search, the feedback loop, Watch Party and per-profile
history. Sanjay's upstream commit added Watch Party, per-profile history,
navigation pages, semantic search and the feedback loop.

**This fork** (Sanjay Balasubramaniam), on branch `sanjay/repository-hardening`:

- Moved the TMDB credential out of the browser bundle behind an allowlisted
  backend proxy
- Added JWT authentication with server-side ownership checks (previously any
  caller could read or change any account's data by supplying its email)
- Secured Watch Together invites, rooms and the WebSocket
- Made the feedback loop real (dislike suppression and bandit counters were
  read but never written) and stopped feeding guessed items into the models
- Fixed SASRec requests using BERT4Rec token offsets when the SASRec model
  was missing
- Added Alembic migrations with foreign keys and cleanup of orphaned data
- Made Docker builds reproducible without bundling artifacts; pinned
  dependencies; added health checks; stopped publishing Redis and Kafka
- Added 208 backend tests, frontend linting and a CI pipeline
- Rewrote this README to match the code

The full list is in the commit history of this branch.
