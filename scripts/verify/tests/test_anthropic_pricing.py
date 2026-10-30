"""Anthropic pricing page adapter, offline. The fixture is the REAL page (fetched 2026-10-28, trimmed to the pricing
sections). Corrupted variants are made from it by text replacement, so a test failing here means the parser's
fail-closed behaviour changed, not that the fixture drifted."""
from __future__ import annotations

import copy

import pytest

from verify.sources import SOURCES
from verify.sources.anthropic_pricing import (URL, AnthropicPricingSource, PageStructureError, alias_table,
                                              parse_page)

from .fx import FakeFetch, outage, raw

FIXTURE = raw("anthropic-pricing.md").decode("utf-8")
LOC = ("costs", "region=*")
FN3 = ("The $2/$10 per million input/output token pricing for Claude Sonnet 5, announced at launch as introductory pricing "
       "through August 31, 2026, is now the standard price. The previously scheduled increase to $3/$15 per million "
       "input/output tokens on September 1, 2026 will not occur.")


def mutate(text: str, old: str, new: str, count: int = 1) -> str:
    assert old in text, f"fixture no longer contains {old!r}"
    return text.replace(old, new, count)


def source(text: str | bytes | None = None, **kw):
    body = (FIXTURE if text is None else text)
    fetch = FakeFetch({URL: body.encode() if isinstance(body, str) else body})
    return AnthropicPricingSource(fetch, **kw), fetch


def cost(**kw):
    return {"region": "*", **kw}


def check(s, model: str, canonical: str | None = None, **costs):
    doc = {"model": model, "costs": [cost(**costs)]}
    if canonical:
        doc["canonical_model"] = canonical
    return s.check(f"providers/anthropic/{model}.yaml", doc)


# The real catalog values of claude-opus-5-5 (page: $4 / $20, 5m $5, 1h $8, hit $0.20, batch $2 / $10).
OPUS55 = dict(input_cost_per_token=4e-6, output_cost_per_token=2e-5, cache_creation_input_token_cost=5e-6,
              cache_creation_input_token_cost_per_hour=8e-6, cache_read_input_token_cost=2e-7,
              input_cost_per_token_batches=2e-6, output_cost_per_token_batches=1e-5)
OPUS5 = dict(input_cost_per_token=5e-6, output_cost_per_token=2.5e-5, cache_creation_input_token_cost=6.25e-6,
             cache_creation_input_token_cost_per_hour=1e-5, cache_read_input_token_cost=5e-7,
             input_cost_per_token_batches=2.5e-6, output_cost_per_token_batches=1.25e-5)
SONNET5 = dict(input_cost_per_token=2e-6, output_cost_per_token=1e-5, cache_creation_input_token_cost=2.5e-6,
               cache_creation_input_token_cost_per_hour=4e-6, cache_read_input_token_cost=2e-7,
               input_cost_per_token_batches=1e-6, output_cost_per_token_batches=5e-6)
HAIKU55 = dict(input_cost_per_token=1e-7, output_cost_per_token=5e-7, cache_creation_input_token_cost=1.25e-7,
               cache_creation_input_token_cost_per_hour=2e-7, cache_read_input_token_cost=1e-8,
               input_cost_per_token_batches=5e-8, output_cost_per_token_batches=2.5e-7)
HAIKU55_TIERS = {"cache_read": [{"cost_per_token": 5e-8, "from": 100000}],
                 "cache_write": [{"cost_per_token": 6.25e-7, "from": 100000}],
                 "input": [{"cost_per_token": 5e-7, "from": 100000}],
                 "output": [{"cost_per_token": 2.5e-6, "from": 100000}], "pricing_mode": "cumulative"}


def opus55(s, **over):
    return check(s, "claude-opus-5-5", "anthropic/claude-opus-5-5", **{**OPUS55, **over})


# ---- identity, parsing, happy path ------------------------------------------------------------------------

def test_registered_and_covers_only_anthropic():
    assert SOURCES["anthropic-pricing-page"] is AnthropicPricingSource
    s, _ = source()
    assert s.covers("anthropic") and not s.covers("openrouter") and s.name == "anthropic-pricing-page"


def test_real_page_parses_into_21_model_rows_with_batch_joined():
    page = parse_page(FIXTURE)
    assert len(page.rows) == 21 and len(page.bases) == 20
    opus = page.rows[("Claude Opus 5.5", None)]
    assert [str(opus.prices[c]) for c in ("input", "write_5m", "write_1h", "read", "output")] == ["4", "5", "8", "0.20", "20"]
    assert opus.marks["read"] == "2" and opus.batch is not None and str(opus.batch["batch_output"]) == "10"
    assert page.rows[("Claude Haiku 5.5", "over")].ident.threshold == 100000
    assert page.read_default is not None and str(page.read_default) == "0.1"
    assert str(page.batch_factor) == "0.5"
    assert page.cache_mult is not None and page.cache_mult.read_over["Claude Opus 5.5"] == page.footnotes["2"].mult


def test_fully_verified_on_the_real_catalog_values():
    s, fetch = source()
    r = opus55(s)
    assert r.fully_verified and len(r.checks) == 7 and r.conflicts == [] and r.uncovered == []
    assert all(c.writable for c in r.checks)
    assert fetch.calls == [URL]


def test_dollars_per_mtok_become_dollars_per_token():
    s, _ = source()
    r = opus55(s)
    got = {c.locator[-1]: c.source_value for c in r.checks}
    assert got["input_cost_per_token"] == 4e-6 and got["cache_read_input_token_cost"] == 2e-7
    assert got["output_cost_per_token_batches"] == 1e-5


def test_a_wrong_catalog_price_is_a_writable_conflict_with_the_page_value():
    s, _ = source()
    r = opus55(s, input_cost_per_token=5e-6)
    (c,) = r.conflicts
    assert c.locator == (*LOC, "input_cost_per_token") and (c.file_value, c.source_value) == (5e-6, 4e-6) and c.writable
    assert "Claude Opus 5.5" in c.note and not r.fully_verified


def test_tolerance_is_half_a_percent():
    s, _ = source()
    assert opus55(s, input_cost_per_token=4.015e-6).fully_verified   # +0.37%
    assert [c.locator[-1] for c in opus55(s, input_cost_per_token=4.03e-6).conflicts] == ["input_cost_per_token"]  # +0.75%


