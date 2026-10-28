from __future__ import annotations

import json

from verify.sources.deepinfra import NO_END, DeepInfraSource

from .fx import FakeFetch, load, outage

URL = "https://api.deepinfra.com/models/list"


def source(mutate=None):
    data = load("deepinfra-models.json")
    if mutate:
        mutate({m["model_name"]: m for m in data})
    fetch = FakeFetch({URL: json.dumps(data).encode()})
    return DeepInfraSource(fetch), fetch


def check(s, name, **costs):
    return s.check(f"providers/deepinfra/{name}.yaml", {"model": name, "costs": [{"region": "*", **costs}]})


def test_covers_only_deepinfra():
    s, _ = source()
    assert s.covers("deepinfra") and not s.covers("openrouter")


def test_token_model_with_cache_read_and_both_cache_writes_is_fully_verified():
    s, _ = source()
    r = check(s, "moonshotai/Kimi-K2.7-Code", input_cost_per_token=6.8e-7, output_cost_per_token=3.4e-6,
              cache_read_input_token_cost=1.36e-7, cache_creation_input_token_cost=8.5e-7,
              cache_creation_input_token_cost_per_hour=1.36e-6)
    assert r.fully_verified and len(r.checks) == 5 and r.promo is None


def test_cents_are_converted_to_dollars():
    s, _ = source()
    r = check(s, "Qwen/Qwen3-235B-A22B", input_cost_per_token=1.8e-7, output_cost_per_token=5.4e-7)
    assert r.fully_verified
    r = check(s, "Qwen/Qwen3-235B-A22B", input_cost_per_token=1.8e-5, output_cost_per_token=5.4e-7)
    assert [c.locator[-1] for c in r.conflicts] == ["input_cost_per_token"]


def test_real_conflict_without_discount():
    s, _ = source()
    r = check(s, "stepfun-ai/Step-5-Preview", input_cost_per_token="1e-6", output_cost_per_token=2.7e-6,
              cache_read_input_token_cost="5e-8")
    (c,) = r.conflicts
    assert c.locator == ("costs", "region=*", "cache_read_input_token_cost")
    assert (c.file_value, c.source_value) == (5e-8, 1e-7)
    assert r.promo is None


def test_discount_file_holding_the_list_price_is_verified_but_promo_partial():
    s, _ = source()
    r = check(s, "XiaomiMiMo/MiMo-V2.6-Flash", input_cost_per_token=1.4e-7, output_cost_per_token=2.8e-7,
              cache_read_input_token_cost=2.8e-9)
    assert r.conflicts == [] and len(r.checks) == 3
    assert r.promo == NO_END and r.partial and not r.fully_verified
    assert any("0.1 discount" in n for n in r.notes)


def test_discount_file_holding_the_discounted_price_is_not_a_conflict():
    s, _ = source()
    # catalog values taken from the real zai-org/GLM-5.3 file: input, cache read and output are the
    # discounted prices, list is 9e-7 / 4e-6
    r = check(s, "zai-org/GLM-5.3", input_cost_per_token=5.63e-7, output_cost_per_token=2.5e-6,
              cache_read_input_token_cost=1.25e-7)
    assert r.conflicts == []
    assert sorted(r.uncovered) == ["costs.region=*.cache_read_input_token_cost", "costs.region=*.input_cost_per_token",
                                   "costs.region=*.output_cost_per_token"]
    assert r.promo == NO_END and r.partial and not r.fully_verified
    assert any("discounted price" in n and "list price" in n for n in r.notes)


def test_discount_end_date_is_reported_as_promo():
    def end(by):
        by["zai-org/GLM-5.3"]["pricing"]["discount_ends_at"] = "2026-12-01"
    s, _ = source(end)
    r = check(s, "zai-org/GLM-5.3", input_cost_per_token=9e-7, output_cost_per_token=4e-6,
              cache_read_input_token_cost=2e-7)
    assert r.promo == "2026-12-01" and r.conflicts == []


def test_price_matching_neither_list_nor_discount_is_still_a_conflict():
    s, _ = source()
    r = check(s, "zai-org/GLM-5.3", input_cost_per_token=7e-7, output_cost_per_token=4e-6,
              cache_read_input_token_cost=2e-7)
    (c,) = r.conflicts
    assert c.locator[-1] == "input_cost_per_token" and "discounted" in c.note


def test_discount_zero_or_missing_is_no_promo():
    def zero(by):
        by["XiaomiMiMo/MiMo-V2.6-Flash"]["pricing"]["discount"] = 0
    s, _ = source(zero)
    r = check(s, "XiaomiMiMo/MiMo-V2.6-Flash", input_cost_per_token=1.4e-7, output_cost_per_token=2.8e-7,
              cache_read_input_token_cost=2.8e-9)
    assert r.promo is None and r.fully_verified


