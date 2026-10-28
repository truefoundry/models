from __future__ import annotations

import copy
import json

import pytest

from verify.sources.aws_price_list import AwsPriceListSource, HOST, id_keys, norm, parse_offer

from .fx import FakeFetch, load, outage

FM, BR = "AmazonBedrockFoundationModels", "AmazonBedrock"


def url(offer: str, region: str) -> str:
    return f"{HOST}/offers/v1.0/aws/{offer}/current/{region}/index.json"


def routes(**extra):
    r = {url(FM, "us-east-1"): load("aws-foundation-us-east-1.json"), url(BR, "us-east-1"): load("aws-bedrock-us-east-1.json"),
         url(FM, "eu-west-1"): load("aws-foundation-eu-west-1.json"), url(BR, "eu-west-1"): load("aws-bedrock-eu-west-1.json")}
    r.update(extra)
    import json
    return {k: (v if isinstance(v, (bytes, Exception)) else json.dumps(v).encode()) for k, v in r.items()}


def source(**extra):
    fetch = FakeFetch(routes(**extra))
    return AwsPriceListSource(fetch), fetch


def doc(model, regions=("us-east-1",), **costs):
    return {"model": model, "costs": [{"region": r, **costs} for r in regions]}


def cl(model, **kw):
    return f"providers/aws-bedrock/{model}.yaml", doc(model, **kw)


SONNET45_REGIONAL = dict(input_cost_per_token=3.3e-6, output_cost_per_token=1.65e-5, cache_read_input_token_cost=3.3e-7,
                         cache_creation_input_token_cost=4.125e-6, cache_creation_input_token_cost_per_hour=6.6e-6)
SONNET45_GLOBAL = dict(input_cost_per_token=3e-6, output_cost_per_token=1.5e-5, cache_read_input_token_cost=3e-7,
                       cache_creation_input_token_cost=3.75e-6, cache_creation_input_token_cost_per_hour=6e-6)


# ---- covers / names ----------------------------------------------------------------------------

def test_covers_bedrock_and_mantle_only():
    s, _ = source()
    assert s.covers("aws-bedrock") and s.covers("aws-bedrock-mantle")
    assert not s.covers("openrouter") and not s.covers("anthropic")


def test_name_normalisation_and_id_keys():
    assert norm("Llama 3.3 70B") == "llama3370b"
    assert norm("Cohere Command R+") == "coherecommandrplus" != norm("Cohere Command R")
    assert id_keys("us.meta.llama3-3-70b-instruct-v1:0") == ("regional", ["metallama3370b", "llama3370b"])
    scope, keys = id_keys("global.anthropic.claude-sonnet-4-5-20250929-v1:0")
    assert scope == "global" and keys[0] == "anthropicclaudesonnet45" and "claudesonnet45" in keys
    assert id_keys("anthropic.claude-3-5-sonnet-20241022-v2:0")[1][-1] == "claude35sonnetv2"
    assert id_keys("anthropic.claude-3-5-sonnet-20240620-v1:0")[1][-1] == "claude35sonnet"
    assert id_keys("openai.gpt-oss-120b-1:0")[1][-1] == "gptoss120b"
    assert id_keys("amazon.nova-2-lite-v1:0")[1][-1] == "nova20lite"  # alias
    assert id_keys("deepseek.v3.2")[0] == "regional"


# ---- Anthropic: both usage-type spellings, regional vs global ----------------------------------

def test_legacy_usage_types_regional_price_incl_cache_write_1h():
    s, _ = source()
    r = s.check(*cl("us.anthropic.claude-sonnet-4-5-20250929-v1:0", **SONNET45_REGIONAL))
    assert r.fully_verified and len(r.checks) == 5


def test_global_id_takes_the_global_price():
    s, _ = source()
    assert s.check(*cl("global.anthropic.claude-sonnet-4-5-20250929-v1:0", **SONNET45_GLOBAL)).fully_verified
    r = s.check(*cl("global.anthropic.claude-sonnet-4-5-20250929-v1:0", **SONNET45_REGIONAL))
    assert {c.locator[-1] for c in r.conflicts} == set(SONNET45_REGIONAL)
    c = next(c for c in r.conflicts if c.locator[-1] == "input_cost_per_token")
    assert (c.file_value, c.source_value) == (3.3e-6, 3e-6)


@pytest.mark.parametrize("model", ["anthropic.claude-sonnet-4-5-20250929-v1:0", "us.anthropic.claude-sonnet-4-5-20250929-v1:0",
                                   "eu.anthropic.claude-sonnet-4-5-20250929-v1:0", "au.anthropic.claude-sonnet-4-5-20250929-v1:0"])
def test_base_and_geo_profile_ids_take_the_regional_price(model):
    s, _ = source()
    assert s.check(*cl(model, **SONNET45_REGIONAL)).fully_verified
    assert s.check(*cl(model, **SONNET45_GLOBAL)).conflicts


def test_new_usage_type_spelling():
    s, _ = source()
    regional = dict(input_cost_per_token=5.5e-6, output_cost_per_token=2.75e-5, cache_read_input_token_cost=5.5e-7,
                    cache_creation_input_token_cost=6.875e-6, cache_creation_input_token_cost_per_hour=1.1e-5)
    glob = dict(input_cost_per_token=5e-6, output_cost_per_token=2.5e-5, cache_read_input_token_cost=5e-7,
                cache_creation_input_token_cost=6.25e-6, cache_creation_input_token_cost_per_hour=1e-5)
    assert s.check(*cl("us.anthropic.claude-opus-5", **regional)).fully_verified
    assert s.check(*cl("global.anthropic.claude-opus-5", **glob)).fully_verified
    assert s.check(*cl("global.anthropic.claude-opus-5", **regional)).conflicts


