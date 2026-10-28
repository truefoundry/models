"""Azure Retail Prices adapter: offline, against trimmed REAL rows (fetched 2026-10-28) and real catalog slices."""
from __future__ import annotations

import copy
import json

import pytest

from verify.sources import azure_retail as az
from verify.sources.azure_retail import AzureRetailSource, Index, build_url, id_keys, parse_sku

from .fx import FakeFetch, load, outage

TODAY = "2026-10-28"
URL1 = build_url()
URL2 = URL1 + "&$skip=1000"
NEXT = "https://prices.azure.com:443/api/retail/prices?api-version=2023-01-01-preview&$filter=x&$skip=1000"


def rows() -> list[dict]:
    return copy.deepcopy(load("azure-retail-items.json"))


def docs() -> dict[str, dict]:
    return copy.deepcopy(load("azure-catalog-docs.json"))


def pages(items: list[dict]) -> dict[str, bytes]:
    half = len(items) // 2
    first = {"Items": items[:half], "NextPageLink": NEXT, "Count": half}
    second = {"Items": items[half:], "NextPageLink": None, "Count": len(items) - half}
    return {URL1: json.dumps(first).encode(), NEXT: json.dumps(second).encode()}


def source(mutate=None, **kw):
    items = rows()
    if mutate:
        mutate(items)
    fetch = FakeFetch(pages(items))
    return AzureRetailSource(fetch, today=TODAY, **kw), fetch


def run(s, name: str, doc_mutate=None):
    path = f"providers/{name}.yaml"
    doc = docs()[path]
    if doc_mutate:
        doc_mutate(doc)
    return s.check(path, doc)


def meter(items, sku, region="eastus2"):
    return [i for i in items if i["skuName"] == sku and i["armRegionName"] == region]




GPT41 = "azure-open-ai/gpt-4.1"
GPT4O = "azure-open-ai/gpt-4o-2024-11-20"
O1 = "azure-open-ai/o1"
O1_DATED = "azure-open-ai/o1-2024-12-17"
O3 = "azure-open-ai/o3"
GPT51 = "azure-open-ai/gpt-5.1"
GPT54 = "azure-open-ai/gpt-5.4"
DSV4 = "microsoft-foundry/DeepSeek-V4-Flash-0731-2026-07-31"
KIMI26 = "microsoft-foundry/Kimi-K2.6"
GROK3 = "microsoft-foundry/grok-3"


def by_field(r):
    return {c.locator[1:]: c for c in r.checks}


def conflict_fields(r):
    return sorted(".".join(c.locator[1:]) for c in r.conflicts)


# ---- the request, the grammar, the matching ------------------------------------------------------------

def test_covers_the_three_azure_providers_only():
    s, _ = source()
    assert all(s.covers(p) for p in ("azure-open-ai", "azure-ai-foundry", "microsoft-foundry"))
    assert not (s.covers("openrouter") or s.covers("aws-bedrock") or s.covers("azure"))


def test_registered_under_its_name():
    from verify.sources import SOURCES
    assert SOURCES["azure-retail-prices"] is AzureRetailSource
    assert AzureRetailSource.name == "azure-retail-prices"


def test_url_is_a_fixed_host_and_a_whitelisted_filter():
    assert URL1.startswith("https://prices.azure.com/api/retail/prices?api-version=2023-01-01-preview&$filter=")
    for region in az.FETCH_REGIONS:
        assert f"armRegionName%20eq%20%27{region}%27" in URL1
    for bad in ("westeurope", "eastus2' or 1 eq 1", "", "EASTUS2", "../x"):
        with pytest.raises(ValueError):
            build_url((bad,))


def test_one_fetch_per_run_follows_next_page_link_and_files_share_it():
    s, fetch = source()
    for path, doc in docs().items():
        s.check(path, doc)
    assert fetch.calls == [URL1, NEXT]


