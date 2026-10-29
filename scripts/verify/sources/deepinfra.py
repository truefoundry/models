"""DeepInfra is its own official source for providers/deepinfra/**.

GET https://api.deepinfra.com/models/list returns every model with `pricing` in CENTS. Token
models: `cents_per_input_token` / `cents_per_output_token`, cached input as a ratio of the input
price (`rate_per_input_token_cached`), cache writes as ratios in `rate_per_explicit_cache_write_token`
(`{"5m": 1.25, "1h": 2.0}`, or the single `rate_per_input_token_cache_write`).

FIELD MAPPING FOLLOWS THE FILE. The API's one `cents_per_input_token` of an `input_tokens` model is
the catalog's `input_cost_per_token`, or, for an image / video generator, whichever of
`output_cost_per_image_token` / `output_cost_per_video_token` / `output_cost_per_token` the file
carries instead (nano-banana, Seedance). A per-unit `image_units` price is the file's
`output_cost_per_image` / `input_cost_per_image`, or its `input_cost_per_request` (Pixverse).

DISCOUNTS. The API publishes `pricing.discount` (a fraction off, optionally `discount_ends_at`)
beside the LIST price, and some catalog files carry the discounted price. The catalog keeps the list
price, so while a discount is active the result is `promo_active` + `partial` (`promo` only when a
real end date is given) and a discount is never a conflict by itself:
  file == list price                          -> verified
  file within 2.5% of the DISCOUNTED price    -> uncovered + note (the file holds the promo price)
  anything else                               -> conflict

An image model with BOTH `input_cost_per_image` and `output_cost_per_image` cannot be checked: the
API quotes one price per image. That is a note and both fields `uncovered`, never a Check (a single
Check could not be written back to either field).

Also never conflicts: a field absent in the file (uncovered, "missing in file"; a cached rate equal to
the input price is derived and not even flagged). Per-second (`output_length`, `input_length`) and
per-character pricing map to the matching `*_per_second` / `*_per_character`; other shapes (`time`,
`frame_units`) are a note and `partial`. Tier tables and batch prices are not in the API. Service-tier
rates ARE (`rate_per_service_tier_priority` / `_flex`, multipliers of the list price: 1.5 and 0.8 on
most token models) but this adapter does not read them: a file's `flex_pricing` / `priority_pricing` is
`uncovered`, and a proposal for a model that has them is `partial` and says so.

DERIVED PRICES. The API quotes cache rates as ratios rounded to 8 decimals (`0.13333333` for 2/15), so
`input * ratio` carries the rounding (`1.99999995e-08` for a real `2e-08`). A derived price is rounded to
6 significant digits (`RATIO_DIGITS`); a plain cents / 100 price keeps 12.
"""
from __future__ import annotations

from ..types import LIMIT_TOLERANCE, Proposal, Proposed, SourceResult
from . import SOURCES
from ._common import (BaseSource, Fetch, Recorder, clean, compare, cost_entries, cost_locator, get_json, iso_date,
                      num, region_of, safe_id, same, stem)

URL = "https://api.deepinfra.com/models/list"
RATIO_DIGITS = 6  # significant digits kept for `input price * ratio`: the API's ratios have 8 decimals

# `input_tokens` models: where the one API price lands, in the order the file is searched.
SINGLE_PRICE_FIELDS = ("input_cost_per_token", "output_cost_per_image_token", "output_cost_per_video_token",
                       "output_cost_per_token")


def model_id(repo_path: str, doc: dict) -> str | None:
    return str(doc["model"]) if doc.get("model") else (stem(repo_path) or None)


def _cents(value) -> float | None:
    n = num(value)
    return None if n is None else n / 100


def _derived(unit: float, ratio: float) -> float:
    """`unit * ratio` without the ratio's rounding noise."""
    return float(f"{unit * ratio:.{RATIO_DIGITS}g}")


class Expect:
    """One official price and where it lands in the file's cost entry."""

    def __init__(self, field: str, price: float, *, skip_absent: bool = False):
        self.field, self.price, self.skip_absent = field, clean(price), skip_absent


