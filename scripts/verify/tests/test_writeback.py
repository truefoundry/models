"""Every writable Check can be applied: write its `source_value` at its `locator` and the same adapter
then verifies that field. This is what the sweep does, so a Check whose value is a derived or combined
number (not writable as-is) must say `writable=False` or not exist.

The corpus is built from the recorded fixtures with every compared field deliberately wrong.
"""
from __future__ import annotations

import copy

from verify.sources.aws_price_list import AwsPriceListSource, HOST
from verify.sources.deepinfra import DeepInfraSource
from verify.sources.openrouter import OpenRouterSource
from verify.types import Check

from .fx import FakeFetch, load, raw


def apply_locator(doc: dict, locator: tuple[str, ...], value) -> None:
    """Write `value` at `locator`; a `key=value` token must select exactly one list item."""
    node = doc
    for i, token in enumerate(locator):
        last = i == len(locator) - 1
        if "=" in token and isinstance(node, list):
            key, _, want = token.partition("=")
            hits = [x for x in node if isinstance(x, dict) and str(x.get(key)) == want]
            assert len(hits) == 1, f"{token} selects {len(hits)} items"
            node = hits[0]
            continue
        assert isinstance(node, dict), f"{token}: not a mapping"
        if last:
            node[token] = value
        else:
            node = node[token]


def roundtrip(source, path: str, doc: dict) -> tuple[list[Check], list[Check]]:
    r = source.check(path, doc)
    fixed = copy.deepcopy(doc)
    writable = [c for c in r.checks if c.writable]
    for c in writable:
        apply_locator(fixed, c.locator, c.source_value)
    again = source.check(path, fixed)
    status = {c.locator: c.status for c in again.checks}
    for c in writable:
        assert status.get(c.locator) == "verified", (path, c.locator, c.source_value, status.get(c.locator))
    return r.checks, writable


def wrong(entry: dict) -> dict:
    return {k: (v * 0.4 if isinstance(v, float) else v) for k, v in entry.items()}


def test_openrouter_writable_checks_roundtrip():
    source = OpenRouterSource(FakeFetch({"https://openrouter.ai/api/v1/models": raw("openrouter-models.json")}))
    n = 0
    for m in load("openrouter-models.json")["data"]:
        p = m["pricing"]
        costs = {"region": "*"}
        for key, fld in (("prompt", "input_cost_per_token"), ("completion", "output_cost_per_token"),
                         ("input_cache_read", "cache_read_input_token_cost"),
                         ("input_cache_write", "cache_creation_input_token_cost"),
                         ("input_cache_write_1h", "cache_creation_input_token_cost_per_hour"),
                         ("audio", "input_cost_per_audio_token"), ("web_search", "input_cost_per_query")):
            if p.get(key) not in (None, "0", "-1"):
                costs[fld] = float(p[key]) * 0.4
        doc = {"model": m["id"], "costs": [costs], "limits": {"context_window": m["context_length"]}}
        checks, writable = roundtrip(source, f"providers/openrouter/{m['id']}.yaml", doc)
        n += len(writable)
        assert all(c.writable for c in checks)
    assert n >= 20


def test_deepinfra_writable_checks_roundtrip_and_the_image_split_has_none():
    source = DeepInfraSource(FakeFetch({"https://api.deepinfra.com/models/list": raw("deepinfra-models.json")}))
    corpus = {
        "moonshotai/Kimi-K2.7-Code": dict(input_cost_per_token=1e-7, output_cost_per_token=1e-7,
                                          cache_read_input_token_cost=1e-9, cache_creation_input_token_cost=1e-9,
                                          cache_creation_input_token_cost_per_hour=1e-9),
        "stepfun-ai/Step-5-Preview": dict(input_cost_per_token=1e-7, output_cost_per_token=1e-7, cache_read_input_token_cost=1e-9),
        "black-forest-labs/FLUX-2-pro": dict(output_cost_per_image=0.5),
        "google/nano-banana-2": dict(output_cost_per_image_token=1e-7),
        "google/nano-banana-2-lite": dict(output_cost_per_token=1e-7),
        "ByteDance/Seedance-1.5-Pro": dict(output_cost_per_video_token=1e-9),
        "Pixverse/Pixverse-T2V": dict(input_cost_per_request=9.0),
        "PrunaAI/p-video": dict(output_cost_per_second=9.0),
        "Qwen/Qwen3-ASR-1.7B": dict(input_cost_per_second=9.0),
        "Qwen/Qwen3-TTS": dict(input_cost_per_character=9.0),
        "BAAI/bge-base-en-v1.5": dict(input_cost_per_token=1.0),
        "zai-org/GLM-5.3": dict(input_cost_per_token=1e-7, output_cost_per_token=1e-7, cache_read_input_token_cost=1e-9),
    }
    n = 0
    for model, costs in corpus.items():
        doc = {"model": model, "costs": [{"region": "*", **costs}]}
        checks, writable = roundtrip(source, f"providers/deepinfra/{model}.yaml", doc)
        assert checks and all(c.status == "conflict" for c in checks), model
        n += len(writable)
    assert n >= 18
    split = {"model": "black-forest-labs/FLUX-2-max", "costs": [{"region": "*", "input_cost_per_image": 0.03,
                                                                  "output_cost_per_image": 0.07}]}
    assert [c for c in source.check("providers/deepinfra/x.yaml", split).checks if c.writable] == []


