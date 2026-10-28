"""OpenRouter is its own official source for providers/openrouter/**.

GET https://openrouter.ai/api/v1/models lists every public model with `pricing` (USD per token as
strings), `context_length` and `top_provider.max_completion_tokens`.

THE LISTING QUOTES THE CHEAPEST ENDPOINT, not a first-party price (verified live: z-ai/glm-5.2,
moonshotai/kimi-k3, qwen/qwen3.8-27b all list one cheap upstream's price). So the comparison is
one-sided and every Check and note says so:
  - file price equals the listing (0.5%)        -> verified
  - file price BELOW the listing                -> conflict (no endpoint can explain it)
  - file price ABOVE the listing                -> uncovered + note: it may be a first-party price
A limit (context window, max output) that differs from the listing is an uncovered note, never a
conflict. A field the file lacks is uncovered ("missing in file"), never a conflict.

A model that is not listed gets a note and `partial`, never a price check: the per-model /endpoints
list is ordered by price too, so no per-model request is made at all.

The model id comes from the path under providers/openrouter/ (`stepfun/step-3.5-flash.yaml` ->
`stepfun/step-3.5-flash`); a flat file with no org in its path falls back to its `sources:` URL
(`https://openrouter.ai/<org>/<slug>[/api]`), then to `model:`. Only that first id is looked up.

Compared: prompt, completion, input_cache_read, input_cache_write (5m), input_cache_write_1h,
and, when the file carries the matching field, audio, input_audio_cache, audio_output,
image_output, request / web_search (per query). NOT compared: the `image` key (its unit is not
verified: per image or per image token), the tier `overrides` (uncovered where the file has
`tiered_pricing`, a note + partial where it lacks them), anything else in the file.
"""
from __future__ import annotations

import re

from ..types import LIMIT_TOLERANCE, SourceResult
from . import SOURCES
from ._common import (BaseSource, Fetch, Recorder, compare, cost_entries, cost_locator, get_json, num,
                      region_of, same, stem)

BASE = "https://openrouter.ai/api/v1"
MODELS_URL = f"{BASE}/models"
CHEAPEST = "OpenRouter /models quotes the cheapest endpoint"
# `openrouter.ai/<org>/<slug>[/api]`; a one-segment `openrouter.ai/<slug>/api` names no org.
_SOURCE_URL = re.compile(r"^https?://openrouter\.ai/(?!api/|docs/)([^/?#]+/(?!api/?$)[^/?#]+?)(?:/api)?/?$")

# Official key -> catalog field. Core fields are looked for in every `*` entry (an absent one is
# uncovered); extras only when the file carries the field.
CORE = {
    "prompt": "input_cost_per_token",
    "completion": "output_cost_per_token",
    "input_cache_read": "cache_read_input_token_cost",
    "input_cache_write": "cache_creation_input_token_cost",
    "input_cache_write_1h": "cache_creation_input_token_cost_per_hour",
}
# OR files never carry the 1h cache-write price by convention: absent is not worth a flag.
CONVENTION_OMITTED = {"cache_creation_input_token_cost_per_hour"}
EXTRAS = {
    "audio": ("input_cost_per_audio_token",),
    "input_audio_cache": ("cache_read_input_audio_token_cost",),
    "audio_output": ("output_cost_per_audio_token",),
    "image_output": ("output_cost_per_image_token",),
    "request": ("input_cost_per_request",),
    "web_search": ("input_cost_per_query", "input_cost_per_request"),
}
UNIT_UNVERIFIED = ("input_cost_per_image", "input_cost_per_image_token")


def source_id(repo_path: str, doc: dict) -> str | None:
    """The OpenRouter id of a file: path under providers/openrouter/, else sources URL, else model."""
    rest = stem(repo_path)
    if "/" in rest:
        return rest
    sources = doc.get("sources")
    for url in sources if isinstance(sources, list) else []:
        match = _SOURCE_URL.match(str(url))
        if match:
            return match[1]
    model = str(doc.get("model") or "")
    return model or None


