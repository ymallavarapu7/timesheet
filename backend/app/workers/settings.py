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


class WorkerSettings:
    """arq WorkerSettings discovered by the worker runtime."""

    functions = [fetch_emails_for_tenant, check_and_send_reminders, scheduled_fetch_emails]
    redis_settings = get_redis_settings()
    job_timeout = 300
    max_tries = 3
    keep_result = 86400
    health_check_interval = 30
    log_results = True
    cron_jobs = [
        cron(check_and_send_reminders, minute={0, 15, 30, 45}),
        cron(scheduled_fetch_emails, minute={0, 15, 30, 45}),
    ]
