from collections import defaultdict, deque
from dataclasses import dataclass
from threading import Lock
from time import time
from typing import Deque, Dict

WINDOW_SECONDS = 60
MAX_REQUESTS_PER_WINDOW = 5
MIN_INTERVAL_SECONDS = 3


@dataclass
class RateLimitExceeded(Exception):
    message: str
    retry_after: int


_requests: Dict[str, Deque[float]] = defaultdict(deque)
_lock = Lock()


def assert_feedback_rate_limit(identity: str) -> None:
    now = time()

    with _lock:
        queue = _requests[identity]

        while queue and now - queue[0] > WINDOW_SECONDS:
            queue.popleft()

        if queue and now - queue[-1] < MIN_INTERVAL_SECONDS:
            retry_after = max(1, int(MIN_INTERVAL_SECONDS - (now - queue[-1])))
            raise RateLimitExceeded(message="请求过于频繁，请稍后重试", retry_after=retry_after)

        if len(queue) >= MAX_REQUESTS_PER_WINDOW:
            retry_after = max(1, int(WINDOW_SECONDS - (now - queue[0])))
            raise RateLimitExceeded(message="提交次数过多，请稍后再试", retry_after=retry_after)

        queue.append(now)
