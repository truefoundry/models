"""Every writable Check of the Anthropic page adapter can be applied: write `source_value` at `locator` and the same
adapter then verifies that field (what the sweep does). The corpus is every model of the recorded page with every
compared field deliberately wrong, plus the Haiku 5.5 tier fields and the older name order / dated snapshots."""
from __future__ import annotations

import copy

from verify.sources.anthropic_pricing import KNOWN_SNAPSHOTS, URL, AnthropicPricingSource, parse_page, slugs_of

from .fx import FakeFetch, raw
from .test_anthropic_pricing import HAIKU55_TIERS
from .test_writeback import roundtrip

FIELDS = ("input_cost_per_token", "output_cost_per_token", "cache_creation_input_token_cost",
          "cache_creation_input_token_cost_per_hour", "cache_read_input_token_cost",
          "input_cost_per_token_batches", "output_cost_per_token_batches")


def test_anthropic_page_writable_checks_roundtrip():
    source = AnthropicPricingSource(FakeFetch({URL: raw("anthropic-pricing.md")}))
    page = parse_page(raw("anthropic-pricing.md").decode())
    n, tier_locators = 0, set()
    for base in page.bases:
        slug = slugs_of(base)[0]
        for model in (slug, *(f"{slug}-{x}" for x in sorted(KNOWN_SNAPSHOTS.get(slug, ())))):
            entry = {"region": "*", **{f: 1e-9 for f in FIELDS}}
            if base == "Claude Haiku 5.5":
                entry["tiered_pricing"] = {k: ([{"cost_per_token": 1e-9, "from": 100000}] if k != "pricing_mode" else "cumulative")
                                           for k in HAIKU55_TIERS}
            doc = {"model": model, "canonical_model": f"anthropic/{slug}", "costs": [entry]}
            checks, writable = roundtrip(source, f"providers/anthropic/{model}.yaml", doc)
            assert checks and all(c.status == "conflict" and c.writable for c in checks), model
            n += len(writable)
            tier_locators.update(c.locator[2:] for c in writable if "tiered_pricing" in c.locator)
    older = {"model": "claude-3-5-haiku-20241022", "canonical_model": "anthropic/claude-3-5-haiku",
             "costs": [{"region": "*", **{f: 1e-9 for f in FIELDS}}]}
    n += len(roundtrip(source, "providers/anthropic/claude-3-5-haiku-20241022.yaml", older)[1])
    assert n >= 140
    assert {t[1] for t in tier_locators} == {"input", "output", "cache_read", "cache_write"}
    assert all(t[-2].startswith("from=") and t[-1] == "cost_per_token" for t in tier_locators)