def test_older_claude_with_v2_name():
    s, _ = source()
    r = s.check(*cl("anthropic.claude-3-5-sonnet-20241022-v2:0", input_cost_per_token=3e-6, output_cost_per_token=1.5e-5,
                    cache_read_input_token_cost=3e-7, cache_creation_input_token_cost=3.75e-6))
    assert r.fully_verified


def test_regions_are_priced_separately_and_a_missing_region_is_a_note():
    s, _ = source()
    d = doc("amazon.nova-2-lite-v1:0", regions=("us-east-1", "eu-west-1", "ap-south-1"),
            input_cost_per_token=3.3e-7, output_cost_per_token=2.75e-6)
    r = s.check("providers/aws-bedrock/amazon.nova-2-lite-v1:0.yaml", d)
    # eu is dearer (3.74e-7 / 3.157e-6); us-east-1's input and output match
    assert {c.locator[1] for c in r.conflicts if c.locator[-1] in ("input_cost_per_token", "output_cost_per_token")} == {"region=eu-west-1"}
    assert any("ap-south-1" in n for n in r.notes) or any("some regions" in n for n in r.notes)
    assert r.partial
    assert "costs.region=ap-south-1.input_cost_per_token" in r.uncovered


def test_global_id_in_a_region_without_a_global_sku_is_missing_not_regional():
    s, _ = source()
    r = s.check(*cl("global.meta.llama3-3-70b-instruct-v1:0", input_cost_per_token=7.2e-7, output_cost_per_token=7.2e-7))
    assert r.checks == [] and r.partial and any("no AWS Price List global price" in n for n in r.notes)


# ---- other vendors, units -------------------------------------------------------------------

def test_llama_priced_per_1k_tokens_is_read_from_the_unit():
    s, _ = source()
    r = s.check(*cl("us.meta.llama3-3-70b-instruct-v1:0", input_cost_per_token=7.2e-7, output_cost_per_token=7.2e-7))
    assert r.fully_verified
    r = s.check(*cl("us.meta.llama3-3-70b-instruct-v1:0", input_cost_per_token=7.2e-7, output_cost_per_token=7.2e-8))
    assert [c.locator[-1] for c in r.conflicts] == ["output_cost_per_token"]


def mutate_units(data, factor_unit, scale):
    data = copy.deepcopy(data)
    for terms in data["terms"]["OnDemand"].values():
        for t in terms.values():
            for d in t["priceDimensions"].values():
                if d["unit"] == "1K tokens":
                    d["unit"] = factor_unit
                    d["pricePerUnit"]["USD"] = repr(float(d["pricePerUnit"]["USD"]) * scale)
    return data


def test_unit_conversion_is_applied_not_assumed():
    # same prices expressed per 1M tokens (x1000) must give the same result as per 1K tokens
    s, _ = source(**{url(BR, "us-east-1"): mutate_units(load("aws-bedrock-us-east-1.json"), "1M tokens", 1000)})
    assert s.check(*cl("us.meta.llama3-3-70b-instruct-v1:0", input_cost_per_token=7.2e-7,
                       output_cost_per_token=7.2e-7)).fully_verified
    # ...and mislabelling the unit changes the answer (1K price read as per 1M would be 1000x too small)
    s, _ = source(**{url(BR, "us-east-1"): mutate_units(load("aws-bedrock-us-east-1.json"), "1M tokens", 1)})
    assert s.check(*cl("us.meta.llama3-3-70b-instruct-v1:0", input_cost_per_token=7.2e-7,
                       output_cost_per_token=7.2e-7)).conflicts


def test_unknown_unit_is_not_compared_and_is_said():
    s, _ = source(**{url(BR, "us-east-1"): mutate_units(load("aws-bedrock-us-east-1.json"), "per furlong", 1)})
    r = s.check(*cl("us.meta.llama3-3-70b-instruct-v1:0", input_cost_per_token=7.2e-7, output_cost_per_token=7.2e-7))
    assert r.checks == [] and r.partial and r.conflicts == []
    assert sorted(r.uncovered) == ["costs.region=us-east-1.input_cost_per_token", "costs.region=us-east-1.output_cost_per_token"]
    assert any("unit" in n for n in r.notes)


def test_tiers_the_price_list_cannot_describe_are_uncovered_and_make_the_file_partial():
    s, _ = source()
    # Llama has batch SKUs only: flex / priority / long-context have nothing to compare with
    r = s.check(*cl("us.meta.llama3-3-70b-instruct-v1:0", input_cost_per_token=7.2e-7, output_cost_per_token=7.2e-7,
                    input_cost_per_token_batches=3.6e-7, output_cost_per_token_batches=3.6e-7,
                    flex_pricing={"input_cost_per_token": 1e-7}, priority_pricing={"input_cost_per_token": 1e-6},
                    tiered_pricing={"input": []}, ultrafast_pricing={"input_cost_per_token": 1e-5}))
    assert r.conflicts == [] and r.partial and not r.fully_verified
    assert sorted(u.split(".")[-1] for u in r.uncovered) == [
        "flex_pricing", "priority_pricing", "tiered_pricing", "ultrafast_pricing"]
    assert len(r.checks) == 4


def test_latency_optimized_sku_is_never_used_for_the_standard_price():
    s, _ = source()
    r = s.check(*cl("meta.llama3-1-70b-instruct-v1:0", input_cost_per_token=9e-7, output_cost_per_token=9e-7))
    assert r.checks == [] and r.partial and "no AWS Price List model I can match" in r.notes[0]


