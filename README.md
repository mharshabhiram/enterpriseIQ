# EnterpriseIQ

AI-powered enterprise knowledge management system using Retrieval-Augmented
Generation (RAG) to answer questions from an organization's own documents,
with role-based access control enforced end-to-end.

> **Status:** Phase 3 (authentication & RBAC) complete. This README will be
> expanded into full documentation (architecture diagrams, API reference,
> troubleshooting, etc.) in Phase 10.

## Tech Stack

- **Frontend:** React, Vite, TypeScript, TailwindCSS, React Router, Axios, TanStack Query
- **Backend:** Python 3.12, FastAPI, SQLAlchemy 2.x (async), Alembic, Pydantic v2
- **Database:** PostgreSQL + pgvector
- **AI:** Provider-agnostic LLM/embedding layer (OpenAI-compatible by default)
- **Infra:** Docker Compose

## Quick Start (Phase 1 scaffold)

```bash
# 1. Configure environment
cp backend/.env.example backend/.env
cp frontend/.env.example frontend/.env
# Edit backend/.env and set a real JWT_SECRET_KEY and LLM/embedding API keys
# once those phases are implemented.

# 2. Start everything
docker compose up --build
```

- Backend health check: http://localhost:8000/health
- Backend interactive API docs: http://localhost:8000/docs
- Frontend: http://localhost:5173

At this stage the frontend shows a placeholder screen and the backend
exposes empty routers (`/api/auth`, `/api/users`, `/api/documents`,
`/api/search`, `/api/chat`, `/api/admin`) with no implemented endpoints yet.
Database models and Alembic migrations are added in Phase 2.

