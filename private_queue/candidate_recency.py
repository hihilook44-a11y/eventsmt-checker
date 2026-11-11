"""Source-time ordering and freshness guard for new Shorts."""
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

MAX_SHORT_AGE = timedelta(hours=24)
FUTURE_TOLERANCE = timedelta(minutes=5)

def source_time(item):
    value = item.get('created_at')
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        try:
            parsed = datetime.fromisoformat(value.strip().replace('Z', '+00:00'))
        except ValueError:
            parsed = parsedate_to_datetime(value.strip())
        if parsed.tzinfo is None:
            return None
        return parsed.astimezone(timezone.utc)
    except (ValueError, TypeError, OverflowError):
        return None

def newest_first(items):
    # Stable ties and unknown timestamps last; never alter the encrypted queue.
    minimum = datetime.min.replace(tzinfo=timezone.utc)
    return sorted(items, key=lambda item: source_time(item) or minimum, reverse=True)

def recent_short(item, now=None):
    when = source_time(item)
    now = now or datetime.now(timezone.utc)
    return when is not None and now - MAX_SHORT_AGE <= when <= now + FUTURE_TOLERANCE