def test_aws_writable_checks_roundtrip():
    routes = {}
    for r in ("us-east-1", "eu-west-1"):
        routes[f"{HOST}/offers/v1.0/aws/AmazonBedrockFoundationModels/current/{r}/index.json"] = raw(f"aws-foundation-{r}.json")
        routes[f"{HOST}/offers/v1.0/aws/AmazonBedrock/current/{r}/index.json"] = raw(f"aws-bedrock-{r}.json")
    source = AwsPriceListSource(FakeFetch(routes))
    five = dict(input_cost_per_token=1e-9, output_cost_per_token=1e-9, cache_read_input_token_cost=1e-9,
                cache_creation_input_token_cost=1e-9, cache_creation_input_token_cost_per_hour=1e-9,
                input_cost_per_token_batches=1e-9, output_cost_per_token_batches=1e-9)
    tiers = dict(input_cost_per_token=1e-9, output_cost_per_token=1e-9, cache_read_input_token_cost=1e-9,
                 cache_creation_input_token_cost=1e-9)
    ids = ["us.anthropic.claude-sonnet-4-5-20250929-v1:0", "global.anthropic.claude-sonnet-4-5-20250929-v1:0",
           "global.anthropic.claude-opus-5", "us.anthropic.claude-opus-5", "anthropic.claude-3-5-sonnet-20241022-v2:0",
           "us.meta.llama3-3-70b-instruct-v1:0", "openai.gpt-oss-120b-1:0", "cohere.command-r-v1:0",
           "global.amazon.nova-2-lite-v1:0", "us.moonshotai.kimi-k3", "deepseek.v3.2"]
    n = 0
    tier_locators: set[tuple[str, ...]] = set()
    for mid in ids:
        entry = dict(five, flex_pricing=dict(tiers), priority_pricing=dict(tiers))
        doc = {"model": mid, "costs": [{"region": r, **copy.deepcopy(entry)} for r in ("us-east-1", "eu-west-1")]}
        checks, writable = roundtrip(source, f"providers/aws-bedrock/{mid}.yaml", doc)
        assert checks, mid
        n += len(writable)
        tier_locators.update(c.locator[2:] for c in writable if len(c.locator) > 3 or "batches" in c.locator[-1])
    mantle = {"model": "deepseek.v3.2", "costs": [{"region": "us-east-1", **five}]}
    n += len(roundtrip(source, "providers/aws-bedrock-mantle/deepseek.v3.2.yaml", mantle)[1])
    assert n >= 60
    # batch, flex and priority fields were written back and re-verified, not just base prices
    assert ("input_cost_per_token_batches",) in tier_locators
    assert ("flex_pricing", "input_cost_per_token") in tier_locators
    assert ("priority_pricing", "cache_read_input_token_cost") in tier_locators


def test_check_has_a_writable_flag_defaulting_to_true_and_promo_active_to_false():
    c = Check(("costs",), 1.0, 2.0, "conflict")
    assert c.writable is True
    from verify.types import SourceResult
    r = SourceResult(source="x", checks=[c])
    assert r.promo_active is False and r.promo is None
    ok = SourceResult(source="x", checks=[Check(("a",), 1.0, 1.0, "verified")])
    assert ok.fully_verified
    ok.promo_active = True
    assert not ok.fully_verified
