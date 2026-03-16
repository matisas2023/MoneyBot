from __future__ import annotations

import time
from threading import Event


def sleep_interruptible(stop_event: Event, seconds: float) -> bool:
    """Sleep with periodic interruption checks. Returns True if interrupted."""
    end_time = time.monotonic() + max(0.0, seconds)
    while time.monotonic() < end_time:
        if stop_event.is_set():
            return True
        remaining = end_time - time.monotonic()
        time.sleep(min(0.25, max(0.0, remaining)))
    return stop_event.is_set()