def test_cohere_per_1m_tokens_in_the_foundation_offer():
    s, _ = source()
    r = s.check(*cl("cohere.command-r-v1:0", input_cost_per_token=5e-7, output_cost_per_token=1.5e-6))
    assert r.fully_verified


def test_gpt_oss_version_stamp_dropped():
    s, _ = source()
    assert s.check(*cl("openai.gpt-oss-120b-1:0", input_cost_per_token=1.5e-7, output_cost_per_token=6e-7)).fully_verified


def test_free_cache_write_is_not_a_conflict_when_the_file_omits_it_but_is_when_it_charges():
    s, _ = source()
    base = dict(input_cost_per_token=3.3e-7, output_cost_per_token=2.75e-6, cache_read_input_token_cost=8.25e-8)
    assert s.check(*cl("us.amazon.nova-2-lite-v1:0", **base)).fully_verified
    r = s.check(*cl("us.amazon.nova-2-lite-v1:0", cache_creation_input_token_cost=6e-8, **base))
    assert [c.locator[-1] for c in r.conflicts] == ["cache_creation_input_token_cost"]


# ---- mantle ---------------------------------------------------------------------------------

def test_mantle_file_uses_the_mantle_sku():
    s, _ = source()
    r = s.check("providers/aws-bedrock-mantle/deepseek.v3.2.yaml",
                doc("deepseek.v3.2", input_cost_per_token=6.2e-7, output_cost_per_token=1.85e-6))
    assert r.fully_verified


def test_mantle_claude_has_no_price_list_sku_so_nothing_is_compared():
    s, _ = source()
    r = s.check("providers/aws-bedrock-mantle/anthropic.claude-opus-5.yaml",
                doc("anthropic.claude-opus-5", input_cost_per_token=5e-6, output_cost_per_token=2.5e-5))
    assert r.checks == [] and r.partial and r.conflicts == []
    assert any("no `-mantle` SKU" in n for n in r.notes)
    assert len(r.uncovered) == 2


def test_native_file_with_only_a_mantle_sku_falls_back_with_a_note():
    s, _ = source()
    r = s.check(*cl("us.moonshotai.kimi-k3", input_cost_per_token=3.3e-6, output_cost_per_token=1.65e-5,
                    cache_read_input_token_cost=3.3e-7))
    assert r.fully_verified and any("only the `-mantle` SKU" in n for n in r.notes)
    r = s.check(*cl("global.moonshotai.kimi-k3", input_cost_per_token=3e-6, output_cost_per_token=1.5e-5,
                    cache_read_input_token_cost=3e-7))
    assert r.fully_verified


# ---- tolerance, ambiguity, failure ---------------------------------------------------------

def test_price_tolerance_half_a_percent():
    s, _ = source()
    base = dict(output_cost_per_token=7.2e-7)
    assert s.check(*cl("us.meta.llama3-3-70b-instruct-v1:0", input_cost_per_token=7.2e-7 * 1.004, **base)).fully_verified
    r = s.check(*cl("us.meta.llama3-3-70b-instruct-v1:0", input_cost_per_token=7.2e-7 * 1.006, **base))
    assert [c.locator[-1] for c in r.conflicts] == ["input_cost_per_token"]


def test_two_skus_with_two_prices_for_one_field_are_not_compared():
    data = copy.deepcopy(load("aws-bedrock-us-east-1.json"))
    sku = next(s for s, p in data["products"].items() if p["attributes"]["usagetype"] == "USE1-Llama3-3-70B-input-tokens")
    clone = copy.deepcopy(data["products"][sku])
    clone["sku"] = "DUPSKU"
    data["products"]["DUPSKU"] = clone
    terms = copy.deepcopy(data["terms"]["OnDemand"][sku])
    for t in terms.values():
        for d in t["priceDimensions"].values():
            d["pricePerUnit"]["USD"] = "0.0009"
    data["terms"]["OnDemand"]["DUPSKU"] = terms
    s, _ = source(**{url(BR, "us-east-1"): data})
    r = s.check(*cl("us.meta.llama3-3-70b-instruct-v1:0", input_cost_per_token=7.2e-7, output_cost_per_token=7.2e-7))
    assert [c.locator[-1] for c in r.checks] == ["output_cost_per_token"]
    assert r.partial and r.uncovered == ["costs.region=us-east-1.input_cost_per_token"]
    assert any("several AWS SKU prices" in n for n in r.notes)


def test_parse_offer_ignores_skus_without_a_single_zero_to_inf_dimension():
    data = copy.deepcopy(load("aws-bedrock-us-east-1.json"))
    for terms in data["terms"]["OnDemand"].values():
        for t in terms.values():
            for d in t["priceDimensions"].values():
                d["endRange"] = "1000000"
    rates = parse_offer(data)
    assert all(price != price for fields in rates.values() for price in fields.values())  # all ambiguous (NaN)


def test_one_region_outage_keeps_the_other_regions_checks():
    s, _ = source(**{url(FM, "eu-west-1"): outage()})
    d = doc("amazon.nova-2-lite-v1:0", regions=("us-east-1", "eu-west-1"), input_cost_per_token=3.3e-7)
    r = s.check("providers/aws-bedrock/amazon.nova-2-lite-v1:0.yaml", d)
    assert any(c.locator[1] == "region=us-east-1" for c in r.checks)
    assert r.partial and any("unreachable" in n and "eu-west-1" in n for n in r.notes)


