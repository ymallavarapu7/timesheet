# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

---

## Project Overview

Full-stack multi-tenant timesheet application for IT consulting firms. Two sub-systems:

- **backend/** — Python FastAPI + SQLAlchemy async + PostgreSQL. Includes the email ingestion pipeline (IMAP fetch, LLM extraction, reviewer queue) as internal services and arq background workers.
- **frontend/** — React 18 + TypeScript + TanStack Query + Tailwind CSS + shadcn/ui

---

## Commands

### Backend

```bash
cd backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# DB setup (first time)
createuser -P timesheet_user   # password: timesheet_pass
createdb -O timesheet_user timesheet_db
alembic upgrade head
python -m app.seed             # idempotent demo data

# Run
uvicorn app.main:app --reload  # http://localhost:8000 · /docs for Swagger

# Test
pytest
pytest tests/test_auth.py -v   # single file
```

### Frontend

```bash
cd frontend
npm install
npm run dev    # http://localhost:5174
npm run build
npm run lint
npm run test
npm run test:watch
```

---

## Environment Variables

### backend/.env

| Variable | Default |
|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://timesheet_user:timesheet_pass@localhost:5432/timesheet_db` |
| `SECRET_KEY` | `dev-secret-key-change-in-production` |
| `ALGORITHM` | `HS256` |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `30` |
| `REFRESH_TOKEN_EXPIRE_DAYS` | `7` |
| `REDIS_URL` | `redis://localhost:6379` |
| `OPENAI_API_KEY` | *(required for ingestion LLM extraction)* |
| `ENCRYPTION_KEY` | AES-256-GCM 32-byte hex key |
| `STORAGE_PROVIDER` | `local` or `s3` |
| `GOOGLE_CLIENT_ID/SECRET/REDIRECT_URI` | OAuth for Gmail mailboxes |
| `MICROSOFT_CLIENT_ID/SECRET/TENANT_ID/REDIRECT_URI` | OAuth for Outlook mailboxes |

### frontend/.env

```
VITE_API_BASE_URL=http://localhost:8000
```

---

## Architecture

### Backend Layers

```
app/api/        → FastAPI route handlers (one file per domain)
app/core/       → config.py (Settings), deps.py (DI), security.py (JWT/bcrypt)
app/models/     → SQLAlchemy ORM models
app/schemas/    → Pydantic v2 request/response schemas (all in __init__.py)
app/crud/       → Async DB operations; all list queries filter by tenant_id
app/services/   → Business logic: ingestion pipeline, LLM extraction, IMAP, encryption, storage
app/workers/    → arq background job handlers (Redis-backed)
```

All DB operations are async (asyncpg). Eager relationship loading is used throughout to prevent N+1 queries.

### Multi-Tenancy

`tenant_id` is **never** trusted from the client — always derived server-side from the JWT.

```python
# DI patterns
current_user: User = Depends(get_current_user)
current_user: User = Depends(require_role("ADMIN", "PLATFORM_ADMIN"))
require_same_tenant(resource.tenant_id, current_user)  # raises 403 on mismatch
tenant_id: int = Depends(get_tenant_id)
```

Every tenanted table has `tenant_id` FK. All `create_*` CRUD functions take it as an explicit kwarg injected from `current_user.tenant_id`.

### User Roles

| Role | tenant_id | Notes |
|---|---|---|
| `EMPLOYEE` | required | Own time entries only |
| `MANAGER` | required | Approves direct reports |
| `SENIOR_MANAGER` | required | Approves managers and employees |
| `CEO` | required | Read-only all entries in tenant |
| `ADMIN` | required | Full management within tenant |
| `PLATFORM_ADMIN` | NULL | Cross-tenant superuser |

`PLATFORM_ADMIN` bypasses all `require_same_tenant` checks. Role is a Python enum — use `current_user.role.value` when comparing to string literals.

### JWT

```json
{ "sub": "<user_id_as_string>", "tenant_id": <int_or_null> }
```

`sub` is `str(user.id)` (integer ID, not email). Login via `POST /auth/login` → `access_token` + `refresh_token`. All protected routes use `Authorization: Bearer <token>` (HTTPBearer, not OAuth2).

### Email Ingestion Pipeline

```
Mailbox (OAuth Google/MS) → IMAP fetch → Parse email → LLM extraction (OpenAI)
  → IngestionTimesheet (pending review) → Manual review → Sync → TimeEntry
```

Services involved: `app/services/ingestion_pipeline.py`, `llm_ingestion.py`, `imap.py`, `email_parser.py`, `ingestion_sync.py`. Encrypted OAuth credentials stored via `app/services/encryption.py` (AES-256-GCM).

### Frontend Structure

```
src/api/          → Axios API clients; token injected via interceptor in client.ts
src/contexts/     → AuthContext.tsx — global auth state, useAuth() hook
src/hooks/        → 80+ TanStack Query hooks; mutations invalidate relevant query keys
src/pages/        → Route-level components
src/components/   → Shared UI; ui/ = shadcn wrappers; layout/ = shell
src/types/        → Centralized TypeScript interfaces
```

Role checks use string comparisons:
```typescript
const isAdmin = user?.role === 'ADMIN' || user?.role === 'PLATFORM_ADMIN';
// UserRole: 'EMPLOYEE' | 'MANAGER' | 'SENIOR_MANAGER' | 'CEO' | 'ADMIN' | 'PLATFORM_ADMIN'
```

### Database Migrations (Alembic)

```bash
cd backend
alembic upgrade head
alembic revision --autogenerate -m "description"
alembic downgrade -1

# For existing DBs without migration history:
alembic stamp 001_baseline_schema
alembic upgrade head
```

Alembic uses async engine (`asyncio.run()` + `run_sync` in `env.py`). Migration history: `001_baseline_schema` → `002_add_multi_tenancy` → subsequent.

---

## Key Patterns

### Adding a New Tenanted Resource

1. Add `tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), nullable=False, index=True)` to model
2. `create_*` CRUD function takes `tenant_id: int` explicitly (not from schema)
3. List queries filter `.where(Model.tenant_id == tenant_id)`
4. After fetching by ID: `require_same_tenant(resource.tenant_id, current_user)`
5. Write Alembic migration

### Service Tokens

Inter-service auth (ingestion platform → backend) uses service tokens, not user JWTs. See `app/core/security.py` and `app/api/` for verification pattern.

### QuickBooks

Pluggable stub in `app/services/quickbooks.py`. Called after time entry approval. Currently mocked.

### File Storage

`STORAGE_PROVIDER=local` writes to `./uploads`. Set to `s3` with S3 env vars for production.

---

## Demo Users (after seeding)

Password for all: `password`

| Role | Email |
|---|---|
| ADMIN | admin@example.com |
| CEO | ceo@example.com |
| SENIOR_MANAGER | alexander@example.com, margaret@example.com |
| MANAGER | manager1–3@example.com |
| EMPLOYEE | emp1-1, emp1-2, emp1-3, emp3-1, emp3-2, emp4-1 @example.com |

All assigned to "Default Tenant" (slug: `default`).

---

## Common Gotchas

- **Role is an enum** in Python — compare with `current_user.role.value == "CEO"` or `current_user.role == UserRole.CEO`, not bare strings.
- **`tenant_id` never in Pydantic schemas** — always injected server-side.
- **`sub` in JWT is `str(user.id)`** — an integer ID as string, not email.
- **Alembic uses async engine** — never run standard sync Alembic outside the configured `env.py`.
- **There is no separate ingestion-platform directory** — email ingestion is implemented entirely within the backend (`app/services/`, `app/workers/`, `app/api/`). The `/sync` API endpoints exist to support an optional external platform connecting via service token.
- **Redis required** for arq background workers. Ingestion pipeline runs async jobs; without Redis the background processing won't function.