@pytest.mark.parametrize("sku,unit,want", [
    ("5.4 nano Batch cd Inp Gl", "1M", ("5.4nano", "global", "batch", "cache_read")),
    ("gpt 4.1 Inp regnl", "1K", ("gpt4.1", "regional", "", "input")),
    ("gpt 4o 1120 Batch Outp DZ", "1K", ("gpt4o1120", "datazone", "batch", "output")),
    ("gpt 4o 0513 Input Data Zone", "1K", ("gpt4o0513", "datazone", "", "input")),
    ("gpt-4o-0806-Batch-Inp-glbl", "1K", ("gpt4o0806", "global", "batch", "input")),
    ("V4 Flash cached DZ", "1K", ("v4flash", "datazone", "", "cache_read")),
    ("5.6 luna ShortCo Cd Wr Std Gl", "1M", ("5.6luna", "global", "", "cache_write")),
    ("5.6 sol ShortCo Inp PP DZ", "1M", ("5.6sol", "datazone", "priority", "input")),
    ("6-sol ShortCo Opt Flex Gl", "1M", ("6sol", "global", "flex", "output")),
    ("o4-mini 0416 cached Inp DataZone", "1K", ("o4mini0416", "datazone", "", "cache_read")),
])
def test_sku_grammar_reads_the_real_spellings(sku, unit, want):
    suffix = "1M Tokens" if unit == "1M" else "Tokens"
    m = parse_sku(sku, f"{sku} {suffix}", unit)
    assert m is not None and (m.model, m.scope, m.tier, m.kind) == want and not m.long and not m.promo


@pytest.mark.parametrize("sku,meter,unit", [
    ("Phi-4-Input", "Phi-4-Input Tokens", "1K"),                              # no deployment-type token: not guessed
    ("gpt 4.1 Inp glbl regnl", "gpt 4.1 Inp glbl regnl Tokens", "1K"),         # two deployment types
    ("gpt 4.1 Inp Outp glbl", "gpt 4.1 Inp Outp glbl Tokens", "1K"),           # two kinds
    ("Provisioned Managed Global", "Provisioned Managed Global Unit", "1/Hour"),
    ("Flex Ref glbl", "Flex Ref glbl Megapixel", "1"),
    ("gpt 4.1 Inp glbl", "gpt 4.1 Inp glbl Tokens", "1M"),                      # the meter name says 1K tokens, the unit 1M
    ("gpt 4.1 Inp glbl", "gpt 4.1 Inp glbl 1M Tokens", "1K"),                   # and the other way round
    ("gpt 4.1 Inp glbl", "gpt 4.1 Inp glbl Pages", "1K"),
    ("Inp glbl", "Inp glbl Tokens", "1K"),                                      # nothing left for a model name
])
def test_sku_grammar_ignores_anything_it_does_not_fully_read(sku, meter, unit):
    assert parse_sku(sku, meter, unit) is None


def test_long_context_sku_is_recognised_but_never_a_standard_price():
    m = parse_sku("5.5 LongCo Batch inp Gl", "5.5 LongCo Batch inp Gl 1M Tokens", "1M")
    assert m is not None and m.long and m.model == "5.5"
    idx = Index()
    for i in rows():
        idx.add(i)
    assert "5.4" in idx.long_ctx
    assert all("longco" not in m for m in idx.rows)


def test_id_keys_dated_ids_try_mmdd_then_mmddyyyy_then_dateless():
    assert id_keys("gpt-4o-2024-11-20") == ["gpt4o1120", "gpt4o11202024", "gpt4o"]
    assert id_keys("gpt-chat-latest-2026-10-07")[:2] == ["gptchatlatest1007", "gptchatlatest10072026"]
    assert id_keys("DeepSeek-V4-Flash-0731-2026-07-31")[0] == "deepseekv4flash07310731"
    assert id_keys("Llama-3.3-70B-Instruct") == ["llama3.370b"]
    assert id_keys("gpt-4.1") == ["gpt4.1"]


# ---- verified, and where the catalog and Azure really differ -------------------------------------------

@pytest.mark.parametrize("name,n", [(GPT41, 24), (GPT51, 32), (O3, 6), (O1, 3), ("microsoft-foundry/Kimi-K2.7-Code", 3),
                                    ("microsoft-foundry/Llama-3.3-70B-Instruct", 2), (GROK3, 2),
                                    ("microsoft-foundry/mistral-large-3", 2)])
