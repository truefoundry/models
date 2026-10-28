"""Amazon Bedrock prices from the public AWS Price List bulk files (no key, no account).

  index    https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/index.json
  offers   AmazonBedrockFoundationModels  (Anthropic, Cohere, AI21, OpenAI-on-Marketplace, Writer, ...)
           AmazonBedrock                  (Nova, Llama, Mistral, Qwen, DeepSeek, gpt-oss, GLM, Kimi, ...)
  region   .../offers/v1.0/aws/<offer>/current/<region>/index.json   (~0.4 to 1.5 MB each)

Covers providers/aws-bedrock/** and providers/aws-bedrock-mantle/** (see MANTLE below).

WHAT IS COMPARED. Per cost entry (one region), the on-demand standard token prices: input, output,
cache read, cache write (5 minute) and cache write (1 hour). The unit is read from each
`priceDimensions.unit` (`1M tokens`, `1K tokens`), never assumed. Two usage-type spellings exist
for Anthropic and are both understood (`InputTokenCount[_Global]` and `input_tokens[_global]_standard`),
as is the AmazonBedrock offer's `<Model>-input-tokens[-cross-region-global]`.

WHICH PRICE APPLIES. `global.<id>` is the global endpoint price; the base id and the geo profiles
(`us.` `eu.` `au.` `apac.` `jp.` `in.` `ca.` `us-gov.`) the regional / in-region price (about +10%
on Claude 4+ and Nova 2). Where a model has no separate global SKU, the one in-region price is the
price of every id.

NOT COMPARED (the file's fields become `uncovered` and the result `partial`): batch, flex,
priority and ultrafast tiers, long-context (`tiered_pricing`), custom-model, latency-optimized and
provisioned / reserved throughput SKUs, 30-minute cache writes, image/audio/video/per-second units.
When two SKUs give two different prices for one field the field is not compared (a note says so).
A SKU with more than one price dimension (a tier) is never read as the standard price. A cross-region
SKU without the `global` modifier is not the global price and is skipped.

SOURCE OUTLIERS. When one region's price for a field is 5x or more (or 0.2x or less) the median of
the file's other regions, that field is `uncovered` in that region with a "source outlier" note
(the Price List itself has 10x typos, e.g. Nova 2 Lite cache read in ca-west-1).

A field absent in the file is `uncovered` ("missing in file"), never a conflict; the empty cost
entries of a deprecated file are not compared at all.

MATCHING A FILE TO A PRICE-LIST MODEL is by normalised name (see `norm`): geo prefix, vendor
prefix, date and `-vN:M` stamps dropped. A file with no match gets a note and `partial`.

MANTLE. aws-bedrock-mantle files are compared only with the `<vendor>.<model>-mantle-*` SKUs.
Where the Price List has none (all Claude-on-mantle files) nothing is compared and a note says why:
the catalog prices those at the global rate in every region, which the Price List neither confirms
nor denies. In the other direction a native aws-bedrock file with no native SKU (Grok, Kimi K3...)
is compared with the mantle SKU of the same model, because wherever both exist the prices are equal
(checked in us-east-1 and eu-west-1); the note says so.
"""
from __future__ import annotations

import re

from ..types import SourceResult
from . import SOURCES
from ._common import (BaseSource, Fetch, NotFound, Recorder, compare, cost_entries, cost_locator, get_json, num,
                      provider_of, region_of, stem)

HOST = "https://pricing.us-east-1.amazonaws.com"
OFFERS = ("AmazonBedrockFoundationModels", "AmazonBedrock")
PROVIDERS = ("aws-bedrock", "aws-bedrock-mantle")
GEO_PREFIXES = ("global", "us", "eu", "apac", "au", "ca", "jp", "in", "us-gov")

# SKU kind -> catalog field
FIELD = {
    "input": "input_cost_per_token",
    "output": "output_cost_per_token",
    "cache_read": "cache_read_input_token_cost",
    "cache_write": "cache_creation_input_token_cost",
    "cache_write_1h": "cache_creation_input_token_cost_per_hour",
}
UNIT_TO_TOKEN = {"1m tokens": 1e-6, "1k tokens": 1e-3, "1 tokens": 1.0, "token": 1.0}

AMBIGUOUS = float("nan")  # two SKUs, two prices: never compared

# ---- usage-type grammars ---------------------------------------------------------------------