def test_image_price_sums_input_and_output_when_the_file_has_both():
    s, _ = source()
    r = check(s, "black-forest-labs/FLUX-2-max", input_cost_per_image=0.03, output_cost_per_image=0.07)
    assert r.fully_verified
    (c,) = r.checks
    assert c.file_value == 0.1 and c.source_value == 0.1 and "sum of" in c.note
    r = check(s, "black-forest-labs/FLUX-2-max", input_cost_per_image=0.03, output_cost_per_image=0.05)
    assert [c.locator[-1] for c in r.conflicts] == ["output_cost_per_image"]


def test_image_split_the_api_cannot_describe_is_uncovered_not_a_conflict():
    s, _ = source()
    # FLUX-2-pro: the API's 0.015 equals the file's input_cost_per_image alone
    r = check(s, "black-forest-labs/FLUX-2-pro", input_cost_per_image=0.015, output_cost_per_image=0.03)
    assert r.conflicts == [] and r.checks == [] and r.partial
    assert sorted(r.uncovered) == ["costs.region=*.input_cost_per_image", "costs.region=*.output_cost_per_image"]


def test_single_image_field_prefers_output_then_input():
    s, _ = source()
    assert check(s, "black-forest-labs/FLUX-2-pro", input_cost_per_image=0.015).fully_verified
    r = check(s, "black-forest-labs/FLUX-2-pro", output_cost_per_image=0.015)
    assert r.fully_verified and r.checks[0].locator[-1] == "output_cost_per_image"
    r = check(s, "black-forest-labs/FLUX-2-pro", input_cost_per_image=0.01, output_cost_per_image=0.015)
    assert r.conflicts == [] and r.partial  # equals the output field alone: split unverifiable, not a conflict


def test_per_second_and_per_character_pricing():
    s, _ = source()
    assert check(s, "Qwen/Qwen3-ASR-1.7B", input_cost_per_second=7.5e-6).fully_verified
    assert check(s, "Qwen/Qwen3-TTS", input_cost_per_character=2e-5).fully_verified
    assert check(s, "PrunaAI/p-video", output_cost_per_second=0.02).fully_verified
    (c,) = check(s, "PrunaAI/p-video", output_cost_per_second=0.05).conflicts
    assert c.locator[-1] == "output_cost_per_second"


def test_unsupported_pricing_shape_is_a_note_and_partial():
    s, _ = source()
    r = check(s, "nvidia/Cosmos3-Nano", output_cost_per_second=0.035)
    assert r.partial and r.checks == [] and "frame_units" in r.notes[0]
    assert r.uncovered == ["costs.region=*.output_cost_per_second"]


def test_token_fields_in_a_non_token_model_are_uncovered():
    s, _ = source()
    r = check(s, "PrunaAI/p-video", output_cost_per_second=0.02, input_cost_per_token=1e-6)
    assert r.partial and r.uncovered == ["costs.region=*.input_cost_per_token"]


def test_embedding_with_string_numbers():
    s, _ = source()
    assert check(s, "BAAI/bge-base-en-v1.5", input_cost_per_token="5e-9").fully_verified


def test_tiers_and_batches_are_uncovered():
    s, _ = source()
    r = check(s, "Qwen/Qwen3-235B-A22B", input_cost_per_token=1.8e-7, output_cost_per_token=5.4e-7,
              tiered_pricing={"input": []}, flex_pricing={"input_cost_per_token": 1e-7},
              input_cost_per_token_batches=9e-8)
    assert sorted(u.split(".")[-1] for u in r.uncovered) == ["flex_pricing", "input_cost_per_token_batches", "tiered_pricing"]
    assert r.partial and r.conflicts == []


def test_unlisted_model_is_partial_with_note():
    s, _ = source()
    r = check(s, "nobody/ghost", input_cost_per_token=1e-7)
    assert r.partial and r.checks == [] and "not in DeepInfra's model list" in r.notes[0]
    assert r.uncovered == ["costs.region=*.input_cost_per_token"]


def test_outage_is_partial_not_a_crash():
    s = DeepInfraSource(FakeFetch({URL: outage()}))
    r = check(s, "Qwen/Qwen3-235B-A22B", input_cost_per_token=1.8e-7)
    assert r.partial and "unreachable" in r.notes[0] and r.checks == []


def test_one_fetch_per_run():
    s, fetch = source()
    for _ in range(4):
        check(s, "Qwen/Qwen3-235B-A22B", input_cost_per_token=1.8e-7, output_cost_per_token=5.4e-7)
    assert fetch.calls == [URL]


def test_non_star_region_entries_are_uncovered():
    s, _ = source()
    r = s.check("providers/deepinfra/x.yaml", {"model": "Qwen/Qwen3-235B-A22B", "costs": [
        {"region": "*", "input_cost_per_token": 1.8e-7, "output_cost_per_token": 5.4e-7},
        {"region": "eu", "input_cost_per_token": 2e-7}]})
    assert r.uncovered == ["costs.region=eu.input_cost_per_token"] and r.partial
