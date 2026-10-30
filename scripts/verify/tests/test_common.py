from __future__ import annotations

import inspect

from verify.sources import _common
from verify.sources._common import Budget, DeadlineExceeded, http_get, iso_date, num, same


def test_http_defaults_are_20_seconds_per_try_and_two_tries():
    sig = inspect.signature(http_get)
    assert sig.parameters["timeout"].default == 20 and sig.parameters["retries"].default == 1


def test_budget_default_is_a_minute_and_is_spent_by_the_clock():
    assert _common.BaseSource().__dict__["_budget"].seconds == 60.0
    now = [0.0]
    b = Budget(60.0, lambda: now[0])
    b.check()
    now[0] = 59.0
    b.check()
    now[0] = 61.0
    try:
        b.check()
    except DeadlineExceeded:
        pass
    else:
        raise AssertionError("budget should be spent")


def test_iso_date_accepts_dates_and_timestamps_only():
    assert iso_date("2026-12-01") == "2026-12-01" and iso_date("2026-12-01T10:00:00Z") == "2026-12-01"
    assert iso_date(1793254601) == "2026-10-29"
    assert iso_date(None) is None and iso_date("soon") is None and iso_date(True) is None and iso_date("") is None


def test_num_and_same():
    assert num("5e-9") == 5e-9 and num(True) is None and num([1]) is None and num("x") is None
    assert same(1.0, 1.004) and not same(1.0, 1.006) and same(0.0, 0.0)
