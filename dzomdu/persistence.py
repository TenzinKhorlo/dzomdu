"""Serialize meeting-note and record mutations within this local app instance."""

from functools import wraps
from threading import RLock

MEETING_LOCK = RLock()


def meeting_locked(function):
    @wraps(function)
    def locked(*args, **kwargs):
        with MEETING_LOCK:
            return function(*args, **kwargs)

    return locked
