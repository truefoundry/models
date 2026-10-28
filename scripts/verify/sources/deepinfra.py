"""DeepInfra is its own official source for providers/deepinfra/**.

GET https://api.deepinfra.com/models/list returns every model with `pricing` in CENTS. Token
models: `cents_per_input_token` / `cents_per_output_token`, cached input as a ratio of the input
price (`rate_per_input_token_cached`), cache writes as ratios in `rate_per_explicit_cache_write_token`
(`{"5m": 1.25, "1h": 2.0}`, or the single `rate_per_input_token_cache_write`).

DISCOUNTS. The API publishes `pricing.discount` (a fraction off, optionally `discount_ends_at`)
beside the LIST price, and some catalog files carry the discounted price. The catalog keeps the list
price, so while a discount is active the result is `promo` + `partial` and a discount is never a
conflict: a field equal to the list price is verified; a field equal to the discounted price is
`uncovered` with a note; a field equal to neither is a conflict. `promo` is `discount_ends_at` when
the API gives it, else the marker `"no-end-date"`.

Image models are priced per image (`cents_per_image_unit`): compared with `output_cost_per_image`
else `input_cost_per_image`, or their SUM when the file has both (FLUX-2-max). When the API number
equals just one of the two (FLUX-2-pro: its per-megapixel input price) the split cannot be verified:
both fields are `uncovered` with a note, never a conflict. Per second of output
(`output_length`), per second of input (`input_length`) and per input character
(`input_character_length`) map to the matching `*_per_second` / `*_per_character` field. Any other
shape (`time`, `frame_units`, per request) is a note and `partial`, never a guess. Tier tables, flex /
priority tiers and batch prices are not in the API: `uncovered`.
"""
from __future__ import annotations

from ..types import SourceResult
from ._common import (Fetch, clean, compare, cost_entries, cost_locator, get_json, http_get, num, region_of,
                      same, stem, uncovered_fields)

URL = "https://api.deepinfra.com/models/list"
NO_END = "no-end-date"


def model_id(repo_path: str, doc: dict) -> str | None:
    return str(doc["model"]) if doc.get("model") else (stem(repo_path) or None)


def _cents(value) -> float | None:
    n = num(value)
    return None if n is None else n / 100