def test_files_whose_every_price_is_azures_are_fully_verified(name, n):
    r = run(source()[0], name)
    assert r.fully_verified and len(r.checks) == n and r.conflicts == [] and r.uncovered == []


def test_every_deployment_type_is_compared_with_its_own_meters():
    r = run(source()[0], GPT41)
    got = by_field(r)
    assert got[("region=global", "input_cost_per_token")].source_value == 2e-06
    assert got[("region=datazone_us", "input_cost_per_token")].source_value == 2.2e-06
    assert got[("region=datazone_eu", "input_cost_per_token")].source_value == 2.2e-06
    assert got[("region=global", "input_cost_per_token_batches")].source_value == 1e-06
    assert got[("region=global", "priority_pricing", "input_cost_per_token")].source_value == 3.5e-06
    assert got[("region=datazone_us", "priority_pricing", "cache_read_input_token_cost")].source_value == 9.63e-07


def test_real_conflicts_are_found_where_the_file_differs():
    s, _ = source()
    r = run(s, "azure-open-ai/gpt-4.1-nano")
    assert conflict_fields(r) == ["region=datazone_us.cache_read_input_token_cost", "region=datazone_us.input_cost_per_token_batches"]
    r = run(s, DSV4)  # the file holds the V4 Flash prices, Azure bills the 0731 meters 2.3x higher
    assert conflict_fields(r) == ["region=global.input_cost_per_token", "region=global.output_cost_per_token"]
    assert (by_field(r)[("region=global", "input_cost_per_token")].file_value,
            by_field(r)[("region=global", "input_cost_per_token")].source_value) == (1.9e-07, 4.4e-07)
    r = run(s, "azure-open-ai/gpt-5.1-chat")
    assert conflict_fields(r) == ["region=datazone_eu.cache_read_input_token_cost", "region=datazone_us.cache_read_input_token_cost"]


def test_the_two_meter_spellings_of_one_model_are_merged():
    r = run(source()[0], KIMI26)  # `K2.6 cached` (no Thinking) + `K2.6 Thinking Inp/Outp`: three prices from two spellings
    assert len(r.checks) == 2 and r.conflicts == []
    r = run(source()[0], GPT51)
    assert r.fully_verified  # `5.1 pp ...` (GPT5 product) and `GPT 5.1 ...` are one model


# ---- mutations: every one of these must change the verdict -----------------------------------------------

def test_mutation_global_vs_regional_vs_datazone_are_scoped():
    # the Global meter alone changes: only the `global` entry may conflict, `*` (Regional) and Data Zone stay verified
    def bump(items):
        for i in meter(items, "gpt 4o 1120 Inp glbl") + meter(items, "gpt 4o 1120 Inp glbl", "swedencentral") + meter(items, "gpt 4o 1120 Inp glbl", "francecentral"):
            i["retailPrice"] *= 1.5
    r = run(source(bump)[0], GPT4O)
    assert conflict_fields(r) == ["region=global.input_cost_per_token"]
    # the Regional meter alone changes: only `*` conflicts
    def regional(items):
        for i in meter(items, "gpt 4o 1120 Inp regnl"):
            i["retailPrice"] *= 1.5
    r = run(source(regional)[0], GPT4O)
    assert conflict_fields(r) == ["region=*.input_cost_per_token"]
    # the Data Zone meter alone changes: both datazone entries conflict, nothing else
    def dz(items):
        for i in [x for x in items if x["skuName"] == "gpt 4o 1120 Inp Data Zone"]:
            i["retailPrice"] *= 1.5
    r = run(source(dz)[0], GPT4O)
    assert conflict_fields(r) == ["region=datazone_eu.input_cost_per_token", "region=datazone_us.input_cost_per_token"]


def test_mutation_datazone_us_and_eu_use_their_own_reference_regions():
    def eu_only(items):
        for i in items:
            if i["skuName"] == "gpt 4o 1120 Inp Data Zone" and i["armRegionName"] in az.EU_REFS:
                i["retailPrice"] *= 2
    r = run(source(eu_only)[0], GPT4O)
    assert conflict_fields(r) == ["region=datazone_eu.input_cost_per_token"]
    def us_only(items):
        for i in items:
            if i["skuName"] == "gpt 4o 1120 Inp Data Zone" and i["armRegionName"] in az.US_REFS:
                i["retailPrice"] *= 2
    r = run(source(us_only)[0], GPT4O)
    assert conflict_fields(r) == ["region=datazone_us.input_cost_per_token"]