# AmazonBedrockFoundationModels: `USE1-MP:USE1_<body>-Units`
_FM_USAGE = re.compile(r"^[A-Z0-9]+-MP:[A-Z0-9]+_(?P<body>.+)-Units$")
_FM_BODY = re.compile(
    r"^(?P<kind>InputTokenCount|OutputTokenCount|outputTokenCount|CacheReadInputTokenCount|CacheWrite1hInputTokenCount|"
    r"CacheWriteInputTokenCount|input_tokens|output_tokens|cache_read_tokens|cache_write_tokens_1h|cache_write_tokens)"
    r"(?P<mod>(?:_[A-Za-z0-9]+)*)$")
_FM_KIND = {
    "InputTokenCount": "input", "input_tokens": "input",
    "OutputTokenCount": "output", "outputTokenCount": "output", "output_tokens": "output",
    "CacheReadInputTokenCount": "cache_read", "cache_read_tokens": "cache_read",
    "CacheWriteInputTokenCount": "cache_write", "cache_write_tokens": "cache_write",
    "CacheWrite1hInputTokenCount": "cache_write_1h", "cache_write_tokens_1h": "cache_write_1h",
}
_FM_NAME = re.compile(r"\s*\(Amazon Bedrock Edition\)\s*$")

# AmazonBedrock: `USE1-<model token>-<kind>[-<modifiers>]`
_BR_USAGE = re.compile(
    r"^[A-Z0-9]+-(?P<model>.+?)-(?P<kind>text-input-tokens|text-output-tokens|input-tokens|output-tokens|"
    r"cache-read-input-token-count|cache-write-input-token-count|cache-read-tokens|cache-write-tokens)"
    r"(?P<mod>(?:-[A-Za-z0-9]+)*)$")
_BR_KIND = {
    "input-tokens": "input", "text-input-tokens": "input",
    "output-tokens": "output", "text-output-tokens": "output",
    "cache-read-input-token-count": "cache_read", "cache-read-tokens": "cache_read",
    "cache-write-input-token-count": "cache_write", "cache-write-tokens": "cache_write",
}

# Names whose Price List spelling cannot be derived from the id. Only 1:1 cases, from the data.
ALIASES = {
    "nova2lite": "nova20lite", "nova2pro": "nova20pro", "nova2omni": "nova20omni",
    "mistrallarge2402": "mistrallarge", "mistralsmall2402": "mistralsmall",
    "cohereembedenglishv3": "cohereembed3modelenglish", "cohereembedmultilingualv3": "cohereembedmodel3multilingual",
    "cohereembedv4": "cohereembed4model", "coherecommandtextv14": "coheregeneratemodelcommand",
    "coherecommandlighttextv14": "coheregeneratemodelcommandlight",
    "metallama213bchat": "metallama2chat13b", "metallama270bchat": "metallama2chat70b",
    "j2mid": "jurassic2mid", "j2ultra": "jurassic2ultra",
}


def norm(name: str) -> str:
    """Lowercase alphanumerics, `+` spelled out, the word `instruct` dropped: `Llama 3.3 70B` ->
    `llama3370b`, `meta.llama3-3-70b-instruct` -> `metallama3370b`."""
    s = name.lower().replace("+", "plus")
    s = re.sub(r"(?<![a-z0-9])instruct(?![a-z0-9])", "", s)
    return re.sub(r"[^a-z0-9]", "", s)


def split_id(model_id: str) -> tuple[str, str]:
    """(scope, rest): `global.anthropic.x` -> ("global", "anthropic.x"); `us.meta.y` and a bare id
    -> ("regional", ...)."""
    low = model_id.lower()
    head, _, tail = low.partition(".")
    if head in GEO_PREFIXES and tail:
        return ("global" if head == "global" else "regional"), tail
    return "regional", low


def id_keys(model_id: str) -> tuple[str, list[str]]:
    """(scope, candidate normalised keys, most specific first) for a catalog model id."""
    scope, rest = split_id(model_id)
    rest = re.sub(r"-\d{8}(?=-|$)", "", rest)  # -20250929
    rest = re.sub(r"-v(\d+)(?::\d+)?$", lambda m: f"-v{m[1]}" if int(m[1]) > 1 else "", rest)
    rest = re.sub(r"-\d+:\d+$", "", rest)  # openai.gpt-oss-120b-1:0
    keys = [norm(rest)]
    if "." in rest.split("-")[0] or "." in rest:
        vendor_stripped = rest.partition(".")[2]
        if vendor_stripped:
            keys.append(norm(vendor_stripped))
    keys = keys + [ALIASES[k] for k in keys if k in ALIASES and ALIASES[k] not in keys]
    return scope, keys


# ---- parsing one region's offer files --------------------------------------------------------