# ---- cache write 5m vs 1h, batch --------------------------------------------------------------------------

def test_5m_and_1h_cache_writes_are_not_interchangeable():
    s, _ = source()
    r = opus55(s, cache_creation_input_token_cost=8e-6, cache_creation_input_token_cost_per_hour=5e-6)
    assert sorted(c.locator[-1] for c in r.conflicts) == ["cache_creation_input_token_cost",
                                                          "cache_creation_input_token_cost_per_hour"]


def test_batch_input_and_output_are_not_interchangeable():
    s, _ = source()
    r = opus55(s, input_cost_per_token_batches=1e-5, output_cost_per_token_batches=2e-6)
    assert sorted(c.locator[-1] for c in r.conflicts) == ["input_cost_per_token_batches", "output_cost_per_token_batches"]


def test_a_model_without_a_batch_row_has_batch_uncovered_not_derived_from_the_discount():
    lines = [l for l in FIXTURE.split("\n") if not (l.startswith("| Claude Opus 5.5") and l.count("$") == 2 and "USD" not in l)]  # the batch row
    assert len(lines) == len(FIXTURE.split("\n")) - 1
    s, _ = source("\n".join(lines))
    r = opus55(s)
    assert r.conflicts == [] and r.partial
    assert sorted(u.rsplit(".", 1)[-1] for u in r.uncovered) == ["input_cost_per_token_batches", "output_cost_per_token_batches"]
    assert len(r.checks) == 5


def test_a_batch_price_that_contradicts_the_stated_discount_is_uncovered_never_verified():
    text = mutate(FIXTURE, "| Claude Opus 5.5                                                                                                                                                        | $2 / MTok    | $10 / MTok    |",
                  "| Claude Opus 5.5                                                                                                                                                        | $3 / MTok    | $10 / MTok    |")
    s, _ = source(text)
    r = opus55(s, input_cost_per_token_batches=3e-6)   # the file agrees with the (typo'd) table
    assert r.conflicts == [] and "costs.region=*.input_cost_per_token_batches" in r.uncovered
    assert any("batch input" in n and "not 0.5x" in n for n in r.notes) and not r.fully_verified
    assert len(r.checks) == 6


def test_the_stated_batch_discount_is_what_is_cross_checked():
    text = mutate(FIXTURE, "50 percent discount", "30 percent discount")
    s, _ = source(text)
    r = opus55(s)
    assert r.conflicts == [] and not r.fully_verified
    assert {"costs.region=*.input_cost_per_token_batches", "costs.region=*.output_cost_per_token_batches"} <= set(r.uncovered)
    text = mutate(FIXTURE, "with a 50 percent discount on both input and output tokens", "at a reduced rate")
    s, _ = source(text)
    r = opus55(s)
    assert not r.fully_verified and any("Batch API discount sentence is unreadable" in n for n in r.notes)


# ---- footnote multipliers ---------------------------------------------------------------------------------

def test_footnote_multiplier_applies_only_to_the_models_it_names():
    s, _ = source()
    assert opus55(s).fully_verified                                        # 0.05x on Opus 5.5
    r = check(s, "claude-opus-5", "anthropic/claude-opus-5", **OPUS5)
    assert r.fully_verified                                                # 0.1x on Opus 5 (not footnoted)
    wrong = check(s, "claude-opus-5", "anthropic/claude-opus-5", **{**OPUS5, "cache_read_input_token_cost": 2.5e-7})
    assert [c.locator[-1] for c in wrong.conflicts] == ["cache_read_input_token_cost"]   # 0.05x is not Opus 5's


def test_both_footnote_models_and_the_0025_group_verify():
    s, _ = source()
    sonnet = check(s, "claude-sonnet-5-5", "anthropic/claude-sonnet-5-5", input_cost_per_token=2e-6, output_cost_per_token=1e-5,
                   cache_read_input_token_cost=1e-7, cache_creation_input_token_cost=2.5e-6,
                   cache_creation_input_token_cost_per_hour=4e-6, input_cost_per_token_batches=1e-6,
                   output_cost_per_token_batches=5e-6)
    assert sonnet.fully_verified
    fable = check(s, "claude-fable-5-1", "anthropic/claude-fable-5-1", input_cost_per_token=1e-5, output_cost_per_token=5e-5,
                  cache_read_input_token_cost=2.5e-7, cache_creation_input_token_cost=1.25e-5,
                  cache_creation_input_token_cost_per_hour=2e-5, input_cost_per_token_batches=5e-6,
                  output_cost_per_token_batches=2.5e-5)
    assert fable.fully_verified
    fable5 = check(s, "claude-fable-5", "anthropic/claude-fable-5", input_cost_per_token=1e-5, cache_read_input_token_cost=1e-6)
    assert [c.status for c in fable5.checks] == ["verified", "verified"]


def test_a_footnote_multiplier_that_does_not_match_the_cell_is_uncovered_not_verified():
    text = mutate(FIXTURE, "priced at 0.05x the base input price", "priced at 0.5x the base input price")
    s, _ = source(text)
    r = opus55(s)
    assert "costs.region=*.cache_read_input_token_cost" in r.uncovered and r.conflicts == []
    assert not r.fully_verified and any("cache hit" in n and "disagree" in n for n in r.notes)
    # the file holding the footnote's (mis-parsed) value must not come out verified either
    r2 = opus55(s, cache_read_input_token_cost=2e-6)
    assert "costs.region=*.cache_read_input_token_cost" in r2.uncovered and r2.conflicts == []


def test_only_the_final_arithmetic_catches_a_footnote_and_prose_table_that_agree_on_a_wrong_multiplier():
    text = mutate(FIXTURE, "priced at 0.05x the base input price", "priced at 0.5x the base input price")
    text = mutate(text, "0.05x on Claude Opus 5.5 and Claude Sonnet 5.5)", "0.5x on Claude Opus 5.5 and Claude Sonnet 5.5)")
    s, _ = source(text)
    r = opus55(s)
    assert "costs.region=*.cache_read_input_token_cost" in r.uncovered and r.conflicts == [] and not r.fully_verified
    assert any("cache hit $0.2 is not 0.5x its base input" in n for n in r.notes)