def test_mutation_only_consumption_rows_of_foundry_models_count():
    def other(items):
        for i in [x for x in items if x["skuName"] == "gpt 4.1 Inp glbl"]:
            items.append({**i, "type": "Reservation", "retailPrice": 9.0})
            items.append({**i, "type": "DevTestConsumption", "retailPrice": 7.0})
            items.append({**i, "serviceName": "Foundry Tools", "retailPrice": 5.0})
            items.append({**i, "armRegionName": "westeurope", "retailPrice": 3.0})
    a, b = run(source()[0], GPT41), run(source(other)[0], GPT41)
    assert b.fully_verified and [(c.locator, c.source_value) for c in a.checks] == [(c.locator, c.source_value) for c in b.checks]


def test_mutation_the_regional_surcharge_of_a_region_is_not_the_list_price():
    # swedencentral's Regional meter is +10%: it is not a reference region for `*`, so it cannot move the verdict
    s, _ = source()
    items = rows()
    sw = [i["retailPrice"] for i in meter(items, "gpt 4.1 Inp regnl", "swedencentral")]
    us = [i["retailPrice"] for i in meter(items, "gpt 4.1 Inp regnl")]
    assert sw == [0.00242] and us == [0.0022]
    doc = {"model": "gpt-4.1", "costs": [{"region": "global", "input_cost_per_token": 2e-06}, {"region": "*", "input_cost_per_token": 2.2e-06}]}
    r = s.check("providers/azure-open-ai/gpt-4.1.yaml", doc)
    assert r.conflicts == [] and [c.status for c in r.checks] == ["verified", "verified"]
    doc["costs"][1]["input_cost_per_token"] = 2.42e-06  # what a +10% region charges
    assert [c.locator[-1] for c in s.check("providers/azure-open-ai/gpt-4.1.yaml", doc).conflicts] == ["input_cost_per_token"]


def test_mutation_unit_scale_1k_vs_1m():
    def retag(items):  # same price, the unit now says 1M while the name still says Tokens (1K): contradiction, ignored
        for i in meter(items, "gpt 4.1 Inp glbl") + meter(items, "gpt 4.1 Inp glbl", "swedencentral") + meter(items, "gpt 4.1 Inp glbl", "francecentral") + meter(items, "gpt 4.1 Inp glbl", "eastus"):
            i["unitOfMeasure"] = "1M"
    r = run(source(retag)[0], GPT41)
    assert not r.fully_verified and r.conflicts == []
    assert "costs.region=global.input_cost_per_token" in r.uncovered
    def scale(items):  # a consistent 1M meter with the 1K number: 1000x off in USD per token
        for i in items:
            if i["skuName"] == "gpt 4.1 Inp glbl":
                i["unitOfMeasure"], i["meterName"] = "1M", "gpt 4.1 Inp glbl 1M Tokens"
    r = run(source(scale)[0], GPT41)
    assert conflict_fields(r) == ["region=global.input_cost_per_token"]
    assert by_field(r)[("region=global", "input_cost_per_token")].source_value == 2e-09


def test_mutation_alias_table_is_what_connects_a_dated_meter_to_an_undated_file(monkeypatch):
    assert run(source()[0], O3).fully_verified
    monkeypatch.setattr(az, "ALIASES", {})
    r = run(source()[0], O3)
    assert r.checks == [] and not r.fully_verified and any("no Azure meter I can match" in n for n in r.notes)
    monkeypatch.setattr(az, "ALIASES", {"o3": ("o4mini0416",)})  # a wrong alias must show up as conflicts, not as verified
    r = run(source()[0], O3)
    assert r.conflicts and not r.fully_verified