# (family, model key) -> (scope, kind) -> USD per token (NaN when ambiguous)
Rates = dict[tuple[str, str], dict[tuple[str, str], float]]


def _per_token(unit: str | None) -> float | None:
    return UNIT_TO_TOKEN.get((unit or "").strip().lower())


def _dimension(offer: dict, sku: str) -> tuple[float, str | None] | None:
    """(USD per unit, unit) of the SKU's single on-demand price dimension; None when there is not
    exactly one dimension spanning 0..Inf."""
    terms = (offer.get("terms") or {}).get("OnDemand", {}).get(sku) or {}
    dims = [d for t in terms.values() for d in (t.get("priceDimensions") or {}).values()]
    if len(dims) != 1:
        return None
    d = dims[0]
    if str(d.get("beginRange", "0")) != "0" or str(d.get("endRange", "Inf")) != "Inf":
        return None
    usd = num((d.get("pricePerUnit") or {}).get("USD"))
    return None if usd is None else (usd, d.get("unit"))


def _mods(mod: str, sep: str) -> tuple[str, bool] | None:
    """(scope, ok) from a modifier tail; None when the tail names a tier we do not compare."""
    tokens = {t.lower() for t in mod.strip(sep).split(sep) if t}
    scope = "global" if "global" in tokens else "regional"
    rest = tokens - {"global", "standard", "cross", "region"}
    if rest or ("cross" in tokens and "global" not in tokens):
        return None
    return scope, True


def parse_offer(offer: dict) -> Rates:
    out: Rates = {}
    for sku, product in (offer.get("products") or {}).items():
        attrs = product.get("attributes") or {}
        usage = attrs.get("usagetype", "")
        parsed = None  # (family, model name, kind, scope)
        m = _FM_USAGE.match(usage)
        if m:
            b = _FM_BODY.match(m["body"])
            tier = _mods(b["mod"], "_") if b else None
            if b and tier:
                parsed = ("native", _FM_NAME.sub("", attrs.get("servicename", "")), _FM_KIND[b["kind"]], tier[0])
        else:
            b = _BR_USAGE.match(usage)
            tier = _mods(b["mod"], "-") if b else None
            if b and tier:
                model, family = b["model"], "native"
                if model.endswith("-mantle"):
                    model, family = model[: -len("-mantle")], "mantle"
                parsed = (family, model, _BR_KIND[b["kind"]], tier[0])
        if not parsed or not parsed[1]:
            continue
        family, name, kind, scope = parsed
        dim = _dimension(offer, sku)
        factor = _per_token(dim[1]) if dim else None
        if dim is None or factor is None:
            price = AMBIGUOUS  # a unit or shape we do not understand: do not compare this field
        else:
            price = dim[0] * factor
        _put(out.setdefault((family, norm(name)), {}), (scope, kind), price)
    return out


def _put(slot: dict, key: tuple[str, str], price: float) -> None:
    """Set a price; the same SKU twice at the same price is fine, a different price is ambiguous."""
    if key not in slot:
        slot[key] = price
        return
    old = slot[key]
    if old != old or price != price or abs(old - price) > 1e-9 * max(abs(old), abs(price)):
        slot[key] = AMBIGUOUS


def merge(into: Rates, other: Rates) -> None:
    for k, fields in other.items():
        slot = into.setdefault(k, {})
        for fk, price in fields.items():
            _put(slot, fk, price)


# ---- the source ------------------------------------------------------------------------------

OUTLIER_FACTOR = 5.0


