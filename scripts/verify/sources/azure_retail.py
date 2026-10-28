"""Azure token prices from the public Azure Retail Prices API (no key, no account).

  https://prices.azure.com/api/retail/prices?api-version=2023-01-01-preview&$filter=...   (NextPageLink paging)

Covers providers/azure-open-ai/**, providers/azure-ai-foundry/** and providers/microsoft-foundry/**.
Every OpenAI, Llama, Mistral, Grok, Phi, Kimi, DeepSeek, Cohere ... meter lives under
`serviceName eq 'Foundry Models'`. Claude on Foundry is Marketplace-billed and has NO meter there: those
files get a note and nothing is compared.

FETCH. ONE filter, fixed in this module and never built from a file: Foundry Models, `Consumption`, five
reference regions (eastus2, eastus, westus3, swedencentral, francecentral): about 10 pages of 1000 rows
(~20 s). Paged once per run, failures cached, the run-level deadline applies to the whole paging; a run
that does not finish paging has NO index at all (never a truncated one). Each NextPageLink must be https
on prices.azure.com /api/retail/prices or the paging stops with an error. File content (model id, region
strings) is only ever a lookup key into the parsed index.

WHAT A METER IS. The token meters are named `<model> <kind> <deployment type>` in a dozen spellings
(`5.4 nano Batch cd Inp Gl`, `gpt 4.1 Inp regnl`, `V4 Flash cached DZ`, `gpt-4o-0806-Batch-Inp-glbl`).
`parse_sku` splits the SKU name into tokens, removes the ones it knows (deployment type, input / output /
cached / cache write, Batch / Flex / PP (priority) / Std, ShortCo) and what is left is the MODEL KEY. A
SKU with no deployment-type token, two different ones, a token set that is not exactly one kind, a unit
other than `1K` / `1M` tokens (the meter name must end `Tokens` / `1M Tokens` and agree with the unit),
is not a standard price and is ignored; a LongCo (long-context) SKU is only remembered, for a note: unknown words stay in the model
key, so an exotic SKU can never match a catalog id. Units are read from `unitOfMeasure`, never assumed.

DEPLOYMENT TYPE -> CATALOG REGION.
  global        Global meters (Gl / glbl / global)       reference regions eastus2 eastus westus3 swedencentral francecentral
  datazone_us   Data Zone meters (Dz / DZone / Data Zone)  eastus2 eastus westus3
  datazone_eu   Data Zone meters                          swedencentral francecentral
  *             Regional meters (regnl / regional)         eastus2 eastus westus3  (Azure prices Regional per region,
                with +10% / +20% / +25% in some; the catalog has no Azure region, so the US reference is the list price)
                BUT the catalog says `*` is "global pricing": a file with NO `global` entry is compared with the Global
                meter (when the model has an input Global meter) and the Regional price is named in a note; a file
                WITH a `global` entry has `*` compared with Regional.
  Any other region string in a cost entry is not looked up (uncovered, a note).
A price is only used when every reference region that has the meter agrees (to 1e-9 relative); otherwise
the field is ambiguous and not compared.

ROUNDING OF THE SOURCE. A `1K` meter is published to 6 decimals per 1K tokens (the API never shows a 7th), so
Azure's `0.000963` stands for a true `0.0009625`/1K. A catalog value within 0.0000005 per 1K tokens of such a
meter is verified even outside 0.5% (`ROUND_1K`); a `1M` meter gets only the 0.5% tolerance.

`*` HAS NO FIXED DEPLOYMENT TYPE. When the file value does not equal the chosen price but equals the OTHER
deployment type's price (Global <-> Regional) the field is `uncovered` with a note, never a conflict and
never verified: the file may be right about a deployment type this adapter cannot know. A value that
equals neither is a conflict; if the choice of Global over Regional was a guess (no `global` entry, the two
differ) that conflict is NOT writable.

FIELDS COMPARED (per cost entry): input, output, cache read, cache write, `input/output_cost_per_token_batches`,
`priority_pricing.*` (PP meters), `flex_pricing.*` (Flex meters). `priority_pricing` / `flex_pricing` count as
compared only when every leaf in them was. NOT COMPARED (the field is `uncovered`, the file partial):
`tiered_pricing` (LongCo meters exist but the threshold is not stated), audio / image / realtime / video /
per-second / per-page / per-character fields, fine-tuning / training / hosting meters, provisioned throughput,
Reservation prices, batch cache prices (the catalog has no field for them).

MODEL MATCH. The catalog id is normalised (`norm`: lowercase, `-_ :/` dropped, `.` kept, the word `instruct`
dropped, `-YYYY-MM-DD` / `-YYYYMMDD` dates tried as `MMDD`, `MMDDYYYY` and then dropped) and looked up
EXACTLY among the meters' model keys, each also reachable through its product's prefix (`v4flash` under
`Azure Deepseek Models` is `deepseekv4flash`) and the explicit ALIASES table. A dated catalog id takes the
dated meter when one exists, the undated meter otherwise; an undated id never takes a dated meter. Two
different meter models behind one key are ambiguous and not matched.

ONE MODEL, SEVERAL SPELLINGS. Azure files the meters of one model under different SKU spellings and products
(`5.1 pp inp Gl` under Azure OpenAI GPT5, `GPT 5.1 inp Gl` under OpenAI; `K2.6 Thinking Inp` and `K2.6 cached` for
Kimi). Every spelling a catalog id reaches is merged; a cell where two spellings give two prices is ambiguous.

PROMOTIONS AND SCHEDULED CHANGES. A SKU whose name carries promo / intro / free / trial / discount makes
the field `promo_active` + uncovered (the catalog keeps the list price). A row whose effectiveStartDate is
in the future is not today's price: the current row is compared; a file value equal to the upcoming one is
uncovered with a note, and any upcoming change is a note.

An absent field is `uncovered` ("missing in file"), never a conflict. A file whose model has no meter is
`partial` with a note.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import date
from typing import Callable
from urllib.parse import quote, urlsplit

from ..types import Check, SourceResult
from . import SOURCES
from ._common import (BaseSource, Fetch, Recorder, compare, cost_entries, cost_locator, get_json, loc_str, num, region_of,
                      safe_id, same, stem)

HOST = "https://prices.azure.com"
PATH = "/api/retail/prices"
API_VERSION = "2023-01-01-preview"
PROVIDERS = ("azure-open-ai", "azure-ai-foundry", "microsoft-foundry")

US_REFS = ("eastus2", "eastus", "westus3")
EU_REFS = ("swedencentral", "francecentral")
FETCH_REGIONS = US_REFS + EU_REFS
# A `1K` meter is published to 6 decimals per 1K tokens (the API never shows a 7th): +-0.0000005 per 1K tokens.
ROUND_1K = 0.5e-6 / 1e3
_REGION_RE = re.compile(r"[a-z]{4,24}[0-9]?", re.ASCII)
MAX_PAGES = 60

def build_url(regions: tuple[str, ...] = FETCH_REGIONS) -> str:
    """The one request URL. Fixed host, a whitelisted filter; every region is validated first."""
    for r in regions:
        if not _REGION_RE.fullmatch(r) or r not in FETCH_REGIONS:
            raise ValueError(f"not a fetchable Azure region: {r[:40]!r}")
    flt = ("serviceName eq 'Foundry Models' and priceType eq 'Consumption' and ("
           + " or ".join(f"armRegionName eq '{r}'" for r in regions) + ")")
    return f"{HOST}{PATH}?api-version={API_VERSION}&$filter={quote(flt, safe='')}"

def _next_link_ok(link: str) -> bool:
    p = urlsplit(link)
    return p.scheme == "https" and p.hostname == "prices.azure.com" and p.port in (None, 443) and p.path == PATH

# ---- the SKU name grammar ----------------------------------------------------------------------

SCOPE_TOKENS = {
    "gl": "global", "glbl": "global", "glb": "global", "global": "global",
    "dz": "datazone", "dzone": "datazone", "dzn": "datazone", "datazone": "datazone",
    "regnl": "regional", "regional": "regional", "rgnl": "regional", "regn": "regional",
}
INPUT_TOKENS = {"inp", "input", "inpt", "in"}
OUTPUT_TOKENS = {"outp", "opt", "out", "output", "outpt"}
CACHED_TOKENS = {"cd", "cached", "cchd", "cache"}
WRITE_TOKENS = {"wr"}
TIER_TOKENS = {"batch": "batch", "flex": "flex", "pp": "priority", "std": ""}
SHORT_TOKENS = {"shortco", "shco"}  # the short-context price is the base price
LONG_TOKENS = {"longco", "loco"}
PROMO_TOKENS = {"promo", "promotion", "promotional", "intro", "introductory", "free", "trial", "discount", "discounted"}

@dataclass(frozen=True)
class Meter:
    model: str   # leftover tokens joined: the model key
    scope: str   # global | datazone | regional
    tier: str    # "" | batch | flex | priority
    kind: str    # input | output | cache_read | cache_write
    promo: bool
    long: bool = False  # a LongCo (long-context) meter: recorded for a note, never compared

def parse_sku(sku: str, meter_name: str, unit: str) -> Meter | None:
    """The standard token price a SKU names, or None for anything else (see the module docstring)."""
    suffix = {"1K": "tokens", "1M": "1m tokens"}.get(unit)
    low = (meter_name or "").lower()
    if suffix is None or not low.startswith((sku or "").lower()) or low[len(sku):].strip() != suffix:
        return None
    s = re.sub(r"\bdata[\s\-_]+zone\b", "datazone", sku.lower())
    toks = [t for t in re.split(r"[\s\-_]+", s) if t]
    scopes = {SCOPE_TOKENS[t] for t in toks if t in SCOPE_TOKENS}
    if len(scopes) != 1:
        return None
    kinds: set[str] = set()
    tiers: set[str] = set()
    model: list[str] = []
    promo = long = False
    for t in toks:
        if t in SCOPE_TOKENS or t in SHORT_TOKENS:
            continue
        if t in LONG_TOKENS:
            long = True
            continue
        if t in INPUT_TOKENS:
            kinds.add("I")
        elif t in OUTPUT_TOKENS:
            kinds.add("O")
        elif t in CACHED_TOKENS:
            kinds.add("C")
        elif t in WRITE_TOKENS:
            kinds.add("W")
        elif t in TIER_TOKENS:
            tiers.add(TIER_TOKENS[t])
        elif t in PROMO_TOKENS:
            promo = True
        else:
            model.append(t)
    kind = {frozenset("I"): "input", frozenset("O"): "output", frozenset("C"): "cache_read", frozenset("CI"): "cache_read",
            frozenset("CW"): "cache_write", frozenset("W"): "cache_write"}.get(frozenset(kinds))
    tiers.discard("")
    if kind is None or len(tiers) > 1 or not model:
        return None
    return Meter("".join(model), next(iter(scopes)), next(iter(tiers), ""), kind, promo, long)

# ---- catalog id -> meter model key -------------------------------------------------------------

# Meters of a product are reachable through these prefixes (`V4 Flash` under Deepseek is deepseek-v4-flash).
PRODUCT_PREFIX = {
    "Azure Deepseek Models": ("deepseek",), "Azure Kimi": ("kimi",), "Azure OpenAI GPT5": ("gpt",),
    "Azure OpenAI GPT6": ("gpt",), "Azure Grok Models": ("grok",), "Cohere Models": ("cohere",),
    "Azure Mistral Models": ("mistral",), "MAI Models": ("mai",), "Azure OpenAI PP FT GPT4s": ("gpt",),
}
# catalog norm key -> meter model keys it also reaches. Each line is a deliberate, reviewed decision; all the
# meters named are merged, and a cell where they disagree is ambiguous.
ALIASES: dict[str, tuple[str, ...]] = {
    # Azure bills exactly one version of these under a dated meter and the catalog has an undated sibling file.
    "gpt4omini": ("gpt4omini0718",), "o3": ("o30416",), "o4mini": ("o4mini0416",), "o1": ("o11217",),
    # Kimi K2.5 / K2.6: the input and output meters say `Thinking`, the cached-input meter does not.
    "kimik2.5": ("k2.5", "k2.5thinking"), "kimik2.6": ("k2.6", "k2.6thinking"),
}

NOT_IN_API = ("claude",)  # Marketplace-billed: no Retail Prices meter exists

_DATE = re.compile(r"-(20\d\d)-?(\d\d)-?(\d\d)$")

def norm(name: str) -> str:
    s = re.sub(r"(?<![a-z0-9])instruct(?![a-z0-9])", "", name.lower())
    return re.sub(r"[\s_\-:/]+", "", s)

def id_keys(model_id: str) -> list[str]:
    """Candidate model keys, most specific first: a dated id as MMDD / MMDDYYYY, then the dateless one."""
    low = model_id.lower()
    m = _DATE.search(low)
    if not m:
        return [norm(low)]
    y, mo, d = m.groups()
    base = norm(low[: m.start()])
    return [base + mo + d, base + mo + d + y, base]

# ---- the index ---------------------------------------------------------------------------------

AMBIGUOUS = float("nan")

@dataclass(frozen=True)
class Obs:
    region: str
    effective: str   # YYYY-MM-DD
    price: float     # USD per token
    promo: bool
    slack: float     # rounding of the source in USD per token: 1K meters are published to 6 decimals per 1K tokens

class Resolved:
    """What the index says for one (model, deployment type, tier, kind) over a set of reference regions."""

    def __init__(self, price: float | None, promo: bool = False, upcoming: tuple[str, float] | None = None, why: str = "",
                 slack: float = 0.0, promo_price: float | None = None):
        self.price, self.promo, self.upcoming, self.why, self.slack = price, promo, upcoming, why, slack
        self.promo_price = promo_price  # the promotional meter's price, when there is one and it is unambiguous

def _differ(a: float, b: float) -> bool:
    return abs(a - b) > 1e-9 * max(abs(a), abs(b))

class Index:
    def __init__(self):
        # meter model key -> (scope, tier, kind) -> [Obs]
        self.rows: dict[str, dict[tuple[str, str, str], list[Obs]]] = {}
        self.products: dict[str, set[str]] = {}
        self.long_ctx: set[str] = set()

    def add(self, item: dict) -> None:
        if item.get("serviceName") != "Foundry Models" or item.get("type") != "Consumption":
            return
        if item.get("armRegionName") not in FETCH_REGIONS:
            return
        unit = str(item.get("unitOfMeasure") or "")
        meter = parse_sku(str(item.get("skuName") or ""), str(item.get("meterName") or ""), unit)
        price = num(item.get("retailPrice"))
        if meter is None or price is None or price < 0:
            return
        if meter.long:
            self.long_ctx.add(meter.model)
            return
        per_token = price / (1e3 if unit == "1K" else 1e6)
        eff = str(item.get("effectiveStartDate") or "")[:10]
        self.rows.setdefault(meter.model, {}).setdefault((meter.scope, meter.tier, meter.kind), []).append(
            Obs(str(item["armRegionName"]), eff, per_token, meter.promo, ROUND_1K if unit == "1K" else 0.0))
        self.products.setdefault(meter.model, set()).add(str(item.get("productName") or ""))

    def keys(self) -> dict[str, set[str]]:
        """catalog-side key -> meter model keys it reaches (more than one = ambiguous)."""
        out: dict[str, set[str]] = {}
        for m, prods in self.products.items():
            names = {m}
            for p in prods:
                names.update(pre + m for pre in PRODUCT_PREFIX.get(p, ()))
            for n in names:
                out.setdefault(n, set()).add(m)
        for alias, targets in ALIASES.items():
            for target in targets:
                if target in self.rows:
                    out.setdefault(alias, set()).add(target)
        return out

    def resolve(self, models: tuple[str, ...], scope: str, tier: str, kind: str, refs: tuple[str, ...], today: str) -> Resolved:
        """The list price over every meter spelling of the model; two spellings or two reference regions with two
        prices are ambiguous. A promotional meter is resolved on its own and never becomes the list price."""
        obs = [o for m in models for o in self.rows.get(m, {}).get((scope, tier, kind), []) if o.region in refs]
        listed, promoted = [o for o in obs if not o.promo], [o for o in obs if o.promo]
        got = self._one(listed, today)
        if promoted:
            got.promo = True
            offer = self._one(promoted, today)
            got.promo_price = offer.price if offer.price is not None and offer.price == offer.price else None
        return got

    @staticmethod
    def _one(obs: list[Obs], today: str) -> Resolved:
        if not obs:
            return Resolved(None)
        prices: list[float] = []
        slack = 0.0
        upcoming: tuple[str, float] | None = None
        for region in sorted({o.region for o in obs}):
            mine = [o for o in obs if o.region == region]
            current = [o for o in mine if o.effective <= today]
            future = [o for o in mine if o.effective > today]
            if future:
                soonest = min(future, key=lambda o: o.effective)
                upcoming = upcoming or (soonest.effective, soonest.price)
            if not current:
                continue  # nothing in force yet in this region
            latest = max(o.effective for o in current)
            day = [o for o in current if o.effective == latest]
            if any(_differ(day[0].price, o.price) for o in day[1:]):
                return Resolved(AMBIGUOUS, why="several meters with different prices")
            prices.append(day[0].price)
            slack = max(slack, *(o.slack for o in day))
        if not prices:
            return Resolved(None, upcoming=upcoming)
        if any(_differ(prices[0], p) for p in prices[1:]):
            return Resolved(AMBIGUOUS, why="the reference regions disagree")
        return Resolved(prices[0], False, upcoming, slack=slack)

# ---- fields ------------------------------------------------------------------------------------

_LEAVES = {"input": "input_cost_per_token", "output": "output_cost_per_token",
           "cache_read": "cache_read_input_token_cost", "cache_write": "cache_creation_input_token_cost"}
_BATCH = {"input": "input_cost_per_token_batches", "output": "output_cost_per_token_batches"}

def field_tails() -> list[tuple[tuple[str, ...], str, str]]:
    """(key path in a cost entry, tier, kind) for every field this adapter can compare."""
    out = [((leaf,), "", kind) for kind, leaf in _LEAVES.items()]
    out += [((leaf,), "batch", kind) for kind, leaf in _BATCH.items()]
    for tier, block in (("priority", "priority_pricing"), ("flex", "flex_pricing")):
        out += [((block, leaf), tier, kind) for kind, leaf in _LEAVES.items()]
    return out

FIELDS = field_tails()

def _dig(entry: dict, tail: tuple[str, ...]):
    node = entry
    for key in tail:
        node = node.get(key) if isinstance(node, dict) else None
    return node

SCOPE_LABEL = {"global": "Global", "regional": "Regional", "datazone": "Data Zone"}

def _g(price: float) -> str:
    return f"{price:.6g}"

# ---- the source --------------------------------------------------------------------------------

class AzureRetailSource(BaseSource):
    name = "azure-retail-prices"

    def __init__(self, fetch: Fetch | None = None, *, today: Callable[[], str] | str | None = None, **kw):
        super().__init__(fetch, **kw)
        self._today = today
        self._index: Index | None = None
        self._keys: dict[str, set[str]] = {}
        self._error: Exception | None = None

    def covers(self, provider: str) -> bool:
        return provider in PROVIDERS

    def today(self) -> str:
        t = self._today() if callable(self._today) else self._today
        return t or date.today().isoformat()

    def prepare(self) -> None:
        """Page the one filter, once per run. A failure (outage, deadline, malformed page) is cached and re-raised."""
        if self._index is not None:
            return
        if self._error is not None:
            raise self._error
        try:
            index = Index()
            url: str | None = build_url()
            seen: set[str] = set()
            while url:
                if url in seen or len(seen) >= MAX_PAGES:
                    raise ValueError("Azure Retail Prices paging did not end")
                seen.add(url)
                data = get_json(self._get, url)
                items = data.get("Items") if isinstance(data, dict) else None
                if not isinstance(items, list):
                    raise ValueError("Azure Retail Prices page without Items")
                for item in items:
                    if isinstance(item, dict):
                        index.add(item)
                link = data.get("NextPageLink")
                if link and not _next_link_ok(str(link)):
                    raise ValueError("Azure Retail Prices NextPageLink points outside prices.azure.com")
                url = str(link) if link else None
            self._index, self._keys = index, index.keys()
        except Exception as e:  # noqa: BLE001
            self._error = e
            raise

    # -- model match --

    def _match(self, model_id: str) -> tuple[tuple[str, ...], str]:
        """(meter model keys, note). Several keys are spellings of one model (`5.1` under the GPT5 product and
        `GPT 5.1` under OpenAI); their prices are merged and a cell where they disagree is ambiguous."""
        assert self._index is not None
        low = model_id.lower()
        if low.startswith(NOT_IN_API):
            return (), f"`{model_id}` is billed through the Azure Marketplace: the Retail Prices API has no meter for it"
        tried = id_keys(model_id)
        for k in tried:
            hit = self._keys.get(k)
            if hit:
                return tuple(sorted(hit)), ""
        return (), f"`{model_id}` has no Azure meter I can match (keys tried: {', '.join(tried)})"

    # -- the check --

    def _check(self, repo_path: str, doc: dict) -> SourceResult:
        result = SourceResult(source=self.name)
        rec = Recorder(result, doc)
        try:
            self.prepare()
        except Exception as e:
            result.partial = True
            result.notes.append(f"Azure Retail Prices API unreachable or unreadable ({type(e).__name__})")
            return rec.finish()
        assert self._index is not None
        model_id = str(doc.get("model") or stem(repo_path))
        if not safe_id(model_id):
            result.partial = True
            result.notes.append(f"model id {model_id[:60]!r} has characters not allowed in an id: not looked up")
            return rec.finish()
        entries = cost_entries(doc)
        if not entries:
            result.partial = True
            result.notes.append("the file has no costs to compare")
            return rec.finish()
        model, why = self._match(model_id)
        if not model:
            result.partial = True
            result.notes.append(why)
            return rec.finish()
        today = self.today()
        has_global = any(region_of(e) == "global" for e in entries)
        unmapped: set[str] = set()
        for entry in entries:
            if rec.skippable(entry):
                continue
            region = region_of(entry)
            if region not in ("*", "global", "datazone_us", "datazone_eu"):
                unmapped.add(region[:40])
                continue
            self._compare_entry(rec, model, entry, region, has_global, today)
        if unmapped:
            result.partial = True
            rec.note("not a deployment type I can map (only *, global, datazone_us, datazone_eu), not looked up: "
                     + ", ".join(repr(r) for r in sorted(unmapped)))
        if any(m in self._index.long_ctx for m in model):
            rec.note("Azure has long-context meters for this model: tiered_pricing is not compared")
        return rec.finish()

    def _compare_entry(self, rec: Recorder, model: tuple[str, ...], entry: dict, region: str, has_global: bool, today: str) -> None:
        idx = self._index
        assert idx is not None
        guessed = False
        alt: tuple[str, tuple[str, ...]] | None = None
        if region == "global":
            scope, refs = "global", FETCH_REGIONS
        elif region == "datazone_us":
            scope, refs = "datazone", US_REFS
        elif region == "datazone_eu":
            scope, refs = "datazone", EU_REFS
        else:
            g = idx.resolve(model, "global", "", "input", FETCH_REGIONS, today)
            r = idx.resolve(model, "regional", "", "input", US_REFS, today)
            if has_global and r.price is not None:  # `*` next to a `global` entry is the standard (Regional) price
                scope, refs, alt = "regional", US_REFS, ("global", FETCH_REGIONS)
            elif g.price is not None:  # the catalog's `*` is "global pricing"; Regional is the other candidate
                scope, refs = "global", FETCH_REGIONS
                if r.price is not None:
                    alt = ("regional", US_REFS)
                    guessed = not has_global and (r.price != r.price or g.price != g.price or _differ(g.price, r.price))
            else:
                scope, refs = "regional", US_REFS
        label = SCOPE_LABEL[scope]
        for tail, tier, kind in FIELDS:
            locator = cost_locator(region, *tail)
            present = num(_dig(entry, tail)) is not None
            got = idx.resolve(model, scope, tier, kind, refs, today)
            name = ".".join(tail)
            if got.promo:
                rec.result.promo_active = True
                rec.result.partial = True
                rec.note(f"Azure lists a promotional {label} meter for {name}: the catalog keeps the list price")
            if got.price is None:
                if present:
                    rec.uncovered(locator)
                    if not got.promo:
                        rec.note(f"no Azure {label} meter for {name}: not compared")
                continue
            if got.price != got.price:
                if present:
                    rec.uncovered(locator)
                    rec.note(f"Azure {label} meters for {name} are ambiguous ({got.why}): not compared")
                continue
            if not present:
                if len(tail) == 1 and not tier:
                    rec.absent(locator, got.price)
                elif got.price:
                    rec.note(f"Azure has a {tier} price this file does not carry (not flagged): {name}")
                continue
            self._judge(rec, model, locator, name, _dig(entry, tail), got, label, tier, kind, alt, guessed, today)
        for tier, block in (("priority", "priority_pricing"), ("flex", "flex_pricing")):
            sub = entry.get(block)
            if isinstance(sub, dict) and sub:
                left = [k for k in sub if loc_str(cost_locator(region, block, k)) in rec.result.uncovered
                        or cost_locator(region, block, k) not in rec.compared]
                if left:
                    rec.note(f"{block} not compared for: {', '.join(sorted(left))}")
                else:
                    rec.compared.add(cost_locator(region, block))

    @staticmethod
    def _compare(locator, mine, got: Resolved) -> Check:
        """Within 0.5% or within the source's own rounding (see ROUND_1K)."""
        check = compare(locator, mine, got.price)
        assert check is not None
        if check.status == "conflict" and abs(check.file_value - check.source_value) <= got.slack:
            check = replace(check, status="verified", note="within the source's rounding (6 decimals per 1K tokens)")
        return check

    def _judge(self, rec: Recorder, model: tuple[str, ...], locator: tuple[str, ...], name: str, mine, got: Resolved, label: str,
               tier: str, kind: str, alt: tuple[str, tuple[str, ...]] | None, guessed: bool, today: str) -> None:
        idx = self._index
        assert idx is not None and got.price is not None
        value = num(mine)
        assert value is not None
        if got.upcoming and _differ(got.upcoming[1], got.price):
            if same(value, got.upcoming[1]) and not same(value, got.price):
                rec.uncovered(locator)
                rec.note(f"{name} is {_g(value)}, the price Azure lists from {got.upcoming[0]} (today {_g(got.price)}): not compared")
                return
            rec.note(f"Azure lists a different {label} price for {name} from {got.upcoming[0]}: {_g(got.upcoming[1])}")
        check = self._compare(locator, mine, got)
        if check.status == "conflict" and got.promo_price is not None and same(value, got.promo_price, 0.025):
            rec.uncovered(locator)
            rec.note(f"{name} is {_g(value)}, the promotional price (list {_g(got.price)}, promo {_g(got.promo_price)})")
            return
        if check.status == "verified" or alt is None:
            rec.add(check)
            return
        other = idx.resolve(model, alt[0], tier, kind, alt[1], today)
        have_other = other.price is not None and other.price == other.price
        if have_other and same(value, other.price):
            rec.uncovered(locator)
            rec.note(f"{name} is {_g(value)}, the {SCOPE_LABEL[alt[0]]} price ({label} is {_g(got.price)}): "
                     "the `*` entry's deployment type is ambiguous, not compared")
            return
        if guessed:  # which price to write is a guess: the sweep must not auto-fix this
            where = f"{SCOPE_LABEL[alt[0]]} {_g(other.price)}" if have_other else "no other deployment type priced"
            rec.add(replace(check, writable=False, note=f"`*` has no `global` sibling and Azure's {label} and Regional prices differ ({label} {_g(got.price)}; {where})"))
            return
        rec.add(check)


SOURCES["azure-retail-prices"] = AzureRetailSource
