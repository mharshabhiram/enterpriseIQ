# EnterpriseIQ

**AI-powered enterprise knowledge management using Retrieval-Augmented Generation (RAG) — running entirely on local models.**

Upload policies, manuals and reports. EnterpriseIQ extracts, chunks and embeds them into PostgreSQL + pgvector. Employees then search by meaning, ask questions in plain language and get answers **with citations** — and only ever from documents they are allowed to read.

All AI runs locally through **Ollama** with **Mistral** (answers, summaries, comparisons) and **nomic-embed-text** (embeddings). There are no AI API keys and no document text leaves your machine.

---

## Contents
1. [Features](#features) · 2. [Architecture](#architecture) · 3. [Tech stack](#tech-stack) · 4. [Quick start (Docker)](#quick-start-docker) · 5. [Ollama & models](#ollama--models) · 6. [Running without Docker](#running-without-docker) · 7. [Environment variables](#environment-variables) · 8. [Database & migrations](#database--migrations) · 9. [Seed data & demo accounts](#seed-data--demo-accounts) · 10. [API](#api) · 11. [Security model](#security-model) · 12. [Tests](#tests) · 13. [Troubleshooting](#troubleshooting) · 14. [Design decisions](#design-decisions) · 15. [Future improvements](#future-improvements)

---

## Features

| Area | What you get |
|---|---|
| **Auth** | Registration, login, logout (server-side token revocation), JWT access tokens, Argon2id password hashing, rate-limited auth endpoints |
| **RBAC** | `ADMIN`, `MANAGER`, `EMPLOYEE` roles stored in a separate `roles` table; per-document visibility (`PUBLIC` / `RESTRICTED`) with grants to roles **or** individual users |
| **Ingestion** | PDF (PyMuPDF), DOCX (python-docx, headings + tables), TXT, Markdown; magic-byte validation, 20 MB limit, sanitised storage paths; background processing with live status (`UPLOADED → PROCESSING → COMPLETED / FAILED`) and retry |
| **Chunking** | Structure-aware: paragraphs packed to `CHUNK_SIZE`, sentence-level splitting for long paragraphs, `CHUNK_OVERLAP` carry-over, page numbers and nearest heading kept as citation metadata |
| **Semantic search** | pgvector HNSW cosine search with **permission filtering inside the SQL query**; filters for file type, department, tags, uploader, date; highlighted excerpts and similarity scores |
| **RAG chat** | Multi-turn conversations, numbered sources `[S1]`, clickable citations, "not found" answers that never cite unrelated text, regenerate, history, delete |
| **Summaries** | Short / detailed / executive; long documents use hierarchical **map-reduce** so nothing is truncated |
| **Comparison** | Structured JSON diff between two documents (added / removed / changed), optional focus topic uses targeted retrieval |
| **Dashboards** | Role-aware stats, recent uploads and conversations, top searches, 14-day activity |
| **Admin** | User management (create, role change, disable, delete), audit log viewer with filters, re-embed documents after a model change |
| **Ops** | Structured JSON logs with secret redaction, audit log table, health endpoints for DB and Ollama, startup model check with exact `ollama pull` commands |

---

## Architecture

```mermaid
flowchart TB
    U[Browser] -->|HTTPS| FE[React + Vite SPA<br/>served by nginx]
    FE -->|REST /api, JWT| BE[FastAPI backend]
    BE -->|SQLAlchemy| PG[(PostgreSQL 16<br/>+ pgvector)]
    BE -->|HTTP :11434| OL[Ollama]
    OL --- M1[mistral<br/>LLM]
    OL --- M2[nomic-embed-text<br/>embeddings]
    BE -->|files| FS[(Upload volume)]
    INIT[ollama-init<br/>one-shot] -->|ollama pull| OL
```

Backend layers (`backend/app/`):

```text
api/routes      HTTP only: validation, dependencies, status codes
services        business logic (auth, documents, ingestion, retrieval, RAG, summaries, comparison, audit)
repositories    all SQL, incl. the permission-filtered vector search
security        JWT, Argon2, RBAC rules (single SQL source of truth), rate limits
ingestion       extractors, cleaning, chunking
ai              provider interfaces + Ollama implementation + prompts + health checks
models/schemas  SQLAlchemy ORM / Pydantic API contracts
```

### RAG pipeline

```mermaid
flowchart LR
    subgraph Ingestion [Ingestion — background task]
      A[Upload] --> B[Validate type, size, magic bytes]
      B --> C[Extract text per page]
      C --> D[Clean & normalise]
      D --> E[Structure-aware chunking<br/>page + section metadata]
      E --> F[Embed with nomic-embed-text<br/>search_document: prefix]
      F --> G[(document_chunks<br/>vector 768 + HNSW)]
    end
    subgraph Query [Question answering]
      Q[Question] --> QE[Embed query<br/>search_query: prefix]
      QE --> R[pgvector cosine search<br/>WHERE user may read document<br/>AND same embedding model]
      G --> R
      R --> S[Threshold + context budget]
      S --> P[Prompt with numbered sources S1..Sn]
      P --> L[Mistral via Ollama]
      L --> V[Keep only sources actually cited]
      V --> ANS[Answer + citations]
    end
```

### Database schema

```mermaid
erDiagram
    roles ||--o{ users : has
    users ||--o{ documents : uploads
    documents ||--o{ document_chunks : "split into"
    documents ||--o{ document_permissions : "restricted to"
    roles ||--o{ document_permissions : "granted"
    users ||--o{ document_permissions : "granted"
    users ||--o{ conversations : owns
    conversations ||--o{ messages : contains
    messages ||--o{ message_sources : cites
    users ||--o{ audit_logs : performs

    roles { int id PK  string name UK  string description }
    users { uuid id PK  string name  string email UK  string password_hash  int role_id FK  string department  bool is_active  int token_version  timestamptz created_at  timestamptz updated_at }
    documents { uuid id PK  string title  string filename  string original_filename  string file_type  bigint file_size  string storage_path  uuid uploaded_by FK  string department  string[] tags  enum processing_status  string processing_error  enum visibility  string embedding_model  int chunk_count  int page_count  timestamptz created_at }
    document_chunks { uuid id PK  uuid document_id FK  int chunk_index  text chunk_text  int page_number  string section  vector embedding }
    document_permissions { uuid id PK  uuid document_id FK  int role_id FK  uuid user_id FK }
    conversations { uuid id PK  uuid user_id FK  string title  timestamptz updated_at }
    messages { uuid id PK  uuid conversation_id FK  enum role  text content  timestamptz created_at }
    message_sources { uuid id PK  uuid message_id FK  int source_number  uuid document_id FK  uuid chunk_id FK  string document_name  int page  string section  text excerpt  float relevance_score }
    audit_logs { uuid id PK  uuid user_id FK  string action  string resource_type  string resource_id  jsonb metadata  timestamptz created_at }
```

---

## Tech stack

| Layer | Choice |
|---|---|
| Frontend | React 18, TypeScript, Vite 5, React Router 6, react-markdown, plain CSS design tokens (`src/styles.css`), Vitest + Testing Library |
| Backend | Python 3.12, FastAPI, SQLAlchemy 2, Alembic, Pydantic v2, PyJWT, argon2-cffi, SlowAPI, structlog |
| Database | PostgreSQL 16 + pgvector (HNSW, cosine) |
| AI | Ollama · `mistral` (LLM) · `nomic-embed-text` (768-dim embeddings) |
| Parsing | PyMuPDF (PDF), python-docx (DOCX) |
| Infra | Docker Compose: `frontend`, `backend`, `postgres`, `ollama`, `ollama-init` |

---

## Quick start (Docker)

Requirements: Docker Desktop / Docker Engine with Compose **v2.24+**, ~10 GB free disk (Mistral ≈ 4.1 GB, nomic-embed-text ≈ 270 MB), 8 GB+ RAM recommended.

```bash
cp .env.example .env            # optional: set JWT_SECRET_KEY, model names
docker compose up --build
```

On first start `ollama-init` downloads both models (**requires internet once**; after that everything runs offline). The backend waits for Postgres, Ollama and the model download, runs migrations automatically, then starts.

Create the demo users and load the sample documents:

```bash
docker compose exec backend python -m app.seed --samples
```

| Service | URL |
|---|---|
| Web app | http://localhost:3000 |
| API + Swagger docs | http://localhost:8000/docs |
| Ollama (debug) | http://localhost:11434 |

> **GPU:** uncomment the `deploy` block under `ollama` in `docker-compose.yml` (NVIDIA Container Toolkit required). On CPU, answers take roughly 10–60 s depending on hardware.

---

## Ollama & models

**Install Ollama (when running without Docker):** download from <https://ollama.com/download> (macOS, Windows, Linux) or `curl -fsSL https://ollama.com/install.sh | sh` on Linux.

```bash
ollama serve                    # if it isn't already running as a service
ollama pull mistral
ollama pull nomic-embed-text
ollama list                     # both should appear
```

Inside Docker the backend talks to `http://ollama:11434` (the Compose service name). Running the backend directly on your machine, use `OLLAMA_BASE_URL=http://localhost:11434`.

At startup the API checks Ollama and logs the exact `ollama pull …` command for any missing model. `GET /api/health/ai` reports the same, and the web app shows a banner while the local AI is not ready.

**Changing models:** set `OLLAMA_LLM_MODEL` / `OLLAMA_EMBEDDING_MODEL`. If the *embedding* model changes, vectors from the old model live in a different space: those documents are automatically excluded from search (each document stores `embedding_model`) and the dashboard flags them. Re-embed with `POST /api/admin/reembed` (admin). If the new model has a different dimension, also change `EMBEDDING_DIMENSIONS` and recreate the database (the vector column is fixed-size).

---

## Running without Docker

```bash
# 1. Database (any PostgreSQL 15+ with pgvector) — or just: docker compose up postgres ollama ollama-init
createdb enterpriseiq && psql enterpriseiq -c "CREATE EXTENSION vector;"

# 2. Backend
cd backend
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env    # then set DATABASE_URL=...@localhost..., OLLAMA_BASE_URL=http://localhost:11434, UPLOAD_DIR=./uploads
alembic upgrade head
python -m app.seed --samples
uvicorn app.main:app --reload --port 8000

# 3. Frontend (new terminal)
cd frontend
npm install
npm run dev             # http://localhost:5173 — /api is proxied to :8000
```

---

## Environment variables

Backend (`backend/.env`, see `backend/.env.example`):

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | `postgresql+psycopg://enterpriseiq:enterpriseiq@postgres:5432/enterpriseiq` | SQLAlchemy URL |
| `JWT_SECRET_KEY` | — (**required**, ≥16 chars) | Token signing key — use a long random value |
| `JWT_ALGORITHM` | `HS256` | |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `60` | |
| `OLLAMA_BASE_URL` | `http://ollama:11434` (Compose) | Local Ollama HTTP API |
| `OLLAMA_LLM_MODEL` | `mistral` | Generation model |
| `OLLAMA_EMBEDDING_MODEL` | `nomic-embed-text` | Embedding model |
| `EMBEDDING_DIMENSIONS` | `768` | Must match the embedding model |
| `OLLAMA_TIMEOUT_SECONDS` | `120` | Per-request timeout |
| `OLLAMA_NUM_CTX` | `8192` | Context window passed to Ollama |
| `OLLAMA_TEMPERATURE` | `0.2` | Low = more factual |
| `OLLAMA_STARTUP_WAIT_SECONDS` | `30` | How long startup waits for Ollama |
| `CHUNK_SIZE` / `CHUNK_OVERLAP` | `1200` / `200` | Characters; overlap must be < half of size |
| `TOP_K` | `6` | Chunks retrieved per question |
| `SIMILARITY_THRESHOLD` | `0.45` | Minimum cosine similarity |
| `MAX_CONTEXT_CHARS` | `12000` | Context budget for the prompt |
| `SUMMARY_SECTION_CHARS` | `8000` | Section size for map-reduce summaries |
| `MAX_FILE_SIZE` | `20971520` | 20 MB |
| `UPLOAD_DIR` | `/data/uploads` | File storage |
| `CORS_ORIGINS` | `http://localhost:5173,http://localhost:3000` | Comma-separated |
| `LOG_LEVEL` | `INFO` | |

There is deliberately **no** `LLM_API_KEY` / `EMBEDDING_API_KEY`: all AI is local.

---

## Database & migrations

Migrations live in `backend/alembic/versions/`. The initial migration enables `vector`, creates all tables and indexes (including the HNSW index `vector_cosine_ops`) and seeds the three roles.

```bash
alembic upgrade head        # apply (the Docker backend does this on every start; it is idempotent)
alembic downgrade base      # drop everything
alembic revision -m "add x" # new migration
```

---

## Seed data & demo accounts

`python -m app.seed` creates three users; `--samples` also uploads and embeds `sample_documents/` (needs Ollama).

| Role | Email | Password |
|---|---|---|
| Admin | `admin@enterpriseiq.dev` | `EnterpriseIQ-Demo-2026!` |
| Manager | `manager@enterpriseiq.dev` | `EnterpriseIQ-Demo-2026!` |
| Employee | `employee@enterpriseiq.dev` | `EnterpriseIQ-Demo-2026!` |

> ⚠️ **Development credentials only.** Delete these accounts or change the passwords before any real deployment, and set a strong `JWT_SECRET_KEY` and `POSTGRES_PASSWORD`.

Sample documents: *HR Policy 2025* and *HR Policy 2026* (public — try **Compare**), and *IT Security Standard* (restricted to managers). Sign in as the employee and ask about MFA rules: you get "I couldn't find this information…", while the manager gets a cited answer.

---

## API

Interactive docs: **http://localhost:8000/docs** (OpenAPI at `/openapi.json`). Errors always look like `{"error": {"code": "...", "message": "..."}}`.

| Method | Path | Who |
|---|---|---|
| POST | `/api/auth/register` · `/api/auth/login` · `/api/auth/logout` | public / signed in |
| GET | `/api/auth/me` | signed in |
| GET/POST/PATCH/DELETE | `/api/users`, `/api/users/{id}` | admin |
| GET | `/api/users/directory` | signed in (for sharing) |
| POST | `/api/documents` (multipart) | manager, admin |
| GET | `/api/documents`, `/api/documents/{id}`, `/{id}/chunks`, `/{id}/download` | readers of the document |
| DELETE | `/api/documents/{id}` | admin, owning manager |
| GET/PUT | `/api/documents/{id}/permissions` | admin, owning manager |
| POST | `/api/documents/{id}/reprocess` | admin, owning manager |
| POST | `/api/documents/{id}/summarize` · `/api/documents/compare` | readers |
| POST | `/api/search` | signed in |
| POST | `/api/chat` · `/api/conversations/{id}/regenerate` | signed in |
| GET/DELETE | `/api/conversations`, `/api/conversations/{id}` | owner |
| GET | `/api/admin/stats` | signed in (role-aware) |
| GET | `/api/admin/audit-logs` · POST `/api/admin/reembed` | admin |
| GET | `/api/health` · `/api/health/ai` | public |

### Example requests

```bash
API=http://localhost:8000
TOKEN=$(curl -s $API/api/auth/login -H 'Content-Type: application/json' \
  -d '{"email":"manager@enterpriseiq.dev","password":"EnterpriseIQ-Demo-2026!"}' | python -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')

# Upload a restricted document visible to managers only
curl -s $API/api/documents -H "Authorization: Bearer $TOKEN" \
  -F file=@sample_documents/it-security-standard.md -F title="IT Security Standard" \
  -F visibility=RESTRICTED -F roles=MANAGER -F tags=security,it

# Semantic search with filters
curl -s $API/api/search -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"query":"multi-factor authentication requirements","filters":{"file_types":["md"]}}'

# Ask a question
curl -s $API/api/chat -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"message":"How many days of annual leave do employees get in 2026?"}'

# Executive summary
curl -s $API/api/documents/<document-id>/summarize -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"type":"executive"}'
```

Example chat response:

```json
{
  "conversation_id": "5b0c…",
  "answer": "Full-time employees receive 20 days of paid annual leave per year [S1].",
  "sources": [{ "source_number": 1, "document_name": "HR Policy 2026", "section": "1. Annual Leave",
                "page": null, "excerpt": "All full-time employees receive 20 days…", "relevance_score": 0.81 }]
}
```

---

## Security model

* **Permissions are enforced in SQL, before retrieval.** `security/permissions.py::accessible_documents_clause` is a single SQL expression used by every document query *and* inside the pgvector similarity search. Unauthorised chunks never leave the database, so they can never reach the prompt. A Python mirror exists only for already-loaded rows.
* **Rules:** admins read everything; everyone reads `PUBLIC` documents; `RESTRICTED` documents are readable by their uploader and by roles/users listed in `document_permissions`. Only admins and the owning manager can delete, re-process or change access.
* **No existence leaks:** an inaccessible document returns the same `404` as a missing one.
* **Tokens:** short-lived JWTs carrying a `token_version`; logout, role change and disabling a user bump it, revoking all existing tokens.
* **Prompt-injection hygiene:** prompts tell the model that document text is data, not instructions; only sources the model actually cites are returned.
* **Uploads:** extension allow-list + magic-byte check + size limit; files stored under random directories with sanitised names; path traversal blocked.
* **Logging:** structured JSON; passwords, tokens and document content are redacted. Audit events (`USER_LOGIN`, `DOCUMENT_UPLOADED`, `DOCUMENT_DELETED`, `DOCUMENT_ACCESSED`, `SEARCH_PERFORMED`, `CHAT_REQUEST`, `ROLE_CHANGED`, `PERMISSION_CHANGED`, `PERMISSION_DENIED`, …) go to `audit_logs`.
* Rate limits: login/register 10/min, chat 30/min, search 60/min, everything else 300/min per IP.

---

## Tests

Backend — 37 tests: chunking, PDF/DOCX extraction, file validation, JWT, Argon2, RBAC rules, citations, and end-to-end API tests against a **real PostgreSQL + pgvector** database. Ollama is replaced by deterministic fakes, so no models are needed.

```bash
# a disposable database with pgvector, e.g.
docker run -d --name eiq-test -e POSTGRES_PASSWORD=test -p 5433:5432 pgvector/pgvector:pg16
cd backend
TEST_DATABASE_URL=postgresql+psycopg://postgres:test@localhost:5433/postgres pytest
```

The most important ones (`tests/test_api.py`): an employee cannot list, open, download or search a restricted document; its text is **never sent to the LLM** during chat; granting the employee access makes it visible; another manager cannot delete or re-share it. Without a reachable `TEST_DATABASE_URL` the integration tests are skipped and the unit tests still run.

Frontend — 10 tests (Vitest + Testing Library): sign-in flow, error display, protected and admin-only routes, document list / upload validation / role-based controls, chat with citations and the "local AI unavailable" state.

```bash
cd frontend && npm install && npm test
```

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| Banner "Local AI not ready" / `503 LLM_UNAVAILABLE` | Ollama isn't running or a model is missing. `docker compose logs ollama-init`, or run `ollama pull mistral` and `ollama pull nomic-embed-text`. |
| `Embedding size mismatch …` | `EMBEDDING_DIMENSIONS` doesn't match the model (nomic-embed-text = 768). Fix it, recreate the DB, re-embed. |
| Answers are slow | CPU inference is slow; enable the GPU block, use a smaller model (e.g. `OLLAMA_LLM_MODEL=llama3.2:3b`), or lower `TOP_K` / `MAX_CONTEXT_CHARS`. |
| `The local model took too long to respond` | Raise `OLLAMA_TIMEOUT_SECONDS`. The first request after start also loads the model into memory. |
| Document stuck `FAILED: No readable text found` | Scanned PDF without a text layer — OCR it first. |
| `extension "vector" is not available` | Use the `pgvector/pgvector` image or install pgvector on your Postgres. |
| Search returns nothing | Lower `SIMILARITY_THRESHOLD` (e.g. 0.35); check the document is `COMPLETED` and embedded with the current model. |
| Backend can't reach Ollama outside Docker | Use `OLLAMA_BASE_URL=http://localhost:11434`. Inside Docker it must be `http://ollama:11434`. |
| `env_file … required` error | Update Docker Compose to v2.24+ (or delete the `env_file` block). |

---

## Design decisions

* **Permission filter inside the vector query** rather than post-filtering: no risk of leaking chunks and `top_k` stays meaningful. pgvector ≥ 0.8 `hnsw.iterative_scan` keeps HNSW recall high with selective filters.
* **Provider interfaces** (`ai/base.py`): retrieval and prompting depend on `LLMProvider` / `EmbeddingProvider`, so tests use fakes and another local runtime can be added without touching the pipeline.
* **Background tasks** for ingestion keep uploads fast; `process_document` is a plain function, ready to move to Celery/RQ for scale.
* **Embedding-model tracking per document** prevents mixing vector spaces after a model change.
* **Map-reduce summaries** handle documents longer than the model's context instead of truncating them.
* **Citations are snapshots** (`message_sources` stores the excerpt), so history stays readable after re-processing.
* The brief suggested Tailwind; the UI uses a small hand-written token stylesheet instead to keep the build dependency-light. Swapping in Tailwind is straightforward.

## Future improvements

OCR for scanned PDFs · streaming answers (SSE) · hybrid BM25 + vector search with re-ranking · Celery/Redis worker queue · refresh tokens in httpOnly cookies · SSO (OIDC/SAML) · per-department roles · document versioning · S3-compatible object storage · Prometheus metrics and OpenTelemetry tracing.
