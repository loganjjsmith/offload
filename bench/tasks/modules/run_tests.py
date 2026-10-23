"""Runs every test_ function in tests.py against solution.py and prints one JSON line of results.

Copied into the sandbox beside the model's solution. Each test has its own time limit, so one
endless loop costs that test only.
"""
import json
import signal

TIME_LIMIT_S = 10


def _timeout(*_):
    raise TimeoutError(f"test took over {TIME_LIMIT_S} s")


def main():
    try:
        import tests
    except BaseException as exc:
        print(json.dumps({"passed": 0, "failures": [f"import: {type(exc).__name__}: {exc}"[:500]]}))
        return
    names = [n for n, f in vars(tests).items() if n.startswith("test_") and callable(f)]
    signal.signal(signal.SIGALRM, _timeout)
    passed, failures = 0, []
    for name in names:
        signal.alarm(TIME_LIMIT_S)
        try:
            getattr(tests, name)()
            passed += 1
        except BaseException as exc:
            failures.append(f"{name}: {type(exc).__name__}: {exc}"[:300])
        finally:
            signal.alarm(0)
    print(json.dumps({"passed": passed, "failures": failures}))


main()
