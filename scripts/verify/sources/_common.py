"""Helpers shared by the source adapters: HTTP, numbers, tolerance, locators, uncovered fields.

Nothing here knows one provider. No LLM, no DB, no secrets; the only I/O is `http_get`, and every
adapter takes an injectable `fetch` so tests run offline.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any, Callable, Iterator

from ..types import LIMIT_TOLERANCE, PRICE_TOLERANCE, Check

Fetch = Callable[[str], bytes]

USER_AGENT = "truefoundry-models-verify/1"


class NotFound(Exception):
    """The URL answered 404 (an unlisted model, a region without an offer file)."""


def http_get(url: str, timeout: float = 90, retries: int = 2) -> bytes:
    """GET with a short retry on 5xx / network errors. 404 raises NotFound, anything else URLError."""
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
            tolerance: float = PRICE_TOLERANCE, source_note: str = "") -> Check | None:
    """One Check, or None when there is nothing to say (file lacks the field and official is 0)."""
    official = clean(official)
    mine = num(file_value)
    if mine is None:
        if official == 0:
            return None
        return Check(locator, None, official, "conflict", (note + " " if note else "") + "missing in the file")
    status = "verified" if same(mine, official, tolerance) else "conflict"
    return Check(locator, mine, official, status, note)


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