class DeepInfraSource:
    name = "deepinfra"

    def __init__(self, fetch: Fetch = http_get):
        self._fetch = fetch
        self._listing: dict[str, dict] | None = None

    def covers(self, provider: str) -> bool:
        return provider == "deepinfra"

    def prepare(self) -> None:
        if self._listing is None:
            data = get_json(self._fetch, URL)
            self._listing = {m["model_name"]: m for m in data if isinstance(m, dict) and "model_name" in m}

    def check(self, repo_path: str, doc: dict) -> SourceResult:
        result = SourceResult(source=self.name)
        compared: set[tuple[str, ...]] = set()
        try:
            self.prepare()
        except Exception as e:
            result.partial = True
            result.notes.append(f"DeepInfra /models/list unreachable ({type(e).__name__})")
            result.uncovered = uncovered_fields(doc, compared)
            return result
        assert self._listing is not None
        mid = model_id(repo_path, doc)
        listed = self._listing.get(mid) if mid else None
        if listed is None:
            result.partial = True
            result.notes.append(f"`{mid}` is not in DeepInfra's model list: no price compared")
        else:
            entries = [e for e in cost_entries(doc) if region_of(e) in ("*", "global")]
            if not entries:
                result.notes.append("no `*` cost entry to compare with the API's single price")
            pricing = listed.get("pricing") or {}
            for entry in entries:
                self._compare_entry(result, compared, entry, pricing)
        result.uncovered = result.uncovered + [u for u in uncovered_fields(doc, compared) if u not in result.uncovered]
        if result.uncovered:
            result.partial = True
        return result

    # -- one `*` cost entry -------------------------------------------------------------------

    def _compare_entry(self, result: SourceResult, compared: set, entry: dict, pricing: dict) -> None:
        region = region_of(entry)
        discount = num(pricing.get("discount")) or 0.0
        expected = self._official(pricing, entry)
        if discount > 0:
            end = pricing.get("discount_ends_at")
            result.promo = str(end) if end else NO_END
            result.partial = True
            result.notes.append(
                f"DeepInfra lists a {discount:.4g} discount" + (f" until {end}" if end else " (no end date)")
                + ": the catalog keeps the list price")
        if not expected:
            result.partial = True
            result.notes.append(f"DeepInfra pricing type `{pricing.get('type')}` is not compared "
                                "(no per-token / per-image / per-second mapping)")
        for fld, listed_price, in_file, also in expected:
            locator = cost_locator(region, fld)
            note = f"sum of {' + '.join(also)}" if also else ""
            compared.update(cost_locator(region, a) for a in also)
            compared.add(locator)
            mine = in_file
            if also and mine is not None and not same(mine, listed_price):
                singles = [num(entry.get(a)) for a in also]
                if any(v is not None and same(v, listed_price) for v in singles):
                    # One API number against two catalog numbers: equal to one of them (FLUX-2-pro:
                    # per-megapixel input price) means the API does not describe the split.
                    result.uncovered.extend(".".join(cost_locator(region, a)) for a in also)
                    result.notes.append(f"the API's per-image price {listed_price:.6g} equals one of "
                                        f"{' / '.join(also)}, not their sum: split not verifiable")
                    continue
            if discount > 0 and mine is not None and not same(mine, listed_price):
                discounted = clean(listed_price * (1 - discount))
                if same(mine, discounted):
                    # The file holds the promotional price: not a conflict, and not verified either.
                    result.uncovered.extend(".".join(cost_locator(region, a)) for a in (also or (fld,)))
                    result.notes.append(f"{fld} is the discounted price {discounted:.6g}; list price is {listed_price:.6g}")
                    continue
                note = (note + "; " if note else "") + f"differs from both the list price and the discounted price {discounted:.6g}"
            check = compare(locator, mine, listed_price, note=note)
            if check is not None:
                result.checks.append(check)

    @staticmethod
    def _official(p: dict, entry: dict) -> list[tuple[str, float, float | None, tuple[str, ...]]]:
        """[(catalog field, list price in USD, the file's value for it, fields summed to get it)] for
        the one cost entry. Only prices the API states are listed."""
        kind = p.get("type")
        out: dict[str, float] = {}
        if kind in ("tokens", "input_tokens") and _cents(p.get("cents_per_input_token")) is not None:
            unit = _cents(p["cents_per_input_token"])
            out["input_cost_per_token"] = unit
            if _cents(p.get("cents_per_output_token")) is not None:
                out["output_cost_per_token"] = _cents(p["cents_per_output_token"])
            ratio = num(p.get("rate_per_input_token_cached"))
            if ratio is not None:
                out["cache_read_input_token_cost"] = unit * ratio
            writes = p.get("rate_per_explicit_cache_write_token")
            if isinstance(writes, dict):
                if num(writes.get("5m")) is not None:
                    out["cache_creation_input_token_cost"] = unit * num(writes["5m"])
                if num(writes.get("1h")) is not None:
                    out["cache_creation_input_token_cost_per_hour"] = unit * num(writes["1h"])
            elif num(p.get("rate_per_input_token_cache_write")) is not None:
                out["cache_creation_input_token_cost"] = unit * num(p["rate_per_input_token_cache_write"])
            if _cents(p.get("cents_per_image_token")) is not None:
                out["input_cost_per_image_token"] = _cents(p["cents_per_image_token"])
        elif kind == "image_units" and _cents(p.get("cents_per_image_unit")) is not None:
            per_image = _cents(p["cents_per_image_unit"])
            i, o = num(entry.get("input_cost_per_image")), num(entry.get("output_cost_per_image"))
            if i is not None and o is not None:
                return [("output_cost_per_image", clean(per_image), i + o,
                         ("input_cost_per_image", "output_cost_per_image"))]
            out["output_cost_per_image" if o is not None else "input_cost_per_image"] = per_image
        elif kind == "output_length" and _cents(p.get("cents_per_output_sec")) is not None:
            out["output_cost_per_second"] = _cents(p["cents_per_output_sec"])
        elif kind == "input_length" and _cents(p.get("cents_per_input_sec")) is not None:
            out["input_cost_per_second"] = _cents(p["cents_per_input_sec"])
        elif kind == "input_character_length" and _cents(p.get("cents_per_input_chars")) is not None:
            out["input_cost_per_character"] = _cents(p["cents_per_input_chars"])
        return [(f, clean(v), num(entry.get(f)), ()) for f, v in out.items()]


def make() -> DeepInfraSource:
    return DeepInfraSource()
