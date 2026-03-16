import time
from threading import Event


def sleep_with_stop(stop_event: Event, seconds: int | float) -> bool:
    """Sleep in small chunks. Return True if interrupted."""
    end_time = time.time() + float(seconds)
    while time.time() < end_time:
        if stop_event.is_set():
            return True
        time.sleep(min(0.25, end_time - time.time()))
    return stop_event.is_set()
