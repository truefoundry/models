"""Helpers shared by the source adapters: HTTP, numbers, tolerance, locators, uncovered fields.

Nothing here knows one provider. No LLM, no DB, no secrets; the only I/O is `http_get`, and every
adapter takes an injectable `fetch` so tests run offline.
"""
from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any, Callable, Iterator

from ..types import LIMIT_TOLERANCE, PRICE_TOLERANCE, Check, SourceResult

Fetch = Callable[[str], bytes]

USER_AGENT = "truefoundry-models-verify/1"


class NotFound(Exception):
    """The URL answered 404 (an unlisted model, a region without an offer file)."""


def http_get(url: str, timeout: float = 20, retries: int = 1) -> bytes:
    """GET, `timeout` seconds per try, `retries` extra tries (2 tries by default) on 5xx / network errors.
    404 raises NotFound, anything else URLError."""
    last: Exception | None = None
    for attempt in range(retries + 1):
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise NotFound(url) from e
            if e.code < 500:
                raise
            last = e
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            last = e
        if attempt < retries:
            time.sleep(1.5 * (attempt + 1))
    assert last is not None
    raise last


def get_json(fetch: Fetch, url: str) -> Any:
    return json.loads(fetch(url))


def num(value: Any) -> float | None:
    """A number from an int/float/numeric string (the catalog has `'5e-9'` style strings); else None."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def same(a: float, b: float, tolerance: float = PRICE_TOLERANCE) -> bool:
    """Equal within `tolerance` relative (0.5% for prices by default)."""
    if a == b:
        return True
    return abs(a - b) <= tolerance * max(abs(a), abs(b))


def clean(value: float) -> float:
    """Drop float noise from cents/100, ratio products and per-1K scaling (0.30000000000000004)."""
    return float(f"{value:.12g}")


def compare(locator: tuple[str, ...], file_value: Any, official: float, *, note: str = "",
            tolerance: float = PRICE_TOLERANCE) -> Check | None:
    """One Check for a value PRESENT in the file; None when the file has no number there (an absent
    field is never a conflict: the caller records it as uncovered, see Recorder.absent)."""
    mine = num(file_value)
    if mine is None:
        return None
    official = clean(official)
    return Check(locator, mine, official, "verified" if same(mine, official, tolerance) else "conflict", note)


def compare_limit(locator: tuple[str, ...], file_value: Any, official: float) -> Check | None:
    return compare(locator, file_value, official, tolerance=LIMIT_TOLERANCE) if num(file_value) is not None else None


def cost_locator(region: str, *path: str) -> tuple[str, ...]:
    return ("costs", f"region={region}", *path)


def loc_str(locator: tuple[str, ...]) -> str:
    return ".".join(locator)


def cost_entries(doc: dict) -> list[dict]:
    costs = doc.get("costs")
    return [c for c in costs if isinstance(c, dict)] if isinstance(costs, list) else []


def region_of(entry: dict) -> str:
    return str(entry.get("region"))


def price_fields(doc: dict) -> Iterator[tuple[tuple[str, ...], Any]]:
    """Every price field in the file: each non-`region` key of each `costs` entry, at the top level
    (a dict such as `tiered_pricing` / `flex_pricing` is one field), plus any other top-level key
    that names a price (`tool_pricing`). The core's definition of "a price in the file"."""
    for entry in cost_entries(doc):
        region = region_of(entry)
        for key, value in entry.items():
            if key != "region":
                yield cost_locator(region, key), value
    for key, value in doc.items():
        if key != "costs" and ("pricing" in key or key.endswith("_cost") or "cost_per" in key):
            yield (key,), value


def uncovered_fields(doc: dict, compared: set[tuple[str, ...]]) -> list[str]:
    """Price fields of the file that no adapter check touched, as dotted locator strings."""
    out = []
    for locator, value in price_fields(doc):
        if locator in compared:
            continue
        out.append(loc_str(locator))
    return out


def stem(repo_path: str) -> str:
    """providers/<p>/<rest>.yaml -> <rest> (the path under the provider folder, no extension)."""
    parts = repo_path.split("/")
    rest = "/".join(parts[2:]) if len(parts) >= 3 and parts[0] == "providers" else repo_path
    return rest[:-5] if rest.endswith(".yaml") else rest


def provider_of(repo_path: str) -> str:
    parts = repo_path.split("/")
    return parts[1] if len(parts) >= 2 and parts[0] == "providers" else ""


# ---- run-level budget, failure caching, never-raise wrapper -----------------------------------