def test_total_outage_is_partial_never_a_crash():
    s = AwsPriceListSource(FakeFetch({}))  # everything 404s
    r = s.check(*cl("us.meta.llama3-3-70b-instruct-v1:0", input_cost_per_token=7.2e-7))
    assert r.partial and r.checks == [] and r.uncovered
    s = AwsPriceListSource(FakeFetch({url(FM, "us-east-1"): outage()}))
    r = s.check(*cl("us.meta.llama3-3-70b-instruct-v1:0", input_cost_per_token=7.2e-7))
    assert r.partial and any("unreachable" in n for n in r.notes)


def test_prepare_is_a_noop_and_each_region_is_fetched_once_per_run():
    s, fetch = source()
    s.prepare()
    assert fetch.calls == []
    for model in ("us.meta.llama3-3-70b-instruct-v1:0", "openai.gpt-oss-120b-1:0", "us.anthropic.claude-opus-5"):
        s.check(*cl(model, regions=("us-east-1", "eu-west-1"), input_cost_per_token=1e-6))
    assert sorted(fetch.calls) == sorted([url(o, r) for o in (FM, BR) for r in ("us-east-1", "eu-west-1")])


def test_file_without_costs_is_partial_with_a_note():
    s, _ = source()
    r = s.check("providers/aws-bedrock/x.yaml", {"model": "us.meta.llama3-3-70b-instruct-v1:0"})
    assert r.partial and r.checks == [] and any("no costs" in n for n in r.notes)


def test_tool_pricing_outside_costs_is_uncovered():
    s, _ = source()
    d = doc("us.meta.llama3-3-70b-instruct-v1:0", input_cost_per_token=7.2e-7, output_cost_per_token=7.2e-7)
    d["tool_pricing"] = {"web_search": 0.01}
    r = s.check("providers/aws-bedrock/x.yaml", d)
    assert r.uncovered == ["tool_pricing"] and r.partial


# ---- absent fields, retired files -------------------------------------------------------------

def test_fields_absent_in_the_file_are_uncovered_missing_in_file_never_conflicts():
    s, _ = source()
    r = s.check(*cl("us.anthropic.claude-sonnet-4-5-20250929-v1:0", input_cost_per_token=3.3e-6,
                    output_cost_per_token=1.65e-5))
    assert r.conflicts == [] and r.partial and not r.fully_verified
    assert sorted(u.split(".")[-1] for u in r.uncovered) == [
        "cache_creation_input_token_cost", "cache_creation_input_token_cost_per_hour", "cache_read_input_token_cost"]
    assert any(n.startswith("missing in file") for n in r.notes)


def test_empty_cost_entries_of_a_deprecated_file_are_not_compared_and_not_fetched():
    s, fetch = source()
    d = {"model": "anthropic.claude-3-haiku-20240307-v1:0", "isDeprecated": True,
         "costs": [{"region": "us-east-1"}, {"region": "eu-west-1"}]}
    r = s.check("providers/aws-bedrock/anthropic.claude-3-haiku-20240307-v1:0.yaml", d)
    assert r.checks == [] and r.conflicts == [] and r.uncovered == [] and fetch.calls == []
    assert any("deprecated file with empty cost entries" in n for n in r.notes)
    live = {"model": LLAMA, "isDeprecated": False, "costs": [{"region": "us-east-1"}]}
    r = s.check("providers/aws-bedrock/x.yaml", live)  # a live file with an empty entry does lack its prices
    assert r.conflicts == [] and r.partial and r.uncovered


# ---- synthetic offers for the shapes the fixtures do not hold -------------------------------------

def sku(usage, usd, unit="1K tokens", dims=None, service="Amazon Bedrock"):
    return {"usagetype": usage, "servicename": service, "servicecode": "AmazonBedrock"}, \
        dims or [{"unit": unit, "beginRange": "0", "endRange": "Inf", "pricePerUnit": {"USD": str(usd)}}]


def offer(*skus):
    products, terms = {}, {}
    for i, (attrs, dims) in enumerate(skus):
        name = f"S{i}"
        products[name] = {"sku": name, "attributes": attrs}
        terms[name] = {f"{name}.T": {"priceDimensions": {f"{name}.T.D{j}": d for j, d in enumerate(dims)}}}
    return {"products": products, "terms": {"OnDemand": terms}}


LLAMA = "us.meta.llama3-3-70b-instruct-v1:0"
LLAMA_IN = "USE1-Llama3-3-70B-input-tokens"
LLAMA_OUT = "USE1-Llama3-3-70B-output-tokens"


def synthetic(regions, **per_region):
    """{region: [sku, ...]} -> routes for the AmazonBedrock offer (the foundation offer 404s)."""
    return {url(BR, r): offer(*skus) for r, skus in regions.items()}


def run(routes_, regions, **costs):
    fetch = FakeFetch({k: __import__("json").dumps(v).encode() for k, v in routes_.items()})
    s = AwsPriceListSource(fetch)
    return s, s.check("providers/aws-bedrock/x.yaml", doc(LLAMA, regions=regions, **costs)), fetch


def llama(inp=0.00072, out=0.00072, extra=()):
    return [sku(LLAMA_IN, inp), sku(LLAMA_OUT, out), *extra]