def test_mutation_batch_is_not_standard():
    def batch(items):
        for i in [x for x in items if x["skuName"] == "gpt 4.1 Batch Inp glbl"]:
            i["retailPrice"] *= 3
    r = run(source(batch)[0], GPT41)
    assert conflict_fields(r) == ["region=global.input_cost_per_token_batches"]
    def standard(items):
        for i in [x for x in items if x["skuName"] == "gpt 4.1 Inp glbl"]:
            i["retailPrice"] *= 3
    r = run(source(standard)[0], GPT41)
    assert conflict_fields(r) == ["region=global.input_cost_per_token"]


def test_mutation_cache_meter():
    def cache(items):
        for i in [x for x in items if x["skuName"] == "gpt 4.1 cached Inp glbl"]:
            i["retailPrice"] *= 2
    assert conflict_fields(run(source(cache)[0], GPT41)) == ["region=global.cache_read_input_token_cost"]
    def gone(items):
        items[:] = [x for x in items if x["skuName"] != "gpt 4.1 cached Inp glbl"]
    r = run(source(gone)[0], GPT41)
    assert r.conflicts == [] and not r.fully_verified
    assert "costs.region=global.cache_read_input_token_cost" in r.uncovered
    r = run(source()[0], GPT41, lambda d: d["costs"][0].pop("cache_read_input_token_cost"))
    assert r.conflicts == [] and not r.fully_verified and any(n.startswith("missing in file") for n in r.notes)


def test_mutation_outage_is_partial_and_the_failure_is_cached():
    fetch = FakeFetch({URL1: outage()})
    s = AzureRetailSource(fetch, today=TODAY)
    for name in (GPT41, GPT51, O3):
        r = run(s, name)
        assert r.partial and r.checks == [] and not r.fully_verified and "unreachable" in r.notes[0]
        assert r.uncovered  # every price of the file is uncovered
    assert fetch.calls == [URL1]


def test_mutation_deadline_stops_the_paging_and_leaves_no_half_index():
    t = iter([0.0, 1.0, 100.0, 100.0, 100.0, 100.0])
    s = AzureRetailSource(FakeFetch(pages(rows())), today=TODAY, deadline_s=60, clock=lambda: next(t))
    r = run(s, GPT41)
    assert r.partial and r.checks == [] and "unreachable" in r.notes[0]
    assert s._index is None
    assert len(s._fetch.calls) == 1  # type: ignore[attr-defined]


def test_mutation_promotional_meter_is_never_the_list_price():
    def promo(items):
        for i in [x for x in items if x["skuName"] == "gpt 4.1 Inp glbl" and x["armRegionName"] == "eastus2"]:
            items.append({**i, "skuName": "gpt 4.1 Inp glbl promo", "meterName": "gpt 4.1 Inp glbl promo Tokens", "retailPrice": 0.001})
    r = run(source(promo)[0], GPT41)
    assert r.conflicts == [] and r.promo_active and r.partial and not r.fully_verified
    assert by_field(r)[("region=global", "input_cost_per_token")].status == "verified"
    assert any("promotional Global meter" in n for n in r.notes)
    r = run(source(promo)[0], GPT41, lambda d: d["costs"][0].update(input_cost_per_token=1.02e-06))  # the file holds the promo price
    assert r.conflicts == [] and "costs.region=global.input_cost_per_token" in r.uncovered and r.promo_active
    r = run(source(promo)[0], GPT41, lambda d: d["costs"][0].update(input_cost_per_token=5e-06))
    assert conflict_fields(r) == ["region=global.input_cost_per_token"]


def test_mutation_preview_meters_belong_to_their_own_model():
    def preview(items):
        for i in items:
            if i["skuName"].startswith("o1 preview"):
                i["retailPrice"] *= 9
    clean_run, mutated = run(source()[0], O1), run(source(preview)[0], O1)
    assert clean_run.fully_verified and mutated.fully_verified
    assert [(c.locator, c.source_value) for c in clean_run.checks] == [(c.locator, c.source_value) for c in mutated.checks]


