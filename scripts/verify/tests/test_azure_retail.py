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

@pytest.mark.parametrize("name,n", [(GPT41, 24), (O3, 6), (O1, 3), ("microsoft-foundry/Kimi-K2.7-Code", 3),
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
    r = run(source()[0], GPT51)  # `5.1 pp ...` (GPT5 product) and `GPT 5.1 ...` are one model: the global entry is whole
    assert r.conflicts == [] and len(r.checks) == 24
    assert not [u for u in r.uncovered if u.startswith("costs.region=global.") or u.startswith("costs.region=datazone")]


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


# ---- hardening: bounds, links, bad prices, the golden id -> meter table, the `*` policy ------------------------

import http.server
import threading
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit

from verify.sources._common import DeadlineExceeded

REAL_NEXT = "https://prices.azure.com:443/api/retail/prices?api-version=2023-01-01-preview&$filter=serviceName%20eq%20%27Foundry%20Models%27&$skip=1000"


@pytest.mark.parametrize("link", [REAL_NEXT, REAL_NEXT.replace(":443", ""), NEXT])
def test_next_link_accepts_what_the_api_writes(link):
    assert az._next_link_ok(link)


@pytest.mark.parametrize("bad", [
    REAL_NEXT.replace("prices.azure.com:443", "prices.azure.com:8443"),
    REAL_NEXT.replace("prices.azure.com:443", "user@prices.azure.com:443"),
    REAL_NEXT.replace("prices.azure.com:443", "prices.azure.com:443@evil.example"),
    REAL_NEXT.replace("prices.azure.com:443", "prices.azure.com:"),
    REAL_NEXT.replace("prices.azure.com", "PRICES.AZURE.COM"),
    REAL_NEXT.replace("prices.azure.com", "prices.azure.com.evil.example"),
    REAL_NEXT.replace("https://", "http://"),
    REAL_NEXT.replace("/api/retail", "\\api\\retail"),
    REAL_NEXT.replace("/api/retail/prices", "/api/retail/prices/../x"),
    REAL_NEXT.replace("/api/retail/prices", "/api/other"),
    REAL_NEXT + "#frag",
    REAL_NEXT + "&x=a\\b",
    REAL_NEXT + "&x=a\tb",
    REAL_NEXT + " ",
    REAL_NEXT + "\n",
    REAL_NEXT.replace("2023-01-01-preview", "2020-01-01"),
    REAL_NEXT.replace("api-version=2023-01-01-preview&", ""),
    REAL_NEXT.replace("Foundry", "F\u00f6undry"),
    "//prices.azure.com/api/retail/prices?api-version=2023-01-01-preview",
    "",
])
def test_next_link_rejects_anything_else(bad):
    assert not az._next_link_ok(bad)


def test_redirects_only_go_to_https_on_the_same_host():
    h = az._SameHostHttps()
    req = urllib.request.Request("https://prices.azure.com/api/retail/prices")
    ok = lambda url: h.redirect_request(req, None, 302, "Found", {}, url)  # noqa: E731
    assert ok("https://prices.azure.com/api/retail/prices?x=1") is not None
    for url in ("http://prices.azure.com/x", "https://evil.example/x", "https://user@prices.azure.com/x",
                "https://prices.azure.com.evil.example/x", "https://prices.azure.com\\@evil/x", "file:///etc/passwd"):
        assert ok(url) is None


def chain_fetch(n_pages, clock=None, step=0.0, pad=0):
    calls = []

    def fetch(url):
        calls.append(url)
        if clock is not None:
            clock[0] += step
        k = len(calls)
        link = f"https://prices.azure.com:443/api/retail/prices?api-version=2023-01-01-preview&$skip={k * 1000}" if k < n_pages else None
        return json.dumps({"Items": rows()[:3], "NextPageLink": link, "pad": "x" * pad}).encode()
    fetch.calls = calls  # type: ignore[attr-defined]
    return fetch


def test_mutation_page_cap_is_twelve():
    for n, ok in ((12, True), (13, False)):
        fetch = chain_fetch(n)
        s = AzureRetailSource(fetch, today=TODAY)
        r = run(s, GPT41)
        assert (s._index is not None) is ok and len(fetch.calls) == min(n, 12)
        assert r.partial and (r.checks == [] or ok is False) or ok
    assert az.MAX_PAGES == 12


def test_mutation_byte_cap_across_pages(monkeypatch):
    monkeypatch.setattr(az, "MAX_BYTES", 3000)
    fetch = chain_fetch(5, pad=1500)  # each page ~1.7 KB: the second page crosses 3 KB
    s = AzureRetailSource(fetch, today=TODAY)
    r = run(s, GPT41)
    assert s._index is None and r.partial and r.checks == [] and len(fetch.calls) == 2
    assert isinstance(s._error, az.ResponseTooLarge)


def test_mutation_deadline_is_wall_clock_with_seven_second_pages():
    clock = [0.0]
    fetch = chain_fetch(20, clock=clock, step=7.0)
    s = AzureRetailSource(fetch, today=TODAY, deadline_s=60, clock=lambda: clock[0])
    r = run(s, GPT41)
    assert s._index is None and r.partial and r.checks == []
    assert len(fetch.calls) == 9  # t = 0, 7, ..., 56 start a page; t = 63 is past the 60 s budget


@pytest.fixture
def local_server(monkeypatch):
    monkeypatch.setattr(az, "_OPENER", urllib.request.build_opener(urllib.request.ProxyHandler({}), az._SameHostHttps))
    servers = []

    def start(handler):
        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        servers.append(srv)
        return f"http://127.0.0.1:{srv.server_port}/"
    yield start
    for srv in servers:
        srv.shutdown()
        srv.server_close()


def test_mutation_slow_drip_body_stops_at_the_deadline(local_server):
    class Drip(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Length", "100000")
            self.end_headers()
            try:
                for _ in range(100):
                    self.wfile.write(b"x")
                    self.wfile.flush()
                    time.sleep(0.2)
            except OSError:
                pass

        def log_message(self, *a):
            pass
    url = local_server(Drip)
    s = AzureRetailSource(deadline_s=1.0)
    t0 = time.monotonic()
    with pytest.raises(DeadlineExceeded):
        s._http(url)
    assert time.monotonic() - t0 < 2.5


def test_mutation_stalled_server_cannot_outlast_the_deadline(local_server):
    class Stall(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            time.sleep(3)

        def log_message(self, *a):
            pass
    s = AzureRetailSource(deadline_s=1.0)
    t0 = time.monotonic()
    with pytest.raises(Exception):
        s._http(local_server(Stall))
    assert time.monotonic() - t0 < 2.5


def test_mutation_oversized_body_is_cut_off_while_reading(local_server, monkeypatch):
    monkeypatch.setattr(az, "MAX_BYTES", 50_000)

    class Big(http.server.BaseHTTPRequestHandler):  # no Content-Length: only the bounded read can stop it
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            try:
                for _ in range(400):
                    self.wfile.write(b"x" * 10_000)
            except OSError:
                pass

        def log_message(self, *a):
            pass

    class Declared(Big):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Length", "10000000")
            self.end_headers()
    for handler in (Big, Declared):
        with pytest.raises(az.ResponseTooLarge):
            AzureRetailSource(deadline_s=10)._http(local_server(handler))


def test_mutation_http_redirect_off_host_or_to_http_is_refused(local_server):
    class Redirect(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(302)
            self.send_header("Location", "http://127.0.0.1:9/elsewhere")
            self.end_headers()

        def log_message(self, *a):
            pass
    with pytest.raises(urllib.error.HTTPError):
        AzureRetailSource(deadline_s=5)._http(local_server(Redirect))


def test_http_reads_a_small_body(local_server):
    class Ok(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"{}")

        def log_message(self, *a):
            pass
    assert AzureRetailSource(deadline_s=5)._http(local_server(Ok)) == b"{}"


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf"), -1.0, -0.002])
def test_mutation_non_finite_and_negative_prices_are_dropped_and_said(bad):
    def poison(items):
        for i in items:
            if i["skuName"] == "gpt 4.1 Inp glbl":
                i["retailPrice"] = bad
    r = run(source(poison)[0], GPT41)
    assert r.conflicts == [] and not r.fully_verified and r.partial
    assert "costs.region=global.input_cost_per_token" in r.uncovered
    assert any("NaN, infinite or negative price" in n for n in r.notes)
    only_one = lambda items: [i.__setitem__("retailPrice", bad) for i in meter(items, "gpt 4.1 Inp glbl")]  # noqa: E731
    r = run(source(only_one)[0], GPT41)  # the other regions still agree: compared, but the file is not "official"
    assert r.conflicts == [] and by_field(r)[("region=global", "input_cost_per_token")].status == "verified"
    assert r.partial and any("dropped" in n for n in r.notes)


def test_a_sku_with_two_tiers_is_not_a_price():
    for sku in ("gpt 4.1 Batch PP Inp glbl", "gpt 4.1 Flex Batch Inp glbl", "gpt 4.1 PP Flex Outp glbl"):
        assert parse_sku(sku, sku + " Tokens", "1K") is None
    assert parse_sku("gpt 4.1 Std Inp glbl", "gpt 4.1 Std Inp glbl Tokens", "1K").tier == ""


# the catalog id -> meter models it reaches: pins the alias table and the product prefixes against the fixture
GOLDEN = {
    "gpt-4o-mini": ("gpt4omini0718",),                       # ALIASES: one dated meter, undated sibling file
    "o4-mini": ("o4mini0416",), "o4-mini-2025-04-16": ("o4mini0416",),
    "o3": ("o30416",),
    "o1": ("o1", "o11217"), "o1-2024-12-17": ("o11217",),
    "Kimi-K2.5": ("k2.5", "k2.5thinking"),                   # ALIASES: cached meter has no `Thinking`
    "Kimi-K2.6": ("k2.6", "k2.6thinking"),
    "Kimi-K2.7-Code": ("k2.7code",),                         # prefix `kimi`
    "DeepSeek-V4-Flash": ("v4flash",), "DeepSeek-V4-Flash-2026-04-23": ("v4flash",),   # prefix `deepseek`
    "DeepSeek-V4-Flash-0731-2026-07-31": ("v4flash0731",),
    "grok-3": ("grok3",), "grok-4.3": ("4.3",),              # grok-4.3 via prefix `grok`; `4.3l` is another model
    "mistral-large-3": ("large3",),                          # prefix `mistral`
    "gpt-5.4": ("5.4",), "gpt-5.1-chat": ("gpt5.1chat",),    # prefix `gpt` on the GPT5 product
    "gpt-4.1": ("4.1", "gpt4.1"),                            # PP product `4.1` + OpenAI product `gpt 4.1`
    "gpt-4o-2024-11-20": ("gpt4o1120",),
    "Llama-3.3-70B-Instruct": ("llama3.370b",),
}
NO_MATCH = ("gpt-4o", "Kimi-K3", "o1-preview-x", "gpt-4.1-nano-x", "DeepSeek-R1-0528", "grok-4.3-l", "gpt-4o-2024-12-31")


@pytest.mark.parametrize("model_id,want", sorted(GOLDEN.items()))
def test_golden_catalog_id_to_meter_models(model_id, want):
    s, _ = source()
    s.prepare()
    got, why = s._match(model_id)
    assert got == want and why == ""


@pytest.mark.parametrize("model_id", NO_MATCH)
def test_golden_ids_that_must_not_match(model_id):
    s, _ = source()
    s.prepare()
    got, why = s._match(model_id)
    assert got == () and "no Azure meter" in why


def test_golden_prefix_and_alias_tables_are_each_load_bearing(monkeypatch):
    s, _ = source()
    s.prepare()
    for prefix_product in ("Azure Deepseek Models", "Azure Kimi", "Azure Grok Models", "Azure Mistral Models", "Azure OpenAI GPT5"):
        monkeypatch.setitem(az.PRODUCT_PREFIX, prefix_product, ())
        assert s._index.keys() != s._keys, prefix_product
        monkeypatch.undo()
    for alias in az.ALIASES:
        monkeypatch.setattr(az, "ALIASES", {k: v for k, v in az.ALIASES.items() if k != alias})
        assert s._index.keys() != s._keys, alias
        monkeypatch.undo()


# ---- `*` policy ---------------------------------------------------------------------------------------------

def test_star_next_to_global_without_a_regional_meter_is_uncovered_with_a_note_never_checked_with_global():
    r = run(source()[0], GPT51)  # global + datazone_us/eu + `*`; Azure has Global + Data Zone meters only
    assert not [c for c in r.checks if c.locator[1] == "region=*"]
    assert {"costs.region=*.input_cost_per_token", "costs.region=*.output_cost_per_token"} <= set(r.uncovered)
    assert any("no Regional meter for this model" in n for n in r.notes) and not r.fully_verified


def test_star_without_global_sibling_verified_as_global_carries_the_assumption_note():
    r = run(source()[0], O1)  # Regional (16.5) is 10% above Global (15): `*` = 15 is verified as Global, with a note
    for c in r.checks:
        assert c.status == "verified" and c.note.startswith("assumes `*` = Global") and "Regional is" in c.note
    r = run(source()[0], GPT4O)  # a `global` sibling: `*` is Regional, no assumption
    assert all("assumes" not in c.note for c in r.checks)
    r = run(source()[0], GPT54)  # no Regional meter exists at all: nothing to assume
    assert all("assumes" not in c.note for c in r.checks if c.locator[1] == "region=*")
