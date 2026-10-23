Write a Python module with a retry helper and a token-bucket rate limiter for calls to a slow local
server. Both take a clock so tests can control time.

## Clock

A clock is any object with `now() -> float` (seconds) and `sleep(seconds: float) -> None`. The module
never reads the real time or sleeps on its own; it only uses the clock it is given.

## retry

`retry(fn, *, clock, attempts=3, base_delay=1.0, factor=2.0, max_delay=30.0, deadline=None,
retry_on=(Exception,), jitter=None)` calls `fn()` with no arguments and returns its result.

- `attempts` is the total number of calls allowed, at least 1; below 1 raises `ValueError` before
  calling `fn`.
- If `fn` raises an exception that is an instance of one of the classes in `retry_on`, and calls remain,
  wait and call again. Any other exception propagates unchanged at once.
- The wait before retry number k (k = 1 for the second call) is `min(max_delay, base_delay * factor **
  (k - 1))`. If `jitter` is given, it is a function called with that number, and its return value is
  the wait instead.
- If `deadline` is given (seconds), the time limit is `start + deadline`, where `start` is `clock.now()`
  read once just before the first call. Before waiting, if `clock.now() + wait` would be later than the
  time limit, stop retrying.
- Waiting is one `clock.sleep(wait)` call.
- When it stops retrying (calls used up, or the deadline), raise `RetryError`. `RetryError` is an
  `Exception` subclass defined in the module, with attributes `last` (the last exception `fn` raised)
  and `attempts` (how many calls were made), and its `__cause__` is `last`.

## TokenBucket

`TokenBucket(rate, capacity, clock)`: `rate` tokens are added per second, continuously, up to
`capacity`. The bucket starts full. `rate` and `capacity` must be greater than 0, otherwise
`ValueError`.

- `available() -> float`: the tokens in the bucket now (after adding what has accumulated since the
  last update).
- `try_take(n=1) -> bool`: if at least `n` tokens are available, remove them and return `True`;
  otherwise change nothing and return `False`.
- `take(n=1) -> float`: remove `n` tokens, first waiting with one `clock.sleep(wait)` call if needed,
  where `wait` is exactly the time until `n` tokens are available. Return the time waited (0.0 if there
  was no need to wait, and in that case do not call `sleep`).
- For `try_take` and `take`, `n` must be greater than 0 and at most `capacity`, otherwise `ValueError`.
- Tokens are fractional: after 0.25 s at rate 2, half a token has been added.