class OpenRouterSource(BaseSource):
    name = "openrouter"

    def __init__(self, fetch: Fetch | None = None, **kw):
        super().__init__(fetch, **kw)
        self._listing: dict[str, dict] | None = None
        self._error: Exception | None = None

    def covers(self, provider: str) -> bool:
        return provider == "openrouter"

    def prepare(self) -> None:
        """One fetch attempt per run: a failure is cached and re-raised, never retried."""
        if self._listing is not None:
            return
        if self._error is not None:
            raise self._error
        try:
            data = get_json(self._get, MODELS_URL)["data"]
            listing = {m["id"]: m for m in data if isinstance(m, dict) and "id" in m}
            for m in data:  # a file may carry the dated slug
                if isinstance(m, dict) and m.get("canonical_slug"):
                    listing.setdefault(m["canonical_slug"], m)
            self._listing = listing
        except Exception as e:  # noqa: BLE001
            self._error = e
            raise

    def _check(self, repo_path: str, doc: dict) -> SourceResult:
        result = SourceResult(source=self.name)
        rec = Recorder(result, doc)
        try:
            self.prepare()
        except Exception as e:  # an outage is partial, never a crash
            result.partial = True
            result.notes.append(f"OpenRouter /models unreachable ({type(e).__name__})")
            return rec.finish()
        assert self._listing is not None
        model_id = source_id(repo_path, doc)
        listed = self._listing.get(model_id) if model_id else None
        if listed is None:
            result.partial = True
            result.notes.append(f"`{model_id}` is not in OpenRouter's /models listing: no price compared")
        else:
            self._compare(rec, doc, listed)
        return rec.finish()

    def _compare(self, rec: Recorder, doc: dict, listed: dict) -> None:
        result = rec.result
        pricing = listed.get("pricing") or {}
        entries = [e for e in cost_entries(doc) if region_of(e) in ("*", "global")]
        if not entries and cost_entries(doc):
            rec.note("no `*` cost entry to compare with OpenRouter's single price")
        above: list[str] = []
        variable: list[str] = []
        for entry in entries:
            if rec.skippable(entry):
                continue
            region = region_of(entry)
            fields = [(k, (f,)) for k, f in CORE.items()] + [(k, c) for k, c in EXTRAS.items()]
            for key, candidates in fields:
                official = num(pricing.get(key))
                if official is None:
                    continue
                if official < 0:  # negative = variable (the `auto` router)
                    variable.append(key)
                    continue
                core = key in CORE
                fld = next((c for c in candidates if c in entry), candidates[0] if core else None)
                if fld is None:
                    continue
                locator = cost_locator(region, fld)
                mine = num(entry.get(fld))
                if mine is None:
                    if not (core and fld in CONVENTION_OMITTED):
                        rec.absent(locator, official)
                elif same(mine, official):
                    rec.add(compare(locator, mine, official, note=CHEAPEST))
                elif mine < official:
                    rec.add(compare(locator, mine, official, note=f"{CHEAPEST}; the file is below every endpoint"))
                else:
                    rec.uncovered(locator)
                    above.append(fld)
            image = num(pricing.get("image"))
            if image is not None and image > 0 and any(f in entry for f in UNIT_UNVERIFIED):
                rec.note("OpenRouter `image` price not compared: its unit (per image or per image token) is not verified")
        if above:
            rec.note("above cheapest endpoint: may be first-party price (" + ", ".join(sorted(set(above))) + ")")
        if variable:
            rec.note("OpenRouter price is variable (negative): not compared (" + ", ".join(sorted(set(variable))) + ")")
        overrides = pricing.get("overrides")
        if overrides:
            floors = sorted({o.get("min_prompt_tokens") for o in overrides if isinstance(o, dict)} - {None})
            has_tiers = any("tiered_pricing" in e for e in entries)
            rec.note(f"OpenRouter lists tier overrides (min_prompt_tokens {floors}) that are not compared"
                     + ("" if has_tiers else "; the file has no tiered_pricing"))
            result.partial = True
        self._limits(rec, doc, listed)
        rec.note(CHEAPEST + ": a file price above it is not a conflict")

    @staticmethod
    def _limits(rec: Recorder, doc: dict, listed: dict) -> None:
        limits = doc.get("limits") if isinstance(doc.get("limits"), dict) else {}
        top = listed.get("top_provider") if isinstance(listed.get("top_provider"), dict) else {}
        for fld, official in (("context_window", num(listed.get("context_length"))),
                              ("max_output_tokens", num(top.get("max_completion_tokens")))):
            if not official or num(limits.get(fld)) is None:
                continue
            check = compare(("limits", fld), limits.get(fld), official, tolerance=LIMIT_TOLERANCE, note=CHEAPEST)
            if check is None:
                continue
            if check.status == "verified":
                rec.add(check)
            else:  # a difference vs the listing is not a catalog error we can assert
                rec.uncovered(("limits", fld))
                rec.note(f"{fld} differs from /models ({CHEAPEST}): file {check.file_value:g}, listing {official:g}")


SOURCES["openrouter"] = OpenRouterSource