class DeadlineExceeded(TimeoutError):
    """The source's run-level time budget is spent; no further fetch is attempted."""


class Budget:
    """A wall-clock budget for one source over one run. It starts at the first fetch; once spent,
    every later `check()` raises, so a hung source costs at most the budget (plus one try)."""

    def __init__(self, seconds: float = 60.0, clock: Callable[[], float] = time.monotonic):
        self.seconds = seconds
        self._clock = clock
        self._t0: float | None = None

    def remaining(self) -> float:
        if self._t0 is None:
            self._t0 = self._clock()
        return self.seconds - (self._clock() - self._t0)

    def check(self) -> None:
        if self.remaining() <= 0:
            raise DeadlineExceeded(f"source time budget of {self.seconds:g}s is spent")


def is_retired(doc: dict) -> bool:
    return bool(doc.get("isDeprecated")) or str(doc.get("status", "")).lower() in ("deprecated", "retired")


def empty_cost_entry(entry: dict) -> bool:
    return all(k == "region" for k in entry)


class Recorder:
    """Collects the checks and the uncovered fields of one `check()` call.

    Absent fields are never conflicts: a field the official source prices but the file lacks is
    recorded as uncovered ("missing in file") and makes the file partial, except for the derived,
    convention-omitted and retired-and-empty cases the adapters pass as `skip_absent`.
    """

    def __init__(self, result: SourceResult, doc: dict):
        self.result = result
        self.doc = doc
        self.compared: set[tuple[str, ...]] = set()
        self._absent: list[str] = []

    def add(self, check: Check | None) -> None:
        if check is not None:
            self.result.checks.append(check)
            self.compared.add(check.locator)

    def uncovered(self, locator: tuple[str, ...]) -> None:
        self.compared.add(locator)
        label = loc_str(locator)
        if label not in self.result.uncovered:
            self.result.uncovered.append(label)

    def absent(self, locator: tuple[str, ...], official: float) -> None:
        """The source prices this field (non-zero) and the file has none."""
        if clean(official) == 0:
            return
        self.uncovered(locator)
        self._absent.append(locator[-1])

    def note(self, text: str) -> None:
        if text not in self.result.notes:
            self.result.notes.append(text)

    def skippable(self, entry: dict) -> bool:
        """An empty cost entry of a deprecated / retired file: nothing to compare, nothing missing."""
        if is_retired(self.doc) and empty_cost_entry(entry):
            self.note("deprecated file with empty cost entries: not compared")
            return True
        return False

    def finish(self) -> SourceResult:
        for label in uncovered_fields(self.doc, self.compared):
            if label not in self.result.uncovered:
                self.result.uncovered.append(label)
        if self._absent:
            self.note("missing in file (official price exists): " + ", ".join(sorted(set(self._absent))))
        if self.result.uncovered:
            self.result.partial = True
        return self.result


def iso_date(value: Any) -> str | None:
    """`YYYY-MM-DD` from an ISO string or a unix timestamp; None for anything else."""
    if isinstance(value, bool) or value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value), tz=timezone.utc).date().isoformat()
        except (OverflowError, OSError, ValueError):
            return None
    m = re.match(r"^\d{4}-\d{2}-\d{2}", str(value))
    return m[0] if m else None


class BaseSource:
    """Shared plumbing: an injectable `fetch`, a per-run time budget, failure caching, and a public
    `check()` that never raises (any exception becomes a partial result with a note)."""

    name = ""

    def __init__(self, fetch: Fetch | None = None, *, deadline_s: float = 60.0,
                 clock: Callable[[], float] = time.monotonic):
        self._budget = Budget(deadline_s, clock)
        self._fetch = fetch if fetch is not None else self._http

    def _http(self, url: str) -> bytes:
        return http_get(url, timeout=min(20.0, max(1.0, self._budget.remaining())), retries=1)

    def _get(self, url: str) -> bytes:
        self._budget.check()
        return self._fetch(url)

    def check(self, repo_path: str, doc: dict) -> SourceResult:
        try:
            return self._check(repo_path, doc)
        except Exception as e:  # noqa: BLE001 - never raise from check()
            result = SourceResult(source=self.name, partial=True)
            result.notes.append(f"adapter error ({type(e).__name__}: {str(e)[:120]}): nothing compared")
            try:
                result.uncovered = uncovered_fields(doc, set())
            except Exception:  # noqa: BLE001
                pass
            return result

    def _check(self, repo_path: str, doc: dict) -> SourceResult:  # pragma: no cover - abstract
        raise NotImplementedError