def test_a_contradicted_field_missing_from_the_file_is_missing_in_file_not_silent():
    text = mutate(FIXTURE, "priced at 0.05x the base input price", "priced at 0.5x the base input price")
    s, _ = source(text)
    only = {k: v for k, v in OPUS55.items() if k != "cache_read_input_token_cost"}
    r = check(s, "claude-opus-5-5", "anthropic/claude-opus-5-5", **only)
    assert r.uncovered == ["costs.region=*.cache_read_input_token_cost"] and r.partial


def test_two_page_models_for_one_slug_do_not_resolve():
    from verify.sources.anthropic_pricing import resolve
    index = {"claude-opus-4": ["Claude Opus 4", "Claude Opus 4 Fast"]}
    base, why = resolve("providers/anthropic/claude-opus-4.yaml", {"model": "claude-opus-4"}, index)
    assert base is None and "matches several page models" in why


def test_a_footnote_naming_a_model_without_its_marker_is_a_contradiction():
    text = mutate(FIXTURE, "on Claude Opus 5.5 and Claude Sonnet 5.5 are priced", "on Claude Opus 5.5, Claude Opus 5 and Claude Sonnet 5.5 are priced")
    s, _ = source(text)
    r = check(s, "claude-opus-5", "anthropic/claude-opus-5", **OPUS5)
    assert "costs.region=*.cache_read_input_token_cost" in r.uncovered and not r.fully_verified
    assert any("names Claude Opus 5 but the cell has no marker" in n for n in r.notes)


def test_a_marker_on_a_model_the_footnote_does_not_name_is_a_contradiction():
    text = mutate(FIXTURE, "on Claude Opus 5.5 and Claude Sonnet 5.5 are priced", "on Claude Opus 5.5 are priced")
    s, _ = source(text)
    r = check(s, "claude-sonnet-5-5", "anthropic/claude-sonnet-5-5", input_cost_per_token=2e-6, cache_read_input_token_cost=1e-7)
    assert "costs.region=*.cache_read_input_token_cost" in r.uncovered
    assert any("does not name Claude Sonnet 5.5" in n for n in r.notes)


def test_the_prose_multiplier_table_must_agree_with_the_footnotes():
    text = mutate(FIXTURE, "0.05x on Claude Opus 5.5 and Claude Sonnet 5.5)", "0.07x on Claude Opus 5.5 and Claude Sonnet 5.5)")
    s, _ = source(text)
    r = opus55(s)
    assert "costs.region=*.cache_read_input_token_cost" in r.uncovered and not r.fully_verified
    assert any("multipliers disagree" in n for n in r.notes)


def test_a_footnote_marker_without_a_footnote_is_uncovered():
    text = mutate(FIXTURE, "<sup>2</sup>", "<sup>9</sup>")
    s, _ = source(text)
    r = opus55(s)
    assert "costs.region=*.cache_read_input_token_cost" in r.uncovered and any("footnote 9 is not on the page" in n for n in r.notes)


def test_cache_write_multipliers_are_cross_checked_against_the_multiplier_table():
    text = mutate(FIXTURE, "| 5-minute cache write | 1.25x base input price", "| 5-minute cache write | 1.5x base input price")
    s, _ = source(text)
    r = opus55(s)
    assert "costs.region=*.cache_creation_input_token_cost" in r.uncovered and r.conflicts == []
    assert any("5m cache write" in n and "1.5x" in n for n in r.notes)


def test_an_unreadable_multiplier_table_degrades_the_cache_fields_but_not_the_page():
    text = mutate(FIXTURE, "| Cache operation      | Multiplier", "| Cache op             | Multiplier")
    s, _ = source(text)
    r = opus55(s)
    assert r.partial and len(r.checks) == 5          # input, output, cache hit (its footnote still cross-checks it), batch x2
    assert sorted(u.rsplit(".", 1)[-1] for u in r.uncovered) == [
        "cache_creation_input_token_cost", "cache_creation_input_token_cost_per_hour"]
    assert any("cache multiplier" in n for n in r.notes)


# ---- promotions and footnotes on prices -----------------------------------------------------------------------

def test_sonnet_5_is_verified_because_the_footnote_says_the_intro_price_is_now_standard():
    s, _ = source()
    r = check(s, "claude-sonnet-5", "anthropic/claude-sonnet-5", **SONNET5)
    assert r.fully_verified and not r.promo_active and r.promo is None


def test_an_introductory_price_footnote_is_a_promo_never_a_conflict():
    text = mutate(FIXTURE, FN3, "The $2/$10 per million input/output token pricing for Claude Sonnet 5 is introductory pricing through December 31, 2026; the price rises to $3/$15 afterwards.")
    s, _ = source(text)
    r = check(s, "claude-sonnet-5", "anthropic/claude-sonnet-5", **SONNET5)
    assert r.promo_active and r.promo == "2026-12-31" and r.partial and r.conflicts == []
    assert {"costs.region=*.input_cost_per_token", "costs.region=*.output_cost_per_token"} <= set(r.uncovered)
    assert {c.locator[-1] for c in r.checks} == {"cache_creation_input_token_cost", "cache_creation_input_token_cost_per_hour",
                                                 "cache_read_input_token_cost", "input_cost_per_token_batches",
                                                 "output_cost_per_token_batches"}
    # a file holding a different (list) price is still not a conflict while the page says the price is promotional
    assert check(s, "claude-sonnet-5", "anthropic/claude-sonnet-5", **{**SONNET5, "input_cost_per_token": 3e-6}).conflicts == []


def test_an_unrecognised_footnote_on_a_price_leaves_it_uncovered():
    text = mutate(FIXTURE, FN3, "Applies to prompts in English only.")
    s, _ = source(text)
    r = check(s, "claude-sonnet-5", "anthropic/claude-sonnet-5", **SONNET5)
    assert {"costs.region=*.input_cost_per_token", "costs.region=*.output_cost_per_token"} <= set(r.uncovered)
    assert not r.promo_active and not r.fully_verified


# ---- tiers (Haiku 5.5) ------------------------------------------------------------------------------------

def haiku(s, tiers=None, **over):
    entry = {**HAIKU55, **over}
    if tiers is not None:
        entry["tiered_pricing"] = tiers
    return check(s, "claude-haiku-5-5", "anthropic/claude-haiku-5-5", **entry)


