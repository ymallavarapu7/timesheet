# Acufy AI - Timesheet Operations

A full-stack, multi-tenant timesheet management platform built for IT consulting firms. Features AI-powered email ingestion, natural language time entry, role-based approval workflows, and comprehensive project/client management.

## Tech Stack

| Layer | Technology |
|---|---|
| **Frontend** | React 18, TypeScript, TanStack Query, Tailwind CSS, shadcn/ui, Vite |
| **Backend** | Python, FastAPI, SQLAlchemy 2.0 (async), Pydantic v2 |
| **Database** | PostgreSQL 16 (asyncpg) |
| **Background Jobs** | arq + Redis 7 |
| **AI/LLM** | OpenAI (email extraction, natural language parsing) |
| **Auth** | JWT (access + refresh tokens), bcrypt, OAuth 2.0 (Google, Microsoft) |
| **Infrastructure** | Docker Compose, Alembic migrations, S3-compatible storage |

## Features

- **Time Entry** — Grid-based logging with natural language input powered by AI
- **Approval Workflows** — Multi-level approval chain (Employee → Manager → Senior Manager)
- **Email Ingestion** — Connect Gmail/Outlook via OAuth, auto-extract timesheets from emails using LLM
- **Review Queue** — Review and approve AI-extracted timesheet data before syncing
- **Time Off Management** — PTO, sick days, half days, and hourly permissions
- **Calendar View** — Weekly and monthly visualization of logged time
- **Client & Project Management** — Organize work by client, project, and task
- **Multi-Tenancy** — Full tenant isolation with role-based access control
- **Dashboard & Analytics** — Summary cards, team overview, and date-range reporting
- **Dark/Light Mode** — Theme toggle with persistence

## User Roles

| Role | Access |
|---|---|
| `EMPLOYEE` | Own time entries |
| `MANAGER` | Approve direct reports |
| `SENIOR_MANAGER` | Approve managers and employees |
| `CEO` | Read-only access to all tenant entries |
| `ADMIN` | Full management within tenant |
| `PLATFORM_ADMIN` | Cross-tenant superuser |

## Getting Started

### Prerequisites

- Python 3.11+
- Node.js 18+
- PostgreSQL 16
- Redis 7

### Backend

```bash
cd backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
alembic upgrade head

uvicorn app.main:app --reload  # http://localhost:8000
```

### Frontend

```bash
cd frontend
npm install
npm run dev    # http://localhost:5174
```

### Docker Compose

```bash
docker compose up --build
```

Starts all services — PostgreSQL, Redis, API server, background worker, and frontend.

| Service | Port |
|---|---|
| Frontend | 3000 |
| API | 8081 |
| PostgreSQL | 5432 |
| Redis | 6379 |

## Environment Variables

Configure the `.env` files before running:

- **`backend/.env`** — Database URL, JWT secrets, Redis URL, OpenAI API key, OAuth credentials, encryption key
- **`frontend/.env`** — `VITE_API_BASE_URL` (defaults to `http://localhost:8000`)

## Project Structure

```
backend/
  app/
    api/          # FastAPI route handlers
    core/         # Config, dependencies, security
    models/       # SQLAlchemy ORM models
    schemas/      # Pydantic request/response schemas
    crud/         # Async database operations
    services/     # Business logic (ingestion, LLM, IMAP, encryption)
    workers/      # arq background job handlers

frontend/
  src/
    api/          # Axios API clients
    components/   # UI components (shadcn/ui wrappers, layout)
    contexts/     # Auth & theme context providers
    hooks/        # TanStack Query hooks
    pages/        # Route-level page components
    types/        # TypeScript interfaces
```

## Testing

```bash
# Backend
cd backend && pytest

# Frontend
cd frontend && npm run test
```

## Documentation

- [User Guide](docs/USER_GUIDE.md) — End-user documentation with role workflows and feature walkthroughs
- [API Docs](http://localhost:8000/docs) — Swagger UI (available when backend is running)
