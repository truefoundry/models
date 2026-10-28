"""`propose()` of the three adapters, the apply helper and the CLI.

The fixtures under fixtures/live/ are trimmed copies of the real public data (OpenRouter /models,
DeepInfra /models/list, the AWS Price List for us-east-1, eu-west-1 and ap-northeast-1, recorded
2026-10-28): the round-trip tests need real shapes, not hand-made ones. Offline and deterministic.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from verify import propose as P
from verify.registry import Entry, Registry
from verify.sources.aws_price_list import HOST, OFFERS, AwsPriceListSource
from verify.sources.deepinfra import URL as DI_URL
from verify.sources.deepinfra import DeepInfraSource
from verify.sources.openrouter import CHEAPEST, OpenRouterSource
from verify.sources.openrouter import MODELS_URL as OR_URL
from verify.types import Proposal, Proposed

from .fx import FakeFetch, outage

LIVE = Path(__file__).parent / "fixtures" / "live"
REGIONS = ["us-east-1", "eu-west-1", "ap-northeast-1"]


def blob(name: str) -> bytes:
    return (LIVE / name).read_bytes()


def jload(name: str):
    return json.loads(blob(name))


def aws_routes() -> dict:
    r = {}
    for off in OFFERS:
        r[f"{HOST}/offers/v1.0/aws/{off}/current/region_index.json"] = blob(f"{off}-region_index.json")
        for region in REGIONS:
            r[f"{HOST}/offers/v1.0/aws/{off}/current/{region}/index.json"] = blob(f"{off}-{region}.json")
    return r


def aws(**kw):
    return AwsPriceListSource(FakeFetch(aws_routes()), **kw)


def aws_propose(model, regions=tuple(REGIONS), source=None, provider="aws-bedrock"):
    s = source or aws()
    doc = {"model": model, "mode": "chat"}
    if regions:
        doc["costs"] = [{"region": r} for r in regions]
    return s.propose(f"providers/{provider}/{model}.yaml", doc), doc, s


def roundtrip(source, repo_path, doc, proposal):
    """Apply the proposal to the empty doc, run check(), return {locator: Check}."""
    filled = P.apply_to_doc(doc, proposal)
    result = source.check(repo_path, filled)
    return {c.locator: c for c in result.checks}, result


def assert_roundtrip(source, repo_path, doc, proposal):
    checks, _ = roundtrip(source, repo_path, doc, proposal)
    assert proposal.values, "nothing proposed"
    for v in proposal.values:
        c = checks.get(v.locator)
        assert c is not None, f"no check at {v.locator}"
        assert c.status == "verified", f"{v.locator}: file {c.file_value} source {c.source_value}"


AWS_IDS = [
    "anthropic.claude-sonnet-4-5-20250929-v1:0", "global.anthropic.claude-sonnet-4-5-20250929-v1:0",
    "anthropic.claude-opus-5-v1:0", "anthropic.claude-haiku-4-5-20251001-v1:0",
    "anthropic.claude-3-5-sonnet-20241022-v2:0", "anthropic.claude-3-haiku-20240307-v1:0",
    "amazon.nova-pro-v1:0", "amazon.nova-micro-v1:0", "meta.llama3-2-3b-instruct-v1:0",
    "mistral.mistral-large-3-675b-instruct", "openai.gpt-oss-120b-1:0", "deepseek.v3.2", "qwen.qwen3-32b-v1:0",
    "cohere.embed-v4:0", "mistral.mistral-7b-instruct-v0:2", "zai.glm-5", "moonshot.kimi-k2-thinking",
]


# ---- AWS ---------------------------------------------------------------------------------------

@pytest.mark.parametrize("model", AWS_IDS)
def test_aws_proposal_round_trips_through_check(model):
    p, doc, s = aws_propose(model)
    assert_roundtrip(s, f"providers/aws-bedrock/{model}.yaml", doc, p)


def test_aws_round_trip_covers_at_least_ten_models_with_values():
    n = sum(1 for m in AWS_IDS if aws_propose(m)[0].values)
    assert n >= 10


def test_aws_global_id_gets_the_global_price_and_the_base_id_the_regional_one():
    g, *_ = aws_propose("global.anthropic.claude-sonnet-4-5-20250929-v1:0", ["us-east-1"])
    r, *_ = aws_propose("anthropic.claude-sonnet-4-5-20250929-v1:0", ["us-east-1"])
    gv = {v.locator[-1]: v.value for v in g.values}
    rv = {v.locator[-1]: v.value for v in r.values}
    assert gv["input_cost_per_token"] == 3e-6 and gv["output_cost_per_token"] == 1.5e-5
    assert rv["input_cost_per_token"] == 3.3e-6 and rv["output_cost_per_token"] == 1.65e-5
    assert gv["cache_creation_input_token_cost_per_hour"] == 6e-6 and rv["cache_creation_input_token_cost_per_hour"] == 6.6e-6


def test_aws_proposes_cache_batch_and_one_entry_per_region_with_exact_locators():
    p, *_ = aws_propose("anthropic.claude-sonnet-4-5-20250929-v1:0")
    fields = {v.locator[2] for v in p.values}
    assert {"input_cost_per_token", "output_cost_per_token", "cache_read_input_token_cost",
            "cache_creation_input_token_cost", "cache_creation_input_token_cost_per_hour",
            "input_cost_per_token_batches", "output_cost_per_token_batches"} <= fields
    assert {v.locator[1] for v in p.values} == {f"region={r}" for r in REGIONS}
    assert all(v.locator[0] == "costs" and len(v.locator) == 3 for v in p.values)


def test_aws_flex_and_priority_land_in_their_dicts_and_round_trip():
    seen = 0
    for m in AWS_IDS:
        p, doc, s = aws_propose(m)
        nested = [v for v in p.values if len(v.locator) == 4]
        if nested:
            seen += 1
            assert {v.locator[2] for v in nested} <= {"flex_pricing", "priority_pricing"}
            assert_roundtrip(s, f"providers/aws-bedrock/{m}.yaml", doc, p)
    assert seen >= 1


def test_aws_unit_scale_is_read_from_the_price_dimension_not_assumed():
    # the same SKU quoted per 1K tokens must give the same per-token price
    base, *_ = aws_propose("amazon.nova-pro-v1:0", ["us-east-1"])
    routes = aws_routes()
    key = f"{HOST}/offers/v1.0/aws/AmazonBedrock/current/us-east-1/index.json"
    data = json.loads(routes[key])
    for terms in data["terms"]["OnDemand"].values():
        for t in terms.values():
            for d in t["priceDimensions"].values():
                if d["unit"] == "1M tokens":
                    d["unit"] = "1K tokens"
                    d["pricePerUnit"]["USD"] = repr(float(d["pricePerUnit"]["USD"]) / 1000)
    routes[key] = json.dumps(data).encode()
    scaled = AwsPriceListSource(FakeFetch(routes))
    p2, *_ = aws_propose("amazon.nova-pro-v1:0", ["us-east-1"], source=scaled)
    a = {v.locator: v.value for v in base.values}
    b = {v.locator: v.value for v in p2.values}
    # absolute anchors: Nova Pro is listed at $0.0008 per 1K tokens input and $0.0032 output
    assert a[("costs", "region=us-east-1", "input_cost_per_token")] == pytest.approx(8e-7)
    assert a[("costs", "region=us-east-1", "output_cost_per_token")] == pytest.approx(3.2e-6)
    assert a and a.keys() == b.keys()
    assert all(b[k] == pytest.approx(a[k], rel=1e-9) for k in a)


def test_aws_without_regions_uses_every_region_of_the_index_that_has_a_price():
    p, doc, s = aws_propose("anthropic.claude-sonnet-4-5-20250929-v1:0", regions=())
    assert {v.locator[1] for v in p.values} == {f"region={r}" for r in REGIONS}
    assert_roundtrip(s, "providers/aws-bedrock/x.yaml", {"model": "anthropic.claude-sonnet-4-5-20250929-v1:0"}, p)
    assert not p.partial  # unpriced regions of the index are the normal case when none were asked for


def test_aws_a_requested_region_without_a_price_is_partial_and_said():
    p, *_ = aws_propose("anthropic.claude-sonnet-4-5-20250929-v1:0", ["us-east-1", "eu-central-1"])
    assert p.partial and any("eu-central-1" in n for n in p.notes)
    assert {v.locator[1] for v in p.values} == {"region=us-east-1"}


def test_aws_partial_when_a_related_sku_is_not_read():
    p, *_ = aws_propose("amazon.nova-pro-v1:0")
    assert p.partial and any("does not read" in n and "latency-optimized" in n for n in p.notes)


BR_US1 = f"{HOST}/offers/v1.0/aws/AmazonBedrock/current/us-east-1/index.json"


def add_br_sku(data, usage, usd, model, unit="1K tokens"):
    """One more on-demand SKU in a recorded AmazonBedrock offer (the live shape, trimmed to what the parser reads)."""
    sku = f"TEST{len(data['products'])}"
    data["products"][sku] = {"attributes": {"model": model, "usagetype": usage, "servicecode": "AmazonBedrock",
                                            "servicename": "Amazon Bedrock", "regionCode": "us-east-1"},
                             "productFamily": "Amazon Bedrock", "sku": sku}
    data["terms"]["OnDemand"][sku] = {f"{sku}.T": {"offerTermCode": "T", "sku": sku, "termAttributes": {}, "priceDimensions": {
        f"{sku}.T.D": {"beginRange": "0", "endRange": "Inf", "unit": unit, "pricePerUnit": {"USD": usd},
                       "rateCode": f"{sku}.T.D", "appliesTo": [], "description": ""}}}}


def aws_with_br(mutate) -> AwsPriceListSource:
    routes = aws_routes()
    data = json.loads(routes[BR_US1])
    mutate(data)
    routes[BR_US1] = json.dumps(data).encode()
    return AwsPriceListSource(FakeFetch(routes))


def test_aws_nova_omni_audio_image_video_skus_are_unread_and_make_the_proposal_partial():
    def mutate(d):
        for usage, usd in (("text-input-tokens", "0.0003"), ("text-output-tokens", "0.0028"),
                           ("text-input-tokens-batch", "0.0002"), ("input-audio-token-count", "0.0011"),
                           ("input-audio-token-count-batch", "0.0006"), ("input-image-token-count", "0.0003"),
                           ("input-video-token-count-cross-region-global", "0.0003"), ("output-image-token-count", "0.044")):
            add_br_sku(d, f"USE1-Nova2.0Omni-{usage}", usd, "Nova 2.0 Omni")

    p, doc, s = aws_propose("amazon.nova-2-omni-v1:0", ["us-east-1"], source=aws_with_br(mutate))
    got = {v.locator[-1]: v.value for v in p.values}
    assert got["input_cost_per_token"] == pytest.approx(3e-7) and got["output_cost_per_token"] == pytest.approx(2.8e-6)
    assert max(got.values()) < 1e-5  # the $0.044 / 1K image output price is not any field of this file
    assert p.partial
    note = next(n for n in p.notes if "does not read" in n)
    for kind in ("input-audio-token-count", "input-image-token-count", "input-video-token-count", "output-image-token-count"):
        assert kind in note
    assert "audio / image / video / speech" in note
    assert_roundtrip(s, "providers/aws-bedrock/amazon.nova-2-omni-v1:0.yaml", doc, p)


def test_aws_nova_sonic_speech_skus_are_unread_not_a_model_of_their_own():
    def mutate(d):
        for usage, usd in (("text-input-tokens", "0.00006"), ("text-output-tokens", "0.00024"),
                           ("speech-input-tokens", "0.0034"), ("speech-output-tokens", "0.0136")):
            add_br_sku(d, f"USE1-NovaSonic-{usage}", usd, "Nova Sonic")

    s = aws_with_br(mutate)
    rates = s.region_rates("us-east-1")
    assert [k for k in rates if "sonic" in k[1]] == [("native", "novasonic")]  # no `NovaSonic-speech` pseudo model
    assert rates.unread[("native", "novasonic")] == {"speech-input-tokens", "speech-output-tokens"}
    p, *_ = aws_propose("amazon.nova-sonic-v1:0", ["us-east-1"], source=s)
    assert p.partial and any("speech-input-tokens" in n and "does not read" in n for n in p.notes)
    assert {v.locator[-1]: v.value for v in p.values}["input_cost_per_token"] == pytest.approx(6e-8)


def test_aws_a_token_sku_family_nobody_taught_the_parser_is_unread_not_silent():
    def mutate(d):
        add_br_sku(d, "USE1-NovaMicro-thinking-token-surcharge", "0.001", "Nova Micro")        # priced per token, no grammar
        add_br_sku(d, "USE1-NovaMicro-Customization-Training", "0.002", "Nova Micro")          # training, not inference
        add_br_sku(d, "USE1-NovaMicro-ProvisionedThroughput-1month-ModelUnits", "55", "Nova Micro", unit="hour")

    p, *_ = aws_propose("amazon.nova-micro-v1:0", ["us-east-1"], source=aws_with_br(mutate))
    note = next(n for n in p.notes if "does not read" in n)
    assert "novamicro-thinking-token-surcharge" in note
    assert "training" not in note and "provisioned" not in note.lower()
    assert p.partial and p.values


def test_aws_nova_pro_text_skus_are_still_read_after_the_modality_grammar():
    p, *_ = aws_propose("amazon.nova-pro-v1:0", ["us-east-1"])
    assert {"input_cost_per_token", "output_cost_per_token"} <= {v.locator[-1] for v in p.values}


def test_aws_an_outage_of_every_region_is_unreachable_but_one_answering_region_is_not():
    routes = {k: outage() for k in aws_routes()}
    down, *_ = aws_propose("amazon.nova-pro-v1:0", source=AwsPriceListSource(FakeFetch(routes)))
    assert down.unreachable and down.values == []
    routes = aws_routes()
    routes[f"{HOST}/offers/v1.0/aws/AmazonBedrock/current/eu-west-1/index.json"] = outage()
    some, *_ = aws_propose("amazon.nova-pro-v1:0", source=AwsPriceListSource(FakeFetch(routes)))
    assert some.partial and some.values and not some.unreachable
    unlisted, *_ = aws_propose("acme.totally-unknown-v1:0")
    assert not unlisted.unreachable  # read fine, the model is just not there
    idx = {k: outage() for k in aws_routes() if k.endswith("region_index.json")}
    no_index, *_ = aws_propose("amazon.nova-pro-v1:0", regions=(), source=AwsPriceListSource(FakeFetch({**aws_routes(), **idx})))
    assert no_index.unreachable


def test_aws_mistral_large_2407_never_takes_the_2402_price_list_model():
    from verify.sources.aws_price_list import id_keys
    assert id_keys("mistral.mistral-large-2402-v1:0")[1][-1] == "mistrallarge"  # the one 1:1 alias
    assert "mistrallarge" not in id_keys("mistral.mistral-large-2407-v1:0")[1]

    def mutate(d):
        add_br_sku(d, "USE1-MistralLarge-input-tokens", "0.004", "Mistral Large")
        add_br_sku(d, "USE1-MistralLarge-output-tokens", "0.012", "Mistral Large")

    s = aws_with_br(mutate)
    old, *_ = aws_propose("mistral.mistral-large-2402-v1:0", ["us-east-1"], source=s)
    new, *_ = aws_propose("mistral.mistral-large-2407-v1:0", ["us-east-1"], source=s)
    assert {v.locator[-1]: v.value for v in old.values}["input_cost_per_token"] == pytest.approx(4e-6)
    assert new.values == [] and new.partial


def test_aws_free_cache_write_is_not_proposed_and_is_said():
    p, *_ = aws_propose("amazon.nova-pro-v1:0")
    assert not any(v.locator[-1] == "cache_creation_input_token_cost" and v.value == 0 for v in p.values)
    assert any("$0" in n for n in p.notes)
    assert all(v.value != 0 for v in p.values)


def test_aws_never_guesses_an_unknown_model():
    p, *_ = aws_propose("acme.totally-unknown-v1:0")
    assert p.values == [] and p.partial and any("no AWS Price List" in n for n in p.notes)


def test_aws_two_skus_two_prices_is_not_proposed():
    routes = aws_routes()
    key = f"{HOST}/offers/v1.0/aws/AmazonBedrock/current/us-east-1/index.json"
    data = json.loads(routes[key])
    # duplicate one nova-pro input SKU under a new id with another price
    sku = next(s for s, p in data["products"].items() if p["attributes"]["usagetype"] == "USE1-NovaPro-input-tokens")
    clone = copy.deepcopy(data["products"][sku])
    data["products"]["DUP"] = clone
    terms = copy.deepcopy(data["terms"]["OnDemand"][sku])
    for t in terms.values():
        for d in t["priceDimensions"].values():
            d["pricePerUnit"]["USD"] = repr(float(d["pricePerUnit"]["USD"]) * 3)
    data["terms"]["OnDemand"]["DUP"] = terms
    routes[key] = json.dumps(data).encode()
    p, *_ = aws_propose("amazon.nova-pro-v1:0", ["us-east-1"], source=AwsPriceListSource(FakeFetch(routes)))
    got = {v.locator for v in p.values}
    assert p.partial and ("costs", "region=us-east-1", "input_cost_per_token") not in got
    assert any("several AWS SKU prices" in n and "input_cost_per_token" in n for n in p.notes)
    assert ("costs", "region=us-east-1", "output_cost_per_token") in got


def test_aws_source_outlier_region_is_not_proposed():
    routes = aws_routes()
    for off in OFFERS:  # a fourth region (a copy of eu-west-1): the guard needs two other regions to compare with
        routes[f"{HOST}/offers/v1.0/aws/{off}/current/eu-west-3/index.json"] = routes[f"{HOST}/offers/v1.0/aws/{off}/current/eu-west-1/index.json"]
    for off in OFFERS:
        key = f"{HOST}/offers/v1.0/aws/{off}/current/ap-northeast-1/index.json"
        data = json.loads(routes[key])
        for terms in data["terms"]["OnDemand"].values():
            for t in terms.values():
                for d in t["priceDimensions"].values():
                    d["pricePerUnit"]["USD"] = repr(float(d["pricePerUnit"]["USD"]) * 10)
        routes[key] = json.dumps(data).encode()
    p, *_ = aws_propose("openai.gpt-oss-120b-1:0", [*REGIONS, "eu-west-3"], source=AwsPriceListSource(FakeFetch(routes)))
    assert p.partial and any("source outlier" in n and "ap-northeast-1" in n for n in p.notes)
    assert "region=ap-northeast-1" not in {v.locator[1] for v in p.values}
    assert {"region=us-east-1", "region=eu-west-1"} <= {v.locator[1] for v in p.values}


def test_aws_mantle_fallback_is_said():
    p, doc, s = aws_propose("mistral.mistral-large-3-675b-instruct")
    assert any("-mantle" in n for n in p.notes)
    assert_roundtrip(s, "providers/aws-bedrock/m.yaml", doc, p)


def test_aws_mantle_provider_uses_only_mantle_skus():
    p, doc, s = aws_propose("openai.gpt-oss-120b", provider="aws-bedrock-mantle")
    assert p.values
    assert_roundtrip(s, "providers/aws-bedrock-mantle/openai.gpt-oss-120b.yaml", doc, p)


def test_aws_outage_is_an_empty_partial_proposal_not_a_crash():
    routes = {k: outage() for k in aws_routes()}
    p, *_ = aws_propose("anthropic.claude-sonnet-4-5-20250929-v1:0", source=AwsPriceListSource(FakeFetch(routes)))
    assert p.values == [] and p.partial and p.notes
    p, *_ = aws_propose("anthropic.claude-sonnet-4-5-20250929-v1:0", regions=(), source=AwsPriceListSource(FakeFetch(routes)))
    assert p.values == [] and p.partial and any("unreachable" in n for n in p.notes)


def test_aws_bad_region_codes_are_never_fetched():
    fetch = FakeFetch(aws_routes())
    s = AwsPriceListSource(fetch)
    p = s.propose("providers/aws-bedrock/x.yaml", {"model": "x", "costs": [{"region": "../../etc"}, {"region": "us-east-1"}]})
    assert p.partial and any("not an AWS region code" in n for n in p.notes)
    assert all("etc" not in u for u in fetch.calls)


def test_aws_one_fetch_per_region_per_offer():
    s = aws()
    for m in AWS_IDS[:5]:
        aws_propose(m, source=s)
    assert len(s._get.__self__._fetch.calls) == len(set(s._get.__self__._fetch.calls))


@pytest.mark.parametrize("junk", [{}, {"model": None}, {"model": 5}, {"model": "a", "costs": "x"}, {"model": "a", "costs": [None, 3]}])
def test_aws_propose_never_raises_on_junk(junk):
    assert aws().propose("providers/aws-bedrock/x.yaml", junk) is not None


# ---- OpenRouter --------------------------------------------------------------------------------

def or_source():
    return OpenRouterSource(FakeFetch({OR_URL: blob("openrouter-models.json")}))


def or_ids():
    return [m["id"] for m in jload("openrouter-models.json")["data"]]


def or_propose(model, source=None):
    s = source or or_source()
    doc = {"model": model, "mode": "chat"}
    return s.propose(f"providers/openrouter/{model}.yaml", doc), doc, s


def test_openrouter_has_at_least_ten_live_models():
    assert len(or_ids()) >= 10


@pytest.mark.parametrize("model", or_ids())
def test_openrouter_proposal_round_trips_where_there_is_a_proposal(model):
    p, doc, s = or_propose(model)
    if not p.values:  # a variable-price router: nothing to give, and it says why
        assert any("variable" in n or "not in" in n for n in p.notes)
        return
    assert_roundtrip(s, f"providers/openrouter/{model}.yaml", doc, p)


def test_openrouter_proposal_is_always_partial_and_says_cheapest_endpoint():
    for model in or_ids():
        p, *_ = or_propose(model)
        assert p.partial is True
        assert any(CHEAPEST in n for n in p.notes)
        assert all(v.note == CHEAPEST for v in p.values)


def test_openrouter_price_values_are_the_listing_prices():
    listing = {m["id"]: m for m in jload("openrouter-models.json")["data"]}
    n = 0
    for model, m in listing.items():
        p, *_ = or_propose(model)
        got = {v.locator: v.value for v in p.values}
        pr = m["pricing"]
        if float(pr["prompt"]) >= 0:
            assert got[("costs", "region=*", "input_cost_per_token")] == pytest.approx(float(pr["prompt"]))
            assert got[("costs", "region=*", "output_cost_per_token")] == pytest.approx(float(pr["completion"]))
            n += 1
    assert n >= 10


def test_openrouter_free_model_gets_zero_prices_like_the_catalog_free_files():
    free = next(m for m in or_ids() if m.endswith(":free"))
    p, *_ = or_propose(free)
    got = {v.locator[-1]: v.value for v in p.values}
    assert got["input_cost_per_token"] == 0 and got["output_cost_per_token"] == 0


def test_openrouter_variable_price_router_is_not_proposed():
    p, *_ = or_propose("openrouter/auto-beta")
    assert not [v for v in p.values if v.locator[0] == "costs"]
    assert any("variable" in n for n in p.notes)


def test_openrouter_unlisted_model_is_empty_partial_with_a_note():
    p, *_ = or_propose("acme/nothing-here")
    assert p.values == [] and p.partial and any("not in OpenRouter" in n for n in p.notes)


def test_openrouter_outage_is_empty_partial():
    s = OpenRouterSource(FakeFetch({OR_URL: outage()}))
    p, *_ = or_propose("a/b", source=s)
    assert p.values == [] and p.partial and any("unreachable" in n for n in p.notes)


def test_openrouter_is_report_only_unless_the_flag_is_given():
    p, *_ = or_propose(or_ids()[2])
    assert p.values
    assert P.applicable(p) is False
    assert P.applicable(p, allow_listing_prices=True) is True
    assert P.proposal_json(p)["apply"] is False
    assert P.proposal_json(p, allow_listing_prices=True)["apply"] is True


def test_openrouter_tier_overrides_and_unverified_units_are_said_not_proposed():
    over = next(m for m in jload("openrouter-models.json")["data"] if m["pricing"].get("overrides"))
    p, *_ = or_propose(over["id"])
    assert any("tier overrides" in n for n in p.notes)
    assert not any(len(v.locator) > 3 for v in p.values)


# ---- DeepInfra ---------------------------------------------------------------------------------

def di_source(data=None):
    return DeepInfraSource(FakeFetch({DI_URL: json.dumps(data).encode() if data is not None else blob("deepinfra-models.json")}))


def di_models():
    return jload("deepinfra-models.json")


def di_propose(model, mode="chat", source=None):
    s = source or di_source()
    doc = {"model": model, "mode": mode}
    return s.propose(f"providers/deepinfra/{model}.yaml", doc), doc, s


MODE_OF = {"tokens": "chat", "input_tokens": "embedding", "output_length": "video", "input_length": "audio_transcription",
           "input_character_length": "text_to_speech", "image_units": "image", "time": "audio_transcription",
           "frame_units": "video"}


def test_deepinfra_has_at_least_ten_live_models_with_a_proposal():
    n = 0
    for m in di_models():
        p, *_ = di_propose(m["model_name"], MODE_OF[m["pricing"]["type"]])
        n += bool(p.values)
    assert n >= 10


@pytest.mark.parametrize("m", di_models(), ids=lambda m: m["model_name"])
def test_deepinfra_proposal_round_trips_through_check(m):
    mode = MODE_OF[m["pricing"]["type"]]
    p, doc, s = di_propose(m["model_name"], mode)
    if p.values:
        assert_roundtrip(s, f"providers/deepinfra/{m['model_name']}.yaml", doc, p)
    else:
        assert p.notes


def test_deepinfra_cents_become_dollars_per_token():
    m = next(x for x in di_models() if x["pricing"]["type"] == "tokens")
    p, *_ = di_propose(m["model_name"])
    got = {v.locator[-1]: v.value for v in p.values}
    assert got["input_cost_per_token"] == pytest.approx(m["pricing"]["cents_per_input_token"] / 100)
    assert got["output_cost_per_token"] == pytest.approx(m["pricing"]["cents_per_output_token"] / 100)
    assert got["input_cost_per_token"] < 1e-3  # a per-token dollar price, not cents and not per million


def test_deepinfra_cached_rate_is_a_ratio_of_the_input_price():
    data = [{"model_name": "x/y", "pricing": {"type": "tokens", "cents_per_input_token": 0.0001, "cents_per_output_token": 0.0004,
                                               "rate_per_input_token_cached": 0.1,
                                               "rate_per_explicit_cache_write_token": {"5m": 1.25, "1h": 2.0}}}]
    p, doc, s = di_propose("x/y", source=di_source(data))
    got = {v.locator[-1]: v.value for v in p.values}
    assert got["cache_read_input_token_cost"] == pytest.approx(1e-7)
    assert got["cache_creation_input_token_cost"] == pytest.approx(1.25e-6)
    assert got["cache_creation_input_token_cost_per_hour"] == pytest.approx(2e-6)
    assert_roundtrip(s, "providers/deepinfra/x/y.yaml", doc, p)


def test_deepinfra_cached_rate_equal_to_input_is_derived_and_left_out():
    data = [{"model_name": "x/y", "pricing": {"type": "tokens", "cents_per_input_token": 0.0001, "cents_per_output_token": 0.0004,
                                               "rate_per_input_token_cached": 1.0}}]
    p, *_ = di_propose("x/y", source=di_source(data))
    assert "cache_read_input_token_cost" not in {v.locator[-1] for v in p.values}


def test_deepinfra_ambiguous_shapes_are_not_proposed():
    # image_units: input or output per image is a catalog convention, not in the API
    # input_tokens on a generator: input or output image/video token price
    seen = set()
    for m in di_models():
        t = m["pricing"]["type"]
        if t == "image_units":
            p, *_ = di_propose(m["model_name"], "image")
            assert p.values == [] and p.partial
            seen.add(t)
        if t == "input_tokens":
            p, *_ = di_propose(m["model_name"], "image")
            assert p.values == [] and p.partial and any("not proposed" in n for n in p.notes)
            seen.add(t)
        if t in ("time", "frame_units"):
            p, *_ = di_propose(m["model_name"], "video")
            assert p.values == [] and p.partial
            seen.add(t)
    assert {"image_units", "input_tokens", "time", "frame_units"} <= seen


def test_deepinfra_embedding_input_tokens_is_the_input_price():
    m = next(x for x in di_models() if x["pricing"]["type"] == "input_tokens")
    p, *_ = di_propose(m["model_name"], "embedding")
    assert [(v.locator[-1], v.value) for v in p.values] == [
        ("input_cost_per_token", pytest.approx(m["pricing"]["cents_per_input_token"] / 100))]


def test_deepinfra_discount_proposes_the_list_price_and_is_partial():
    data = copy.deepcopy(di_models())
    m = next(x for x in data if x["pricing"]["type"] == "tokens")
    m["pricing"]["discount"] = 0.5
    list_price = m["pricing"]["cents_per_input_token"] / 100
    p, doc, s = di_propose(m["model_name"], source=di_source(data))
    got = {v.locator[-1]: v.value for v in p.values}
    assert got["input_cost_per_token"] == pytest.approx(list_price)
    assert p.partial and any("discount" in n and "list price" in n for n in p.notes)
    assert_roundtrip(s, "providers/deepinfra/x.yaml", doc, p)


def di_one(**pricing) -> list:
    return [{"model_name": "x/y", "pricing": {"type": "tokens", "cents_per_input_token": 0.0001, "cents_per_output_token": 0.0004,
                                               **pricing}}]


def test_deepinfra_lookup_is_exact_and_case_sensitive():
    # a different spelling is a different catalog file: a case duplicate must never inherit another model's price
    m = next(x for x in di_models() if x["pricing"]["type"] == "tokens" and x["model_name"] != x["model_name"].swapcase())
    assert di_propose(m["model_name"])[0].values
    for wrong in (m["model_name"].swapcase(), m["model_name"].lower() if m["model_name"] != m["model_name"].lower() else m["model_name"].upper()):
        p, *_ = di_propose(wrong)
        assert p.values == [] and any("not in DeepInfra's model list" in n for n in p.notes), wrong
    s = di_source()
    r = s.check(f"providers/deepinfra/{m['model_name'].swapcase()}.yaml",
                {"model": m["model_name"].swapcase(), "costs": [{"region": "*", "input_cost_per_token": 1e-6}]})
    assert r.checks == [] and any("not in DeepInfra's model list" in n for n in r.notes)


def test_deepinfra_service_tier_rates_are_not_read_and_the_proposal_says_so_and_is_partial():
    p, *_ = di_propose("x/y", source=di_source(di_one(rate_per_service_tier_priority=1.5, rate_per_service_tier_flex=0.8)))
    assert p.partial and p.values
    note = next(n for n in p.notes if "service-tier" in n)
    assert "priority x1.5" in note and "flex x0.8" in note and "not read or compared" in note
    assert not any("flex_pricing" in ".".join(v.locator) or "priority_pricing" in ".".join(v.locator) for v in p.values)
    assert not any("publishes no" in n for n in p.notes)  # the old claim was false: the API does publish them
    p, *_ = di_propose("x/y", source=di_source(di_one(rate_per_service_tier_flex=0.8)))
    assert "(flex x0.8 of the list price)" in p.notes[-1]  # only the rate the API gave


def test_deepinfra_without_tier_rates_or_discount_is_complete_and_has_no_notes():
    p, *_ = di_propose("x/y", source=di_source(di_one(rate_per_service_tier_priority=None, rate_per_service_tier_flex=None, discount=None)))
    assert p.values and not p.partial and p.notes == []


def test_deepinfra_discount_note_states_the_discount_the_end_date_and_what_is_written():
    p, *_ = di_propose("x/y", source=di_source(di_one(discount=0.51, discount_ends_at="2026-12-31")))
    note = next(n for n in p.notes if "discount" in n)
    assert "51% discount" in note and "until 2026-12-31" in note and "LIST price is proposed" in note
    assert p.partial and {v.locator[-1]: v.value for v in p.values}["input_cost_per_token"] == pytest.approx(1e-6)  # list, not 0.49x
    p, *_ = di_propose("x/y", source=di_source(di_one(discount=0.125)))
    assert "12.5% discount" in p.notes[0] and "no end date given" in p.notes[0]


def test_deepinfra_ratio_rounding_noise_does_not_reach_the_price():
    # the API rounds ratios to 8 decimals: 0.15 $/M x 0.13333333 is 1.99999995e-08, the real price is 2e-08
    p, doc, s = di_propose("x/y", source=di_source(di_one(cents_per_input_token=1.5e-05, rate_per_input_token_cached=0.13333333)))
    got = {v.locator[-1]: v.value for v in p.values}
    assert got["cache_read_input_token_cost"] == 2e-08
    assert_roundtrip(s, "providers/deepinfra/x/y.yaml", doc, p)
    # a plain cents / 100 price is untouched by the 6 digit rule
    p, *_ = di_propose("x/y", source=di_source(di_one(cents_per_input_token=1.23456789e-05)))
    assert {v.locator[-1]: v.value for v in p.values}["input_cost_per_token"] == 1.23456789e-07


def test_deepinfra_unreachable_flag_is_only_for_an_outage():
    down, *_ = di_propose("a/b", source=DeepInfraSource(FakeFetch({DI_URL: outage()})))
    assert down.unreachable
    missing, *_ = di_propose("acme/none")
    assert missing.partial and not missing.unreachable


def test_the_propose_json_carries_the_unreachable_flag():
    reg = registry(("deepinfra", "deepinfra", ("price",)))
    r = P.propose_for(reg, "deepinfra", "a/b", sources={"deepinfra": lambda **kw: DeepInfraSource(FakeFetch({DI_URL: outage()}))})
    assert r["proposals"][0]["unreachable"] is True
    r = P.propose_for(reg, "deepinfra", "acme/none", sources=factories())
    assert r["proposals"][0]["unreachable"] is False


def test_deepinfra_unlisted_and_outage():
    p, *_ = di_propose("acme/none")
    assert p.values == [] and p.partial and any("not in DeepInfra" in n for n in p.notes)
    p, *_ = di_propose("a/b", source=DeepInfraSource(FakeFetch({DI_URL: outage()})))
    assert p.values == [] and p.partial and any("unreachable" in n for n in p.notes)


def test_deepinfra_unsafe_id_is_not_looked_up():
    p, *_ = di_propose("../../x")
    assert p.values == [] and any("not allowed" in n for n in p.notes)


# ---- locators, apply, never-raise --------------------------------------------------------------

def test_set_at_builds_costs_entries_nested_dicts_and_numeric_selectors():
    doc: dict = {}
    P.set_at(doc, ("costs", "region=us-east-1", "input_cost_per_token"), 1e-6)
    P.set_at(doc, ("costs", "region=us-east-1", "flex_pricing", "input_cost_per_token"), 5e-7)
    P.set_at(doc, ("costs", "region=eu-west-1", "output_cost_per_token"), 2e-6)
    P.set_at(doc, ("costs", "region=us-east-1", "tiered_pricing", "input", "from=200000", "cost_per_token"), 3e-6)
    P.set_at(doc, ("limits", "context_window"), 8192)
    assert doc["costs"][0] == {"region": "us-east-1", "input_cost_per_token": 1e-6, "flex_pricing": {"input_cost_per_token": 5e-7},
                               "tiered_pricing": {"input": [{"from": 200000, "cost_per_token": 3e-6}]}}
    assert doc["costs"][1] == {"region": "eu-west-1", "output_cost_per_token": 2e-6}
    assert doc["limits"] == {"context_window": 8192}


def test_apply_to_doc_keeps_the_original_and_honours_a_prefix():
    doc = {"model": "m", "limits": {"max_tokens": 5}}
    prop = Proposal("s", [Proposed(("costs", "region=*", "input_cost_per_token"), 1e-6), Proposed(("limits", "context_window"), 9)])
    out = P.apply_to_doc(doc, prop, prefix=("costs",))
    assert out["costs"] == [{"region": "*", "input_cost_per_token": 1e-6}] and out["limits"] == {"max_tokens": 5}
    assert doc == {"model": "m", "limits": {"max_tokens": 5}}


def test_a_source_without_propose_gives_none_and_a_failing_one_does_not_raise():
    class Boom(DeepInfraSource):
        def _propose(self, repo_path, doc):
            raise RuntimeError("x" * 500)

    p = Boom(FakeFetch({})).propose("providers/deepinfra/x.yaml", {"model": "x"})
    assert p.values == [] and p.partial and "adapter error" in p.notes[0] and len(p.notes[0]) < 200


# ---- CLI ---------------------------------------------------------------------------------------

def registry(*rows) -> Registry:
    return Registry(tuple(Entry(p, "api", s, f, "2026-10-28") for p, s, f in rows))


def factories():
    return {"deepinfra": lambda **kw: di_source(), "openrouter": lambda **kw: or_source(),
            "aws-price-list": lambda **kw: aws()}


def test_propose_for_runs_the_registered_price_sources_and_marks_apply():
    reg = registry(("deepinfra", "deepinfra", ("price", "limits")), ("openrouter", "openrouter", ("price",)))
    m = next(x for x in di_models() if x["pricing"]["type"] == "tokens")
    r = P.propose_for(reg, "deepinfra", m["model_name"], "chat", sources=factories())
    assert [p["source"] for p in r["proposals"]] == ["deepinfra"] and r["proposals"][0]["apply"] is True
    assert r["proposals"][0]["values"][0]["locator"][0] == "costs" and r["reason"] is None
    r = P.propose_for(reg, "openrouter", or_ids()[2], sources=factories())
    assert r["proposals"][0]["apply"] is False and r["proposals"][0]["partial"] is True
    r = P.propose_for(reg, "openrouter", or_ids()[2], allow_listing_prices=True, sources=factories())
    assert r["proposals"][0]["apply"] is True


def test_propose_for_unregistered_or_price_less_provider_says_why():
    reg = registry(("deepinfra", "deepinfra", ("limits",)))
    for provider in ("deepinfra", "azure-open-ai"):
        r = P.propose_for(reg, provider, "m", sources=factories())
        assert r["proposals"] == [] and "no price source" in r["reason"]


def test_propose_for_never_raises_on_a_broken_or_missing_adapter():
    reg = registry(("deepinfra", "deepinfra", ("price",)), ("deepinfra", "ghost", ("price",)))

    def boom(**kw):
        raise RuntimeError("no")

    r = P.propose_for(reg, "deepinfra", "m", sources={"deepinfra": boom})
    assert [p["values"] for p in r["proposals"]] == [[], []]
    assert any("failed" in n or "not available" in n for p in r["proposals"] for n in p["notes"])
    json.dumps(r)


def test_propose_for_passes_regions_to_the_aws_adapter():
    reg = registry(("aws-bedrock", "aws-price-list", ("price",)))
    r = P.propose_for(reg, "aws-bedrock", "anthropic.claude-sonnet-4-5-20250929-v1:0", regions=["us-east-1"], sources=factories())
    assert {v["locator"][1] for v in r["proposals"][0]["values"]} == {"region=us-east-1"}


def test_main_json_and_registry_failure(tmp_path, capsys):
    (tmp_path / "providers" / "deepinfra").mkdir(parents=True)
    bad = tmp_path / "sources"
    bad.mkdir()
    (bad / "registry.yaml").write_text("version: 7\nsources: []\n")
    assert P.main(["--provider", "deepinfra", "--model-id", "m", "--repo", str(tmp_path), "--json"]) == 3
    out = json.loads(capsys.readouterr().out)
    assert out["proposals"] == [] and "registry unusable" in out["reason"]
    (bad / "registry.yaml").write_text("version: 1\nsources: []\n")
    assert P.main(["--provider", "deepinfra", "--model-id", "m", "--repo", str(tmp_path)]) == 0
    assert "no price source" in capsys.readouterr().out


def test_cli_applies_only_deepinfra_and_aws_by_default():
    assert P.APPLY_SOURCES == frozenset({"deepinfra", "aws-price-list"})


# ---- the registry rows for anthropic / azure: no proposal, cleanly ------------------------------------
def test_providers_whose_adapter_has_no_propose_give_no_proposal_not_an_error():
    from verify import registry
    from verify.sources.anthropic_pricing import AnthropicPricingSource
    from verify.sources.azure_retail import AzureRetailSource
    root = Path(__file__).resolve().parents[3]
    reg = registry.load(root / "sources" / "registry.yaml", root / "providers")
    sources = {"anthropic-pricing-page": lambda **kw: AnthropicPricingSource(fetch=FakeFetch({})),
               "azure-retail-prices": lambda **kw: AzureRetailSource(fetch=FakeFetch({}))}
    for provider in ("anthropic", "azure-open-ai", "azure-ai-foundry", "microsoft-foundry"):
        out = P.propose_for(reg, provider, "some-model", sources=sources)
        expected = "no source had anything for this model" if provider == "anthropic" else "no price source is registered for this provider"
        assert out["proposals"] == [] and out["reason"] == expected, provider
    out = P.propose_for(reg, "openrouter", "x/y", sources=sources)          # price-less in the registry on purpose
    assert out["proposals"] == [] and out["reason"] == "no price source is registered for this provider"