def test_haiku_5_5_base_row_and_over_100k_row_both_verify():
    s, _ = source()
    r = haiku(s, copy.deepcopy(HAIKU55_TIERS))
    assert r.fully_verified and len(r.checks) == 11 and r.uncovered == []
    assert (*LOC, "tiered_pricing", "input", "from=100000", "cost_per_token") in {c.locator for c in r.checks}
    assert any("1h cache write $1" in n and "tiered_pricing cannot hold" in n for n in r.notes)


def test_haiku_5_5_top_level_is_the_up_to_row_not_the_over_row():
    s, _ = source()
    r = haiku(s, copy.deepcopy(HAIKU55_TIERS), input_cost_per_token=5e-7)
    assert [c.locator[-1] for c in r.conflicts] == ["input_cost_per_token"]


def test_a_wrong_tier_price_is_a_writable_conflict_at_the_tier_locator():
    s, _ = source()
    tiers = copy.deepcopy(HAIKU55_TIERS)
    tiers["output"][0]["cost_per_token"] = 1e-6
    (c,) = haiku(s, tiers).conflicts
    assert c.locator == (*LOC, "tiered_pricing", "output", "from=100000", "cost_per_token") and c.writable
    assert c.source_value == 2.5e-6


def test_tier_cache_write_is_the_5m_rate():
    s, _ = source()
    tiers = copy.deepcopy(HAIKU55_TIERS)
    tiers["cache_write"][0]["cost_per_token"] = 1e-6   # the 1h over-threshold rate
    assert [c.locator[-2:] for c in haiku(s, tiers).conflicts] == [("from=100000", "cost_per_token")]


def test_marginal_or_missing_pricing_mode_leaves_the_tiers_unverified():
    s, _ = source()
    tiers = copy.deepcopy(HAIKU55_TIERS)
    del tiers["pricing_mode"]
    r = haiku(s, tiers)
    assert "costs.region=*.tiered_pricing.pricing_mode" in r.uncovered and r.partial and r.conflicts == []
    assert any("cumulative" in n for n in r.notes)


def test_unknown_threshold_tier_is_uncovered_and_a_missing_tier_is_missing_in_file():
    s, _ = source()
    tiers = copy.deepcopy(HAIKU55_TIERS)
    tiers["input"][0]["from"] = 200000
    r = haiku(s, tiers)
    assert "costs.region=*.tiered_pricing.input.from=200000" in r.uncovered
    assert "costs.region=*.tiered_pricing.input.from=100000.cost_per_token" in r.uncovered
    r = haiku(s)   # no tiered_pricing at all
    assert r.partial and any("has no tiered_pricing" in n for n in r.notes)
    assert "costs.region=*.tiered_pricing.input" in r.uncovered


def test_tiers_on_a_one_price_model_are_uncovered():
    s, _ = source()
    r = check(s, "claude-opus-5-5", "anthropic/claude-opus-5-5", **OPUS55, tiered_pricing=copy.deepcopy(HAIKU55_TIERS))
    assert "costs.region=*.tiered_pricing" in r.uncovered and r.partial


def test_a_lone_over_row_or_mismatched_thresholds_make_the_model_ambiguous():
    lines = [l for l in FIXTURE.split("\n") if "for prompts up to 100,000" not in l]
    s, _ = source("\n".join(lines))
    r = haiku(s, copy.deepcopy(HAIKU55_TIERS))
    assert r.checks == [] and r.partial and any("ambiguous set of rows" in n for n in r.notes)
    text = mutate(FIXTURE, "for prompts over 100,000 tokens", "for prompts over 200,000 tokens", 2)
    s, _ = source(text)
    r = haiku(s, copy.deepcopy(HAIKU55_TIERS))
    assert r.checks == [] and any("different thresholds" in n for n in r.notes)


# ---- the alias table ----------------------------------------------------------------------------------------

def table(**docs):
    return alias_table(docs, parse_page(FIXTURE))


def d(model, canonical=None, **kw):
    out = {"model": model, **kw}
    if canonical is not None:
        out["canonical_model"] = canonical
    return out


def test_dated_snapshots_latest_and_the_older_name_order_resolve():
    t = table(**{
        "providers/anthropic/claude-opus-4-1-20250805.yaml": d("claude-opus-4-1-20250805", "anthropic/claude-opus-4-1"),
        "providers/anthropic/claude-opus-4-1.yaml": d("claude-opus-4-1", "anthropic/claude-opus-4-1"),
        "providers/anthropic/claude-opus-4-20250514.yaml": d("claude-opus-4-20250514", "anthropic/claude-opus-4"),
        "providers/anthropic/claude-4-opus-20250514.yaml": d("claude-4-opus-20250514", "anthropic/claude-4-opus"),
        "providers/anthropic/claude-3-5-haiku-20241022.yaml": d("claude-3-5-haiku-20241022", "anthropic/claude-3-5-haiku"),
        "providers/anthropic/claude-haiku-5-5.yaml": d("claude-haiku-5-5", "anthropic/claude-haiku-5-5"),
    })
    got = {p.split("/")[-1][:-5]: v[0] for p, v in t.items()}
    assert got == {"claude-opus-4-1-20250805": "Claude Opus 4.1", "claude-opus-4-1": "Claude Opus 4.1",
                   "claude-opus-4-20250514": "Claude Opus 4", "claude-4-opus-20250514": "Claude Opus 4",
                   "claude-3-5-haiku-20241022": "Claude Haiku 3.5",
                   "claude-haiku-5-5": "Claude Haiku 5.5"}


def test_4_1_is_never_confused_with_4_nor_4_5_with_4():
    t = table(**{"providers/anthropic/claude-opus-4-1.yaml": d("claude-opus-4-1"),
                 "providers/anthropic/claude-opus-4-5.yaml": d("claude-opus-4-5"),
                 "providers/anthropic/claude-opus-4.yaml": d("claude-opus-4")})
    assert t["providers/anthropic/claude-opus-4-1.yaml"][0] == "Claude Opus 4.1"
    assert t["providers/anthropic/claude-opus-4-5.yaml"][0] == "Claude Opus 4.5"
    assert t["providers/anthropic/claude-opus-4.yaml"][0] == "Claude Opus 4"