def test_a_sku_with_several_price_dimensions_is_a_tier_not_the_standard_price():
    tiered = sku(LLAMA_IN, 0, dims=[{"unit": "1K tokens", "beginRange": "0", "endRange": "200000",
                                      "pricePerUnit": {"USD": "0.00072"}},
                                     {"unit": "1K tokens", "beginRange": "200000", "endRange": "Inf",
                                      "pricePerUnit": {"USD": "0.00144"}}])
    _, r, _ = run(synthetic({"us-east-1": [tiered, sku(LLAMA_OUT, 0.00072)]}), ["us-east-1"],
                  input_cost_per_token=7.2e-7, output_cost_per_token=7.2e-7)
    assert [c.locator[-1] for c in r.checks] == ["output_cost_per_token"]
    assert r.uncovered == ["costs.region=us-east-1.input_cost_per_token"] and r.partial
    # two dimensions that both span 0..Inf (the first one alone would look like the standard price)
    both = sku(LLAMA_IN, 0, dims=[{"unit": "1K tokens", "beginRange": "0", "endRange": "Inf", "pricePerUnit": {"USD": "0.00072"}},
                                  {"unit": "1K tokens", "beginRange": "0", "endRange": "Inf", "pricePerUnit": {"USD": "0.0009"}}])
    _, r, _ = run(synthetic({"us-east-1": [both, sku(LLAMA_OUT, 0.00072)]}), ["us-east-1"],
                  input_cost_per_token=7.2e-7, output_cost_per_token=7.2e-7)
    assert [c.locator[-1] for c in r.checks] == ["output_cost_per_token"]


def test_a_cross_region_sku_without_the_global_modifier_is_not_the_standard_price():
    cross = sku(LLAMA_IN + "-cross-region", 0.0009)
    _, r, _ = run(synthetic({"us-east-1": llama(extra=[cross])}), ["us-east-1"],
                  input_cost_per_token=7.2e-7, output_cost_per_token=7.2e-7)
    assert r.fully_verified
    glob = sku(LLAMA_IN + "-cross-region-global", 0.00065)
    s, r, _ = run(synthetic({"us-east-1": llama(extra=[glob])}), ["us-east-1"],
                  input_cost_per_token=7.2e-7, output_cost_per_token=7.2e-7)
    assert r.fully_verified  # the global SKU is only for global.* ids
    assert s.check("providers/aws-bedrock/g.yaml", doc("global." + LLAMA.split(".", 1)[1], input_cost_per_token=6.5e-7)) \
        .checks[0].status == "verified"


def regions4(price4):
    return {"us-east-1": llama(), "us-east-2": llama(), "us-west-2": llama(),
            "eu-west-1": llama(price4, 0.00072)}


def test_a_region_five_times_off_the_others_is_a_source_outlier():
    _, r, _ = run(synthetic(regions4(0.0072)), ["us-east-1", "us-east-2", "us-west-2", "eu-west-1"],
                  input_cost_per_token=7.2e-7, output_cost_per_token=7.2e-7)
    assert r.conflicts == [] and r.partial
    assert r.uncovered == ["costs.region=eu-west-1.input_cost_per_token"]
    assert any("source outlier" in n and "eu-west-1" in n for n in r.notes)
    assert len(r.checks) == 7 and all(c.status == "verified" for c in r.checks)  # 3 regions x2 + eu-west-1 output


def test_outlier_guard_both_directions_and_not_for_ordinary_regional_spread():
    regs = ["us-east-1", "us-east-2", "us-west-2", "eu-west-1"]
    _, r, _ = run(synthetic(regions4(0.00072 / 6)), regs, input_cost_per_token=7.2e-7, output_cost_per_token=7.2e-7)
    assert "costs.region=eu-west-1.input_cost_per_token" in r.uncovered
    _, r, _ = run(synthetic(regions4(0.00072 * 1.4)), regs, input_cost_per_token=7.2e-7, output_cost_per_token=7.2e-7)
    assert "costs.region=eu-west-1.input_cost_per_token" not in r.uncovered  # a real 40% regional premium
    _, r, _ = run(synthetic(regions4(0.00072 * 4.9)), regs, input_cost_per_token=7.2e-7, output_cost_per_token=7.2e-7)
    assert "costs.region=eu-west-1.input_cost_per_token" not in r.uncovered
    two = {"us-east-1": llama(), "eu-west-1": llama(0.0072)}  # the guard needs two other regions
    _, r, _ = run(synthetic(two), ["us-east-1", "eu-west-1"], input_cost_per_token=7.2e-7, output_cost_per_token=7.2e-7)
    assert r.uncovered == []  # two regions are not enough to call either an outlier


# ---- time budget, cached failures, never raising ---------------------------------------------

def test_the_time_budget_is_shared_by_all_regions_of_a_file():
    clock = [0.0]
    calls = []
    data = __import__("json").dumps(load("aws-bedrock-us-east-1.json")).encode()

    def slow(u):
        calls.append(u)
        clock[0] += 25.0
        if "AmazonBedrockFoundationModels" in u:
            raise NotFound_(u)
        return data

    from verify.sources._common import NotFound as NotFound_
    s = AwsPriceListSource(slow, deadline_s=60.0, clock=lambda: clock[0])
    regs = [f"us-east-{i}" for i in range(1, 9)]
    r = s.check(*cl(LLAMA, regions=regs, input_cost_per_token=7.2e-7, output_cost_per_token=7.2e-7))
    assert len(calls) <= 3  # 25s per fetch: the budget is spent after the third
    assert r.partial and any("unreachable" in n for n in r.notes)
    n = len(calls)
    s.check(*cl(LLAMA, regions=regs, input_cost_per_token=7.2e-7))
    assert len(calls) == n  # later files cost no further fetch: failures are cached per region