def _median(values: list[float]) -> float:
    v = sorted(values)
    n = len(v)
    return v[n // 2] if n % 2 else (v[n // 2 - 1] + v[n // 2]) / 2


class AwsPriceListSource(BaseSource):
    name = "aws-price-list"

    def __init__(self, fetch: Fetch | None = None, **kw):
        super().__init__(fetch, **kw)
        self._regions: dict[str, Rates | Exception] = {}

    def covers(self, provider: str) -> bool:
        return provider in PROVIDERS

    def prepare(self) -> None:
        """Nothing is needed up front: each region's offer files are fetched on first use (only the
        regions the checked files carry), once per run; a failure is cached per region and the
        run-level time budget covers all regions together."""

    def region_rates(self, region: str) -> Rates:
        """Both offers merged for one region. Raises when a fetch failed; cached either way."""
        cached = self._regions.get(region)
        if isinstance(cached, Exception):
            raise cached
        if cached is None:
            rates: Rates = {}
            try:
                for offer in OFFERS:
                    try:
                        data = get_json(self._get, f"{HOST}/offers/v1.0/aws/{offer}/current/{region}/index.json")
                    except NotFound:
                        continue  # this offer does not exist in the region
                    merge(rates, parse_offer(data))
                    del data
            except Exception as e:  # noqa: BLE001
                self._regions[region] = e
                raise
            self._regions[region] = rates
            cached = rates
        return cached

    def _check(self, repo_path: str, doc: dict) -> SourceResult:
        result = SourceResult(source=self.name)
        rec = Recorder(result, doc)
        model_id = str(doc.get("model") or stem(repo_path))
        scope, keys = id_keys(model_id)
        mantle = provider_of(repo_path) == "aws-bedrock-mantle"
        families = ("mantle",) if mantle else ("native", "mantle")
        missing, failed, ambiguous, outliers, fell_back, unmatched = [], [], set(), set(), False, False
        # pass 1: the official price of every kind in every region the file lists
        found: list[tuple[dict, str, dict]] = []  # (entry, region, {kind: price})
        for entry in cost_entries(doc):
            region = region_of(entry)
            if rec.skippable(entry):
                continue
            try:
                rates = self.region_rates(region)
            except Exception as e:  # one region's outage must not discard the others' checks
                failed.append(f"{region} ({type(e).__name__})")
                continue
            hit = None
            for family in families:
                for key in keys:
                    if (family, key) in rates:
                        hit = (family, rates[(family, key)])
                        break
                if hit:
                    break
            if hit is None:
                unmatched = True
                continue
            if not mantle and hit[0] == "mantle":
                fell_back = True
            prices = {kind: hit[1][(scope, kind)] for kind in FIELD if (scope, kind) in hit[1]}
            if not prices:
                missing.append(region)
                continue
            found.append((entry, region, prices))
        # pass 2: outlier regions per kind, then compare
        medians = self._outlier_regions(found)
        for entry, region, prices in found:
            for kind, price in prices.items():
                fld = FIELD[kind]
                locator = cost_locator(region, fld)
                if price != price:
                    ambiguous.add(fld)
                    rec.uncovered(locator)
                    continue
                if (region, kind) in medians:
                    outliers.add(f"{region} {fld} (price {price:.6g}, other regions ~{medians[(region, kind)]:.6g})")
                    rec.uncovered(locator)
                    continue
                if num(entry.get(fld)) is None:
                    rec.absent(locator, price)
                else:
                    rec.add(compare(locator, entry.get(fld), price))
        if unmatched and not result.checks:
            result.notes.append(f"`{model_id}` has no AWS Price List model I can match (keys tried: {', '.join(keys)})")
        elif unmatched:
            result.notes.append("some regions have no Price List entry for this model")
        if missing:
            result.notes.append(f"no AWS Price List {scope} price for this model in: {', '.join(sorted(set(missing)))}")
        if failed:
            result.notes.append(f"AWS Price List unreachable for: {', '.join(sorted(set(failed)))}")
        if ambiguous:
            result.notes.append(f"several AWS SKU prices (or a unit I do not read) for {', '.join(sorted(ambiguous))}: not compared")
        if outliers:
            result.notes.append("source outlier, not compared: " + "; ".join(sorted(outliers)))
        if fell_back:
            result.notes.append("the Price List has only the `-mantle` SKU of this model: compared with that")
        if unmatched and mantle and not result.checks:
            result.notes.append("the Price List has no `-mantle` SKU for this file, so nothing was compared")
        if not cost_entries(doc):
            result.notes.append("the file has no costs to compare")
            result.partial = True
        if unmatched or missing or failed or ambiguous or outliers:
            result.partial = True
        return rec.finish()

    @staticmethod
    def _outlier_regions(found: list[tuple[dict, str, dict]]) -> dict[tuple[str, str], float]:
        """{(region, kind): median of the other regions} for prices 5x above or below that median.
        Needs at least two other regions with a price."""
        by_kind: dict[str, list[tuple[str, float]]] = {}
        for _entry, region, prices in found:
            for kind, price in prices.items():
                if price == price:
                    by_kind.setdefault(kind, []).append((region, price))
        out: dict[tuple[str, str], float] = {}
        for kind, rows in by_kind.items():
            for region, price in rows:
                others = [p for r, p in rows if r != region]
                if len(others) < 2:
                    continue
                med = _median(others)
                if med > 0 and price > 0 and (price >= OUTLIER_FACTOR * med or price <= med / OUTLIER_FACTOR):
                    out[(region, kind)] = med
        return out


SOURCES["aws-price-list"] = AwsPriceListSource