def test_a_snapshot_suffix_must_be_a_known_snapshot_of_that_model():
    from verify.sources.anthropic_pricing import KNOWN_SNAPSHOTS, resolve, slug_index
    index = slug_index(parse_page(FIXTURE).bases)
    ok = ("providers/anthropic/claude-opus-5-20251101.yaml", {"model": "claude-opus-5-20251101"})
    base, why = resolve(*ok, index)
    assert base is None and "not a known snapshot of `claude-opus-5`" in why      # a free date does not resolve
    # a date that is known for ANOTHER model does not borrow its identity
    base, why = resolve("providers/anthropic/claude-opus-4-5-20250805.yaml", {"model": "claude-opus-4-5-20250805"}, index)
    assert base is None and "not a known snapshot" in why
    base, _ = resolve(*ok, index, {"claude-opus-5": frozenset({"20251101"})})
    assert base == "Claude Opus 5"
    base, _ = resolve("providers/anthropic/claude-opus-5-latest.yaml", {"model": "claude-opus-5-latest"}, index)
    assert base is None
    base, _ = resolve("providers/anthropic/claude-opus-5-latest.yaml", {"model": "claude-opus-5-latest"}, index,
                      {"claude-opus-5": frozenset({"latest"})})
    assert base == "Claude Opus 5"
    # the table is the catalog's: every id in it is a file there
    from pathlib import Path
    root = Path(__file__).resolve().parents[3] / "providers" / "anthropic"
    ids = {p.stem for p in root.glob("claude-*.yaml")}
    assert {f"{slug}-{x}" for slug, xs in KNOWN_SNAPSHOTS.items() for x in xs} <= ids


def test_a_file_with_an_unknown_date_is_uncovered_not_verified_as_the_base_model():
    s, _ = source()
    r = check(s, "claude-opus-5-20251101", "anthropic/claude-opus-5", **OPUS5)
    assert r.checks == [] and r.partial and "not a known snapshot" in r.notes[0]


@pytest.mark.parametrize("model,canonical,why", [
    ("claude-opus-4-1-20250805", "anthropic/claude-opus-4", "canonical_model"),       # canonical disagrees
    ("claude-opus-4-1-2025", None, "not on Anthropic"),              # not an 8-digit date... slug is opus-4-1-2025
    ("claude-opus-4-1-20251399", "anthropic/claude-opus-4-1", "not a known snapshot"),
    ("claude-opus-4-1-beta", "anthropic/claude-opus-4-1", ""),
    ("claude-opus-9-9", "anthropic/claude-opus-9-9", "not on Anthropic's pricing page"),
    ("claude-3-5-sonnet-latest", "anthropic/claude-3-5-sonnet", "not on Anthropic's pricing page"),
    ("gpt-5", None, "not a claude"),
    ("claude-opus-4-1", "anthropic/claude-opus-4-1-extra", "canonical_model"),
])
def test_ambiguous_or_unlisted_ids_do_not_resolve(model, canonical, why):
    base, reason = table(**{f"providers/anthropic/{model}.yaml": d(model, canonical)})[f"providers/anthropic/{model}.yaml"]
    assert base is None and why in reason


def test_a_file_name_that_differs_from_the_model_id_does_not_resolve():
    t = table(**{"providers/anthropic/claude-opus-5.yaml": d("claude-opus-5-5")})
    assert t["providers/anthropic/claude-opus-5.yaml"][0] is None
    s, fetch = source()
    r = s.check("providers/anthropic/claude-opus-5.yaml", {"model": ["x"], "costs": [cost(input_cost_per_token=1e-6)]})
    assert r.partial and r.checks == []


def test_a_file_not_on_the_page_is_partial_with_its_fields_uncovered():
    s, _ = source()
    r = check(s, "claude-3-5-sonnet-latest", "anthropic/claude-3-5-sonnet", input_cost_per_token=3e-6)
    assert r.partial and r.checks == [] and r.uncovered == ["costs.region=*.input_cost_per_token"]
    assert "not on Anthropic's pricing page" in r.notes[0]


def test_dated_snapshot_files_are_checked_against_the_page_row_of_their_model():
    s, _ = source()
    r = check(s, "claude-opus-4-1-20250805", "anthropic/claude-opus-4-1", input_cost_per_token=1.5e-5, output_cost_per_token=7.5e-5,
              cache_creation_input_token_cost=1.875e-5, cache_creation_input_token_cost_per_hour=3e-5,
              cache_read_input_token_cost=1.5e-6, input_cost_per_token_batches=7.5e-6, output_cost_per_token_batches=3.75e-5)
    assert r.fully_verified and r.conflicts == [] and len(r.checks) == 7   # the retired annotation is a note only
    assert any("retired on the first-party API per the page" in n and "lifecycle is not compared" in n for n in r.notes)


# ---- scope of a file -----------------------------------------------------------------------------------------

def test_other_regions_and_unknown_fields_stay_uncovered():
    s, _ = source()
    doc = {"model": "claude-opus-5-5", "canonical_model": "anthropic/claude-opus-5-5",
           "costs": [cost(**OPUS55, input_cost_per_token_priority=1e-5), {"region": "eu", "input_cost_per_token": 4.4e-6}]}
    r = s.check("providers/anthropic/claude-opus-5-5.yaml", doc)
    assert set(r.uncovered) == {"costs.region=*.input_cost_per_token_priority", "costs.region=eu.input_cost_per_token"}
    assert r.partial and len(r.checks) == 7


def test_missing_in_file_and_not_on_page_are_uncovered_never_conflicts():
    s, _ = source()
    without_1h = {k: v for k, v in OPUS55.items() if k != "cache_creation_input_token_cost_per_hour"}
    r = check(s, "claude-opus-5-5", "anthropic/claude-opus-5-5", **without_1h)
    assert r.conflicts == [] and r.uncovered == ["costs.region=*.cache_creation_input_token_cost_per_hour"]
    assert any(n.startswith("missing in file") for n in r.notes)


def test_a_page_dash_means_not_offered_and_the_file_field_is_uncovered():
    row = "| Claude Haiku 4.5                                                                                                                                                       | $1 / MTok             | $1.25 / MTok    | $2 / MTok       | $0.10 / MTok             | $5 / MTok              |"
    text = mutate(FIXTURE, row, row.replace("| $2 / MTok       |", "| —               |"))
    s, _ = source(text)
    r = check(s, "claude-haiku-4-5", "anthropic/claude-haiku-4-5", input_cost_per_token=1e-6, cache_creation_input_token_cost_per_hour=2e-6)
    assert r.conflicts == [] and "costs.region=*.cache_creation_input_token_cost_per_hour" in r.uncovered
    assert any("lists no 1h cache write price" in n for n in r.notes)


