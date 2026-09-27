"""Optional error tracking (Sentry), enabled purely by configuration.

No DSN -> no import, no overhead, no behavioral difference. Both the API
process and the Celery worker call init_sentry() at startup; the same DSN
covers request handlers and background tasks.
"""

from app import __version__
from app.core.config import Settings
from app.core.logging import get_logger

log = get_logger("core.observability")


def init_sentry(settings: Settings) -> bool:
    if not settings.sentry_dsn:
        return False
    try:
        import sentry_sdk
    except ImportError:  # pragma: no cover - dependency ships in the image
        log.warning("sentry_dsn_set_but_sdk_missing")
        return False
    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.app_env,
        release=__version__,
        # Error tracking only by default; tracing is opt-in and sampled.
        traces_sample_rate=settings.sentry_traces_sample_rate,
        send_default_pii=False,
    )
    log.info("sentry_initialized", environment=settings.app_env)
    return True