def test_mutation_scheduled_price_change_is_not_todays_price():
    def later(items):
        for i in [x for x in items if x["skuName"] == "gpt 4.1 Inp glbl"]:
            items.append({**i, "retailPrice": 0.003, "effectiveStartDate": "2026-12-01T00:00:00Z"})
    r = run(source(later)[0], GPT41)
    assert r.conflicts == [] and by_field(r)[("region=global", "input_cost_per_token")].status == "verified"
    assert any("from 2026-12-01" in n for n in r.notes)  # said, not flagged: the file is right today
    r = run(source(later)[0], GPT41, lambda d: d["costs"][0].update(input_cost_per_token=3e-06))  # already holds the new price
    assert r.conflicts == [] and "costs.region=global.input_cost_per_token" in r.uncovered
    r = run(source(later)[0], GPT41, lambda d: d["costs"][0].update(input_cost_per_token=9e-06))
    assert conflict_fields(r) == ["region=global.input_cost_per_token"]
    def replaced(items):  # the new price took effect yesterday: it is the price now
        for i in [x for x in items if x["skuName"] == "gpt 4.1 Inp glbl"]:
            items.append({**i, "retailPrice": 0.003, "effectiveStartDate": "2026-10-27T00:00:00Z"})
    r = run(source(replaced)[0], GPT41)
    assert conflict_fields(r) == ["region=global.input_cost_per_token"]


def test_mutation_region_strings_and_ids_never_reach_a_url():
    s, fetch = source()
    for region in ("eastus2", "westeurope", "eastus2' or 1 eq 1", "../../etc", "datazone_asia", ""):
        r = run(s, GPT41, lambda d, region=region: d["costs"][0].update(region=region))
        assert r.partial and any("not looked up" in n for n in r.notes)
    bad = s.check("providers/azure-open-ai/x.yaml", {"model": "gpt-4.1/../../etc?x=1", "costs": [{"region": "*", "input_cost_per_token": 1e-6}]})
    assert bad.partial and bad.checks == [] and "not allowed in an id" in bad.notes[0]
    assert fetch.calls == [URL1, NEXT]  # nothing the files said was ever requested


def test_mutation_next_page_link_must_stay_on_the_host():
    for evil in ("https://evil.example/api/retail/prices?$skip=1000", "http://prices.azure.com/api/retail/prices?$skip=1000",
                 "https://prices.azure.com:8443/api/retail/prices?$skip=1000", "https://prices.azure.com/other?$skip=1000"):
        first = json.dumps({"Items": rows()[:5], "NextPageLink": evil}).encode()
        fetch = FakeFetch({URL1: first, evil: b'{"Items": []}'})
        r = run(AzureRetailSource(fetch, today=TODAY), GPT41)
        assert r.partial and r.checks == [] and fetch.calls == [URL1]


def test_mutation_paging_that_never_ends_is_an_error():
    first = json.dumps({"Items": [], "NextPageLink": NEXT}).encode()
    fetch = FakeFetch({URL1: first, NEXT: json.dumps({"Items": [], "NextPageLink": NEXT}).encode()})
    r = run(AzureRetailSource(fetch, today=TODAY), GPT41)
    assert r.partial and r.checks == [] and fetch.calls == [URL1, NEXT]


def test_mutation_reference_regions_that_disagree_are_ambiguous_not_verified():
    def split(items):
        for i in meter(items, "gpt 4.1 Inp glbl", "eastus"):
            i["retailPrice"] = 0.0021
    r = run(source(split)[0], GPT41)
    assert r.conflicts == [] and not r.fully_verified
    assert "costs.region=global.input_cost_per_token" in r.uncovered and any("reference regions disagree" in n for n in r.notes)


def test_mutation_two_spellings_with_two_prices_are_ambiguous():
    def clash(items):  # the priority meter (2.5) is renamed to the standard one (1.25), same day: two prices for one cell
        for i in items:
            if i["skuName"] in ("5.1 pp inp Gl", "GPT 5.1 inp Gl"):
                i["skuName"], i["meterName"] = "GPT 5.1 inp Gl", "GPT 5.1 inp Gl 1M Tokens"
                i["effectiveStartDate"] = "2026-01-01T00:00:00Z"
    r = run(source(clash)[0], GPT51)
    assert not r.fully_verified and r.conflicts == [] and any("several meters with different prices" in n for n in r.notes)
    assert "costs.region=global.input_cost_per_token" in r.uncovered