# ---- fail closed ---------------------------------------------------------------------------------------------

MODEL_ROW_OPUS55 = "| Claude Opus 5.5 "

def corrupt_header(t):    # renamed header cell
    return mutate(t, "| Base input tokens     |", "| Input tokens          |")

def corrupt_extra_column(t):   # a column added to every row of the model table
    out, inside = [], False
    for l in t.split("\n"):
        if l.startswith("| Model ") and "Base input tokens" in l:
            inside = True
        elif inside and not l.startswith("|"):
            inside = False
        if inside:
            l = l + (" Tier |" if "Base input" in l else (" :--- |" if l.startswith("| :--") else " x |"))
        out.append(l)
    return "\n".join(out)

def corrupt_one_row_extra_cell(t):
    return mutate(t, "| $0.20 / MTok<sup>2</sup> | $20 / MTok             |", "| $0.20 / MTok<sup>2</sup> | $20 / MTok             | $1 / MTok |")

def corrupt_unit(t):   # per-MTok -> per-KTok in one cell
    return mutate(t, "$20 / MTok             |", "$20 / KTok             |")

def corrupt_unit_currency(t):
    return mutate(t, "$4 / MTok             | $5 / MTok", "€4 / MTok             | $5 / MTok")

def corrupt_merged_cells(t):   # two cells merged into one
    return mutate(t, "| $4 / MTok             | $5 / MTok       |", "| $4 / MTok $5 / MTok |")

def corrupt_pipe_removed(t):
    return mutate(t, "$4 / MTok             | $5 / MTok", "$4 / MTok             $5 / MTok")

def corrupt_batch_header(t):
    return mutate(t, "| Batch input  | Batch output  |", "| Batch in     | Batch output  |")

def corrupt_unknown_annotation(t):
    return mutate(t, "| Claude Opus 5     ", "| Claude Opus 5 (preview) ")

def corrupt_name_pattern(t):
    return mutate(t, "| Claude Opus 5.5 ", "| Opus 5.5 ", 1)

def corrupt_duplicate_row(t):
    line = next(l for l in t.split("\n") if l.startswith("| Claude Opus 5.5") and "Base" not in l)
    return t.replace(line, line + "\n" + line, 1)

def corrupt_truncated(t):
    out, n = [], 0
    for l in t.split("\n"):
        if l.startswith("| Claude ") and n >= 3 and l.count("$") >= 5:   # drop model rows after the third
            continue
        out.append(l)
        if l.startswith("| Claude "):
            n += 1
    return "\n".join(out)

def corrupt_second_table(t):   # a "legacy models" table appears after the main one, in the same section
    return mutate(t, "Claude 4.7 and later models and Claude Mythos Preview use a newer tokenizer",
                  "Legacy models:\n\n| Model | Base input tokens |\n| --- | --- |\n| Claude Opus 3 | $15 / MTok |\n\nClaude 4.7 and later models and Claude Mythos Preview use a newer tokenizer")

def corrupt_html(t):
    return "<!doctype html><html><body>Not Found</body></html>"

def corrupt_currency_sentence(t):
    return mutate(t, "All prices are in USD.", "All prices are in EUR.")

def corrupt_heading(t):
    return mutate(t, "## Model pricing", "## Pricing of models")

def corrupt_sup_mid_cell(t):
    return mutate(t, "$0.20 / MTok<sup>2</sup>", "<sup>2</sup>$0.20 / MTok")

def corrupt_price_text(t):
    return mutate(t, "$20 / MTok             |", "TBD                    |")

def corrupt_no_batch_section(t):
    return mutate(t, "### Batch processing", "### Batches")

def corrupt_separator(t):   # the model table loses its separator row
    lines = t.split("\n")
    i = next(k for k, l in enumerate(lines) if l.startswith("| :---"))
    del lines[i]
    return "\n".join(lines)

CORRUPTIONS = [corrupt_header, corrupt_extra_column, corrupt_one_row_extra_cell, corrupt_unit, corrupt_unit_currency,
               corrupt_merged_cells, corrupt_pipe_removed, corrupt_batch_header, corrupt_unknown_annotation,
               corrupt_name_pattern, corrupt_duplicate_row, corrupt_truncated, corrupt_second_table, corrupt_html,
               corrupt_currency_sentence, corrupt_heading, corrupt_sup_mid_cell, corrupt_price_text,
               corrupt_no_batch_section, corrupt_separator]


@pytest.mark.parametrize("corrupt", CORRUPTIONS, ids=lambda f: f.__name__)
def test_a_changed_page_shape_refuses_everything_with_one_loud_note(corrupt):
    s, fetch = source(corrupt(FIXTURE))
    for model, canon, costs in (("claude-opus-5-5", "anthropic/claude-opus-5-5", OPUS55),
                                ("claude-sonnet-5", "anthropic/claude-sonnet-5", SONNET5),
                                ("claude-haiku-5-5", "anthropic/claude-haiku-5-5", HAIKU55)):
        r = check(s, model, canon, **costs)
        assert r.partial and r.checks == [] and not r.fully_verified, corrupt.__name__
        assert len(r.notes) == 1 and "changed shape" in r.notes[0], r.notes
        assert sorted(r.uncovered) == sorted(f"costs.region=*.{k}" for k in costs)
    assert fetch.calls == [URL]
    with pytest.raises(PageStructureError):
        s.row_fingerprints()


def test_the_unmodified_fixture_is_not_refused():
    s, _ = source()
    assert opus55(s).fully_verified and len(s.row_fingerprints()) == 21


def test_a_corrupted_page_never_yields_a_conflict_or_a_verified_check():
    for corrupt in CORRUPTIONS:
        s, _ = source(corrupt(FIXTURE))
        r = opus55(s, input_cost_per_token=9e-6)   # wrong on purpose: a refused page must not flag it either
        assert r.conflicts == [] and r.checks == []