## Running the backend without Docker

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # then point DATABASE_URL at a local Postgres
uvicorn app.main:app --reload
```

## Running the frontend without Docker

```bash
cd frontend
npm install
cp .env.example .env
npm run dev
```

## Database Schema & Migrations

Eight tables, matching the ER design: `users`, `documents`, `document_chunks`
(with a pgvector `vector(1536)` column and an HNSW cosine-similarity index),
`document_permissions`, `conversations`, `messages`, `message_sources`,
`audit_logs`. All primary keys are UUIDs; foreign keys use `CASCADE` where a
child row has no meaning without its parent (e.g. chunks without their
document) and `SET NULL` where the record should outlive its owner (e.g. a
document should survive the uploader's account being deleted; an audit log
should survive the actor's account being deleted).

Run migrations after the `postgres` container is up:

```bash
docker compose up -d postgres
cd backend
alembic upgrade head          # apply migrations
alembic downgrade base        # or roll everything back
```

Or, once the whole stack is running via `docker compose up --build`, run it
inside the backend container:

```bash
docker compose exec backend alembic upgrade head
```

To add new models later: add the SQLAlchemy model, import it in
`app/models/__init__.py`, then run:

```bash
alembic revision --autogenerate -m "describe the change"
```

**Note:** `alembic revision --autogenerate` cannot generate the pgvector
`hnsw` index or the `CREATE EXTENSION vector` statement (they use raw SQL
inside the migration, since pgvector's index types aren't representable as
plain SQLAlchemy `Index` objects) - as a result, `alembic check` will always
report that index as spurious "drift." That's expected; don't let
autogenerate remove it.

## Authentication & RBAC

**Login flow:** `POST /api/auth/register` (public, always creates an
`EMPLOYEE`) or an admin creates an account via `POST /api/users` with any
role. `POST /api/auth/login` exchanges email+password for a JWT access
token. Every protected endpoint expects `Authorization: Bearer <token>`.

**Key design decision - tokens carry no role claim.** The JWT payload is
just `{"sub": "<user id>", "iat": ..., "exp": ...}`. `get_current_user`
re-loads the user (and their current role and `is_active` flag) from the
database on *every* request rather than trusting a claim baked into the
token at login time. This costs one extra query per request but means a
role change or account deactivation takes effect immediately, on the very
next request - not just after the old token happens to expire. This is
covered by `test_deactivated_user_token_rejected_on_next_request`.

**RBAC:** `require_role(*roles)` is a dependency factory built on top of
`get_current_user`; every `/api/users` route uses
`require_role(UserRole.ADMIN)`. There's no separate "is this allowed"
logic anywhere else - routes, and only routes, declare which roles they
need, and the check always happens server-side regardless of what the
frontend shows or hides.

**Admin safety guardrails** (enforced in `user_service`, not just routes):
an admin can never delete their own account, and the last remaining active
ADMIN can never be demoted, deactivated, or deleted by anyone (including
themselves) - otherwise the system would have no admin left to fix things.

**Consistent errors:** every error response - ours or FastAPI's own - has
the shape `{"error": {"code": "...", "message": "..."}}` (see
`app/utils/errors.py` and the exception handlers in `app/main.py`).

**Password hashing:** uses the `bcrypt` library directly rather than
`passlib` - `passlib` 1.7.4 (its latest release) is incompatible with
`bcrypt>=4.1` (confirmed while building this project: it crashes reading
`bcrypt.__about__`, which was removed upstream, and mishandles bcrypt's
72-byte input limit).

### Seed data

```bash
docker compose exec backend python -m app.db.seed
# or locally: cd backend && python -m app.db.seed
```

Creates these accounts if they don't already exist (idempotent - safe to
re-run):

| Role | Email | Password |
|---|---|---|
| ADMIN | `admin@enterpriseiq.local` | `Admin123!` |
| MANAGER | `manager@enterpriseiq.local` | `Manager123!` |
| EMPLOYEE | `employee@enterpriseiq.local` | `Employee123!` |

**These are local-development defaults only and must never be used as-is
anywhere shared or production.**

## Running tests

```bash
cd backend
pip install -r requirements.txt
docker compose up -d postgres   # tests run against a real Postgres+pgvector DB
alembic upgrade head
pytest -v
```

## Project Structure

```text
enterpriseiq/
├── backend/
│   ├── app/
│   │   ├── main.py            # FastAPI app, routers, CORS, /health
│   │   ├── config.py          # Settings loaded from environment variables
│   │   ├── db/                # Async engine, session factory, declarative Base
│   │   ├── api/
│   │   │   ├── dependencies.py     # get_db, get_current_user, require_role
│   │   │   └── routes/             # auth, users, documents, search, chat, summaries, admin
│   │   ├── models/            # SQLAlchemy ORM models (User, Document, DocumentChunk, ...)
│   │   ├── schemas/            # Pydantic request/response schemas
│   │   ├── services/           # Business logic (auth_service, user_service, ...)
│   │   ├── repositories/       # DB query layer (user_repository, audit_log_repository, ...)
│   │   ├── ai/                 # LLMProvider / EmbeddingProvider abstractions (Phase 5-6)
│   │   ├── ingestion/          # PDF/DOCX/TXT/MD extraction + chunking (Phase 4)
│   │   ├── security/            # password.py (bcrypt), jwt.py (access tokens)
│   │   └── utils/               # errors.py, audit_actions.py
│   ├── tests/
│   ├── alembic/
│   ├── requirements.txt
│   ├── Dockerfile
│   └── .env.example
│
├── frontend/
│   ├── src/
│   │   ├── pages/              # Route-level components
│   │   ├── components/         # Reusable UI components
│   │   ├── layouts/, hooks/, services/, api/, types/, context/, utils/
│   ├── package.json
│   ├── vite.config.ts
│   ├── tailwind.config.js
│   └── Dockerfile
│
├── sample_documents/
├── docker-compose.yml
├── .gitignore
└── README.md
```

## Roadmap

1. ✅ Project scaffolding
2. ✅ Database models & Alembic migrations
3. ✅ Authentication & RBAC
4. Document upload & processing pipeline
5. Embedding generation & pgvector search
6. RAG question answering & citations
7. Chat & conversation history
8. Summarization & document comparison
9. Dashboard & admin panel
10. Testing, security hardening, Docker polish, full documentation

## Future Improvements

- Refresh tokens + server-side revocation (token blacklist)
- Celery/RQ-based task queue for document processing at scale
- Multi-tenant support