class DeepInfraSource(BaseSource):
    name = "deepinfra"

    def __init__(self, fetch: Fetch | None = None, **kw):
        super().__init__(fetch, **kw)
        self._listing: dict[str, dict] | None = None
        self._error: Exception | None = None

    def covers(self, provider: str) -> bool:
        return provider == "deepinfra"

    def prepare(self) -> None:
        """One fetch attempt per run: a failure is cached and re-raised, never retried."""
        if self._listing is not None:
            return
        if self._error is not None:
            raise self._error
        try:
            data = get_json(self._get, URL)
            self._listing = {m["model_name"]: m for m in data if isinstance(m, dict) and "model_name" in m}
        except Exception as e:  # noqa: BLE001
            self._error = e
            raise

    def _check(self, repo_path: str, doc: dict) -> SourceResult:
        result = SourceResult(source=self.name)
        rec = Recorder(result, doc)
        try:
            self.prepare()
        except Exception as e:
            result.partial = True
            result.notes.append(f"DeepInfra /models/list unreachable ({type(e).__name__})")
            return rec.finish()
        listed, problem = self._lookup(model_id(repo_path, doc))
        if listed is None:
            result.partial = True
            result.notes.append(str(problem))
            return rec.finish()
        entries = [e for e in cost_entries(doc) if region_of(e) in ("*", "global")]
        if not entries:
            rec.note("no `*` cost entry to compare with the API's single price")
        pricing = listed.get("pricing") or {}
        discount = num(pricing.get("discount")) or 0.0
        if discount > 0:
            end = iso_date(pricing.get("discount_ends_at"))
            result.promo_active = True
            result.promo = end
            result.partial = True
            rec.note(f"DeepInfra lists a {discount:.4g} discount" + (f" until {end}" if end else " (no end date)")
                     + ": the catalog keeps the list price")
        for entry in entries:
            if not rec.skippable(entry):
                self._compare_entry(rec, entry, pricing, discount)
        return rec.finish()

    def _lookup(self, mid: str | None) -> tuple[dict | None, str | None]:
        """(listing entry, None) or (None, why not); shared by `check` and `propose`. `prepare()` must
        have succeeded."""
        assert self._listing is not None
        if mid is not None and not safe_id(mid):
            return None, f"model id {mid[:60]!r} has characters not allowed in a DeepInfra id: not looked up"
        listed = self._listing.get(mid) if mid else None
        if listed is None:
            return None, f"`{mid}` is not in DeepInfra's model list: no price compared"
        return listed, None

    # -- a NEW model ---------------------------------------------------------------------------

    def _propose(self, repo_path: str, doc: dict) -> Proposal | None:
        """The LIST prices of a model with none, through the same `_expectations` that `check` uses (an
        empty cost entry, so the field names are the defaults). Where the file's own shape decides the
        field and a new file has no shape, nothing is proposed: an `input_tokens` price is the input
        price only for an embedding model (a generator's lands in output_cost_per_image_token / ...
        video_token / output_cost_per_token), and an `image_units` price is input or output per image
        by catalog convention, not by the API. An active discount makes the proposal `partial`: the
        list price is proposed, never the discounted one. Zero prices are not proposed."""
        out = Proposal(source=self.name)
        try:
            self.prepare()
        except Exception as e:
            out.partial = out.unreachable = True
            out.notes.append(f"DeepInfra /models/list unreachable ({type(e).__name__})")
            return out
        listed, problem = self._lookup(model_id(repo_path, doc))
        if listed is None:
            out.partial = True
            out.notes.append(str(problem))
            return out
        pricing = listed.get("pricing") or {}
        discount = num(pricing.get("discount")) or 0.0
        if discount > 0:
            end = iso_date(pricing.get("discount_ends_at"))
            out.partial = True
            out.notes.append(f"DeepInfra is running a {discount * 100:.3g}% discount" + (f" until {end}" if end else " (no end date given)")
                             + ": it bills that much below its list price today. The LIST price is proposed, not the discounted "
                             "one; the PR gate marks the file partial while the discount lasts")
        kind = pricing.get("type")
        mode = str(doc.get("mode") or "")
        if kind == "input_tokens" and mode != "embedding":
            out.partial = True
            out.notes.append(f"DeepInfra `input_tokens` price of a `{mode or 'unknown'}` model: whether it is the input or "
                             "the output (image / video token) price depends on the file, so it is not proposed")
            return out
        expected = self._expectations(Recorder(SourceResult(source=self.name), {}), {}, pricing, "*")
        if not expected:
            out.partial = True
            out.notes.append(f"DeepInfra pricing type `{kind}` has no unambiguous catalog field for a new file: not proposed")
            return out
        for ex in expected:
            if ex.skip_absent:  # a cached rate equal to the input price is derived, files leave it out
                continue
            if ex.price <= 0:
                out.notes.append(f"{ex.field}: DeepInfra lists {ex.price:g}: not proposed")
                continue
            out.values.append(Proposed(cost_locator("*", ex.field), ex.price))
        tiers = [f"{label} x{num(pricing[key]):g}" for key, label in (("rate_per_service_tier_priority", "priority"),
                                                                      ("rate_per_service_tier_flex", "flex"))
                 if num(pricing.get(key)) is not None]
        if tiers:
            out.partial = True
            out.notes.append(f"DeepInfra lists service-tier rates for this model ({', '.join(tiers)} of the list price): "
                             "they are not read or compared by this adapter, so no flex / priority price is proposed")
        return out

    # -- one `*` cost entry -------------------------------------------------------------------

    def _compare_entry(self, rec: Recorder, entry: dict, pricing: dict, discount: float) -> None:
        region = region_of(entry)
        expected = self._expectations(rec, entry, pricing, region)
        if expected is None:
            return
        if not expected:
            rec.result.partial = True
            rec.note(f"DeepInfra pricing type `{pricing.get('type')}` is not compared "
                     "(no per-token / per-image / per-second mapping)")
        for ex in expected:
            locator = cost_locator(region, ex.field)
            mine = num(entry.get(ex.field))
            if mine is None:
                if not ex.skip_absent:
                    rec.absent(locator, ex.price)
                continue
            if discount > 0 and not same(mine, ex.price):
                discounted = clean(ex.price * (1 - discount))
                if same(mine, discounted, LIMIT_TOLERANCE):
                    # The file holds the promotional price: not a conflict, and not verified either.
                    rec.uncovered(locator)
                    rec.note(f"{ex.field} is {mine:.6g}, the discounted price (list {ex.price:.6g}, "
                             f"discounted {discounted:.6g})")
                    continue
                rec.add(compare(locator, mine, ex.price,
                                note=f"outside the list price {ex.price:.6g} and the discounted price {discounted:.6g}"))
                continue
            rec.add(compare(locator, mine, ex.price))

    def _expectations(self, rec: Recorder, entry: dict, p: dict, region: str) -> list[Expect] | None:
        """What the API says about this entry. None when the entry was fully handled here (the image
        split)."""
        kind = p.get("type")
        out: list[Expect] = []
        unit = _cents(p.get("cents_per_input_token"))
        if kind in ("tokens", "input_tokens") and unit is not None:
            if kind == "input_tokens":
                field = next((f for f in SINGLE_PRICE_FIELDS if f in entry), "input_cost_per_token")
            else:
                field = "input_cost_per_token"
            out.append(Expect(field, unit))
            if _cents(p.get("cents_per_output_token")) is not None:
                out.append(Expect("output_cost_per_token", _cents(p["cents_per_output_token"])))
            ratio = num(p.get("rate_per_input_token_cached"))
            if ratio is not None:
                # a cached rate equal to the input price is derived from it: absent is not a gap
                out.append(Expect("cache_read_input_token_cost", _derived(unit, ratio), skip_absent=same(ratio, 1.0)))
            writes = p.get("rate_per_explicit_cache_write_token")
            if isinstance(writes, dict):
                if num(writes.get("5m")) is not None:
                    out.append(Expect("cache_creation_input_token_cost", _derived(unit, num(writes["5m"]))))
                if num(writes.get("1h")) is not None:
                    out.append(Expect("cache_creation_input_token_cost_per_hour", _derived(unit, num(writes["1h"]))))
            elif num(p.get("rate_per_input_token_cache_write")) is not None:
                out.append(Expect("cache_creation_input_token_cost", _derived(unit, num(p["rate_per_input_token_cache_write"]))))
            if _cents(p.get("cents_per_image_token")) is not None:
                out.append(Expect("input_cost_per_image_token", _cents(p["cents_per_image_token"])))
            return out
        if kind == "image_units" and _cents(p.get("cents_per_image_unit")) is not None:
            per_image = _cents(p["cents_per_image_unit"])
            i, o = num(entry.get("input_cost_per_image")), num(entry.get("output_cost_per_image"))
            if i is not None and o is not None:
                return self._image_split(rec, region, per_image, i, o)
            if o is not None:
                return [Expect("output_cost_per_image", per_image)]
            if i is not None:
                return [Expect("input_cost_per_image", per_image)]
            req = next((f for f in ("input_cost_per_request", "output_cost_per_request") if f in entry), None)
            return [Expect(req, per_image)] if req else []
        if kind == "output_length" and _cents(p.get("cents_per_output_sec")) is not None:
            return [Expect("output_cost_per_second", _cents(p["cents_per_output_sec"]))]
        if kind == "input_length" and _cents(p.get("cents_per_input_sec")) is not None:
            return [Expect("input_cost_per_second", _cents(p["cents_per_input_sec"]))]
        if kind == "input_character_length" and _cents(p.get("cents_per_input_chars")) is not None:
            return [Expect("input_cost_per_character", _cents(p["cents_per_input_chars"]))]
        return out

    @staticmethod
    def _image_split(rec: Recorder, region: str, per_image: float, i: float, o: float) -> None:
        verdict = "equals" if same(i + o, per_image) else "does not equal"
        rec.uncovered(cost_locator(region, "input_cost_per_image"))
        rec.uncovered(cost_locator(region, "output_cost_per_image"))
        rec.note(f"the API quotes one price per image ({clean(per_image):.6g}); it {verdict} the sum of the file's "
                 f"input_cost_per_image + output_cost_per_image ({clean(i + o):.6g}): the split cannot be verified")
        return None


SOURCES["deepinfra"] = DeepInfraSource