def test_the_whole_page_must_be_utf8_and_not_huge():
    s, _ = source(b"\xff\xfe\x00bad")
    r = opus55(s)
    assert r.partial and r.checks == [] and "changed shape" in r.notes[0]
    s, _ = source(("x" * 3_000_100).encode())
    assert "changed shape" in opus55(s).notes[0]


# ---- outage, deadline, caching -------------------------------------------------------------------------------

def test_outage_is_partial_not_a_crash_and_is_tried_once():
    fetch = FakeFetch({URL: outage()})
    s = AnthropicPricingSource(fetch)
    for _ in range(4):
        r = opus55(s)
        assert r.partial and "unreachable" in r.notes[0] and r.checks == []
        assert len(r.uncovered) == 7
    assert fetch.calls == [URL]
    with pytest.raises(Exception):
        s.row_fingerprints()
    assert fetch.calls == [URL]


def test_a_404_is_an_outage_too():
    s = AnthropicPricingSource(FakeFetch({}))
    r = opus55(s)
    assert r.partial and "unreachable" in r.notes[0]


def test_run_deadline_stops_a_hung_source():
    clock = [0.0]

    def slow(url):
        clock[0] += 100.0
        raise TimeoutError("hung")

    s = AnthropicPricingSource(slow, deadline_s=60.0, clock=lambda: clock[0])
    r = opus55(s)
    assert r.partial and "unreachable" in r.notes[0]
    spent = AnthropicPricingSource(lambda u: FIXTURE.encode(), deadline_s=60.0, clock=lambda: clock[0])
    spent._budget.remaining()
    clock[0] += 1000.0
    r = opus55(spent)
    assert r.partial and "unreachable" in r.notes[0] and r.checks == []


def test_one_fetch_per_run():
    s, fetch = source()
    for _ in range(5):
        opus55(s)
    s.row_fingerprints()
    s.extra_fingerprints()
    assert fetch.calls == [URL]


def test_junk_never_raises():
    s, _ = source()
    for doc in ({"model": ["x"], "costs": [cost(input_cost_per_token=[1])]}, {"costs": "nope"}, {},
                {"model": "claude-opus-5-5", "costs": [cost(input_cost_per_token="abc", tiered_pricing=7)]},
                {"model": "claude-haiku-5-5", "costs": [cost(tiered_pricing={"input": 5, "output": [7, None]})]}):
        r = s.check("providers/anthropic/claude-opus-5-5.yaml", doc)
        assert r.partial or r.checks is not None
    r = s.check("providers/anthropic/claude-haiku-5-5.yaml", {"model": "claude-haiku-5-5", "costs": [cost(tiered_pricing={"input": [None, 3], "output": 5})]})
    assert r.partial
    s._compare = lambda *a, **k: (_ for _ in ()).throw(TypeError("boom"))
    r = opus55(s)
    assert r.partial and "adapter error" in r.notes[0]


# ---- fingerprints --------------------------------------------------------------------------------------------

def test_fingerprints_are_per_row_and_stable():
    a, b = source()[0], source()[0]
    fa, fb = a.row_fingerprints(), b.row_fingerprints()
    assert fa == fb and len(fa) == 21 and "Claude Haiku 5.5 (for prompts over 100,000 tokens)" in fa
    assert all(len(v) == 64 for v in fa.values()) and len(set(fa.values())) == 21


def test_fingerprints_ignore_whitespace_markers_link_urls_trailing_zeros_and_row_order():
    base = source()[0].row_fingerprints()
    variants = [
        FIXTURE.replace("  ", "   "),                                              # collapsed/expanded whitespace
        mutate(FIXTURE, "<sup>1</sup>", "<sup>7</sup>", 2).replace("<sup>1 Cache", "<sup>7 Cache"),   # renumbered footnote
        FIXTURE.replace("https://support.claude.com/en/articles/14604842", "https://example.com/other"),
        mutate(FIXTURE, "| $4 / MTok             |", "| $4.00 / MTok           |"),
        mutate(FIXTURE, "$0.20 / MTok<sup>2</sup>", "$0.20 / MTok"),                # marker dropped
    ]
    for v in variants:
        assert source(v)[0].row_fingerprints() == base
    lines = FIXTURE.split("\n")
    i = next(k for k, l in enumerate(lines) if l.startswith("| Claude Fable 5.1"))
    lines[i], lines[i + 1] = lines[i + 1], lines[i]
    assert source("\n".join(lines))[0].row_fingerprints() == base


def test_fingerprints_change_only_for_the_row_that_changed():
    base = source()[0].row_fingerprints()
    price = source(mutate(FIXTURE, "| $4 / MTok             |", "| $4.1 / MTok            |"))[0].row_fingerprints()
    assert {k for k in base if base[k] != price[k]} == {"Claude Opus 5.5"}
    batch = source(mutate(FIXTURE, "| $2.50 / MTok | $12.50 / MTok |", "| $2.60 / MTok | $12.50 / MTok |"))[0].row_fingerprints()
    assert {k for k in base if base[k] != batch[k]} == {"Claude Opus 5"}   # first of five rows with this batch pair
    retired = source(mutate(FIXTURE, "retired, except on Bedrock and Claude Models on Google Cloud (Google managed)", "retired", 1))[0].row_fingerprints()
    assert sum(base[k] != retired[k] for k in base) == 1


def test_extra_fingerprints_cover_footnotes_multipliers_and_fast_mode():
    base = source()[0].extra_fingerprints()
    assert set(base) == {"footnotes", "cache-multipliers", "fast-mode", "batch-discount"}
    for old, new, key in (("priced at 0.05x", "priced at 0.06x", "footnotes"), ("| 2x base input price", "| 3x base input price", "cache-multipliers"),
                          ("$8 USD / MTok", "$9 USD / MTok", "fast-mode"), ("50 percent", "40 percent", "batch-discount")):
        other = source(mutate(FIXTURE, old, new))[0].extra_fingerprints()
        assert {k for k in base if base[k] != other[k]} == {key}, key
    assert source()[0].extra_fingerprints() == base


def test_a_raw_hash_would_not_be_stable_but_row_hashes_are():
    stamped = FIXTURE + "\n<!-- build 1234567 -->\n"
    a, b = source(FIXTURE)[0], source(stamped)[0]
    a.prepare(); b.prepare()
    assert a.page_sha256 != b.page_sha256 and a.row_fingerprints() == b.row_fingerprints()


