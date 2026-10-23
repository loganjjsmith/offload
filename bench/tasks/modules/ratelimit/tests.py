from solution import RetryError, TokenBucket, retry


class FakeClock:
    def __init__(self, t=100.0):
        self.t = t
        self.sleeps = []

    def now(self):
        return self.t

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.t += seconds


class Flaky:
    """Raises the given exceptions in turn, then returns 'ok'."""

    def __init__(self, *errors, clock=None, cost=0.0):
        self.errors = list(errors)
        self.calls = 0
        self.clock, self.cost = clock, cost

    def __call__(self):
        self.calls += 1
        if self.clock:
            self.clock.t += self.cost
        if self.errors:
            raise self.errors.pop(0)
        return "ok"


def _close(a, b):
    return abs(a - b) < 1e-9


def test_retry_success_first_time():
    c = FakeClock()
    assert retry(Flaky(), clock=c) == "ok"
    assert c.sleeps == []


def test_retry_then_success():
    c = FakeClock()
    fn = Flaky(OSError("a"), OSError("b"))
    assert retry(fn, clock=c, attempts=3) == "ok"
    assert fn.calls == 3
    assert c.sleeps == [1.0, 2.0]


def test_retry_backoff_and_cap():
    c = FakeClock()
    fn = Flaky(*[OSError()] * 5)
    assert retry(fn, clock=c, attempts=6, base_delay=3, factor=3, max_delay=20) == "ok"
    assert c.sleeps == [3, 9, 20, 20, 20]


def test_retry_gives_up():
    c = FakeClock()
    errors = [OSError("1"), OSError("2"), OSError("3")]
    fn = Flaky(*errors)
    try:
        retry(fn, clock=c, attempts=3)
    except RetryError as exc:
        assert exc.last is errors[2]
        assert exc.attempts == 3
        assert exc.__cause__ is errors[2]
    else:
        raise AssertionError("no RetryError")
    assert c.sleeps == [1.0, 2.0]


def test_retry_error_is_exception():
    assert issubclass(RetryError, Exception)


def test_retry_single_attempt():
    c = FakeClock()
    try:
        retry(Flaky(OSError()), clock=c, attempts=1)
    except RetryError as exc:
        assert exc.attempts == 1
    else:
        raise AssertionError("no RetryError")
    assert c.sleeps == []


def test_retry_attempts_validated():
    fn = Flaky()
    try:
        retry(fn, clock=FakeClock(), attempts=0)
    except ValueError:
        pass
    else:
        raise AssertionError("attempts=0 accepted")
    assert fn.calls == 0


def test_retry_other_exceptions_propagate():
    c = FakeClock()
    err = KeyError("x")
    fn = Flaky(OSError(), err)
    try:
        retry(fn, clock=c, attempts=5, retry_on=(OSError,))
    except KeyError as exc:
        assert exc is err
    else:
        raise AssertionError("KeyError swallowed")
    assert fn.calls == 2


def test_retry_on_several_classes():
    c = FakeClock()
    fn = Flaky(OSError(), ValueError(), TimeoutError())
    assert retry(fn, clock=c, attempts=4, retry_on=(OSError, ValueError)) == "ok"


def test_retry_jitter_replaces_wait():
    c = FakeClock()
    seen = []

    def jitter(w):
        seen.append(w)
        return w / 2

    retry(Flaky(OSError(), OSError()), clock=c, attempts=3, jitter=jitter)
    assert seen == [1.0, 2.0]
    assert c.sleeps == [0.5, 1.0]


def test_retry_deadline_stops_early():
    c = FakeClock()
    fn = Flaky(*[OSError()] * 10)
    try:
        retry(fn, clock=c, attempts=10, deadline=5)
    except RetryError as exc:
        assert exc.attempts == 3
    else:
        raise AssertionError("no RetryError")
    assert c.sleeps == [1.0, 2.0]


def test_retry_deadline_counts_call_time():
    c = FakeClock()
    fn = Flaky(*[OSError()] * 10, clock=c, cost=2.0)
    try:
        retry(fn, clock=c, attempts=10, deadline=6)
    except RetryError as exc:
        assert exc.attempts == 2
    else:
        raise AssertionError("no RetryError")
    assert c.sleeps == [1.0]


def test_retry_deadline_exact_boundary_allowed():
    c = FakeClock()
    fn = Flaky(OSError(), OSError())
    assert retry(fn, clock=c, attempts=3, deadline=3) == "ok"
    assert c.sleeps == [1.0, 2.0]


def test_bucket_validation():
    for rate, cap in ((0, 1), (1, 0), (-1, 5)):
        try:
            TokenBucket(rate, cap, FakeClock())
        except ValueError:
            pass
        else:
            raise AssertionError(f"rate={rate} capacity={cap} accepted")


def test_bucket_starts_full():
    assert _close(TokenBucket(2, 5, FakeClock()).available(), 5)


def test_try_take():
    b = TokenBucket(1, 3, FakeClock())
    assert b.try_take() and b.try_take(2)
    assert not b.try_take()
    assert _close(b.available(), 0)


def test_try_take_failure_changes_nothing():
    c = FakeClock()
    b = TokenBucket(1, 3, c)
    b.try_take(3)
    c.t += 1.5
    assert not b.try_take(2)
    assert _close(b.available(), 1.5)


def test_refill_continuous_and_capped():
    c = FakeClock()
    b = TokenBucket(2, 4, c)
    b.try_take(4)
    c.t += 0.25
    assert _close(b.available(), 0.5)
    c.t += 100
    assert _close(b.available(), 4)


def test_take_without_wait():
    c = FakeClock()
    b = TokenBucket(1, 2, c)
    assert b.take() == 0.0
    assert c.sleeps == []
    assert _close(b.available(), 1)


def test_take_waits_exact_time():
    c = FakeClock()
    b = TokenBucket(4, 4, c)
    b.take(4)
    waited = b.take(2)
    assert _close(waited, 0.5)
    assert len(c.sleeps) == 1 and _close(c.sleeps[0], 0.5)
    assert _close(b.available(), 0)


def test_take_partial_tokens():
    c = FakeClock()
    b = TokenBucket(2, 2, c)
    b.take(2)
    c.t += 0.25
    waited = b.take(1)
    assert _close(waited, 0.25)


def test_take_and_try_take_validate_n():
    b = TokenBucket(1, 3, FakeClock())
    for n in (0, -1, 4):
        for method in (b.take, b.try_take):
            try:
                method(n)
            except ValueError:
                pass
            else:
                raise AssertionError(f"{method.__name__}({n}) accepted")


def test_fractional_n():
    c = FakeClock()
    b = TokenBucket(1, 2, c)
    assert b.try_take(1.5)
    assert _close(b.available(), 0.5)


def test_steady_rate_over_many_calls():
    c = FakeClock(0.0)
    b = TokenBucket(10, 1, c)
    for _ in range(50):
        b.take()
    assert _close(c.t, 4.9)
