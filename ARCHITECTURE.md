# TimesheetIQ — Architecture Reference

Full-stack multi-tenant timesheet management platform for IT consulting firms.

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Technology Stack](#2-technology-stack)
3. [Repository Layout](#3-repository-layout)
4. [Running the Application](#4-running-the-application)
5. [Database Schema](#5-database-schema)
6. [Backend Architecture](#6-backend-architecture)
7. [API Reference](#7-api-reference)
8. [Frontend Architecture](#8-frontend-architecture)
9. [Email Ingestion Pipeline](#9-email-ingestion-pipeline)
10. [Background Jobs](#10-background-jobs)
11. [Authentication & Security](#11-authentication--security)
12. [Multi-Tenancy](#12-multi-tenancy)
13. [Configuration Reference](#13-configuration-reference)
14. [Docker & Deployment](#14-docker--deployment)
15. [Database Migrations](#15-database-migrations)

---

## 1. System Overview

TimesheetIQ has two parallel workflows:

**Direct Entry** — Employees log time against projects, submit weekly, managers approve.

**Email Ingestion** — Contractors email timesheets (PDF, Excel, images). An AI pipeline extracts structured data, reviewers confirm, and time entries are created automatically.

Both workflows share the same approval hierarchy, role model, and data store.

---

## 2. Technology Stack

| Layer | Technology |
|---|---|
| Backend API | FastAPI 0.109.0 (Python 3.12) |
| ORM | SQLAlchemy 2.0.25 async |
| Database | PostgreSQL 16 (asyncpg driver) / SQLite (dev) |
| Migrations | Alembic 1.13.1 async |
| Auth | JWT HS256 + bcrypt + AES-256-GCM |
| Background Jobs | arq 0.26.1 (Redis-backed) |
| File Storage | Local filesystem or S3 |
| LLM | OpenAI API 1.51.0 (gpt-4o, gpt-4o-mini) |
| Email Fetch | imapclient 2.3.1, mail-parser 3.15.0 |
| OCR | pytesseract 0.3.13, pdf2image 1.17.0, pdfplumber 0.11.4 |
| Excel | openpyxl 3.1.5, xlrd 2.0.1 |
| Encryption | cryptography 43.0.3 |
| Rate Limiting | slowapi 0.1.9 |
| Frontend | React 18 + TypeScript 5.3 |
| Routing | React Router v6 |
| Server State | TanStack Query v5 |
| HTTP Client | Axios 1.6.5 |
| Forms | React Hook Form + Zod |
| Styling | Tailwind CSS 3.4 + shadcn/ui |
| Build | Vite 5 |
| Frontend Tests | Vitest + React Testing Library |

---

## 3. Repository Layout

```
Timesheet/
├── backend/
│   ├── app/
│   │   ├── api/            # Route handlers (one file per domain)
│   │   ├── core/           # config.py, deps.py, security.py
│   │   ├── crud/           # Async DB operations
│   │   ├── models/         # SQLAlchemy ORM models
│   │   ├── schemas/        # Pydantic v2 schemas
│   │   ├── services/       # Business logic
│   │   ├── workers/        # arq job handlers
│   │   ├── main.py         # FastAPI app, middleware, router registration
│   │   └── db.py           # Engine, session factory, init_db
│   ├── alembic/
│   │   └── versions/       # 12 migration files (001–012)
│   ├── tests/
│   ├── requirements.txt
│   ├── run_worker.py
│   └── Dockerfile
│
├── frontend/
│   └── src/
│       ├── api/            # Axios client + all endpoint functions
│       ├── components/     # Shared UI (Sidebar, TopBar, Modal, Badge, etc.)
│       ├── contexts/       # AuthContext.tsx
│       ├── hooks/          # useAuth.ts, useData.ts (90+ hooks)
│       ├── pages/          # Route-level page components
│       ├── types/          # TypeScript interfaces
│       └── App.tsx         # Routes + role guards
│   ├── package.json
│   ├── nginx.conf
│   └── Dockerfile
│
├── docker-compose.yml
├── package.json            # Root dev scripts (concurrently)
├── start.bat               # Windows dev launcher
├── stop.bat                # Windows dev killer
├── CLAUDE.md
├── ARCHITECTURE.md         # This file
├── logins.md               # Test credentials
├── edge_cases_testing.md   # QA scenarios
└── docs/
    ├── USER_GUIDE.md
    └── DB_BACKUP_RESTORE.md
```

---

## 4. Running the Application

### Windows (local dev)

```bat
start.bat          # Starts backend (:8000), worker, frontend (:5174)
stop.bat           # Kills all three windows
```

Or manually:

```bash
# Backend (from /backend)
python -m venv venv && source venv/Scripts/activate
pip install -r requirements.txt
uvicorn app.main:app --reload

# Worker (from /backend)
python run_worker.py

# Frontend (from /frontend)
npm install
npm run dev
```

### Docker (production)

```bash
docker-compose up --build
```

Services: PostgreSQL (:5432), Redis (:6379), API (:8000), Frontend (:80).

### First-time DB setup (local)

```bash
createuser -P timesheet_user      # password: timesheet_pass
createdb -O timesheet_user timesheet_db
cd backend
alembic upgrade head
python -m app.seed                 # loads demo users and data
```

### URLs

| Service | URL |
|---|---|
| Frontend | http://localhost:5174 (dev) / http://localhost (Docker) |
| Backend API | http://localhost:8000 |
| Swagger Docs | http://localhost:8000/docs |

---

## 5. Database Schema

### Core Tables

**tenants**
| Column | Type | Notes |
|---|---|---|
| id | int PK | |
| name | varchar(255) | |
| slug | varchar(100) | unique, indexed |
| status | enum | active / inactive / suspended |
| ingestion_enabled | bool | default false |
| created_at, updated_at | timestamptz | |

**users**
| Column | Type | Notes |
|---|---|---|
| id | int PK | |
| tenant_id | int FK → tenants | nullable (PLATFORM_ADMIN only) |
| email | varchar(255) | unique |
| username | varchar(255) | unique |
| full_name | varchar(255) | |
| title | varchar(255) | nullable |
| department | varchar(255) | nullable |
| hashed_password | varchar(255) | bcrypt |
| has_changed_password | bool | default false |
| role | enum | EMPLOYEE / MANAGER / SENIOR_MANAGER / CEO / ADMIN / PLATFORM_ADMIN |
| is_active | bool | default true |
| can_review | bool | default false — ingestion reviewer permission |
| is_external | bool | default false — contractor flag |
| timesheet_locked | bool | default false |
| timesheet_locked_reason | text | nullable |
| failed_login_attempts | int | default 0 |
| locked_until | timestamptz | nullable — account lockout |
| ingestion_employee_id | varchar(36) | external sync ID |
| ingestion_created_by | varchar(255) | nullable |

**clients**
| Column | Type | Notes |
|---|---|---|
| id | int PK | |
| tenant_id | int FK → tenants | indexed |
| name | varchar(255) | unique per tenant |
| quickbooks_customer_id | varchar(255) | nullable |
| ingestion_client_id | varchar(36) | unique, external sync ID |

**projects**
| Column | Type | Notes |
|---|---|---|
| id | int PK | |
| tenant_id | int FK → tenants | |
| client_id | int FK → clients | |
| name | varchar(255) | |
| code | varchar(80) | nullable |
| description | text | nullable |
| billable_rate | decimal(10,2) | |
| start_date / end_date | date | nullable |
| estimated_hours | decimal(10,2) | nullable |
| budget_amount | decimal(12,2) | nullable |
| currency | varchar(10) | nullable |
| is_active | bool | default true |
| quickbooks_project_id | varchar(255) | nullable |
| ingestion_project_id | varchar(36) | unique, external sync ID |

**tasks**
| Column | Type | Notes |
|---|---|---|
| id | int PK | |
| tenant_id | int FK → tenants | |
| project_id | int FK → projects | |
| name | varchar(255) | |
| code | varchar(80) | nullable |
| description | text | nullable |
| is_active | bool | default true |

**time_entries**
| Column | Type | Notes |
|---|---|---|
| id | int PK | |
| tenant_id | int FK → tenants | |
| user_id | int FK → users | |
| project_id | int FK → projects | |
| task_id | int FK → tasks | nullable |
| entry_date | date | indexed |
| hours | decimal(5,2) | |
| description | text | |
| is_billable | bool | default true |
| status | enum | DRAFT / SUBMITTED / APPROVED / REJECTED |
| submitted_at | timestamptz | nullable |
| approved_by | int FK → users | nullable |
| approved_at | timestamptz | nullable |
| rejection_reason | text | nullable |
| last_edit_reason | text | nullable |
| last_history_summary | text | nullable |
| quickbooks_time_activity_id | varchar(255) | nullable |
| ingestion_timesheet_id | varchar(36) | nullable |
| ingestion_line_item_id | varchar(36) | unique, deduplication key |
| ingestion_approved_by_name | varchar(255) | nullable |
| ingestion_source_tenant | varchar(255) | nullable |

**time_entry_edit_history**
| Column | Type | Notes |
|---|---|---|
| id | int PK | |
| time_entry_id | int FK → time_entries | |
| edited_by | int FK → users | |
| edited_at | timestamptz | |
| edit_reason | text | |
| history_summary | text | |
| previous_project_id | int FK → projects | |
| previous_entry_date | date | |
| previous_hours | decimal(5,2) | |
| previous_description | text | |

**time_off_requests**
| Column | Type | Notes |
|---|---|---|
| id | int PK | |
| tenant_id | int FK → tenants | |
| user_id | int FK → users | |
| request_date | date | |
| hours | decimal(5,2) | |
| leave_type | enum | SICK_DAY / PTO / HALF_DAY / HOURLY_PERMISSION / OTHER_LEAVE |
| reason | text | |
| status | enum | DRAFT / SUBMITTED / APPROVED / REJECTED |
| submitted_at | timestamptz | nullable |
| approved_by | int FK → users | nullable |
| approved_at | timestamptz | nullable |
| rejection_reason | text | nullable |
| external_reference | varchar(255) | nullable |

### Relationship Tables

**employee_manager_assignments** — Maps each employee to their manager (one-to-one per employee)
- employee_id (PK, FK → users)
- manager_id (FK → users)

**user_project_access** — Explicit project grants per user
- user_id (PK, FK → users)
- project_id (PK, FK → projects)

### Auth & Security Tables

**refresh_tokens**
- id, user_id (FK CASCADE), jti (unique), revoked bool, expires_at

**service_tokens** — Machine-to-machine auth for sync API
- id, name, token_hash (bcrypt), tenant_id (FK), issuer, is_active, last_used_at

### Notification Tables

**user_notification_states** — Tracks last_read_at per (user_id, notification_id)
**user_notification_dismissals** — Tracks deleted_at per (user_id, notification_id)

### Activity & Audit

**activity_log**
- tenant_id, actor_user_id, actor_name, activity_type, visibility_scope, entity_type, entity_id, summary, route, route_params (JSON), metadata_json (JSON), severity, created_at

**sync_log** — Inbound/outbound sync tracking
- direction (inbound/outbound), entity_type (user/client/project/timesheet), local_id, ingestion_id, status (success/failed/skipped/partial), error_message, payload, action

### Tenant Configuration

**tenant_settings** — Key-value config per tenant (used for reminders, deadline config)
- tenant_id, key (varchar 100), value (text)
- unique: (tenant_id, key)

### Email Ingestion Tables

**mailboxes**
- tenant_id, label, protocol (imap/pop3/graph), host, port, use_ssl
- auth_type (basic/oauth2), username, password_enc (AES encrypted)
- oauth_provider (google/microsoft), oauth_email, oauth_access_token_enc, oauth_refresh_token_enc, oauth_token_expiry
- smtp_host, smtp_port, smtp_username, smtp_password_enc
- linked_client_id (FK → clients), is_active, last_fetched_at

**ingested_emails**
- tenant_id, mailbox_id (FK), message_id (unique per tenant), subject, sender_email, sender_name
- recipients (JSON), body_text, body_html, received_at, fetched_at, has_attachments, raw_headers (JSON)
- llm_classification (JSON) — result of LLM classify_email() call

**email_attachments**
- email_id (FK), filename, mime_type, size_bytes, storage_key
- is_timesheet bool, extraction_method (native_pdf/native_spreadsheet/tesseract/vision_api/llm_structured)
- extraction_status (pending/processing/completed/failed), extraction_error, raw_extracted_text

**ingestion_timesheets**
- tenant_id, email_id (FK), attachment_id (FK), employee_id (FK → users), client_id (FK → clients)
- reviewer_id (FK → users), period_start, period_end, total_hours
- status (pending/under_review/approved/rejected/on_hold)
- extracted_data (JSON), corrected_data (JSON), llm_anomalies (JSON), llm_match_suggestions (JSON), llm_summary
- rejection_reason, internal_notes, submitted_at, reviewed_at, time_entries_created bool

**ingestion_timesheet_line_items**
- ingestion_timesheet_id (FK CASCADE), work_date, hours, description, project_code, project_id (FK)
- is_corrected bool, original_value (JSON), is_rejected bool, rejection_reason

**ingestion_audit_log**
- ingestion_timesheet_id (FK), user_id (FK), action, actor_type (user/system)
- previous_value (JSON), new_value (JSON), comment, created_at

**email_sender_mappings**
- tenant_id, match_type (email/domain), match_value, client_id (FK), employee_id (FK nullable)
- index on (tenant_id, match_value)

---

## 6. Backend Architecture

### Layer Overview

```
app/api/        Route handlers — validate input, call CRUD/services, return responses
app/crud/       Async DB queries — all list queries filter by tenant_id
app/services/   Business logic — ingestion pipeline, LLM, email, encryption, storage
app/workers/    arq background jobs — email fetch, reminder notifications
app/core/       config.py, deps.py (DI), security.py (JWT/bcrypt)
app/models/     SQLAlchemy ORM models
app/schemas/    Pydantic v2 request/response schemas
```

### Startup Sequence (`main.py`)

1. FastAPI app created with lifespan handler
2. `init_db()` called on startup — creates tables, runs legacy column backfill
3. CORS middleware registered (localhost:5173–5175, :3000)
4. Security headers middleware (X-Content-Type-Options, X-Frame-Options, HSTS in prod)
5. Rate limiter registered (slowapi)
6. 14 routers registered
7. `/health` and `/` endpoints available

### Configuration (`core/config.py`)

All settings via environment variables with defaults:

| Setting | Default | Notes |
|---|---|---|
| DATABASE_URL | postgresql+asyncpg://... | Switches to aiosqlite for sqlite:// URLs |
| SECRET_KEY | (required) | min 32 chars in production |
| ALGORITHM | HS256 | |
| ACCESS_TOKEN_EXPIRE_MINUTES | 30 | |
| REFRESH_TOKEN_EXPIRE_DAYS | 7 | |
| MAX_HOURS_PER_ENTRY | 24.0 | |
| MAX_HOURS_PER_DAY | 24.0 | |
| MAX_HOURS_PER_WEEK | 80.0 | |
| MIN_SUBMIT_WEEKLY_HOURS | 1.0 | |
| TIME_ENTRY_BACKDATE_WEEKS | 8 | |
| STORAGE_PROVIDER | local | or s3 |
| STORAGE_PATH | ./uploads | local only |
| ENCRYPTION_KEY | (required) | 32-byte hex for AES-256-GCM |
| REDIS_URL | redis://localhost:6379 | |
| OPENAI_API_KEY | (required for ingestion) | |
| INGESTION_PLATFORM_URL | (optional) | external sync target |
| INGESTION_SERVICE_TOKEN | (optional) | external sync auth |
| SMTP_HOST | (optional) | enables reminder emails |

### Dependency Injection (`core/deps.py`)

```python
get_current_user(credentials, db) → User
    # Decodes JWT, verifies user exists and is active

require_role(*roles) → Depends(...)
    # Raises 403 if current user's role not in allowed list

require_same_tenant(resource_tenant_id, current_user)
    # Raises 403 on tenant mismatch; PLATFORM_ADMIN bypasses

get_service_token_tenant(request, db) → (tenant_id, ServiceToken)
    # Reads X-Service-Token + X-Tenant-ID headers, validates bcrypt hash

require_ingestion_enabled(current_user, db) → User
    # Raises 403 if tenant.ingestion_enabled == False

require_can_review(current_user) → User
    # Raises 403 if not ADMIN and not can_review
```

### CRUD Layer Key Patterns

**Tenant scoping** — every list query includes `.where(Model.tenant_id == tenant_id)`.

**Eager loading** — relationships loaded via `selectinload` to prevent N+1 queries.

**Time entry validation** (enforced on create and update):
- Max 24h per entry
- Max 24h per calendar day (sum of non-REJECTED entries)
- Max 80h per week (Monday–Sunday)
- Backdate limit: 8 weeks
- Future dates blocked
- User must have explicit UserProjectAccess
- Task (if provided) must belong to project and be active

**Edit history** — every update to a DRAFT or REJECTED entry creates a `TimeEntryEditHistory` row capturing previous values and the edit reason.

**Submission validation:**
- All submitted entries must be DRAFT
- Minimum 1.0 hours for the week
- Submission only allowed on or after the Friday of that week

### Services

| Service | File | Purpose |
|---|---|---|
| Ingestion Pipeline | `ingestion_pipeline.py` | Orchestrates parse → classify → extract → match → persist |
| LLM Ingestion | `llm_ingestion.py` | classify_email, extract_timesheet_data, match_entities, detect_anomalies |
| Extraction | `extraction.py` | PDF (native → OCR → Vision API), Excel (openpyxl/xlrd), images |
| Email Parser | `email_parser.py` | Parses raw MIME bytes into ParsedEmail + attachments |
| IMAP | `imap.py` | Fetches messages from IMAP/POP3/Graph, handles OAuth token refresh |
| Sync | `ingestion_sync.py` | Upserts employees/clients/projects from external platform, pushes approved timesheets |
| Storage | `storage.py` | Save/read/delete files — local filesystem or S3 |
| Encryption | `encryption.py` | AES-256-GCM encrypt/decrypt for credentials stored in DB |
| Activity | `activity.py` | Builds and bulk-inserts ActivityLog events |
| Email Send | `email_service.py` | SMTP send for reminder notifications |
| Summary Sheet | `summary_timesheet.py` | Detects and parses pivot-style Excel summary timesheets |
| QuickBooks | `quickbooks.py` | Stub — called post-approval, not yet implemented |

---

## 7. API Reference

All protected routes require: `Authorization: Bearer <access_token>`
Sync routes require: `X-Service-Token: <token>` + `X-Tenant-ID: <id>`

### Auth (`/auth`)

| Method | Path | Auth | Description |
|---|---|---|---|
| POST | `/auth/login` | None | Login. Rate: 10/min. Returns access+refresh tokens |
| POST | `/auth/register` | ADMIN/PLATFORM_ADMIN | Create user |
| GET | `/auth/me` | Bearer | Current user |
| POST | `/auth/refresh` | None | Rotate refresh token. Rate: 20/min |
| POST | `/auth/change-password` | Bearer | Change own password |
| POST | `/auth/logout` | Bearer | Revoke refresh token |
| POST | `/auth/revoke-all-tokens` | Bearer | Force logout all sessions |
| POST | `/auth/admin/revoke-user-tokens/{user_id}` | ADMIN | Force logout specific user |

### Users (`/users`)

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/users` | Bearer | List users (role-scoped) |
| POST | `/users` | ADMIN | Create user |
| GET | `/users/{id}` | Bearer | Get user |
| PUT | `/users/{id}` | ADMIN/self | Update user |
| DELETE | `/users/{id}` | ADMIN | Delete user |
| GET | `/users/me/profile` | Bearer | Own profile with manager chain |
| PATCH | `/users/me/profile` | Bearer | Update name, title, department |
| POST | `/users/me/password` | Bearer | Change own password |
| GET | `/users/tenant-settings` | ADMIN | Get tenant key-value settings |
| PATCH | `/users/tenant-settings` | ADMIN | Upsert tenant settings |
| POST | `/users/{id}/unlock-timesheet` | ADMIN | Unlock locked user |

### Clients (`/clients`)

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/clients` | Bearer | List clients |
| GET | `/clients/{id}` | Bearer | Get client |
| POST | `/clients` | ADMIN | Create client |
| PUT | `/clients/{id}` | ADMIN | Update client (triggers outbound webhook) |
| DELETE | `/clients/{id}` | ADMIN | Delete client |

### Projects (`/projects`)

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/projects` | Bearer | List (params: client_id, active_only) |
| GET | `/projects/{id}` | Bearer | Get project |
| POST | `/projects` | ADMIN | Create project |
| PUT | `/projects/{id}` | ADMIN | Update project (triggers outbound webhook) |
| DELETE | `/projects/{id}` | ADMIN | Delete project |

### Tasks (`/tasks`)

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/tasks` | Bearer | List (params: project_id, active_only) |
| GET | `/tasks/{id}` | Bearer | Get task |
| POST | `/tasks` | ADMIN | Create task |
| PUT | `/tasks/{id}` | ADMIN | Update task |
| DELETE | `/tasks/{id}` | ADMIN | Delete task |

### Time Entries (`/timesheets`)

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/timesheets/my` | Bearer | Own entries (filterable) |
| GET | `/timesheets/weekly-submit-status` | Bearer | Can submit this week? |
| GET | `/timesheets/all` | MANAGER+ | All tenant entries (role-scoped) |
| GET | `/timesheets/{id}` | Bearer | Single entry |
| POST | `/timesheets` | Bearer | Create DRAFT entry |
| PUT | `/timesheets/{id}` | Bearer | Update DRAFT/REJECTED entry |
| DELETE | `/timesheets/{id}` | Bearer | Delete DRAFT entry |
| POST | `/timesheets/submit` | Bearer | Submit entry IDs for approval |

### Approvals (`/approvals`)

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/approvals/pending` | MANAGER+ | Pending SUBMITTED entries |
| GET | `/approvals/history` | MANAGER+ | Approved/rejected history (7-day TTL) |
| GET | `/approvals/history-grouped` | MANAGER+ | History grouped by employee+week |
| POST | `/approvals/{id}/approve` | MANAGER+ | Approve single entry |
| POST | `/approvals/{id}/reject` | MANAGER+ | Reject with reason |
| POST | `/approvals/batch-approve` | MANAGER+ | Approve all in same employee+week |
| POST | `/approvals/batch-reject` | MANAGER+ | Reject all in same employee+week |
| POST | `/approvals/{id}/revert-rejection` | MANAGER+ | Revert REJECTED → SUBMITTED |

### Time Off (`/time-off`, `/time-off-approvals`)

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/time-off/my` | Bearer | Own requests |
| GET | `/time-off/{id}` | Bearer | Single request |
| POST | `/time-off` | Bearer | Create DRAFT |
| PUT | `/time-off/{id}` | Bearer | Update DRAFT |
| DELETE | `/time-off/{id}` | Bearer | Delete DRAFT |
| POST | `/time-off/submit` | Bearer | Submit request IDs |
| GET | `/time-off-approvals/pending` | MANAGER+ | Pending approvals |
| GET | `/time-off-approvals/history` | MANAGER+ | Approval history |
| POST | `/time-off-approvals/{id}/approve` | MANAGER+ | Approve |
| POST | `/time-off-approvals/{id}/reject` | MANAGER+ | Reject with reason |

### Dashboard (`/dashboard`)

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/dashboard/summary` | Bearer | Hours logged, approved, pending KPIs |
| GET | `/dashboard/team` | Bearer | Team member list |
| GET | `/dashboard/team-daily-overview` | Bearer | Yesterday's submission stats |
| GET | `/dashboard/analytics` | Bearer | Daily + project breakdowns (date range required) |
| GET | `/dashboard/recent-activity` | ADMIN | Recent activity log (max 20 items) |

### Notifications (`/notifications`)

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/notifications/summary` | Bearer | All notifications with route counts |
| POST | `/notifications/read` | Bearer | Mark one as read |
| POST | `/notifications/read-all` | Bearer | Mark all as read |
| POST | `/notifications/delete` | Bearer | Dismiss one |
| POST | `/notifications/delete-all` | Bearer | Dismiss all |

### Tenants (`/tenants`) — PLATFORM_ADMIN only except `/tenants/mine`

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/tenants/mine` | Bearer | Current user's tenant |
| GET | `/tenants` | PLATFORM_ADMIN | List all tenants |
| POST | `/tenants` | PLATFORM_ADMIN | Create tenant |
| GET | `/tenants/{id}` | PLATFORM_ADMIN | Get tenant |
| PATCH | `/tenants/{id}` | PLATFORM_ADMIN | Update tenant |
| POST | `/tenants/{id}/service-tokens` | PLATFORM_ADMIN | Create service token (plaintext shown once) |
| GET | `/tenants/{id}/service-tokens` | PLATFORM_ADMIN | List tokens |
| DELETE | `/tenants/{id}/service-tokens/{token_id}` | PLATFORM_ADMIN | Revoke token |
| POST | `/tenants/{id}/provision-system-user` | PLATFORM_ADMIN | Idempotent system user creation |

### Mailboxes (`/mailboxes`)

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/mailboxes` | ADMIN + ingestion | List mailboxes |
| POST | `/mailboxes` | ADMIN + ingestion | Create mailbox |
| GET | `/mailboxes/{id}` | ADMIN + ingestion | Get mailbox |
| PATCH | `/mailboxes/{id}` | ADMIN + ingestion | Update mailbox |
| DELETE | `/mailboxes/{id}` | ADMIN + ingestion | Delete mailbox |
| POST | `/mailboxes/{id}/test` | ADMIN + ingestion | Test connectivity |
| POST | `/mailboxes/{id}/reset-cursor` | ADMIN + ingestion | Reset last_fetched_at |
| GET | `/mailboxes/oauth/connect/{provider}` | ADMIN + ingestion | Get OAuth authorization URL |
| GET | `/auth/oauth/callback/{provider}` | None | OAuth callback (creates/updates mailbox) |

### Sender Mappings (`/mappings`)

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/mappings` | ADMIN + ingestion | List mappings |
| POST | `/mappings` | ADMIN + ingestion | Create mapping |
| PATCH | `/mappings/{id}` | ADMIN + ingestion | Update mapping |
| DELETE | `/mappings/{id}` | ADMIN + ingestion | Delete mapping |

### Ingestion (`/api/ingestion`)

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/api/ingestion/timesheets` | can_review | List staged timesheets |
| GET | `/api/ingestion/timesheets/{id}` | can_review | Detail with line items + audit log |
| PATCH | `/api/ingestion/timesheets/{id}/data` | can_review | Update corrected_data |
| POST | `/api/ingestion/timesheets/{id}/approve` | can_review | Approve → creates TimeEntry records |
| POST | `/api/ingestion/timesheets/{id}/reject` | can_review | Reject with reason |
| POST | `/api/ingestion/timesheets/{id}/hold` | can_review | Put on hold |
| POST | `/api/ingestion/timesheets/{id}/revert-rejection` | can_review | Revert rejected back to pending |
| POST | `/api/ingestion/timesheets/{id}/draft-comment` | can_review | LLM draft audit comment |
| POST | `/api/ingestion/timesheets/{id}/line-items` | can_review | Add line item |
| PATCH | `/api/ingestion/timesheets/{id}/line-items/{item_id}` | can_review | Edit line item |
| DELETE | `/api/ingestion/timesheets/{id}/line-items/{item_id}` | can_review | Delete line item |
| POST | `/api/ingestion/timesheets/{id}/line-items/{item_id}/reject` | can_review | Reject single line item |
| POST | `/api/ingestion/timesheets/{id}/line-items/{item_id}/unreject` | can_review | Unreject line item |
| POST | `/api/ingestion/fetch-emails` | ADMIN | Trigger background email fetch |
| GET | `/api/ingestion/fetch-emails/status/{job_id}` | ADMIN | Poll job status |
| POST | `/api/ingestion/fetch-emails/reprocess-skipped` | ADMIN | Reprocess skipped emails |
| POST | `/api/ingestion/fetch-emails/reprocess` | ADMIN | Reprocess single email |
| GET | `/api/ingestion/skipped-emails` | can_review | List skipped/non-timesheet emails |
| GET | `/api/ingestion/emails/{id}` | can_review | Full stored email detail |
| DELETE | `/api/ingestion/emails/{id}` | ADMIN | Delete stored email |
| GET | `/api/ingestion/attachments/{id}/file` | can_review | Download attachment |
| POST | `/api/ingestion/timesheets/reapply-mappings` | ADMIN | Re-apply sender mappings |

### Sync (`/sync`) — Service Token auth only

| Method | Path | Description |
|---|---|---|
| POST | `/sync/employees` | Upsert employee from external platform |
| POST | `/sync/clients` | Upsert client |
| POST | `/sync/projects` | Upsert project |
| POST | `/sync/timesheets/push` | Push approved timesheet as APPROVED time entries |
| GET | `/sync/logs` | View sync log |
| GET | `/sync/health` | Health check |
| POST | `/sync/webhook/inbound` | Receive change events from external platform |

---

## 8. Frontend Architecture

### Route Guards

```
ProtectedRoute            → requires authenticated user
AnonymousOnlyRoute        → redirects to /dashboard if already logged in
PlatformAdminGuard        → PLATFORM_ADMIN only
AdminOrManagerGuard       → ADMIN, MANAGER, SENIOR_MANAGER, CEO
TenantAdminGuard          → ADMIN only
ManagerGuard              → MANAGER, SENIOR_MANAGER, CEO
IngestionEnabledGuard     → tenant.ingestion_enabled == true
ReviewGuard               → ADMIN or user.can_review
```

### Routes

| Path | Guard | Page |
|---|---|---|
| `/login` | AnonymousOnly | LoginPage |
| `/dashboard` | Protected | DashboardPage |
| `/my-time` | Protected | MyTimePage |
| `/time-off` | Protected | TimeOffPage |
| `/calendar` | Protected | CalendarPage |
| `/profile` | Protected | ProfilePage |
| `/user-management` | AdminOrManager | AdminPage |
| `/client-management` | TenantAdmin | ClientManagementPage |
| `/approvals` | Manager | ApprovalsPage |
| `/platform/tenants` | PlatformAdmin | PlatformAdminPage |
| `/mailboxes` | Ingestion + TenantAdmin | MailboxesPage |
| `/mappings` | Ingestion + TenantAdmin | MappingsPage |
| `/ingestion/inbox` | Ingestion + Review | InboxPage |
| `/ingestion/review/:timesheetId` | Ingestion + Review | ReviewPanelPage |
| `/ingestion/email/:emailId` | Ingestion + Review | ReviewPanelPage |

### Auth Context (`src/contexts/AuthContext.tsx`)

Global state stored in sessionStorage:

```typescript
interface AuthContextType {
  user: User | null
  tenant: Tenant | null
  accessToken: string | null
  isLoading: boolean
  error: string | null
  login(email, password): Promise<User>
  logout(): void
  refreshUser(): Promise<void>
  refreshTenant(user?): Promise<void>
}
```

**Session restore on mount:** checks sessionStorage → validates token → fetches tenant.
**401 handling:** Axios interceptor clears storage and redirects to `/login` (only if request had a token).
**Post-login redirect:** PLATFORM_ADMIN → `/platform/tenants`, all others → `/dashboard`.

### Auth Hooks (`src/hooks/useAuth.ts`)

```typescript
useAuth()              // full context
useIsAdmin()           // role === 'ADMIN'
useIsPlatformAdmin()   // role === 'PLATFORM_ADMIN'
useIsManager()         // MANAGER | SENIOR_MANAGER | CEO
useCanReview()         // ADMIN || user.can_review
useIngestionEnabled()  // tenant.ingestion_enabled
```

### Data Hooks (`src/hooks/useData.ts`)

~90 TanStack Query hooks covering every API resource. Pattern:

```typescript
// Read
useTimeEntries(params?)           // GET /timesheets/my
usePendingApprovals(params?)      // GET /approvals/pending
useIngestionTimesheets(params?)   // GET /api/ingestion/timesheets

// Write (invalidate related query keys on success)
useCreateTimeEntry()              // POST /timesheets
useApproveTimeEntryBatch()        // POST /approvals/batch-approve
useApproveIngestionTimesheet()    // POST /api/ingestion/timesheets/{id}/approve
```

### TypeScript Types (`src/types/index.ts`)

All backend models are mirrored as TypeScript interfaces. Key types:

```typescript
type UserRole = 'EMPLOYEE' | 'MANAGER' | 'SENIOR_MANAGER' | 'CEO' | 'ADMIN' | 'PLATFORM_ADMIN'
type TimeEntryStatus = 'DRAFT' | 'SUBMITTED' | 'APPROVED' | 'REJECTED'
type TimeOffType = 'SICK_DAY' | 'PTO' | 'HALF_DAY' | 'HOURLY_PERMISSION' | 'OTHER_LEAVE'
type IngestionStatus = 'pending' | 'under_review' | 'approved' | 'rejected' | 'on_hold'
type MailboxProtocol = 'imap' | 'pop3' | 'graph'
```

### Pages

| Page | Key Features |
|---|---|
| **LoginPage** | Email/password form, quick-login test buttons |
| **DashboardPage** | Hours KPI cards, team daily overview, analytics charts, recent activity feed |
| **MyTimePage** | Time entry grid, create/edit DRAFT entries, weekly submission, notifications |
| **ApprovalsPage** | Pending entries grouped by employee+week, batch approve/reject, history |
| **TimeOffPage** | Create/submit/track leave requests |
| **CalendarPage** | Calendar view of entries by status |
| **ProfilePage** | View/edit profile, change password, supervisor chain, direct reports |
| **AdminPage** | User CRUD, role assignment, manager assignment, project access grants |
| **ClientManagementPage** | Client → Project → Task hierarchy CRUD |
| **PlatformAdminPage** | Tenant CRUD, service token management |
| **MailboxesPage** | Mailbox CRUD, OAuth flow, connectivity test |
| **MappingsPage** | Sender mapping CRUD, reapply mappings |
| **InboxPage** | Ingestion queue, trigger fetch, reprocess skipped |
| **ReviewPanelPage** | Line item editor, LLM suggestions, anomaly panel, audit log, approve/reject/hold |

### Shared Components

| Component | Purpose |
|---|---|
| `AppLayout` | Shell: Sidebar + TopBar + Outlet |
| `Sidebar` | Role-aware nav, collapse/mobile support |
| `TopBar` | Notifications dropdown, profile menu |
| `Modal` | Overlay dialog |
| `Badge` | Status/severity pill (success/warning/danger/info) |
| `Card` | Container with header/content sections |
| `LoadingSkeleton` | Animated shimmer for async states |
| `SearchInput` | Autocomplete input with keyboard nav |
| `ChangePasswordModal` | Password change form with validation |
| `TimeEntry` | Single entry row with status-aware actions |

---

## 9. Email Ingestion Pipeline

### Overview

```
Mailbox (IMAP/POP3/Graph OAuth)
  → arq background job: fetch_emails_for_tenant
  → parse_email()            — MIME → ParsedEmail + attachments
  → classify_email()         — LLM: is this a timesheet?
  → extract_text()           — PDF/Excel/image → raw text
  → extract_timesheet_data() — LLM: structured line items
  → match_entities()         — LLM: name → User, client → Client
  → apply sender mappings    — email/domain → auto-assign
  → detect_anomalies()       — deterministic + LLM checks
  → IngestionTimesheet created (status: pending | skipped)
  → Reviewer queue (/ingestion/inbox)
  → Approve → TimeEntry records created
```

### Step Detail

**1. Fetch** — `imap.py`
- Supports IMAP, POP3, Microsoft Graph API
- OAuth2 for Google (Gmail) and Microsoft (Outlook)
- Token refresh handled automatically (5-min buffer before expiry)
- Batch size: 50 messages
- `last_fetched_at` updated per mailbox after fetch

**2. Parse** — `email_parser.py`
- Extracts: message_id, subject, sender, recipients, body_text, body_html, received_at, raw_headers
- Walks MIME tree for attachments
- Filters out signature/logo/icon images via filename heuristics
- Marks attachments as `likely_timesheet` if filename contains timesheet keywords
- Processable MIME types: PDF, Excel (xlsx/xls), CSV, JPEG, PNG, TIFF, BMP, Word docs

**3. Classify** — `llm_ingestion.classify_email()` (gpt-4o-mini)
- Returns: `{is_timesheet_email, intent, confidence, reasoning}`
- Intents: new_submission, resubmission, correction, query, unrelated
- Heuristic fallback if OpenAI unavailable

**4. Extract Text** — `extraction.py`
- **CSV/Excel:** openpyxl → xlrd fallback → tab-delimited text; detects summary pivot sheets
- **PDF:** PDFPlumber native text → pdf2image + Vision API (gpt-4o) → Tesseract OCR fallback
- **Images:** Vision API (gpt-4o) → Tesseract fallback
- Language detection via langdetect → Tesseract lang codes

**5. Extract Structured Data** — `llm_ingestion.extract_timesheet_data()` (gpt-4o)
- Returns list of timesheet objects (handles multi-sheet files):
  ```json
  {
    "employee_name": "...",
    "client_name": "...",
    "period_start": "YYYY-MM-DD",
    "period_end": "YYYY-MM-DD",
    "total_hours": 40.0,
    "line_items": [{"work_date": "...", "hours": 8.0, "description": "...", "project_code": "..."}],
    "extraction_confidence": 0.9,
    "uncertain_fields": []
  }
  ```

**6. Entity Matching** — `llm_ingestion.match_entities()`
- Fuzzy-matches extracted names against DB records (SequenceMatcher, threshold 0.5)
- Returns `{employee: {suggested_id, suggested_name, confidence}, client: {...}}`
- Only included if confidence > 0.5

**7. Sender Mappings**
- Checks `email_sender_mappings` for exact email or domain match
- Auto-populates employee_id and client_id when matched
- Overrides LLM entity matches

**8. Anomaly Detection** — `llm_ingestion.detect_anomalies()`
- Deterministic: duplicate dates, weekend work, high daily hours (>12), missing descriptions, hours mismatch
- LLM-assisted: additional anomalies from context
- Severity levels: error, warning, info
- Stored in `ingestion_timesheet.llm_anomalies`

**9. Persist**
- `IngestedEmail` created (or deduplicated by message_id + tenant_id)
- `EmailAttachment` records created, files saved to storage
- `IngestionTimesheet` + `IngestionTimesheetLineItem` records created
- Status: `pending` if enough data extracted, `skipped` with reason if not
- Skip reasons: `not_timesheet_email`, `no_attachments`, `no_candidate_attachment`, `attachment_extraction_failed`, `no_structured_timesheet_data`

**10. Review & Approval**
- Reviewer opens `/ingestion/inbox` → `/ingestion/review/:id`
- Can edit: employee, client, line items (date, hours, description, project)
- Approve → creates `TimeEntry` records (status=APPROVED, bypasses hour limits)
  - Deduplicates on `ingestion_line_item_id`
  - `time_entries_created` flag set on IngestionTimesheet
- Reject → status=rejected, reason stored
- Hold → status=on_hold, no action yet

---

## 10. Background Jobs

Powered by arq (Redis-backed). Worker started with `python run_worker.py`.

### Jobs

**`fetch_emails_for_tenant(ctx, tenant_id, mailbox_id?, job_id?)`**
- Fetches emails from all active mailboxes (or a specific one)
- Processes each through the ingestion pipeline
- Writes progress to Redis (key: `ingestion:job-status:{job_id}`, TTL 24h)
- Polled by frontend via `GET /api/ingestion/fetch-emails/status/{job_id}`

**`scheduled_fetch_emails(ctx)`**
- Triggers fetch for all tenants with `ingestion_enabled=true`
- Runs on cron: every 15 minutes (`0,15,30,45` of each hour)

**`check_and_send_reminders(ctx)`**
- Checks tenant_settings for reminder config per tenant
- Sends email reminders 3h before and at submission deadline
- Optionally locks user accounts after deadline (`lock_enabled=true`)
- Runs on cron: every 15 minutes

### Reminder Configuration (via tenant_settings keys)

| Key | Values | Description |
|---|---|---|
| `reminder_internal_enabled` | true/false | Enable employee reminders |
| `reminder_internal_deadline_day` | monday...friday/sunday | Submission deadline day |
| `reminder_internal_deadline_time` | HH:MM | Submission deadline time |
| `reminder_internal_lock_enabled` | true/false | Lock accounts after deadline |

---

## 11. Authentication & Security

### JWT Structure

```json
{
  "sub": "42",        // str(user.id) — integer ID as string
  "tenant_id": 1,     // null for PLATFORM_ADMIN
  "can_review": false
}
```

### Token Lifecycle

1. `POST /auth/login` → returns `access_token` (30 min) + `refresh_token` (7 days)
2. Frontend stores both in sessionStorage
3. Axios request interceptor adds `Authorization: Bearer {access_token}`
4. On 401 → frontend clears storage, redirects to `/login`
5. `POST /auth/refresh` → single-use rotation: old refresh token revoked, new pair returned
6. `POST /auth/logout` → refresh token revoked server-side

### Account Security

- **Lockout:** 5 failed login attempts → locked for 15 minutes (`locked_until` column)
- **Password policy:** enforced on change — min 8 chars, uppercase, lowercase, digit, special char
- **First login:** `has_changed_password=false` → frontend forces password change before access
- **Admin force-logout:** `POST /auth/admin/revoke-user-tokens/{user_id}` revokes all sessions

### Encryption

- **OAuth tokens and mailbox passwords** encrypted at rest using AES-256-GCM
- **Service tokens** stored as bcrypt hashes
- **ENCRYPTION_KEY** env var: 32-byte hex string

### Rate Limiting (slowapi)

- Login: 10 req/min
- Token refresh: 20 req/min

### Security Headers

```
X-Content-Type-Options: nosniff
X-Frame-Options: DENY
X-XSS-Protection: 1; mode=block
Referrer-Policy: strict-origin-when-cross-origin
Strict-Transport-Security: max-age=31536000 (production only)
```

---

## 12. Multi-Tenancy

Every tenanted table has `tenant_id` FK. The system enforces isolation at three levels:

**1. JWT** — `tenant_id` is embedded in the token. Clients cannot specify a different tenant — it's always derived server-side.

**2. Query level** — every list query includes `.where(Model.tenant_id == tenant_id)`.

**3. Resource fetch** — after fetching by ID, `require_same_tenant(resource.tenant_id, current_user)` raises 403 if there's a mismatch.

**PLATFORM_ADMIN** (`tenant_id = NULL`) bypasses all `require_same_tenant` checks and can see/modify any tenant's data.

### Role Access Matrix

| Role | tenant_id | Can Do |
|---|---|---|
| EMPLOYEE | required | Log own time, request time off |
| MANAGER | required | Approve direct reports |
| SENIOR_MANAGER | required | Approve managers + their reports |
| CEO | required | Approve anyone, read all tenant entries |
| ADMIN | required | Full management within tenant |
| PLATFORM_ADMIN | null | Cross-tenant superuser |

### Manager Hierarchy Rules

- EMPLOYEE can report to: MANAGER, SENIOR_MANAGER, CEO, ADMIN
- MANAGER can report to: SENIOR_MANAGER, CEO
- SENIOR_MANAGER can report to: CEO
- Department compatibility is checked and enforced
- CEO and PLATFORM_ADMIN have no manager

---

## 13. Configuration Reference

### backend/.env

```env
DATABASE_URL=postgresql+asyncpg://timesheet_user:timesheet_pass@localhost:5432/timesheet_db
SECRET_KEY=change-me-32-chars-minimum-required
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30
REFRESH_TOKEN_EXPIRE_DAYS=7
ENCRYPTION_KEY=<32-byte-hex>
REDIS_URL=redis://localhost:6379

# Time entry policies
MAX_HOURS_PER_ENTRY=24
MAX_HOURS_PER_DAY=24
MAX_HOURS_PER_WEEK=80
MIN_SUBMIT_WEEKLY_HOURS=1.0
TIME_ENTRY_BACKDATE_WEEKS=8

# Storage
STORAGE_PROVIDER=local         # or s3
STORAGE_PATH=./uploads
# S3 (if STORAGE_PROVIDER=s3):
S3_BUCKET=your-bucket
S3_REGION=us-east-1
S3_ACCESS_KEY_ID=...
S3_SECRET_ACCESS_KEY=...

# LLM (required for ingestion)
OPENAI_API_KEY=sk-...

# OAuth (required for Gmail/Outlook mailboxes)
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
GOOGLE_REDIRECT_URI=http://localhost:8000/auth/oauth/callback/google
MICROSOFT_CLIENT_ID=...
MICROSOFT_CLIENT_SECRET=...
MICROSOFT_TENANT_ID=common
MICROSOFT_REDIRECT_URI=http://localhost:8000/auth/oauth/callback/microsoft

# SMTP (optional — enables reminder emails)
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USERNAME=...
SMTP_PASSWORD=...
SMTP_FROM_ADDRESS=noreply@example.com
SMTP_USE_TLS=true

# External sync (optional)
INGESTION_PLATFORM_URL=https://...
INGESTION_SERVICE_TOKEN=...

DEBUG=false
```

### frontend/.env

```env
VITE_API_BASE_URL=http://localhost:8000
```

---

## 14. Docker & Deployment

### docker-compose.yml Services

| Service | Image | Port | Notes |
|---|---|---|---|
| db | postgres:16-alpine | 5432 | Named volume: pgdata |
| redis | redis:7-alpine | 6379 | |
| api | ./backend | 8000 | Runs init_db() then uvicorn |
| worker | ./backend | — | Same image, runs run_worker.py |
| frontend | ./frontend | 80 | nginx serves built React app |

**Startup order:** db and redis must pass health checks before api and worker start.

**Shared volumes:**
- `pgdata` — PostgreSQL data persistence
- `uploads` — shared between api and worker for local attachment storage

### backend/Dockerfile

```dockerfile
FROM python:3.12-slim
RUN apt-get install tesseract-ocr poppler-utils libpq-dev gcc  # OCR + PDF + pg
COPY requirements.txt . && pip install -r requirements.txt
COPY . .
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

The worker container uses the same image with CMD overridden in docker-compose to `python run_worker.py`.

### frontend/Dockerfile

Two-stage build:
1. `node:20-alpine` — `npm run build` with `VITE_API_BASE_URL` baked in as build arg
2. `nginx:alpine` — serves `/dist` with SPA fallback and 1-year asset caching

### Environment Overrides

```bash
# Custom ports
POSTGRES_PORT=5433 BACKEND_PORT=8080 FRONTEND_PORT=8081 docker-compose up

# Custom API URL baked into frontend
VITE_API_BASE_URL=https://api.mycompany.com docker-compose up
```

---

## 15. Database Migrations

Alembic with async engine. Migration files in `backend/alembic/versions/`.

```bash
cd backend
alembic upgrade head                         # Apply all migrations
alembic downgrade -1                         # Roll back one
alembic revision --autogenerate -m "desc"    # Generate new migration

# For existing DBs without migration history:
alembic stamp 001_baseline_schema
alembic upgrade head
```

### Migration History

| # | Description |
|---|---|
| 001 | Baseline schema — users, clients, projects, tasks, time_entries, time_off_requests |
| 002 | Multi-tenancy — tenants table, tenant_id on all tables, PLATFORM_ADMIN role |
| 003 | Ingestion sync — sync_log, service_tokens, external sync ID columns |
| 004 | Activity log table |
| 005 | ingestion_enabled flag on tenants |
| 006 | can_review and is_external flags on users |
| 007 | Full ingestion tables — mailboxes, ingested_emails, email_attachments, ingestion_timesheets, line_items, audit_log, sender_mappings |
| 008 | graph protocol added to mailboxprotocol enum (Microsoft Graph) |
| 009 | Line item rejection fields |
| 010 | tenant_settings table + timesheet_locked fields on users |
| 011 | Account lockout fields on users (failed_login_attempts, locked_until) |
| 012 | refresh_tokens table |

**Note:** Alembic env.py uses `asyncio.run()` + `run_sync` — never run standard sync Alembic commands outside the configured env.py.