def test_a_failed_region_is_fetched_once_per_run():
    s, fetch = source(**{url(FM, "eu-west-1"): outage()})
    for _ in range(3):
        s.check("providers/aws-bedrock/n.yaml", doc("amazon.nova-2-lite-v1:0", regions=("eu-west-1",), input_cost_per_token=1e-7))
    assert sum(u.endswith("eu-west-1/index.json") for u in fetch.calls) == 1


def test_check_never_raises_on_junk():
    s, _ = source()
    r = s.check("providers/aws-bedrock/x.yaml", {"model": 5, "costs": [{"region": ["x"], "input_cost_per_token": {}}, "junk"]})
    assert r.partial
    s._outlier_regions = lambda *a, **k: (_ for _ in ()).throw(KeyError("boom"))
    r = s.check(*cl(LLAMA, input_cost_per_token=7.2e-7))
    assert r.partial and "adapter error" in r.notes[0]


# ---- batch, flex and priority ------------------------------------------------------------------

def test_batch_prices_are_compared_with_the_batch_sku():
    s, _ = source()
    r = s.check(*cl("us.meta.llama3-3-70b-instruct-v1:0", input_cost_per_token=7.2e-7, output_cost_per_token=7.2e-7,
                    input_cost_per_token_batches=3.6e-7, output_cost_per_token_batches=3.6e-7))
    assert r.fully_verified and len(r.checks) == 4
    r = s.check(*cl("us.meta.llama3-3-70b-instruct-v1:0", input_cost_per_token=7.2e-7, output_cost_per_token=7.2e-7,
                    input_cost_per_token_batches=7.2e-7, output_cost_per_token_batches=3.6e-7))
    (c,) = r.conflicts
    assert c.locator == ("costs", "region=us-east-1", "input_cost_per_token_batches")
    assert (c.file_value, c.source_value) == (7.2e-7, 3.6e-7) and c.writable


def test_batch_follows_the_same_regional_vs_global_rule_for_claude():
    s, _ = source()
    std_r = dict(input_cost_per_token=5.5e-6, output_cost_per_token=2.75e-5, cache_read_input_token_cost=5.5e-7,
                 cache_creation_input_token_cost=6.875e-6, cache_creation_input_token_cost_per_hour=1.1e-5)
    std_g = dict(input_cost_per_token=5e-6, output_cost_per_token=2.5e-5, cache_read_input_token_cost=5e-7,
                 cache_creation_input_token_cost=6.25e-6, cache_creation_input_token_cost_per_hour=1e-5)
    assert s.check(*cl("us.anthropic.claude-opus-5", input_cost_per_token_batches=2.75e-6,
                       output_cost_per_token_batches=1.375e-5, **std_r)).fully_verified
    assert s.check(*cl("global.anthropic.claude-opus-5", input_cost_per_token_batches=2.5e-6,
                       output_cost_per_token_batches=1.25e-5, **std_g)).fully_verified
    r = s.check(*cl("global.anthropic.claude-opus-5", input_cost_per_token_batches=2.75e-6,
                    output_cost_per_token_batches=1.375e-5, **std_g))
    assert sorted(c.locator[-1] for c in r.conflicts) == ["input_cost_per_token_batches", "output_cost_per_token_batches"]


def test_legacy_claude_batch_usage_types():
    s, _ = source()
    r = s.check(*cl("anthropic.claude-3-5-sonnet-20241022-v2:0", input_cost_per_token=3e-6, output_cost_per_token=1.5e-5,
                    cache_read_input_token_cost=3e-7, cache_creation_input_token_cost=3.75e-6,
                    input_cost_per_token_batches=1.5e-6, output_cost_per_token_batches=7.5e-6))
    assert r.fully_verified
    r = s.check(*cl("anthropic.claude-sonnet-4-5-20250929-v1:0", **{**SONNET45_REGIONAL},
                    input_cost_per_token_batches=1.65e-6, output_cost_per_token_batches=8.25e-6))
    assert r.fully_verified


GPT_OSS = dict(input_cost_per_token=1.5e-7, output_cost_per_token=6e-7)


def test_flex_and_priority_dicts_are_compared_leaf_by_leaf():
    s, _ = source()
    r = s.check(*cl("openai.gpt-oss-120b-1:0", input_cost_per_token_batches=7.5e-8, output_cost_per_token_batches=3e-7,
                    flex_pricing={"input_cost_per_token": 7.5e-8, "output_cost_per_token": 3e-7},
                    priority_pricing={"input_cost_per_token": "2.625e-7", "output_cost_per_token": 1.05e-6}, **GPT_OSS))
    assert r.fully_verified and len(r.checks) == 8
    loc = {c.locator[2:] for c in r.checks}
    assert ("flex_pricing", "input_cost_per_token") in loc and ("priority_pricing", "output_cost_per_token") in loc
    r = s.check(*cl("openai.gpt-oss-120b-1:0", flex_pricing={"input_cost_per_token": 7.5e-8, "output_cost_per_token": 3e-7},
                    priority_pricing={"input_cost_per_token": 3e-7, "output_cost_per_token": 1.05e-6}, **GPT_OSS))
    (c,) = r.conflicts
    assert c.locator == ("costs", "region=us-east-1", "priority_pricing", "input_cost_per_token") and c.source_value == 2.625e-7


