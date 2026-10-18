"""A main-thread wall clock guard also bounds coordinator and Git overhead."""
from contextlib import contextmanager
import signal
import threading
import time
from .workspace import SafetyError


@contextmanager
def wall_deadline(deadline):
    if threading.current_thread() is not threading.main_thread():
        raise SafetyError('execution requires the main thread for hard elapsed enforcement')
    remaining = deadline - time.time()
    if remaining <= 0:
        raise SafetyError('objective elapsed limit reached')
    previous = signal.getsignal(signal.SIGALRM)
    previous_timer = signal.getitimer(signal.ITIMER_REAL)
    if previous_timer[0]:
        raise SafetyError('an existing process timer prevents exclusive elapsed enforcement')
    def expired(signum, frame):
        raise SafetyError('objective elapsed limit reached')
    signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, remaining)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)
