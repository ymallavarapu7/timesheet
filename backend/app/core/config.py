import json
import os
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

ENV_FILE = Path(__file__).resolve().parents[2] / ".env"
ENV_FIELD_MAP = {
    "database_url": "DATABASE_URL",
    "secret_key": "SECRET_KEY",
    "algorithm": "ALGORITHM",
    "access_token_expire_minutes": "ACCESS_TOKEN_EXPIRE_MINUTES",
    "refresh_token_expire_days": "REFRESH_TOKEN_EXPIRE_DAYS",
    "cors_origins": "CORS_ORIGINS",
    "debug": "DEBUG",
    "backend_host": "BACKEND_HOST",
    "backend_port": "BACKEND_PORT",
    "max_hours_per_entry": "MAX_HOURS_PER_ENTRY",
    "max_hours_per_day": "MAX_HOURS_PER_DAY",
    "max_hours_per_week": "MAX_HOURS_PER_WEEK",
    "min_submit_weekly_hours": "MIN_SUBMIT_WEEKLY_HOURS",
    "time_entry_backdate_weeks": "TIME_ENTRY_BACKDATE_WEEKS",
    "ingestion_platform_url": "INGESTION_PLATFORM_URL",
    "ingestion_service_token": "INGESTION_SERVICE_TOKEN",
    "storage_provider": "STORAGE_PROVIDER",
    "storage_path": "STORAGE_PATH",
    "s3_bucket": "S3_BUCKET",
    "s3_region": "S3_REGION",
    "s3_access_key": "S3_ACCESS_KEY",
    "s3_secret_key": "S3_SECRET_KEY",
    "encryption_key": "ENCRYPTION_KEY",
    "openai_api_key": "OPENAI_API_KEY",
    "google_client_id": "GOOGLE_CLIENT_ID",
    "google_client_secret": "GOOGLE_CLIENT_SECRET",
    "google_redirect_uri": "GOOGLE_REDIRECT_URI",
    "microsoft_client_id": "MICROSOFT_CLIENT_ID",
    "microsoft_client_secret": "MICROSOFT_CLIENT_SECRET",
    "microsoft_tenant_id": "MICROSOFT_TENANT_ID",
    "microsoft_redirect_uri": "MICROSOFT_REDIRECT_URI",
    "redis_url": "REDIS_URL",
    "smtp_host": "SMTP_HOST",
    "smtp_port": "SMTP_PORT",
    "smtp_username": "SMTP_USERNAME",
    "smtp_password": "SMTP_PASSWORD",
    "smtp_from_address": "SMTP_FROM_ADDRESS",
    "smtp_from_name": "SMTP_FROM_NAME",
    "smtp_use_tls": "SMTP_USE_TLS",
    "frontend_base_url": "FRONTEND_BASE_URL",
    # Worker / email fetch schedule
    "worker_cron_minutes": "WORKER_CRON_MINUTES",
    "worker_job_timeout": "WORKER_JOB_TIMEOUT",
    "worker_max_tries": "WORKER_MAX_TRIES",
    "worker_keep_result": "WORKER_KEEP_RESULT",
    "email_fetch_interval_minutes": "EMAIL_FETCH_INTERVAL_MINUTES",
    "email_fetch_days": "EMAIL_FETCH_DAYS",
    "email_fetch_start_time": "EMAIL_FETCH_START_TIME",
    "email_fetch_end_time": "EMAIL_FETCH_END_TIME",
    "email_fetch_initial_days": "EMAIL_FETCH_INITIAL_DAYS",
    "DEPLOYMENT_MODE": "DEPLOYMENT_MODE",
    "LICENSE_KEY": "LICENSE_KEY",
    "LICENSE_API_URL": "LICENSE_API_URL",
    "LICENSE_PHONE_HOME_INTERVAL_HOURS": "LICENSE_PHONE_HOME_INTERVAL_HOURS",
    "LICENSE_GRACE_PERIOD_DAYS": "LICENSE_GRACE_PERIOD_DAYS",
    "LICENSE_SIGNING_KEY_PEM": "LICENSE_SIGNING_KEY_PEM",
    "LICENSE_PUBLIC_KEY_PEM": "LICENSE_PUBLIC_KEY_PEM",
    "LICENSE_SERVER_HASH_SALT": "LICENSE_SERVER_HASH_SALT",
    "LICENSE_VALIDATE_TOKEN": "LICENSE_VALIDATE_TOKEN",
}


def _read_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}

    values: dict[str, str] = {}
    for line in path.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue

        key, value = stripped.split("=", 1)
        values[key.strip()] = value.strip()

    return values


def _coerce_debug(value: Any) -> bool:
    if isinstance(value, bool):
        return value

    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on", "debug", "dev", "development"}:
            return True
        if normalized in {"0", "false", "no", "off", "release", "prod", "production"}:
            return False

    return bool(value)