# ---- review fixes ---------------------------------------------------------------------------------------------

def test_duplicate_from_thresholds_are_uncovered_not_silently_first_wins():
    s, _ = source()
    tiers = copy.deepcopy(HAIKU55_TIERS)
    tiers["input"] = [{"cost_per_token": 9e-7, "from": 100000}, {"cost_per_token": 5e-7, "from": 100000}]
    r = haiku(s, tiers)
    assert not r.fully_verified and r.partial
    assert "costs.region=*.tiered_pricing.input.from=100000.cost_per_token" in r.uncovered
    assert not [c for c in r.checks if c.locator[-4:-2] == ("input", "from=100000")] and r.conflicts == []
    assert any("2 tiers from 100000" in n for n in r.notes)


def test_an_introductory_price_only_through_a_date_is_a_promo():
    for body in ("The $2/$10 per million input/output token pricing for Claude Sonnet 5 is an introductory price only through December 31, 2026.",
                 "The $2/$10 price for Claude Sonnet 5 is valid until the end of the year.",
                 "Limited offer on Claude Sonnet 5."):
        s, _ = source(mutate(FIXTURE, FN3, body))
        r = check(s, "claude-sonnet-5", "anthropic/claude-sonnet-5", **SONNET5)
        assert r.promo_active and r.partial and not r.fully_verified, body
        assert {"costs.region=*.input_cost_per_token", "costs.region=*.output_cost_per_token"} <= set(r.uncovered), body


def test_the_standard_price_footnote_must_match_the_row_it_sits_on():
    for old, new in (("The $2/$10 per million", "The $3/$15 per million"),          # prices differ from the cells
                     ("pricing for Claude Sonnet 5, announced", "pricing for Claude Opus 5, announced"),  # other model
                     ("is now the standard price.", "is now the standard price, subject to change.")):  # not the exact form
        s, _ = source(mutate(FIXTURE, FN3, FN3.replace(old, new)))
        r = check(s, "claude-sonnet-5", "anthropic/claude-sonnet-5", **SONNET5)
        assert not r.fully_verified and "costs.region=*.input_cost_per_token" in r.uncovered, new


def test_a_page_typo_in_the_base_price_is_a_conflict_that_is_not_written_back():
    text = mutate(FIXTURE, "| $4 / MTok             | $5 / MTok       | $8 / MTok       |", "| $6 / MTok             | $5 / MTok       | $8 / MTok       |")
    s, _ = source(text)
    r = opus55(s)
    (c,) = r.conflicts
    assert c.locator[-1] == "input_cost_per_token" and c.source_value == 6e-6 and c.writable is False
    assert "contradict" in c.note and "5m cache write" in c.note
    # the derived cells that disagree are uncovered; the output price and its own (consistent) cells still verify
    assert "costs.region=*.cache_creation_input_token_cost" in r.uncovered
    assert not r.fully_verified
    # a plain wrong catalog value on a consistent page stays writable
    ok, _ = source()
    assert opus55(ok, input_cost_per_token=5e-6).conflicts[0].writable is True


def test_batch_output_typo_blocks_the_output_write_back():
    text = mutate(FIXTURE, "| $2 / MTok    | $10 / MTok    |", "| $2 / MTok    | $14 / MTok    |")
    s, _ = source(text)
    r = opus55(s, output_cost_per_token=3e-5)
    (c,) = r.conflicts
    assert c.locator[-1] == "output_cost_per_token" and not c.writable


def test_a_footnote_with_a_multiplier_on_a_non_cache_column_is_not_accepted():
    text = mutate(FIXTURE, "| $4 / MTok             |", "| $4 / MTok<sup>2</sup>   |")
    s, _ = source(text)
    r = opus55(s)
    assert "costs.region=*.input_cost_per_token" in r.uncovered and not r.fully_verified
    assert any("footnote 2 on the base input price is not understood" in n for n in r.notes)


def test_the_multiplier_table_header_is_checked_cell_by_cell():
    s, _ = source(mutate(FIXTURE, "| Duration ", "| Valid for "))
    r = opus55(s)
    assert {"costs.region=*.cache_creation_input_token_cost", "costs.region=*.cache_creation_input_token_cost_per_hour"} <= set(r.uncovered)
    assert any("cache multiplier table unreadable" in n for n in r.notes)


def test_the_cross_check_tolerance_is_half_a_percent_not_five():
    text = mutate(FIXTURE, "| $4 / MTok             | $5 / MTok       |", "| $4 / MTok             | $5.05 / MTok    |")
    s, _ = source(text)
    r = opus55(s)
    assert "costs.region=*.cache_creation_input_token_cost" in r.uncovered
    assert "cache_creation_input_token_cost" not in {c.locator[-1] for c in r.checks}


def test_retired_rows_stay_verified_with_the_first_party_note():
    s, _ = source()
    r = check(s, "claude-opus-4-1", "anthropic/claude-opus-4-1", input_cost_per_token=1.5e-5, output_cost_per_token=7.5e-5,
              cache_creation_input_token_cost=1.875e-5, cache_creation_input_token_cost_per_hour=3e-5,
              cache_read_input_token_cost=1.5e-6, input_cost_per_token_batches=7.5e-6, output_cost_per_token_batches=3.75e-5)
    assert r.fully_verified and any(n.startswith("retired on the first-party API per the page") for n in r.notes)


def test_cli_fingerprint_json_is_versioned_and_stable(tmp_path, capsys):
    import json
    from verify.sources.anthropic_pricing import main
    f = tmp_path / "page.md"
    f.write_text(FIXTURE)
    assert main(["--fingerprints", "--file", str(f)]) == 0
    first = capsys.readouterr().out
    assert main(["--fingerprints", "--file", str(f)]) == 0
    assert capsys.readouterr().out == first
    out = json.loads(first)
    assert out["version"] == 1 and set(out) == {"version", "source", "rows", "extras"} and len(out["rows"]) == 21


def test_limited_availability_rows_are_noted_and_still_compared():
    s, _ = source()
    r = check(s, "claude-mythos-5", "anthropic/claude-mythos-5", input_cost_per_token=1e-5, output_cost_per_token=5e-5)
    assert [c.status for c in r.checks] == ["verified", "verified"]
    assert any("`limited availability`" in n and "lifecycle is not compared" in n for n in r.notes)
