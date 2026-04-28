import logging

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from app.core.config import settings
from app.core.permissions import shadow_check
from app.core.rate_limit import limiter
from app.db import AsyncSessionLocal, init_db, close_db
from app.api import (
    approvals,
    auth,
    clients,
    dashboard,
    departments,
    ingestion,
    leave_types,
    mailboxes,
    notifications,
    platform_settings,
    projects,
    sync,
    tasks,
    tenants,
    time_off,
    time_off_approvals,
    timesheets,
    users,
)
from app.models.mailbox import Mailbox  # noqa: F401
from app.models.ingested_email import IngestedEmail  # noqa: F401
from app.models.email_attachment import EmailAttachment  # noqa: F401
from app.models.ingestion_timesheet import (  # noqa: F401
    IngestionTimesheet,
    IngestionTimesheetLineItem,
    IngestionAuditLog,
)
from app.models.tenant import Tenant  # noqa: F401 — registers Tenant with Base.metadata
from app.models.tenant_settings import TenantSettings  # noqa: F401
from app.models.platform_settings import PlatformSettings  # noqa: F401
from app.models.user import UserRole

logger = logging.getLogger(__name__)

# Lifespan handler for startup/shutdown


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await init_db()
    print("[OK] Database initialized")
    yield
    # Shutdown
    await close_db()
    print("[OK] Database connection closed")


# Create FastAPI app
app = FastAPI(
    title="Timesheet API",
    description="Time tracking and approval system for IT consulting",
    version="1.0.0",
    lifespan=lifespan,
)

# Rate limiting
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Configure CORS — explicitly list allowed methods and headers
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=[
        "Authorization",
        "Content-Type",
        "X-Service-Token",
        "X-Tenant-ID",
    ],
)


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response: Response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    if not settings.debug:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    # Default Content-Security-Policy: lock down what the API can serve.
    # The API is a JSON service for the most part; the only HTML it renders
    # is the OAuth popup at /auth/oauth/callback/{provider}, which sets a
    # relaxed policy for itself (inline script needed to postMessage back
    # to the opener). Any other endpoint that ever returns HTML inherits
    # this strict default unless it explicitly overrides.
    if "content-security-policy" not in {h.lower() for h in response.headers}:
        response.headers["Content-Security-Policy"] = (
            "default-src 'none'; "
            "frame-ancestors 'none'; "
            "base-uri 'none'; "
            "form-action 'none'"
        )
    return response


@app.middleware("http")
async def shadow_pending_approvals_permission_check(request: Request, call_next):
    response: Response = await call_next(request)

    if request.method != "GET" or request.url.path != "/approvals/pending":
        return response
    if response.status_code >= 400:
        return response

    current_user = getattr(request.state, "current_user", None)
    if current_user is None:
        return response

    permission = (
        "time_entry.approve_any"
        if current_user.role == UserRole.CEO
        else "time_entry.approve"
    )
    try:
        async with AsyncSessionLocal() as db:
            await shadow_check(
                db,
                current_user,
                permission,
                old_decision=True,
                context="GET /approvals/pending",
            )
    except Exception as exc:  # pragma: no cover - defensive only
        logger.error("shadow middleware failed for approvals pending: %s", exc)

    return response

# Include routers
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(clients.router)
app.include_router(departments.router)
app.include_router(leave_types.router)
app.include_router(projects.router)
app.include_router(tasks.router)
app.include_router(timesheets.router)
app.include_router(approvals.router)
app.include_router(time_off.router)
app.include_router(time_off_approvals.router)
app.include_router(dashboard.router)
app.include_router(notifications.router)
app.include_router(tenants.router)
app.include_router(platform_settings.router)
app.include_router(sync.router)
app.include_router(mailboxes.router, prefix="/api")
app.include_router(mailboxes.oauth_router)
app.include_router(ingestion.router, prefix="/api")


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "ok"}


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "name": "Timesheet API",
        "version": "1.0.0",
        "docs": "/docs",
        "openapi": "/openapi.json",
    }
