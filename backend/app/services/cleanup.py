"""Keeps the shared demo database small: after every N activities (offer letters added or
comparisons run) all stored offers are deleted and the count starts again."""
from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Counter, Offer

COUNTER = "activity_since_cleanup"


def record_activity(db: Session) -> bool:
    """Count one activity. Returns True if this activity triggered a cleanup.
    The caller commits; call before creating a new offer so that offer survives the wipe."""
    if settings.cleanup_every <= 0:
        return False
    counter = db.get(Counter, COUNTER) or Counter(name=COUNTER, value=0)
    db.add(counter)
    counter.value += 1
    if counter.value < settings.cleanup_every:
        return False
    db.execute(delete(Offer))
    counter.value = 0
    return True