def test_a_flex_dict_with_a_leaf_the_price_list_lacks_stays_uncovered():
    s, _ = source()
    r = s.check(*cl("openai.gpt-oss-120b-1:0", flex_pricing={"input_cost_per_token": 7.5e-8, "cache_read_input_token_cost": 1e-8},
                    **GPT_OSS))
    assert r.conflicts == [] and r.partial and not r.fully_verified
    assert r.uncovered == ["costs.region=us-east-1.flex_pricing"]
    assert any("flex_pricing not compared for: cache_read_input_token_cost" in n for n in r.notes)
    assert [c.locator[-1] for c in r.checks if c.locator[-2] == "flex_pricing"] == ["input_cost_per_token"]


def test_global_ids_take_global_flex_and_priority_prices():
    s, _ = source()
    glob = dict(input_cost_per_token=3e-7, output_cost_per_token=2.5e-6, cache_read_input_token_cost=7.5e-8)
    r = s.check(*cl("global.amazon.nova-2-lite-v1:0", input_cost_per_token_batches=1.5e-7,
                    output_cost_per_token_batches=1.25e-6,
                    flex_pricing={"input_cost_per_token": 1.5e-7, "output_cost_per_token": 1.25e-6, "cache_read_input_token_cost": 3.75e-8},
                    priority_pricing={"input_cost_per_token": 5.25e-7, "output_cost_per_token": 4.375e-6, "cache_read_input_token_cost": 1.3125e-7},
                    **glob))
    assert r.fully_verified, (r.conflicts, r.uncovered, r.notes)
    regional = s.check(*cl("us.amazon.nova-2-lite-v1:0", input_cost_per_token=3.3e-7, output_cost_per_token=2.75e-6,
                           cache_read_input_token_cost=8.25e-8,
                           flex_pricing={"input_cost_per_token": 1.65e-7, "output_cost_per_token": 1.375e-6},
                           input_cost_per_token_batches=1.65e-7, output_cost_per_token_batches=1.375e-6))
    assert regional.fully_verified
    wrong = s.check(*cl("global.amazon.nova-2-lite-v1:0", flex_pricing={"input_cost_per_token": 1.65e-7}, **glob))
    assert [c.locator[-1] for c in wrong.conflicts if c.locator[-2] == "flex_pricing"] == ["input_cost_per_token"]


def test_zero_priced_tier_cache_write_matches_a_zero_in_the_file():
    s, _ = source()
    r = s.check(*cl("us.amazon.nova-2-lite-v1:0", input_cost_per_token=3.3e-7, output_cost_per_token=2.75e-6,
                    cache_read_input_token_cost=8.25e-8,
                    flex_pricing={"input_cost_per_token": 1.65e-7, "output_cost_per_token": 1.375e-6,
                                  "cache_read_input_token_cost": 4.125e-8, "cache_creation_input_token_cost": 0}))
    assert r.fully_verified
    r = s.check(*cl("us.amazon.nova-2-lite-v1:0", flex_pricing={"cache_creation_input_token_cost": 1e-7}))
    assert [c.locator[-1] for c in r.conflicts] == ["cache_creation_input_token_cost"]


def test_tier_prices_the_file_does_not_carry_are_a_note_not_a_flag():
    s, _ = source()
    r = s.check(*cl("openai.gpt-oss-120b-1:0", **GPT_OSS))
    assert r.fully_verified
    assert any("has batch prices this file does not carry" in n and "input_cost_per_token_batches" in n for n in r.notes)
    assert any("has flex prices" in n for n in r.notes) and any("has priority prices" in n for n in r.notes)


def test_a_cross_region_batch_sku_is_the_global_batch_price_only_with_the_global_modifier():
    glob = sku(LLAMA_IN + "-cross-region-global-batch", 0.0003)
    plain = sku(LLAMA_IN + "-cross-region-batch", 0.0009)
    both = [*llama(), glob, plain, sku(LLAMA_IN + "-batch", 0.00036)]
    _, r, _ = run(synthetic({"us-east-1": both}), ["us-east-1"], input_cost_per_token=7.2e-7, output_cost_per_token=7.2e-7,
                  input_cost_per_token_batches=3.6e-7)
    assert r.fully_verified


def test_two_tiers_in_one_usage_type_or_an_unknown_tier_word_is_skipped():
    odd = [sku(LLAMA_IN + "-batch-flex", 0.0001), sku(LLAMA_IN + "-provisioned", 0.0001), *llama()]
    _, r, _ = run(synthetic({"us-east-1": odd}), ["us-east-1"], input_cost_per_token=7.2e-7, output_cost_per_token=7.2e-7,
                  input_cost_per_token_batches=1e-4)
    assert r.checks and all(c.locator[-1] != "input_cost_per_token_batches" for c in r.checks)
    assert r.uncovered == ["costs.region=us-east-1.input_cost_per_token_batches"]


def test_a_tier_sku_with_two_prices_is_ambiguous_and_not_compared():
    _, r, _ = run(synthetic({"us-east-1": [*llama(), sku(LLAMA_IN + "-batch", 0.00036), sku(LLAMA_IN + "-batch", 0.0004)]}),
                  ["us-east-1"], input_cost_per_token=7.2e-7, output_cost_per_token=7.2e-7, input_cost_per_token_batches=3.6e-7)
    assert all(c.locator[-1] != "input_cost_per_token_batches" for c in r.checks)
    assert "costs.region=us-east-1.input_cost_per_token_batches" in r.uncovered


