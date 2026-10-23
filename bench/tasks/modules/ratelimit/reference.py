class RetryError(Exception):
    def __init__(self, last, attempts):
        super().__init__(f"gave up after {attempts} attempts: {last!r}")
        self.last = last
        self.attempts = attempts
        self.__cause__ = last


def retry(fn, *, clock, attempts=3, base_delay=1.0, factor=2.0, max_delay=30.0, deadline=None,
          retry_on=(Exception,), jitter=None):
    if attempts < 1:
        raise ValueError("attempts must be at least 1")
    start = clock.now()
    made = 0
    while True:
        made += 1
        try:
            return fn()
        except tuple(retry_on) as exc:
            last = exc
        if made >= attempts:
            raise RetryError(last, made)
        wait = min(max_delay, base_delay * factor ** (made - 1))
        if jitter is not None:
            wait = jitter(wait)
        if deadline is not None and clock.now() + wait > start + deadline:
            raise RetryError(last, made)
        clock.sleep(wait)


class TokenBucket:
    def __init__(self, rate, capacity, clock):
        if rate <= 0 or capacity <= 0:
            raise ValueError("rate and capacity must be positive")
        self.rate, self.capacity, self.clock = rate, capacity, clock
        self.tokens = float(capacity)
        self.updated = clock.now()

    def _refill(self):
        now = self.clock.now()
        self.tokens = min(self.capacity, self.tokens + (now - self.updated) * self.rate)
        self.updated = now

    def _check(self, n):
        if not 0 < n <= self.capacity:
            raise ValueError(f"n must be in (0, {self.capacity}]")

    def available(self):
        self._refill()
        return self.tokens

    def try_take(self, n=1):
        self._check(n)
        self._refill()
        if self.tokens >= n:
            self.tokens -= n
            return True
        return False

    def take(self, n=1):
        self._check(n)
        self._refill()
        wait = 0.0
        if self.tokens < n:
            wait = (n - self.tokens) / self.rate
            self.clock.sleep(wait)
            self._refill()
        self.tokens = max(0.0, self.tokens - n)
        return wait
