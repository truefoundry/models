"""Anthropic's pricing documentation is the official source for providers/anthropic/** (first-party API).

GET https://platform.claude.com/docs/en/about-claude/pricing.md is clean Markdown. This is the first PAGE-BASED
adapter, so the parser is deterministic (no LLM) and FAILS CLOSED: if the page's shape is not exactly the one
this module was written against, NOTHING is compared (every file is `partial` with ONE loud note) rather than
guessing. It is a pilot for "direct provider with no price API".

TABLES READ (exact header cells, column counts and the `$ / MTok` unit are checked; any difference refuses the page):
  `## Model pricing`            Model | Base input tokens | 5m cache writes | 1h cache writes | Cache hits and refreshes | Output tokens
  `### Batch processing`        Model | Batch input | Batch output
  `### Prompt caching` (cross-check only; if it is unreadable the cache fields become uncovered, not the page refused)
                                Cache operation | Multiplier | Duration
A model cell must be `Claude <Family> <n[.m]>` plus at most one annotation: a `[retired ...](url)` /
`[limited availability](url)` link, or `(for prompts up to|over N,NNN tokens)`. A row that cannot be parsed, a
duplicated row, a second table in a pricing section or a truncated page refuses the whole page.

FIELD MAPPING (per MTok -> per token). input / output / 5m write / 1h write / cache hit map to
input_cost_per_token / output_cost_per_token / cache_creation_input_token_cost /
cache_creation_input_token_cost_per_hour / cache_read_input_token_cost; the batch table maps to
input_cost_per_token_batches / output_cost_per_token_batches. A model with two rows (Claude Haiku 5.5: up to /
over 100,000 tokens) compares the "up to" row with the top-level fields and the "over" row with the file's
`tiered_pricing` (input / output / cache_read / cache_write, `from=100000`; the tiered cache_write is the 5m rate).
`tiered_pricing.pricing_mode` must be `cumulative` (the page bills the whole request at the higher rate), else the
tier is uncovered. Numbers the file schema cannot hold (the 1h write and the batch price over the threshold) are a
note only.

NOTHING IS TRUSTED ON ITS OWN. Each literal cell is cross-checked against the page's own rules and a field the page
contradicts is `uncovered` with a note, never `verified` and never a conflict (which of two page statements is the
official one is a human question):
  5m write = 1.25x input and 1h write = 2x input (the Prompt caching multiplier table);
  cache hit = the multiplier a footnote EXPLICITLY states for the models it names ("0.05x on Claude Opus 5.5 and
    Claude Sonnet 5.5"), else the standard multiplier the page states, and the prose table must agree; a footnote
    applies only to the models it names and only where its marker sits (a model it names without the marker, or a
    marker on a model it does not name, is a contradiction);
  batch = the stated Batch API discount ("50 percent") applied to the model's own price, per row.
A footnote on a price that announces introductory / promotional pricing sets `promo_active` (`promo` only from a real
"through <Month D, YYYY>") and the cell is `uncovered`; a footnote that says the intro price "is now the standard
price" is not a promo; any other unrecognised footnote on a price cell leaves that cell `uncovered`.

COVERAGE. Page model names map to catalog files through an explicit alias table (`alias_table()`), never a fuzzy
match: the file's model id must be `claude-<family>-<ver>` (or `claude-<ver>-<family>`, the older catalog order, e.g.
claude-3-5-haiku = "Claude Haiku 3.5") optionally followed by `-YYYYMMDD` (a dated snapshot) or `-latest`, and its
`canonical_model` and path must name the same slug. Anything else, or two page models for one slug, is uncovered.
Not covered at all: tool, fast-mode, data-residency (+10% for `inference_geo`) and per-region prices (the page
covers the global first-party API only; other regions stay uncovered). The page's retired / limited-availability
annotations are noted per file; lifecycle is never compared.

ROW FINGERPRINTS. `row_fingerprints()` -> {model row name: sha256 of the normalised row cells (model-pricing row +
batch row)}. Normalisation: NFKC, whitespace collapsed, `<sup>` footnote markers dropped, markdown links reduced to
their text, prices rewritten as `$<decimal>/MTok` (so `$5.00` == `$5`). The page's raw hash changes on every fetch;
these do not, so they are the schedule's change-detection signal. `extra_fingerprints()` covers what is not a model
row (footnote texts, cache multiplier table, fast-mode table, batch discount sentence). Both raise if the page is
unreachable or has changed shape, so "page changed shape" is distinguishable from "nothing changed".

    python -m verify.sources.anthropic_pricing --fingerprints [--file page.md]
    python -m verify.sources.anthropic_pricing --aliases [--root ..]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from ..types import SourceResult
from . import SOURCES
from ._common import (USER_AGENT, BaseSource, Fetch, NotFound, Recorder, clean, compare, cost_entries, cost_locator,
                      num, region_of, same, stem)

URL = "https://platform.claude.com/docs/en/about-claude/pricing.md"
NAME = "anthropic-pricing-page"
MAX_BYTES = 3_000_000
MIN_MODEL_ROWS = 5  # a page with fewer rows than this was truncated or replaced

MODEL_HEADER = ["Model", "Base input tokens", "5m cache writes", "1h cache writes", "Cache hits and refreshes",
                "Output tokens"]
BATCH_HEADER = ["Model", "Batch input", "Batch output"]
MULT_HEADER = ["Cache operation", "Multiplier", "Duration"]

MODEL_COLS = ("input", "write_5m", "write_1h", "read", "output")
BATCH_COLS = ("batch_input", "batch_output")

class PageStructureError(Exception):
    """The page is not the shape this adapter was written for: nothing is compared."""

# ---------------------------------------------------------------------------------------------------------------
# text helpers

_WS = re.compile(r"\s+")
_SUP = re.compile(r"<sup>(.*?)</sup>", re.S)
_LINK = re.compile(r"\[([^\]]*)\]\([^)\s]*\)")
_SEP_CELL = re.compile(r"^:?-{3,}:?$")
_PRICE = re.compile(r"^\$\s*(\d+(?:\.\d+)?)\s*/\s*MTok$")
_ABSENT = {"—", "–", "-", "n/a", "N/A", "Not available", "not available"}
_FENCE = re.compile(r"^\s*(```|~~~)")
_HEADING = re.compile(r"^(#{1,6}) +(.+?) *$")

def _ws(text: str) -> str:
    return _WS.sub(" ", unicodedata.normalize("NFKC", text).replace(" ", " ")).strip()

def _split_row(line: str) -> list[str]:
    s = line.strip()
    if not (s.startswith("|") and s.endswith("|")):
        raise PageStructureError(f"table row is not pipe-delimited: {s[:60]!r}")
    cells, cur, esc = [], [], False
    for ch in s[1:-1]:
        if esc:
            cur.append(ch)
            esc = False
        elif ch == "\\":
            cur.append(ch)
            esc = True
        elif ch == "|":
            cells.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    cells.append("".join(cur))
    return [_ws(c) for c in cells]

@dataclass
class Table:
    header: list[str]
    rows: list[list[str]]

def _tables(lines: list[str]) -> list[Table]:
    """Every pipe table in `lines` (code fences skipped). The separator row must have one `---` cell per column."""
    out: list[Table] = []
    i, fenced = 0, False
    while i < len(lines):
        line = lines[i]
        if _FENCE.match(line):
            fenced = not fenced
        if fenced or not line.lstrip().startswith("|"):
            i += 1
            continue
        block = []
        while i < len(lines) and lines[i].lstrip().startswith("|"):
            block.append(lines[i])
            i += 1
        if len(block) < 2:
            raise PageStructureError("a table has no separator row")
        header = _split_row(block[0])
        sep = _split_row(block[1])
        if len(sep) != len(header) or not all(_SEP_CELL.match(c) for c in sep):
            raise PageStructureError(f"table {header[:2]} has a malformed separator row")
        rows = [_split_row(b) for b in block[2:]]
        for r in rows:
            if len(r) != len(header):
                raise PageStructureError(f"table {header[:2]}: a row has {len(r)} cells, the header has "
                                         f"{len(header)} ({r[0][:50]!r})")
        out.append(Table(header, rows))
    return out

def _sections(lines: list[str]) -> list[tuple[int, int, str, int]]:
    """(line index, level, title, end index) for every heading outside code fences."""
    heads: list[tuple[int, int, str]] = []
    fenced = False
    for i, line in enumerate(lines):
        if _FENCE.match(line):
            fenced = not fenced
            continue
        m = None if fenced else _HEADING.match(line)
        if m:
            heads.append((i, len(m[1]), m[2]))
    out = []
    for k, (i, level, title) in enumerate(heads):
        end = len(lines)
        for j, lv, _ in heads[k + 1:]:
            if lv <= level:
                end = j
                break
        out.append((i, level, title, end))
    return out

def _section(lines: list[str], secs, level: int, title: str, *, required: bool = True) -> list[str] | None:
    hits = [s for s in secs if s[1] == level and s[2] == title]
    if len(hits) != 1:
        if not hits and not required:
            return None
        raise PageStructureError(f"expected exactly one `{'#' * level} {title}` section, found {len(hits)}")
    i, _, _, end = hits[0]
    return lines[i + 1:end]

def _dec(text: str) -> Decimal:
    return Decimal(text)

def _price_cell(text: str) -> Decimal | None:
    """`$12.50 / MTok` -> Decimal; an explicit "not offered" token -> None; anything else refuses the page."""
    if text in _ABSENT:
        return None
    m = _PRICE.match(text)
    if not m:
        raise PageStructureError(f"price cell {text[:60]!r} is not `$<n> / MTok`")
    return _dec(m[1])

def _fmt(d: Decimal) -> str:
    return format(d.normalize(), "f")

# ---------------------------------------------------------------------------------------------------------------
# model rows

_NAME = re.compile(r"^(?P<base>Claude [A-Z][A-Za-z]+ \d+(?:\.\d+)?)(?: \((?P<ann>.+)\))?$")
_TIER = re.compile(r"^for prompts (?P<kind>up to|over) (?P<n>\d{1,3}(?:,\d{3})*) tokens$")
_LABEL = re.compile(r"^\[(?P<label>(?:limited availability|retired(?:, [^\]]*)?))\]\(https://[^)\s]+\)$")
_MODEL_NAME = re.compile(r"^Claude [A-Z][A-Za-z]+ \d+(?:\.\d+)?$")

@dataclass
class Ident:
    base: str
    tier: str | None = None  # None | "up_to" | "over"
    threshold: int | None = None
    label: str | None = None  # "retired, except on ..." | "limited availability"

    @property
    def key(self) -> tuple[str, str | None]:
        return (self.base, self.tier)

    @property
    def display(self) -> str:
        if self.tier is None:
            return self.base
        return f"{self.base} (for prompts {'up to' if self.tier == 'up_to' else 'over'} {self.threshold:,} tokens)"

def _ident(cell: str) -> Ident:
    m = _NAME.match(cell)
    if not m:
        raise PageStructureError(f"model cell {cell[:80]!r} does not match `Claude <Family> <version>`")
    ident = Ident(m["base"])
    ann = m["ann"]
    if ann is None:
        return ident
    t = _TIER.match(ann)
    if t:
        ident.tier = "up_to" if t["kind"] == "up to" else "over"
        ident.threshold = int(t["n"].replace(",", ""))
        return ident
    lk = _LABEL.match(ann)
    if lk:
        ident.label = lk["label"]
        return ident
    raise PageStructureError(f"model cell {cell[:80]!r} has an annotation this parser does not know")

def _marker(cell: str) -> tuple[str, str | None]:
    """(cell text without the footnote marker, marker number). A `<sup>` anywhere but the end leaves the cell
    unparsable (price / model patterns are anchored), which refuses the page."""
    m = re.match(r"^(.*?)\s*<sup>(\d+)</sup>$", cell)
    if m:
        text, mark = m[1], m[2]
    else:
        text, mark = cell, None
    return text, mark

@dataclass
class Row:
    ident: Ident
    prices: dict[str, Decimal | None] = field(default_factory=dict)
    marks: dict[str, str | None] = field(default_factory=dict)
    cells: list[str] = field(default_factory=list)
    batch: dict[str, Decimal | None] | None = None
    batch_cells: list[str] = field(default_factory=list)

def _parse_model_table(t: Table) -> dict[tuple[str, str | None], Row]:
    if t.header != MODEL_HEADER:
        raise PageStructureError(f"model pricing header changed: {t.header}")
    rows: dict[tuple[str, str | None], Row] = {}
    for cells in t.rows:
        ident = _ident(cells[0])
        row = Row(ident)
        for col, cell in zip(MODEL_COLS, cells[1:]):
            text, mark = _marker(cell)
            row.prices[col] = _price_cell(text)
            row.marks[col] = mark
        row.cells = [_canon_cell(c) for c in cells]
        if ident.key in rows:
            raise PageStructureError(f"model {ident.display!r} appears twice in the model pricing table")
        rows[ident.key] = row
    if len(rows) < MIN_MODEL_ROWS:
        raise PageStructureError(f"only {len(rows)} model rows (the page looks truncated)")
    return rows

def _canon_cell(cell: str) -> str:
    """The cell as it enters a fingerprint: marker and links gone, a price as `$<decimal>/MTok`."""
    text = _ws(_LINK.sub(r"\1", _SUP.sub("", cell)))
    m = _PRICE.match(text)
    return f"${_fmt(_dec(m[1]))}/MTok" if m else text

def _attach_batch(rows: dict[tuple[str, str | None], Row], t: Table) -> list[str]:
    """Join the batch table onto the model rows. Returns notes for batch models that have no model row."""
    if t.header != BATCH_HEADER:
        raise PageStructureError(f"batch pricing header changed: {t.header}")
    notes, seen = [], set()
    for cells in t.rows:
        ident = _ident(cells[0])
        if ident.key in seen:
            raise PageStructureError(f"model {ident.display!r} appears twice in the batch table")
        seen.add(ident.key)
        prices = {}
        for col, cell in zip(BATCH_COLS, cells[1:]):
            text, mark = _marker(cell)
            if mark is not None:
                raise PageStructureError("a footnote marker in the batch table is not expected")
            prices[col] = _price_cell(text)
        row = rows.get(ident.key)
        if row is None:
            notes.append(f"batch table lists {ident.display!r}, which the model table does not")
            continue
        row.batch = prices
        row.batch_cells = [_canon_cell(c) for c in cells[1:]]
    return notes

# ---------------------------------------------------------------------------------------------------------------
# footnotes and multipliers

_FOOTNOTE = re.compile(r"^\*<sup>(?:(\d+) )?(.+?)</sup>\*$")
_READ_FN = re.compile(r"^Cache hits and refreshes on (?P<models>.+?) (?:are|is) priced at (?P<m>\d+(?:\.\d+)?)x "
                      r"the base input price\.$")
_STD_FN = re.compile(r"^All other models use the standard (?P<m>\d+(?:\.\d+)?)x multiplier\.$")
_PROMO = re.compile(r"\b(introductory|promotional|promotion|discount(?:ed)?|limited[- ]time|temporary)\b", re.I)
_END = re.compile(r"\b(?:through|until|ending|ends(?: on)?) (?P<d>[A-Z][a-z]+ \d{1,2}, \d{4})")

def _models_list(text: str) -> tuple[str, ...] | None:
    names = tuple(_ws(x) for x in re.split(r", and |, | and ", text))
    return names if names and all(_MODEL_NAME.match(n) for n in names) else None

def _iso(text: str) -> str | None:
    try:
        return datetime.strptime(text, "%B %d, %Y").date().isoformat()
    except ValueError:
        return None

@dataclass
class Footnote:
    n: str
    text: str
    kind: str  # read-mult | standard | promo | other
    mult: Decimal | None = None
    models: tuple[str, ...] = ()
    promo_end: str | None = None

def _classify(n: str, text: str) -> Footnote:
    m = _READ_FN.match(text)
    if m:
        models = _models_list(m["models"])
        if models:
            return Footnote(n, text, "read-mult", _dec(m["m"]), models)
        return Footnote(n, text, "other")
    if _PROMO.search(text):
        if "now the standard" in text.lower():
            return Footnote(n, text, "standard")
        end = _END.search(text)
        return Footnote(n, text, "promo", promo_end=_iso(end["d"]) if end else None)
    return Footnote(n, text, "other")

@dataclass
class CacheMult:
    write_5m: Decimal
    write_1h: Decimal
    read_default: Decimal
    read_over: dict[str, Decimal]

def _parse_mult_table(t: Table) -> CacheMult:
    if t.header != MULT_HEADER:
        raise PageStructureError(f"multiplier table header changed: {t.header}")
    by = {r[0]: r for r in t.rows}
    if set(by) != {"5-minute cache write", "1-hour cache write", "Cache read (hit)"} or len(by) != len(t.rows):
        raise PageStructureError(f"multiplier table rows changed: {sorted(by)}")
    def one(cell: str) -> tuple[Decimal, str | None]:
        m = re.match(r"^(\d+(?:\.\d+)?)x base input price(?: \((.*)\))?$", cell)
        if not m:
            raise PageStructureError(f"multiplier cell {cell[:60]!r} not understood")
        return _dec(m[1]), m[2]
    w5, extra5 = one(by["5-minute cache write"][1])
    w1, extra1 = one(by["1-hour cache write"][1])
    rd, ov = one(by["Cache read (hit)"][1])
    if extra5 or extra1:
        raise PageStructureError("a cache write multiplier has an unexpected per-model clause")
    over: dict[str, Decimal] = {}
    for part in (ov or "").split(";") if ov else []:
        m = re.match(r"^\s*(\d+(?:\.\d+)?)x on (.+?)\s*$", part)
        models = _models_list(m[2]) if m else None
        if not m or not models:
            raise PageStructureError(f"cache read clause {part.strip()[:60]!r} not understood")
        for name in models:
            if name in over:
                raise PageStructureError(f"{name} has two cache read multipliers")
            over[name] = _dec(m[1])
    return CacheMult(w5, w1, rd, over)

@dataclass
class Page:
    rows: dict[tuple[str, str | None], Row]
    footnotes: dict[str, Footnote]
    read_default: Decimal | None
    cache_mult: CacheMult | None
    batch_factor: Decimal | None
    notes: list[str]
    extras: dict[str, str]

    @property
    def bases(self) -> dict[str, dict[str | None, Row]]:
        out: dict[str, dict[str | None, Row]] = {}
        for (base, tier), row in self.rows.items():
            out.setdefault(base, {})[tier] = row
        return out

_BATCH_SENTENCE = re.compile(r"with a (\d+(?:\.\d+)?) percent discount on both input and output tokens")

def parse_page(text: str) -> Page:
    """Parse the pricing Markdown or raise PageStructureError. Pure: no network, no clock."""
    if "\x00" in text or "<html" in text[:500].lower() or "<!doctype" in text[:200].lower():
        raise PageStructureError("the response is not Markdown")
    if not re.search(r"All prices are in USD\.", text):
        raise PageStructureError("the page no longer says `All prices are in USD.`")
    lines = text.split("\n")
    secs = _sections(lines)
    model_sec = _section(lines, secs, 2, "Model pricing")
    tables = _tables(model_sec)
    if len(tables) != 1:
        raise PageStructureError(f"`## Model pricing` has {len(tables)} tables, expected 1")
    rows = _parse_model_table(tables[0])
    notes: list[str] = []

    footnotes: dict[str, Footnote] = {}
    read_default: Decimal | None = None
    std_seen = 0
    fn_texts: list[str] = []
    for line in model_sec:
        m = _FOOTNOTE.match(line.strip())
        if not m:
            continue
        n, body = m[1], _ws(m[2])
        fn_texts.append(_canon_footnote(body))
        s = _STD_FN.match(body)
        if n is None and s:
            std_seen += 1
            read_default = _dec(s["m"])
            continue
        if n is None:
            notes.append(f"unnumbered footnote not understood: {body[:80]}")
            continue
        if n in footnotes:
            raise PageStructureError(f"footnote {n} appears twice")
        footnotes[n] = _classify(n, body)
    if std_seen != 1:
        read_default = None

    batch_sec = _section(lines, secs, 3, "Batch processing")
    btables = _tables(batch_sec)
    if len(btables) != 1:
        raise PageStructureError(f"`### Batch processing` has {len(btables)} tables, expected 1")
    notes.extend(_attach_batch(rows, btables[0]))
    bf = _BATCH_SENTENCE.findall("\n".join(batch_sec))
    batch_factor = (Decimal(1) - _dec(bf[0]) / Decimal(100)) if len(bf) == 1 else None

    cache_mult: CacheMult | None = None
    mult_cells = "absent"
    cache_sec = _section(lines, secs, 3, "Prompt caching", required=False)
    if cache_sec is not None:
        try:
            ctables = [t for t in _tables(cache_sec) if t.header and t.header[0] == "Cache operation"]
            if len(ctables) != 1:
                raise PageStructureError(f"expected one cache multiplier table, found {len(ctables)}")
            cache_mult = _parse_mult_table(ctables[0])
            mult_cells = "\n".join("|".join(_canon_cell(c) for c in r) for r in ctables[0].rows)
        except PageStructureError as e:
            notes.append(f"cache multiplier table unreadable ({e}): cache fields cannot be cross-checked")
    else:
        notes.append("no `### Prompt caching` section: cache fields cannot be cross-checked")

    fast_cells = "absent"
    fast_sec = _section(lines, secs, 3, "Fast mode pricing", required=False)
    if fast_sec is not None:
        fast_cells = "\n".join("|".join(_canon_cell(c) for c in [*t.header, *r]) for t in _tables(fast_sec)
                               for r in [t.header] + t.rows)

    extras = {
        "footnotes": _sha("\n".join(sorted(fn_texts))),
        "cache-multipliers": _sha(mult_cells),
        "fast-mode": _sha(fast_cells),
        "batch-discount": _sha(f"{batch_factor}"),
    }
    return Page(rows, footnotes, read_default, cache_mult, batch_factor, notes, extras)

def _canon_footnote(text: str) -> str:
    return _ws(text)

def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()

def fingerprints(page: Page) -> dict[str, str]:
    """{row name: sha256 of the normalised model-pricing row cells + batch row cells}."""
    out = {}
    for row in page.rows.values():
        payload = "\x1f".join(row.cells) + "\x1e" + "\x1f".join(row.batch_cells or ["-"])
        out[row.ident.display] = _sha(payload)
    return dict(sorted(out.items()))

# ---------------------------------------------------------------------------------------------------------------
# alias table: catalog model id -> page model

_ID = re.compile(r"^(?P<slug>claude-[a-z0-9]+(?:-[a-z0-9]+)*?)(?:-(?P<date>\d{8})|-(?P<latest>latest))?$")

def slugs_of(base: str) -> tuple[str, ...]:
    """`Claude Opus 5.5` -> (claude-opus-5-5, claude-5-5-opus): the two orders the catalog uses."""
    m = re.match(r"^Claude ([A-Za-z]+) (\d+)(?:\.(\d+))?$", base)
    if not m:
        return ()
    fam = m[1].lower()
    ver = m[2] + (f"-{m[3]}" if m[3] else "")
    return (f"claude-{fam}-{ver}", f"claude-{ver}-{fam}")

def slug_index(bases) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for b in bases:
        for s in slugs_of(b):
            out.setdefault(s, []).append(b)
    return out

def resolve(repo_path: str, doc: dict, index: dict[str, list[str]]) -> tuple[str | None, str]:
    """(page model name | None, why). Only a file that CLEARLY corresponds to one page model resolves."""
    model, path_id = doc.get("model", stem(repo_path)), stem(repo_path)
    if not isinstance(model, str) or not model:
        return None, "the file has no usable `model` id"
    if path_id and model != path_id:
        return None, f"model `{model}` differs from the file name `{path_id}`"
    m = _ID.match(model)
    if not m:
        return None, f"`{model}` is not a claude-<family>-<version> id"
    if m["date"]:
        try:
            datetime.strptime(m["date"], "%Y%m%d")
        except ValueError:
            return None, f"`{model}` has an invalid snapshot date"
    slug = m["slug"]
    canon = doc.get("canonical_model")
    if canon is not None:
        if not isinstance(canon, str) or canon.removeprefix("anthropic/") != slug:
            return None, f"canonical_model `{canon}` does not name `{slug}`"
    hits = index.get(slug, [])
    if not hits:
        return None, f"`{model}` is not on Anthropic's pricing page"
    if len(hits) > 1:
        return None, f"`{slug}` matches several page models ({', '.join(sorted(hits))})"
    return hits[0], ""

def alias_table(docs: dict[str, dict], page: Page) -> dict[str, tuple[str | None, str]]:
    """repo_path -> (page model, why not) for the catalog files given."""
    index = slug_index(page.bases)
    return {p: resolve(p, d, index) for p, d in sorted(docs.items())}

# ---------------------------------------------------------------------------------------------------------------
# the adapter

PER_MTOK = Decimal(1_000_000)

@dataclass
class Expect:
    field: str  # file field (or tier key for a tier expectation)
    label: str  # column on the page
    value: Decimal | None
    reason: str | None = None  # a page-internal contradiction: uncovered, with this note
    promo: Footnote | None = None
    unrecognised: str | None = None
    col: str = ""  # the page column this comes from

    @property
    def per_token(self) -> float | None:
        return None if self.value is None else clean(float(self.value / PER_MTOK))

class AnthropicPricingSource(BaseSource):
    name = NAME

    def __init__(self, fetch: Fetch | None = None, **kw):
        super().__init__(fetch, **kw)
        self._page: Page | None = None
        self._error: Exception | None = None
        self.page_sha256: str | None = None

    def covers(self, provider: str) -> bool:
        return provider == "anthropic"

    def _http(self, url: str) -> bytes:
        """GET with a pinned User-Agent, asking for Markdown; 2 tries on 5xx / network errors."""
        last: Exception | None = None
        for attempt in range(2):
            timeout = min(20.0, max(1.0, self._budget.remaining()))
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/markdown, text/plain;q=0.9"})
            try:
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    body = resp.read(MAX_BYTES + 1)
                    if len(body) > MAX_BYTES:
                        raise PageStructureError("the page is over 3 MB")
                    return body
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    raise NotFound(url) from e
                if e.code < 500:
                    raise
                last = e
            except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
                last = e
            if attempt == 0:
                self._budget.check()
                time.sleep(1.5)
        assert last is not None
        raise last

    def prepare(self) -> None:
        """One fetch attempt per run. A failure (network or structure) is cached and re-raised, never retried."""
        if self._page is not None:
            return
        if self._error is not None:
            raise self._error
        try:
            raw = self._get(URL)
            if len(raw) > MAX_BYTES:
                raise PageStructureError("the page is over 3 MB")
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError as e:
                raise PageStructureError("the page is not UTF-8") from e
            page = parse_page(text)
            self.page_sha256 = hashlib.sha256(raw).hexdigest()
            self._page = page
        except Exception as e:  # noqa: BLE001
            self._error = e
            raise

    # -- change detection -----------------------------------------------------------------------------------
    def row_fingerprints(self) -> dict[str, str]:
        """Stable per-row hashes for the schedule. Raises when the page is unreachable or changed shape."""
        self.prepare()
        assert self._page is not None
        return fingerprints(self._page)

    def extra_fingerprints(self) -> dict[str, str]:
        self.prepare()
        assert self._page is not None
        return dict(self._page.extras)

    # -- the check ------------------------------------------------------------------------------------------
    def _check(self, repo_path: str, doc: dict) -> SourceResult:
        result = SourceResult(source=self.name)
        rec = Recorder(result, doc)
        try:
            self.prepare()
        except PageStructureError as e:
            result.partial = True
            result.notes.append(f"Anthropic pricing page changed shape ({e}): nothing compared. Update "
                                "verify/sources/anthropic_pricing.py before trusting this source")
            return rec.finish()
        except Exception as e:  # noqa: BLE001
            result.partial = True
            result.notes.append(f"Anthropic pricing page unreachable ({type(e).__name__})")
            return rec.finish()
        page = self._page
        assert page is not None
        base, why = resolve(repo_path, doc, slug_index(page.bases))
        if base is None:
            result.partial = True
            result.notes.append(f"{why}: no price compared")
            return rec.finish()
        group = page.bases[base]
        problem = _group_problem(base, group)
        if problem:
            result.partial = True
            result.notes.append(f"{problem}: no price compared")
            return rec.finish()
        main = group.get(None) or group["up_to"]
        long = group.get("over")
        label = main.ident.label
        if label:
            rec.note(f"the page marks {base} as `{label}`: lifecycle is not compared")
        for n in page.notes:
            if "unnumbered footnote" in n or "cache multiplier" in n:
                rec.note(n)

        entries = [e for e in cost_entries(doc) if region_of(e) in ("*", "global")]
        if not entries:
            rec.note("no `*` cost entry: the page prices the global first-party API only")
        if any(region_of(e) not in ("*", "global") for e in cost_entries(doc)):
            rec.note("the page covers the global first-party API only; other regions stay uncovered")
        expects = self._expectations(page, main, rec)
        tier_expects = self._tier_expectations(page, long, rec) if long else {}
        for entry in entries:
            if rec.skippable(entry):
                continue
            region = region_of(entry)
            for ex in expects:
                self._compare(rec, cost_locator(region, ex.field), num(entry.get(ex.field)), ex, base)
            self._compare_tiers(rec, entry, region, long, tier_expects)
        return rec.finish()

    # field -> expectations ---------------------------------------------------------------------------------
    def _expectations(self, page: Page, row: Row, rec: Recorder) -> list[Expect]:
        out = [
            self._cell(page, row, "input", "input_cost_per_token", "base input"),
            self._cell(page, row, "output", "output_cost_per_token", "output"),
            self._cell(page, row, "write_5m", "cache_creation_input_token_cost", "5m cache write"),
            self._cell(page, row, "write_1h", "cache_creation_input_token_cost_per_hour", "1h cache write"),
            self._cell(page, row, "read", "cache_read_input_token_cost", "cache hit"),
        ]
        out.append(self._batch(row, "batch_input", "input_cost_per_token_batches"))
        out.append(self._batch(row, "batch_output", "output_cost_per_token_batches"))
        for ex in out:
            self._apply_cross_checks(page, row, ex)
        return out

    def _tier_expectations(self, page: Page, row: Row, rec: Recorder) -> dict[str, Expect]:
        exps = {
            "input": self._cell(page, row, "input", "input", "input over the threshold"),
            "output": self._cell(page, row, "output", "output", "output over the threshold"),
            "cache_write": self._cell(page, row, "write_5m", "cache_write", "5m cache write over the threshold"),
            "cache_read": self._cell(page, row, "read", "cache_read", "cache hit over the threshold"),
        }
        for ex in exps.values():
            self._apply_cross_checks(page, row, ex)
        return exps

    @staticmethod
    def _cell(page: Page, row: Row, col: str, field_name: str, label: str) -> Expect:
        ex = Expect(field_name, label, row.prices.get(col), col=col)
        mark = row.marks.get(col)
        if mark is not None:
            fn = page.footnotes.get(mark)
            if fn is None:
                ex.reason = f"footnote {mark} is not on the page"
            elif fn.kind == "promo":
                ex.promo = fn
            elif fn.kind == "other" or (fn.kind == "read-mult" and col != "read"):
                ex.unrecognised = f"footnote {mark} on the {label} price is not understood ({fn.text[:80]})"
        return ex

    @staticmethod
    def _batch(row: Row, col: str, field_name: str) -> Expect:
        value = row.batch.get(col) if row.batch else None
        return Expect(field_name, col.replace("_", " "), value, col=col)

    def _apply_cross_checks(self, page: Page, row: Row, ex: Expect) -> None:
        """Set `ex.reason` when the page contradicts itself about this field (or cannot confirm it)."""
        if ex.value is None or ex.reason:
            return
        col = ex.col
        inp = row.prices.get("input")
        base = row.ident.base
        if col in ("write_5m", "write_1h"):
            if page.cache_mult is None:
                ex.reason = "the cache multiplier table is unreadable: the cache write cannot be cross-checked"
                return
            mult = page.cache_mult.write_5m if col == "write_5m" else page.cache_mult.write_1h
            ex.reason = _expect(ex, inp, mult, f"{'5m' if col == 'write_5m' else '1h'} cache write",
                                f"{mult.normalize():f}x its base input")
        elif col == "read":
            ex.reason = self._read_reason(page, row, ex, inp, base)
        elif col in ("batch_input", "batch_output"):
            ref = row.prices.get("input" if col == "batch_input" else "output")
            if page.batch_factor is None:
                ex.reason = "the page's Batch API discount sentence is unreadable: batch cannot be cross-checked"
                return
            ex.reason = _expect(ex, ref, page.batch_factor, col.replace("_", " "),
                                f"{page.batch_factor.normalize():f}x its own price")

    def _read_reason(self, page: Page, row: Row, ex: Expect, inp: Decimal | None, base: str) -> str | None:
        mark = row.marks.get("read")
        named = [fn for fn in page.footnotes.values() if fn.kind == "read-mult" and base in fn.models]
        mults: set[Decimal] = set()
        if mark is not None:
            fn = page.footnotes.get(mark)
            if fn is None or fn.kind != "read-mult":
                return f"footnote {mark} on the cache hit price states no multiplier"
            if base not in fn.models:
                return f"footnote {mark} carries a multiplier but does not name {base}"
            if len(named) != 1:
                return f"{base} is named by {len(named)} cache hit footnotes"
            assert fn.mult is not None
            mults.add(fn.mult)
        else:
            if named:
                return f"footnote {named[0].n} names {base} but the cell has no marker"
            if page.read_default is not None:
                mults.add(page.read_default)
        if page.cache_mult is not None:
            mults.add(page.cache_mult.read_over.get(base, page.cache_mult.read_default))
        if not mults:
            return "the page states no cache hit multiplier for this model"
        if len(mults) > 1:
            return f"the page's cache hit multipliers disagree for {base} ({', '.join(sorted(f'{m.normalize():f}x' for m in mults))})"
        (mult,) = mults
        return _expect(ex, inp, mult, "cache hit", f"{mult.normalize():f}x its base input")

    # compare ---------------------------------------------------------------------------------------------------
    def _compare(self, rec: Recorder, locator: tuple[str, ...], mine: float | None, ex: Expect, base: str) -> None:
        price = ex.per_token
        if ex.value is None:
            if mine is not None:
                rec.uncovered(locator)
                rec.note(f"the page lists no {ex.label} price for {base}: `{locator[-1]}` is not compared")
            return
        if ex.promo is not None:
            rec.result.promo_active = True
            rec.result.partial = True
            if ex.promo.promo_end:
                rec.result.promo = ex.promo.promo_end
            rec.uncovered(locator)
            rec.note(f"the page announces introductory / promotional pricing on {base} {ex.label} "
                     f"(footnote {ex.promo.n}): the catalog keeps the list price")
            return
        if ex.unrecognised:
            rec.uncovered(locator)
            rec.note(ex.unrecognised)
            return
        if ex.reason:
            if mine is None:
                rec.absent(locator, price)
            else:
                rec.uncovered(locator)
            rec.note(f"{base} {ex.label}: {ex.reason}")
            return
        assert price is not None
        if mine is None:
            rec.absent(locator, price)
            return
        rec.add(compare(locator, mine, price, note=f"page: {base} {ex.label} ${_fmt(ex.value)} / MTok"))

    def _compare_tiers(self, rec: Recorder, entry: dict, region: str, long: Row | None, exps: dict[str, Expect]) -> None:
        tp = entry.get("tiered_pricing")
        top = cost_locator(region, "tiered_pricing")
        base = long.ident.base if long else ""
        if long is None:
            if tp is not None:
                rec.uncovered(top)
                rec.note("the file has tiered_pricing but the page lists one price for the model: not compared")
            return
        threshold = long.ident.threshold
        rec.compared.add(top)
        if not isinstance(tp, dict):
            for key, ex in exps.items():
                if ex.value is not None:
                    rec.absent(cost_locator(region, "tiered_pricing", key), ex.per_token or 0.0)
            rec.note(f"the page prices prompts over {threshold:,} tokens differently; the file has no tiered_pricing")
            return
        mode = tp.get("pricing_mode")
        if mode != "cumulative":
            rec.uncovered(cost_locator(region, "tiered_pricing", "pricing_mode"))
            rec.note(f"the page bills the whole request at the higher rate once the prompt is over {threshold:,} "
                     f"tokens (`cumulative`); the file says `{mode or 'marginal (default)'}`")
        for key in tp:
            if key not in exps and key != "pricing_mode":
                rec.uncovered(cost_locator(region, "tiered_pricing", str(key)))
        for key, ex in exps.items():
            items = tp.get(key)
            if items is None:
                if ex.value is not None:
                    rec.absent(cost_locator(region, "tiered_pricing", key), ex.per_token or 0.0)
                continue
            hit = None
            for item in items if isinstance(items, list) else []:
                if isinstance(item, dict) and num(item.get("from")) == float(threshold):
                    hit = item
                else:
                    frm = item.get("from") if isinstance(item, dict) else item
                    rec.uncovered(cost_locator(region, "tiered_pricing", key, f"from={frm}"))
                    rec.note(f"tiered_pricing.{key} has a tier from {frm}; the page gives only the {threshold:,} threshold")
            if hit is None:
                if ex.value is not None:
                    rec.absent(cost_locator(region, "tiered_pricing", key, f"from={threshold}", "cost_per_token"),
                               ex.per_token or 0.0)
                continue
            self._compare(rec, cost_locator(region, "tiered_pricing", key, f"from={threshold}", "cost_per_token"),
                          num(hit.get("cost_per_token")), ex, base)
        inexpressible = []
        if long.prices.get("write_1h") is not None:
            inexpressible.append(f"1h cache write ${_fmt(long.prices['write_1h'])}")
        if long.batch:
            inexpressible.append("batch ${} / ${}".format(_fmt(long.batch["batch_input"]), _fmt(long.batch["batch_output"]))
                                 if long.batch.get("batch_input") is not None and long.batch.get("batch_output") is not None
                                 else "batch")
        if inexpressible:
            rec.note(f"over {threshold:,} tokens the page also prices {', '.join(inexpressible)} per MTok; "
                     "tiered_pricing cannot hold them")

def _group_problem(base: str, group: dict[str | None, Row]) -> str | None:
    tiers = set(group)
    if tiers == {None}:
        return None
    if tiers == {"up_to", "over"}:
        if group["up_to"].ident.threshold != group["over"].ident.threshold:
            return f"{base}: the up-to and over rows use different thresholds"
        return None
    return f"{base} has an ambiguous set of rows ({sorted(str(t) for t in tiers)})"

def _expect(ex: Expect, ref: Decimal | None, mult: Decimal, what: str, rule: str) -> str | None:
    """None when ex.value == ref * mult (within the price tolerance), else the contradiction."""
    if ref is None:
        return f"the page has no price to derive the {what} from"
    want = ref * mult
    assert ex.value is not None
    if same(float(ex.value), float(want)):
        return None
    return f"the page's {what} ${_fmt(ex.value)} is not {rule} (${_fmt(want)})"

SOURCES[NAME] = AnthropicPricingSource

# ---------------------------------------------------------------------------------------------------------------
# CLI for the schedule and for humans

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--fingerprints", action="store_true", help="print the row fingerprints as JSON")
    ap.add_argument("--aliases", action="store_true", help="print catalog file -> page model")
    ap.add_argument("--file", help="read the page from this file instead of the network")
    ap.add_argument("--root", default=str(Path(__file__).resolve().parents[3]))
    args = ap.parse_args(argv)
    fetch: Fetch | None = (lambda _u: Path(args.file).read_bytes()) if args.file else None
    source = AnthropicPricingSource(fetch)
    if args.fingerprints:
        rows = source.row_fingerprints()
        json.dump({"source": URL, "rows": rows, "extras": source.extra_fingerprints()}, sys.stdout, indent=1, sort_keys=True)
        print()
    if args.aliases:
        import yaml
        source.prepare()
        docs = {}
        for p in sorted((Path(args.root) / "providers" / "anthropic").glob("*.yaml")):
            d = yaml.safe_load(p.read_text())
            if isinstance(d, dict) and "model" in d:
                docs[p.relative_to(args.root).as_posix()] = d
        assert source._page is not None
        for path, (base, why) in alias_table(docs, source._page).items():
            print(f"{path}\t{base or '-'}\t{why}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
