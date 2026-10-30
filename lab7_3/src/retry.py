import random
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime


def classify(status=None, error=None):
    if error:
        return "network", True
    if status == 429:
        return "rate_limit", True
    if status and 500 <= status < 600:
        return "server", True
    if status == 403:
        return "blocked", False
    if status == 401:
        return "auth", False
    if status and 400 <= status < 500:
        return "client", False
    return "ok", False


def retry_delay(value, attempt, now=None):
    if value:
        try:
            return max(0, float(value)), "Retry-After"
        except ValueError:
            try:
                return (
                    max(
                        0,
                        (
                            parsedate_to_datetime(value)
                            - (now or datetime.now(timezone.utc))
                        ).total_seconds(),
                    ),
                    "Retry-After",
                )
            except (ValueError, TypeError, OverflowError):
                pass
    return random.uniform(0, min(4, 0.5 * 2 ** (attempt - 1))), "backoff"