def test_legacy_million_batch_usage_types_of_the_foundation_offer():
    hk = "Claude 3 Haiku (Amazon Bedrock Edition)"
    fm = offer(sku("USE1-MP:USE1_InputTokenCount-Units", 0.25, "1M tokens", service=hk),
               sku("USE1-MP:USE1_OutputTokenCount-Units", 1.25, "1M tokens", service=hk),
               sku("USE1-MP:USE1_MillionBatchInputTokens-Units", 0.125, "1M tokens", service=hk),
               sku("USE1-MP:USE1_MillionBatchOutputTokens-Units", 0.625, "1M tokens", service=hk),
               sku("USE1-MP:USE1_InputTokenCount_Batch-Units", 0.125, "1M tokens", service=hk))  # same price twice: fine
    import json
    s = AwsPriceListSource(FakeFetch({url(FM, "us-east-1"): json.dumps(fm).encode()}))
    ok = dict(input_cost_per_token=2.5e-7, output_cost_per_token=1.25e-6, input_cost_per_token_batches=1.25e-7,
              output_cost_per_token_batches=6.25e-7)
    r = s.check("providers/aws-bedrock/c.yaml", doc("anthropic.claude-3-haiku-20240307-v1:0", **ok))
    assert r.fully_verified and len(r.checks) == 4
    r = s.check("providers/aws-bedrock/c.yaml", doc("anthropic.claude-3-haiku-20240307-v1:0", **{**ok, "output_cost_per_token_batches": 1.25e-6}))
    assert [c.locator[-1] for c in r.conflicts] == ["output_cost_per_token_batches"]


def test_batch_cache_prices_have_no_catalog_field_and_never_leak_into_the_standard_cache_price():
    extra = [sku("USE1-Llama3-3-70B-cache-read-input-token-count", 0.0001), sku("USE1-Llama3-3-70B-cache-read-input-token-count-batch", 0.00005)]
    _, r, _ = run(synthetic({"us-east-1": llama(extra=extra)}), ["us-east-1"], input_cost_per_token=7.2e-7,
                  output_cost_per_token=7.2e-7, cache_read_input_token_cost=1e-7)
    assert r.fully_verified


# ---- explicit $0 SKUs, hostile region strings --------------------------------------------------------

def test_an_explicit_zero_sku_against_a_nonzero_catalog_value_says_so():
    s, _ = source()
    r = s.check(*cl("us.amazon.nova-2-lite-v1:0", input_cost_per_token=3.3e-7, output_cost_per_token=2.75e-6,
                    cache_read_input_token_cost=8.25e-8, cache_creation_input_token_cost=6e-8,
                    flex_pricing={"cache_creation_input_token_cost": 5e-8}))
    zeros = {c.locator[2:]: c for c in r.conflicts}
    assert zeros[("cache_creation_input_token_cost",)].note == "source lists $0"
    assert zeros[("flex_pricing", "cache_creation_input_token_cost")].note == "source lists $0"
    assert zeros[("cache_creation_input_token_cost",)].source_value == 0.0 and zeros[("cache_creation_input_token_cost",)].writable
    r = s.check(*cl("us.amazon.nova-2-lite-v1:0", input_cost_per_token=9e-7))  # a real price conflict has no such text
    assert r.conflicts and all("source lists $0" not in c.note for c in r.conflicts)


def test_nova_micro_style_zero_cache_write_from_a_synthetic_offer():
    micro = [sku("USE1-NovaMicro-input-tokens", 0.000035), sku("USE1-NovaMicro-output-tokens", 0.00014),
             sku("USE1-NovaMicro-cache-write-input-token-count", 0.0)]
    s = AwsPriceListSource(FakeFetch({url(BR, "us-east-1"): json.dumps(offer(*micro)).encode()}))
    path = "providers/aws-bedrock/amazon.nova-micro-v1:0.yaml"
    base = dict(input_cost_per_token=3.5e-8, output_cost_per_token=1.4e-7)
    (c,) = s.check(path, doc("amazon.nova-micro-v1:0", cache_creation_input_token_cost=4.375e-8, **base)).conflicts
    assert c.note == "source lists $0" and c.file_value == 4.375e-8
    assert s.check(path, doc("amazon.nova-micro-v1:0", cache_creation_input_token_cost=0, **base)).fully_verified


HOSTILE_REGIONS = ["../../etc/passwd", "us-east-1/../../x", "//evil.example/x", "us-east-1%2f..%2fx", "us-east-1?x=1",
                   "us-east-1#", "us-east-1\n", "us-east-1 ", "us-eâst-1", "us-east-١", "US-EAST-1", "us-east", "*",
                   "global", "", "None", "us-east-1/index.json?", "http://evil/us-east-1", "-east-1"]


def test_a_hostile_region_is_never_put_in_a_url():
    s, fetch = source()
    for region in HOSTILE_REGIONS:
        r = s.check("providers/aws-bedrock/x.yaml", {"model": LLAMA, "costs": [
            {"region": region, "input_cost_per_token": 7.2e-7, "output_cost_per_token": 7.2e-7}]})
        assert r.partial and r.checks == [], region
        assert sorted(u.split(".")[-1] for u in r.uncovered) == ["input_cost_per_token", "output_cost_per_token"], region
        assert any("not an AWS region code" in n for n in r.notes), region
    assert fetch.calls == []
    with pytest.raises(ValueError):  # the URL builder itself refuses too
        s.region_rates("../x")
    r = s.check("providers/aws-bedrock/x.yaml", {"model": LLAMA, "costs": [{"region": ["us-east-1"], "input_cost_per_token": 1}]})
    assert r.partial and fetch.calls == []


def test_real_region_codes_pass_the_validator():
    from verify.sources.aws_price_list import REGION_RE
    for ok in ("us-east-1", "us-gov-west-1", "ap-southeast-7", "eu-central-2", "me-central-1", "il-central-1"):
        assert REGION_RE.fullmatch(ok), ok
