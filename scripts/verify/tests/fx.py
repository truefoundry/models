"""Test helpers: recorded fixtures and a counting fake `fetch` (tests never touch the network)."""
from __future__ import annotations

import json
import urllib.error
from pathlib import Path

from verify.sources._common import NotFound

FIXTURES = Path(__file__).parent / "fixtures"


def raw(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def load(name: str):
    return json.loads(raw(name))


class FakeFetch:
    """url -> bytes (or an Exception to raise). Unknown URLs raise NotFound, like a 404."""

    def __init__(self, routes: dict[str, bytes | Exception]):
        self.routes = dict(routes)
        self.calls: list[str] = []

    def __call__(self, url: str) -> bytes:
        self.calls.append(url)
        got = self.routes.get(url)
        if got is None:
            raise NotFound(url)
        if isinstance(got, Exception):
            raise got
        return got


def outage() -> Exception:
    return urllib.error.URLError("connection refused")


def checks_by_field(result) -> dict[str, object]:
    """last locator component -> Check, for the checks of one result."""
    out = {}
    for c in result.checks:
        out[c.locator[-1]] = c
    return out