def _coerce_cors_origins(value: Any) -> list[str] | Any:
    if isinstance(value, list):
        return value

    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return []
        if stripped.startswith("["):
            return json.loads(stripped)
        return [item.strip() for item in stripped.split(",") if item.strip()]

    return value


class Settings(BaseModel):
    """Application configuration from environment variables."""

    # Database
    database_url: str = Field(
        default="postgresql+asyncpg://timesheet_user:timesheet_pass@localhost:5432/timesheet_db",
        description="PostgreSQL connection URL"
    )

    # JWT
    secret_key: str = Field(
        default="",
        description="Secret key for JWT signing. Must be set via SECRET_KEY env var."
    )
    algorithm: str = Field(
        default="HS256",
        description="JWT algorithm"
    )
    access_token_expire_minutes: int = Field(
        default=30,
        description="Access token expiration time in minutes"
    )
    refresh_token_expire_days: int = Field(
        default=7,
        description="Refresh token expiration time in days"
    )

    # CORS
    cors_origins: list[str] = Field(
        default=[
            "http://localhost:5173",
            "http://localhost:5174",
            "http://localhost:5175",
            "http://127.0.0.1:5173",
            "http://127.0.0.1:5174",
            "http://127.0.0.1:5175",
            "http://localhost:3000",
            "http://127.0.0.1:3000",
        ],
        description="Allowed CORS origins"
    )

    # Application
    debug: bool = Field(
        default=True,
        description="Enable debug mode; accepts booleans and legacy env values like debug/release"
    )
    backend_host: str = Field(
        default="127.0.0.1",
        description="Backend server host"
    )
    backend_port: int = Field(
        default=8000,
        description="Backend server port"
    )

    # Time entry policies
    max_hours_per_entry: float = Field(
        default=24.0,
        description="Maximum hours allowed per single time entry"
    )
    max_hours_per_day: float = Field(
        default=24.0,
        description="Maximum total hours allowed per user per day (guards against data entry errors; real policy is enforced during approval)"
    )
    max_hours_per_week: float = Field(
        default=80.0,
        description="Maximum total hours allowed per user per week (guards against data entry errors; real policy is enforced during approval)"
    )
    min_submit_weekly_hours: float = Field(
        default=1.0,
        description="Minimum weekly hours required to submit entries for a week"
    )
    time_entry_backdate_weeks: int = Field(
        default=8,
        description="How many weeks in the past a time entry can be logged"
    )

    # Ingestion Platform integration (for outbound webhooks)
    ingestion_platform_url: str = Field(
        default="",
        description="Base URL of the ingestion platform, e.g. http://localhost:3000. Leave empty to disable outbound webhooks."
    )
    ingestion_service_token: str = Field(
        default="",
        description="Service token issued by the ingestion platform for outbound webhook auth."
    )

    # File storage
    storage_provider: str = Field(
        default="local",
        description="Storage backend for attachments: local or s3."
    )
    storage_path: str = Field(
        default="./uploads",
        description="Base path for local attachment storage."
    )
    s3_bucket: str = Field(
        default="",
        description="S3 bucket name when STORAGE_PROVIDER=s3."
    )
    s3_region: str = Field(
        default="",
        description="S3 region when STORAGE_PROVIDER=s3."
    )
    s3_access_key: str = Field(
        default="",
        description="S3 access key when STORAGE_PROVIDER=s3."
    )
    s3_secret_key: str = Field(
        default="",
        description="S3 secret key when STORAGE_PROVIDER=s3."
    )

    # Encryption and LLM
    encryption_key: str = Field(
        default="",
        description="32-byte hex key used for AES-256-GCM encryption."
    )
    openai_api_key: str = Field(
        default="",
        description="OpenAI API key used for extraction/classification features."
    )

    # Google OAuth2
    google_client_id: str = Field(
        default="",
        description="Google OAuth client ID for Gmail mailbox connections."
    )
    google_client_secret: str = Field(
        default="",
        description="Google OAuth client secret for Gmail mailbox connections."
    )
    google_redirect_uri: str = Field(
        default="http://localhost:8000/auth/oauth/callback/google",
        description="Google OAuth redirect URI."
    )

    # Microsoft OAuth2
    microsoft_client_id: str = Field(
        default="",
        description="Microsoft OAuth client ID for Outlook mailbox connections."
    )
    microsoft_client_secret: str = Field(
        default="",
        description="Microsoft OAuth client secret for Outlook mailbox connections."
    )
    microsoft_tenant_id: str = Field(
        default="common",
        description="Microsoft tenant ID for OAuth token refresh."
    )
    microsoft_redirect_uri: str = Field(
        default="http://localhost:8000/auth/oauth/callback/microsoft",
        description="Microsoft OAuth redirect URI."
    )

    # Redis / arq
    redis_url: str = Field(
        default="redis://localhost:6379",
        description="Redis connection URL for arq background jobs."
    )

    # SMTP / outbound email
    smtp_host: str = Field(default="", description="SMTP server hostname for outbound notifications")
    smtp_port: int = Field(default=587, description="SMTP server port")
    smtp_username: str = Field(default="", description="SMTP auth username")
    smtp_password: str = Field(default="", description="SMTP auth password")
    smtp_from_address: str = Field(default="no-reply@acufy.ai", description="From address for outbound emails")
    smtp_from_name: str = Field(default="Acufy Platform", description="From name for outbound emails")
    smtp_use_tls: bool = Field(default=True, description="Use STARTTLS for SMTP")

    # Frontend
    frontend_base_url: str = Field(
        default="http://localhost:5174",
        description="Base URL of the frontend app, used to build email verification links."
    )

    # Worker / email fetch schedule
    worker_cron_minutes: str = Field(
        default="0,5,10,15,20,25,30,35,40,45,50,55",
        description="Comma-separated minutes when arq cron tasks fire (e.g. '0,5,10,...,55' = every 5 min)."
    )
    worker_job_timeout: int = Field(
        default=300,
        description="Timeout in seconds for each arq background job."
    )
    worker_max_tries: int = Field(
        default=3,
        description="Maximum retry attempts for a failed arq job."
    )
    worker_keep_result: int = Field(
        default=86400,
        description="Seconds to keep job results in Redis (default 24 hours)."
    )
    email_fetch_interval_minutes: int = Field(
        default=60,
        description="Default interval (minutes) between auto email fetches per tenant."
    )
    email_fetch_days: str = Field(
        default="mon,tue,wed,thu,fri",
        description="Default days of the week for auto email fetch (comma-separated)."
    )
    email_fetch_start_time: str = Field(
        default="00:00",
        description="Default start time (HH:MM) for the auto fetch window."
    )
    email_fetch_end_time: str = Field(
        default="23:59",
        description="Default end time (HH:MM) for the auto fetch window."
    )
    email_fetch_initial_days: int = Field(
        default=30,
        description="On first fetch (no cursor), only fetch emails from this many days back."
    )

    # Licensing / deployment mode
    DEPLOYMENT_MODE: str = Field(
        default="saas",
        description="Deployment mode: saas or self_hosted."
    )
    LICENSE_KEY: str = Field(
        default="",
        description="Signed self-hosted license JWT."
    )
    LICENSE_API_URL: str = Field(
        default="https://licenses.yourdomain.com",
        description="Base URL of the licensing API."
    )
    LICENSE_PHONE_HOME_INTERVAL_HOURS: int = Field(
        default=720,
        description="How often the worker re-verifies the license with the licensing API."
    )
    LICENSE_GRACE_PERIOD_DAYS: int = Field(
        default=7,
        description="Grace period after failed online license validation."
    )
    LICENSE_SIGNING_KEY_PEM: str = Field(
        default="",
        description="PEM-encoded RSA private key used only by the issuing server."
    )
    LICENSE_PUBLIC_KEY_PEM: str = Field(
        default="",
        description="PEM-encoded RSA public key used by all deployments for local validation."
    )
    LICENSE_SERVER_HASH_SALT: str = Field(
        default="",
        description="Secret salt used when computing the license server hash."
    )
    LICENSE_VALIDATE_TOKEN: str = Field(
        default="",
        description="Optional shared secret fallback for the validate endpoint."
    )

    @classmethod
    def load(cls) -> "Settings":
        env_file_values = _read_env_file(ENV_FILE)
        values: dict[str, Any] = {}

        for field_name, env_name in ENV_FIELD_MAP.items():
            raw_value = os.environ.get(env_name, env_file_values.get(env_name))
            if raw_value is None:
                continue

            if field_name == "debug":
                values[field_name] = _coerce_debug(raw_value)
                continue

            if field_name == "smtp_use_tls":
                values[field_name] = _coerce_debug(raw_value)
                continue

            if field_name == "cors_origins":
                values[field_name] = _coerce_cors_origins(raw_value)
                continue

            values[field_name] = raw_value

        return cls(**values)


settings = Settings.load()

# ── Startup safety checks ───────────────────────────────────────────
_INSECURE_KEYS = {"", "dev-secret-key-change-in-production", "changeme", "secret"}

if settings.secret_key in _INSECURE_KEYS:
    if settings.debug:
        import warnings
        settings.secret_key = "dev-secret-key-DO-NOT-USE-IN-PRODUCTION"
        warnings.warn(
            "SECRET_KEY is not set — using an insecure default. "
            "Set SECRET_KEY in your environment before deploying to production.",
            stacklevel=1,
        )
    else:
        raise RuntimeError(
            "SECRET_KEY is not set or is insecure. "
            "Set a strong SECRET_KEY (>= 32 characters) via environment variable."
        )
