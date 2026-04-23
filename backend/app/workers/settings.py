"""
arq worker configuration.
Defines which job functions are available and worker behaviour.
"""

import logging
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

try:
    from arq.connections import RedisSettings
except ModuleNotFoundError:
    class RedisSettings:  # type: ignore[override]
        def __init__(self, **kwargs):
            self.kwargs = kwargs

from app.core.config import settings
from app.workers.email_fetch import fetch_emails_for_tenant, scheduled_fetch_emails
from app.workers.license_verify_worker import reverify_license
from app.workers.reminder_worker import check_and_send_reminders

try:
    from arq import cron
except ImportError:
    def cron(*args, **kwargs):  # type: ignore[misc]
        return None


def get_redis_settings() -> RedisSettings:
    """Parse REDIS_URL into arq RedisSettings."""
    try:
        parsed = urlparse(settings.redis_url)
        host = parsed.hostname or "localhost"
        port = parsed.port or 6379
        password = parsed.password or None
        database = int(parsed.path.lstrip("/") or 0)
        return RedisSettings(
            host=host,
            port=port,
            password=password,
            database=database,
        )
    except Exception as exc:
        logger.warning("Failed to parse REDIS_URL '%s', falling back to localhost:6379: %s", settings.redis_url, exc)
        return RedisSettings(host="localhost", port=6379)


def _parse_cron_minutes() -> set[int]:
    """Parse WORKER_CRON_MINUTES from settings into a set of ints."""
    try:
        return {int(m.strip()) for m in settings.worker_cron_minutes.split(",") if m.strip()}
    except (ValueError, AttributeError) as exc:
        logger.warning("Invalid WORKER_CRON_MINUTES '%s', falling back to {0,15,30,45}: %s", settings.worker_cron_minutes, exc)
        return {0, 15, 30, 45}


_cron_minutes = _parse_cron_minutes()
logger.info("Worker cron schedule: minute=%s  job_timeout=%s  max_tries=%s",
            _cron_minutes, settings.worker_job_timeout, settings.worker_max_tries)


class WorkerSettings:
    """arq WorkerSettings discovered by the worker runtime."""

    functions = [
        fetch_emails_for_tenant,
        check_and_send_reminders,
        scheduled_fetch_emails,
        reverify_license,
    ]
    redis_settings = get_redis_settings()
    job_timeout = settings.worker_job_timeout
    max_tries = settings.worker_max_tries
    keep_result = settings.worker_keep_result
    health_check_interval = 30
    log_results = True
    cron_jobs = [
        cron(check_and_send_reminders, minute=_cron_minutes),
        cron(scheduled_fetch_emails, minute=_cron_minutes),
        cron(reverify_license, hour=0, minute=0),
    ]