def test_mutation_long_context_meters_never_become_the_standard_price():
    def longer(items):
        for i in items:
            if "longco" in i["skuName"].lower():
                i["retailPrice"] *= 5
    a, b = run(source()[0], GPT54), run(source(longer)[0], GPT54)
    assert [(c.locator, c.source_value, c.status) for c in a.checks] == [(c.locator, c.source_value, c.status) for c in b.checks]
    assert "costs.region=*.tiered_pricing" in a.uncovered and any("long-context meters" in n for n in a.notes)


def test_mutation_the_half_percent_tolerance_is_the_boundary():
    s, _ = source()
    for value, status in ((2e-06 * 1.004, "verified"), (2e-06 * 0.996, "verified"), (2e-06 * 1.006, "conflict"), (2e-06 * 0.994, "conflict")):
        r = s.check("providers/azure-open-ai/gpt-4.1.yaml", {"model": "gpt-4.1", "costs": [{"region": "global", "input_cost_per_token": value}]})
        assert [c.status for c in r.checks] == [status], value


def test_mutation_one_k_meters_are_rounded_to_six_decimals_by_the_source():
    s, _ = source()
    check = lambda v: s.check("providers/azure-open-ai/gpt-4.1.yaml", {"model": "gpt-4.1", "costs": [{"region": "datazone_us", "priority_pricing": {"cache_read_input_token_cost": v}}]})  # noqa: E731
    # Azure publishes 0.000963 per 1K for a true 0.0009625: 9.625e-07 is the same price, 9.7e-07 is not
    assert [c.status for c in check(9.625e-07).checks] == ["verified"]
    assert [c.status for c in check(9.7e-07).checks] == ["conflict"]
    assert [c.status for c in check(9.4e-07).checks] == ["conflict"]


# ---- the `*` entry: Global or Regional ---------------------------------------------------------------------

def test_star_equal_to_the_other_deployment_type_is_uncovered_never_verified_and_never_a_conflict():
    r = run(source()[0], O1_DATED)  # `*` holds the Regional price; the file has no `global` entry, Global is the guess
    assert r.checks == [] and r.conflicts == [] and not r.fully_verified
    assert sorted(r.uncovered) == ["costs.region=*.cache_read_input_token_cost", "costs.region=*.input_cost_per_token", "costs.region=*.output_cost_per_token"]
    assert any("the Regional price (Global is 1.5e-05)" in n for n in r.notes)
    r = run(source()[0], O1)  # `*` holds the Global price
    assert r.fully_verified


def test_star_that_matches_neither_is_a_conflict_that_is_not_writable_when_the_choice_was_a_guess():
    s, _ = source()
    r = run(s, O1, lambda d: d["costs"][0].update(input_cost_per_token=9e-06))
    (c,) = r.conflicts
    assert c.source_value == 1.5e-05 and c.writable is False and "Regional" in c.note
    # with a `global` sibling `*` is the Regional price and the conflict is an ordinary, writable one
    doc = {"model": "gpt-4o-2024-11-20", "costs": [{"region": "global", "input_cost_per_token": 2.5e-06},
                                                   {"region": "*", "input_cost_per_token": 9e-06}]}
    r = s.check("providers/azure-open-ai/gpt-4o-2024-11-20.yaml", doc)
    (c,) = r.conflicts
    assert c.locator == ("costs", "region=*", "input_cost_per_token") and c.source_value == 2.75e-06 and c.writable


def test_star_without_a_regional_meter_is_compared_with_global():
    r = run(source()[0], GPT54)  # Azure bills gpt-5.4 as Global + Data Zone only
    assert all(c.status == "verified" for c in r.checks if c.locator[1] == "region=*")
    assert any(c.locator[1] == "region=*" for c in r.checks)


# ---- what is not compared ------------------------------------------------------------------------------------

def test_names_azure_does_not_bill_through_the_retail_api_are_a_note_and_partial():
    r = run(source()[0], "microsoft-foundry/claude-sonnet-4-5")
    assert r.checks == [] and r.partial and "Azure Marketplace" in r.notes[0] and not r.fully_verified


