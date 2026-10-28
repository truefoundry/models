"""OpenRouter is its own official source for providers/openrouter/**.

GET https://openrouter.ai/api/v1/models lists every public model with `pricing` (USD per token as
strings) and `context_length`. A model that is not listed gets a note and `partial`, never a price
check: the per-model /endpoints list is ordered by price, so its first entry is the cheapest
upstream, not what OpenRouter quotes. (No per-model request is made at all: the listing is the
single fetch.)

The model id comes from the path under providers/openrouter/ (`stepfun/step-3.5-flash.yaml` ->
`stepfun/step-3.5-flash`); a flat file with no org in its path falls back to its `sources:` URL
(`https://openrouter.ai/<org>/<slug>[/api]`), then to `model:`. Only that first id is looked up: a
`:beta` or `:free` file is never priced from the model it was derived from.

Compared: prompt, completion, input_cache_read, input_cache_write (5m), input_cache_write_1h, and,
when the file carries the matching field, audio, input_audio_cache, audio_output, image,
image_output, request / web_search (per query), plus the context window (2.5%). Tier `overrides`
are not compared: they are `uncovered` where the file has `tiered_pricing`, and a note + `partial`
where the API lists tiers the file lacks. Everything else in the file (batches, video tokens, ...)
is `uncovered`.
"""
from __future__ import annotations

import re

from ..types import SourceResult
from ._common import (Fetch, compare, compare_limit, cost_entries, cost_locator, get_json, http_get, num, region_of,
                      stem, uncovered_fields)

BASE = "https://openrouter.ai/api/v1"
MODELS_URL = f"{BASE}/models"
# `openrouter.ai/<org>/<slug>[/api]`; a one-segment `openrouter.ai/<slug>/api` names no org.
_SOURCE_URL = re.compile(r"^https?://openrouter\.ai/(?!api/|docs/)([^/?#]+/(?!api/?$)[^/?#]+?)(?:/api)?/?$")

# Official key -> catalog field. Core fields are compared even when the file lacks them (a missing
# non-zero price is a real gap); extras only when the file carries one of the candidate fields.
CORE = {
    "prompt": "input_cost_per_token",
    "completion": "output_cost_per_token",
    "input_cache_read": "cache_read_input_token_cost",
    "input_cache_write": "cache_creation_input_token_cost",
    "input_cache_write_1h": "cache_creation_input_token_cost_per_hour",
}
EXTRAS = {
    "audio": ("input_cost_per_audio_token", "input_cost_per_second"),
    "input_audio_cache": ("cache_read_input_audio_token_cost",),
    "audio_output": ("output_cost_per_audio_token",),
    "image": ("input_cost_per_image_token", "input_cost_per_image"),
    "image_output": ("output_cost_per_image_token", "output_cost_per_image"),
    "request": ("input_cost_per_request",),
    "web_search": ("input_cost_per_query", "input_cost_per_request"),
}


def source_id(repo_path: str, doc: dict) -> str | None:
    """The OpenRouter id of a file: path under providers/openrouter/, else sources URL, else model."""
    rest = stem(repo_path)
    if "/" in rest:
        return rest
    for url in doc.get("sources") or []:
        match = _SOURCE_URL.match(str(url))
        if match:
            return match[1]
    model = str(doc.get("model") or "")
    return model or None


class OpenRouterSource:
    name = "openrouter"

    def __init__(self, fetch: Fetch = http_get):
        self._fetch = fetch
        self._listing: dict[str, dict] | None = None

    def covers(self, provider: str) -> bool:
        return provider == "openrouter"

    def prepare(self) -> None:
        if self._listing is None:
            data = get_json(self._fetch, MODELS_URL)["data"]
            listing = {m["id"]: m for m in data if isinstance(m, dict) and "id" in m}
            for m in data:  # a file may carry the dated slug
                if isinstance(m, dict) and m.get("canonical_slug"):
                    listing.setdefault(m["canonical_slug"], m)
            self._listing = listing

    def check(self, repo_path: str, doc: dict) -> SourceResult:
        result = SourceResult(source=self.name)
        try:
            self.prepare()
        except Exception as e:  # an outage is partial, never a crash
            return self._outage(result, doc, e)
        assert self._listing is not None
        model_id = source_id(repo_path, doc)
        listed = self._listing.get(model_id) if model_id else None
        compared: set[tuple[str, ...]] = set()
        if listed is None:
            result.partial = True
            result.notes.append(f"`{model_id}` is not in OpenRouter's /models listing: no price compared")
        else:
            self._compare(result, doc, listed, compared)
        result.uncovered = uncovered_fields(doc, compared)
        if result.uncovered:
            result.partial = True
        return result

    def _outage(self, result: SourceResult, doc: dict, error: Exception) -> SourceResult:
        result.partial = True
        result.notes.append(f"OpenRouter /models unreachable ({type(error).__name__})")
        result.uncovered = uncovered_fields(doc, set())
        return result

    def _compare(self, result: SourceResult, doc: dict, listed: dict, compared: set[tuple[str, ...]]) -> None:
        pricing = listed.get("pricing") or {}
        entries = [e for e in cost_entries(doc) if region_of(e) in ("*", "global")]
        if not entries and cost_entries(doc):
            result.notes.append("no `*` cost entry to compare with OpenRouter's single price")
        for entry in entries:
            region = region_of(entry)
            for key, fld in CORE.items():
                official = num(pricing.get(key))
                if official is None or official < 0:  # negative = variable (the `auto` router)
                    continue
                self._add(result, compared, region, entry, fld, official)
            for key, candidates in EXTRAS.items():
                official = num(pricing.get(key))
                if official is None or official < 0:
                    continue
                fld = next((c for c in candidates if c in entry), None)
                if fld is not None:
                    self._add(result, compared, region, entry, fld, official)
        overrides = pricing.get("overrides")
        if overrides:
            floors = sorted({o.get("min_prompt_tokens") for o in overrides if isinstance(o, dict)} - {None})
            has_tiers = any("tiered_pricing" in e for e in entries)
            result.notes.append(
                f"OpenRouter lists tier overrides (min_prompt_tokens {floors}) that are not compared"
                + ("" if has_tiers else "; the file has no tiered_pricing"))
            result.partial = True
        context = num(listed.get("context_length"))
        limits = doc.get("limits") if isinstance(doc.get("limits"), dict) else {}
        if context:
            check = compare_limit(("limits", "context_window"), limits.get("context_window"), context)
            if check:
                result.checks.append(check)

    @staticmethod
    def _add(result: SourceResult, compared: set, region: str, entry: dict, fld: str, official: float) -> None:
        check = compare(cost_locator(region, fld), entry.get(fld), official)
        if check is None:
            return
        result.checks.append(check)
        compared.add(check.locator)


def make() -> OpenRouterSource:
    return OpenRouterSource()