def test_unknown_models_and_undated_ids_that_could_be_any_of_several_dated_meters():
    s, _ = source()
    for name in ("azure-ai-foundry/Phi-4", "azure-open-ai/gpt-4o"):  # gpt-4o: Azure has 0513 / 0806 / 1120, none undated
        r = run(s, name)
        assert r.checks == [] and r.partial and "no Azure meter I can match" in r.notes[0]
        assert r.uncovered


def test_tiered_flex_and_priority_dicts_stay_uncovered_when_a_leaf_is_not_compared():
    r = run(source()[0], GPT54)
    assert "costs.region=*.priority_pricing" in r.uncovered and "costs.region=*.flex_pricing" in r.uncovered
    assert "costs.region=*.priority_pricing.input_cost_per_token" not in r.uncovered
    r = run(source()[0], "azure-open-ai/gpt-6-sol")
    assert "costs.region=global.tiered_pricing" in r.uncovered


def test_a_file_without_costs_or_with_garbage_never_raises():
    s, _ = source()
    assert s.check("providers/azure-open-ai/x.yaml", {"model": "gpt-4.1"}).partial
    for doc in ({"model": None, "costs": "x"}, {"costs": [None, 3, {"region": None}]}, {"model": 5, "costs": [{"region": "*", "input_cost_per_token": "x"}]},
                {"model": "gpt-4.1", "costs": [{"region": "*", "input_cost_per_token": True}]}):
        r = s.check("providers/azure-open-ai/gpt-4.1.yaml", doc)
        assert not r.fully_verified


def test_deprecated_file_with_empty_cost_entries_is_not_compared():
    r = source()[0].check("providers/azure-open-ai/gpt-4.1.yaml", {"model": "gpt-4.1", "isDeprecated": True, "costs": [{"region": "*"}]})
    assert r.checks == [] and any("deprecated" in n for n in r.notes)


# ---- write-back: the sweep applies source_value at the locator --------------------------------------------

def apply_locator(doc: dict, locator: tuple[str, ...], value) -> None:
    node = doc
    for i, token in enumerate(locator):
        last = i == len(locator) - 1
        if "=" in token and isinstance(node, list):
            key, _, want = token.partition("=")
            hits = [x for x in node if isinstance(x, dict) and str(x.get(key)) == want]
            assert len(hits) == 1, f"{token} selects {len(hits)} items"
            node = hits[0]
            continue
        assert isinstance(node, dict)
        if last:
            node[token] = value
        else:
            node = node[token]


def wrong(value):
    if isinstance(value, dict):
        return {k: (wrong(v) if k != "tiered_pricing" else v) for k, v in value.items()}
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value * 0.4
    if isinstance(value, str):
        try:
            return float(value) * 0.4
        except ValueError:
            return value
    return value


def test_writable_source_values_written_back_verify_for_every_file():
    s, _ = source()
    seen = 0
    for path, doc in docs().items():
        bad = copy.deepcopy(doc)
        for entry in bad["costs"]:
            for k in list(entry):
                if k not in ("region", "tiered_pricing"):
                    entry[k] = wrong(entry[k])
        r = s.check(path, bad)
        writable = [c for c in r.checks if c.writable]
        fixed = copy.deepcopy(bad)
        for c in writable:
            apply_locator(fixed, c.locator, c.source_value)
        again = {c.locator: c.status for c in s.check(path, fixed).checks}
        for c in writable:
            assert again.get(c.locator) == "verified", (path, c.locator, c.source_value, again.get(c.locator))
        seen += len(writable)
    assert seen > 150


def test_a_guessed_star_conflict_is_the_only_kind_that_is_not_writable():
    s, _ = source()
    for path, doc in docs().items():
        bad = copy.deepcopy(doc)
        for entry in bad["costs"]:
            for k in list(entry):
                if k not in ("region", "tiered_pricing"):
                    entry[k] = wrong(entry[k])
        for c in s.check(path, bad).checks:
            if not c.writable:
                assert c.locator[1] == "region=*" and "Regional" in c.note, (path, c.locator, c.note)
