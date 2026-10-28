from __future__ import annotations

import json

from verify.sources.deepinfra import DeepInfraSource

from .fx import FakeFetch, load, outage

URL = "https://api.deepinfra.com/models/list"


def source(mutate=None, **kw):
    data = load("deepinfra-models.json")
    if mutate:
        mutate({m["model_name"]: m for m in data})
    fetch = FakeFetch({URL: json.dumps(data).encode()})
    return DeepInfraSource(fetch, **kw), fetch


def check(s, name, **costs):
    return s.check(f"providers/deepinfra/{name}.yaml", {"model": name, "costs": [{"region": "*", **costs}]})


GLM = "zai-org/GLM-5.3"
GLM_LIST = dict(input_cost_per_token=9e-7, output_cost_per_token=4e-6, cache_read_input_token_cost=2e-7)


def test_covers_only_deepinfra():
    s, _ = source()
    assert s.covers("deepinfra") and not s.covers("openrouter")


def test_token_model_with_cache_read_and_both_cache_writes_is_fully_verified():
    s, _ = source()
    r = check(s, "moonshotai/Kimi-K2.7-Code", input_cost_per_token=6.8e-7, output_cost_per_token=3.4e-6,
              cache_read_input_token_cost=1.36e-7, cache_creation_input_token_cost=8.5e-7,
              cache_creation_input_token_cost_per_hour=1.36e-6)
    assert r.fully_verified and len(r.checks) == 5 and r.promo is None and not r.promo_active


def test_cents_are_converted_to_dollars():
    s, _ = source()
    assert check(s, "Qwen/Qwen3-235B-A22B", input_cost_per_token=1.8e-7, output_cost_per_token=5.4e-7).fully_verified
    r = check(s, "Qwen/Qwen3-235B-A22B", input_cost_per_token=1.8e-5, output_cost_per_token=5.4e-7)
    assert [c.locator[-1] for c in r.conflicts] == ["input_cost_per_token"]


def test_real_conflict_without_discount():
    s, _ = source()
    r = check(s, "stepfun-ai/Step-5-Preview", input_cost_per_token="1e-6", output_cost_per_token=2.7e-6,
              cache_read_input_token_cost="5e-8")
    (c,) = r.conflicts
    assert c.locator == ("costs", "region=*", "cache_read_input_token_cost")
    assert (c.file_value, c.source_value) == (5e-8, 1e-7) and c.writable
    assert r.promo is None and not r.promo_active


# ---- discounts ----------------------------------------------------------------------------

def test_discount_file_holding_the_list_price_is_verified_but_promo_partial():
    s, _ = source()
    r = check(s, "XiaomiMiMo/MiMo-V2.6-Flash", input_cost_per_token=1.4e-7, output_cost_per_token=2.8e-7,
              cache_read_input_token_cost=2.8e-9)
    assert r.conflicts == [] and len(r.checks) == 3
    assert r.promo is None and r.promo_active and r.partial and not r.fully_verified
    assert any("0.1 discount" in n for n in r.notes)


def test_discount_file_holding_the_discounted_price_is_not_a_conflict():
    s, _ = source()
    # values of the real zai-org/GLM-5.3 file: input, cache read and output are the discounted prices
    r = check(s, GLM, input_cost_per_token=5.63e-7, output_cost_per_token=2.5e-6, cache_read_input_token_cost=1.25e-7)
    assert r.conflicts == []
    assert sorted(r.uncovered) == ["costs.region=*.cache_read_input_token_cost", "costs.region=*.input_cost_per_token",
                                   "costs.region=*.output_cost_per_token"]
    assert r.promo is None and r.promo_active and r.partial and not r.fully_verified
    assert any("the discounted price (list 9e-07" in n for n in r.notes)


def test_a_real_end_date_is_promo_and_the_bare_fact_is_promo_active():
    def end(by):
        by[GLM]["pricing"]["discount_ends_at"] = "2026-12-01T00:00:00+00:00"
    s, _ = source(end)
    r = check(s, GLM, **GLM_LIST)
    assert r.promo == "2026-12-01" and r.promo_active and r.conflicts == []

    def ts(by):
        by[GLM]["pricing"]["discount_ends_at"] = 1793254601
    s, _ = source(ts)
    assert check(s, GLM, **GLM_LIST).promo == "2026-10-29"

    def junk(by):
        by[GLM]["pricing"]["discount_ends_at"] = "soon"
    s, _ = source(junk)
    r = check(s, GLM, **GLM_LIST)
    assert r.promo is None and r.promo_active


def test_discounted_band_is_two_and_a_half_percent_around_the_discounted_price():
    s, _ = source()
    base = dict(output_cost_per_token=4e-6, cache_read_input_token_cost=2e-7)
    # discounted input is 5.625e-7: 2.5% either side is promo, just outside is a conflict
    for inside in (5.625e-7 * 1.024, 5.625e-7 * 0.976):
        r = check(s, GLM, input_cost_per_token=inside, **base)
        assert r.conflicts == [] and r.uncovered == ["costs.region=*.input_cost_per_token"]
    for outside in (5.625e-7 * 1.03, 5.625e-7 * 0.97):
        r = check(s, GLM, input_cost_per_token=outside, **base)
        (c,) = r.conflicts
        assert c.locator[-1] == "input_cost_per_token" and "discounted price" in c.note


def test_price_between_discounted_and_list_is_a_conflict_unless_it_is_the_list():
    s, _ = source()
    base = dict(output_cost_per_token=4e-6, cache_read_input_token_cost=2e-7)
    assert [c.locator[-1] for c in check(s, GLM, input_cost_per_token=7e-7, **base).conflicts] == ["input_cost_per_token"]
    assert check(s, GLM, input_cost_per_token=9e-7, **base).conflicts == []
    assert [c.locator[-1] for c in check(s, GLM, input_cost_per_token=1.2e-6, **base).conflicts] == ["input_cost_per_token"]


def test_discount_zero_or_missing_is_no_promo():
    def zero(by):
        by["XiaomiMiMo/MiMo-V2.6-Flash"]["pricing"]["discount"] = 0
    s, _ = source(zero)
    r = check(s, "XiaomiMiMo/MiMo-V2.6-Flash", input_cost_per_token=1.4e-7, output_cost_per_token=2.8e-7,
              cache_read_input_token_cost=2.8e-9)
    assert r.promo is None and not r.promo_active and r.fully_verified


# ---- images: the split is never a writable check -------------------------------------------

def test_image_with_both_input_and_output_price_cannot_be_checked_and_emits_no_check():
    s, _ = source()
    r = check(s, "black-forest-labs/FLUX-2-max", input_cost_per_image=0.03, output_cost_per_image=0.07)
    assert r.checks == [] and r.conflicts == [] and r.partial and not r.fully_verified
    assert sorted(r.uncovered) == ["costs.region=*.input_cost_per_image", "costs.region=*.output_cost_per_image"]
    assert any("equals the sum" in n for n in r.notes)
    r = check(s, "black-forest-labs/FLUX-2-max", input_cost_per_image=0.03, output_cost_per_image=0.05)
    assert r.checks == [] and any("does not equal the sum" in n for n in r.notes)


def test_flux_2_pro_split_is_uncovered_too():
    s, _ = source()
    r = check(s, "black-forest-labs/FLUX-2-pro", input_cost_per_image=0.015, output_cost_per_image=0.03)
    assert r.conflicts == [] and r.checks == [] and r.partial
    assert sorted(r.uncovered) == ["costs.region=*.input_cost_per_image", "costs.region=*.output_cost_per_image"]


def test_single_image_field_prefers_output_then_input():
    s, _ = source()
    assert check(s, "black-forest-labs/FLUX-2-pro", input_cost_per_image=0.015).fully_verified
    r = check(s, "black-forest-labs/FLUX-2-pro", output_cost_per_image=0.015)
    assert r.fully_verified and r.checks[0].locator[-1] == "output_cost_per_image"


# ---- the API's one price lands on the field the file carries ---------------------------------

def test_input_tokens_generators_map_to_the_field_the_file_has():
    s, _ = source()
    assert check(s, "google/nano-banana-2", output_cost_per_image_token=6e-5).fully_verified
    assert check(s, "google/nano-banana-pro", output_cost_per_image_token=1.2e-4).fully_verified
    assert check(s, "google/nano-banana-2-lite", output_cost_per_token=3e-5).fully_verified
    assert check(s, "ByteDance/Seedance-1.5-Pro", output_cost_per_video_token=1.2e-6).fully_verified
    r = check(s, "google/nano-banana-2", output_cost_per_image_token=1e-5)
    assert [c.locator[-1] for c in r.conflicts] == ["output_cost_per_image_token"]


def test_input_tokens_with_an_input_price_keeps_the_input_field():
    s, _ = source()
    r = check(s, "ByteDance/Seedance-2.0", input_cost_per_token=4.7e-6, output_cost_per_token=4.7e-6)
    assert [c.locator[-1] for c in r.checks] == ["input_cost_per_token"]
    assert r.uncovered == ["costs.region=*.output_cost_per_token"] and r.partial and r.conflicts == []


def test_per_unit_image_price_maps_to_a_per_request_field_when_that_is_what_the_file_has():
    s, _ = source()
    assert check(s, "Pixverse/Pixverse-T2V", input_cost_per_request=0.2).fully_verified
    assert check(s, "Pixverse/Pixverse-T2V-HD", input_cost_per_request=0.4).fully_verified
    r = check(s, "Pixverse/Pixverse-T2V", input_cost_per_request=0.5)
    assert [c.locator[-1] for c in r.conflicts] == ["input_cost_per_request"]
    r = check(s, "Pixverse/Pixverse-T2V")  # nothing to put the price on
    assert r.checks == [] and r.partial


def test_per_second_and_per_character_pricing():
    s, _ = source()
    assert check(s, "Qwen/Qwen3-ASR-1.7B", input_cost_per_second=7.5e-6).fully_verified
    assert check(s, "Qwen/Qwen3-TTS", input_cost_per_character=2e-5).fully_verified
    assert check(s, "PrunaAI/p-video", output_cost_per_second=0.02).fully_verified
    assert check(s, "Pixverse/Pixverse-6-T2V", output_cost_per_second=0.045).fully_verified
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


# ---- absent fields are never conflicts -----------------------------------------------------

def test_field_absent_in_the_file_is_uncovered_missing_in_file_not_a_conflict():
    s, _ = source()
    r = check(s, "moonshotai/Kimi-K2.7-Code", input_cost_per_token=6.8e-7, output_cost_per_token=3.4e-6)
    assert r.conflicts == [] and r.partial and not r.fully_verified
    assert sorted(r.uncovered) == [
        "costs.region=*.cache_creation_input_token_cost", "costs.region=*.cache_creation_input_token_cost_per_hour",
        "costs.region=*.cache_read_input_token_cost"]
    assert any(n.startswith("missing in file") for n in r.notes)


def test_a_cached_rate_equal_to_the_input_price_is_derived_and_never_flagged():
    s, _ = source()
    r = check(s, "nace-ai/drex-max", input_cost_per_token=1.2e-7)
    assert r.uncovered == [] and not any(n.startswith("missing in file") for n in r.notes)


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


def test_outage_is_partial_not_a_crash_and_is_tried_once():
    fetch = FakeFetch({URL: outage()})
    s = DeepInfraSource(fetch)
    for _ in range(4):
        r = check(s, "Qwen/Qwen3-235B-A22B", input_cost_per_token=1.8e-7)
        assert r.partial and "unreachable" in r.notes[0] and r.checks == []
    assert fetch.calls == [URL]


def test_run_deadline_stops_a_hung_source():
    clock = [0.0]

    def slow(url):
        clock[0] += 100.0
        raise TimeoutError("hung")

    s = DeepInfraSource(slow, deadline_s=60.0, clock=lambda: clock[0])
    r = check(s, "Qwen/Qwen3-235B-A22B", input_cost_per_token=1.8e-7)
    assert r.partial and "unreachable" in r.notes[0]


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


def test_junk_never_raises():
    s, _ = source()
    r = s.check("providers/deepinfra/x.yaml", {"model": ["not", "a", "str"], "costs": [{"region": "*", "input_cost_per_token": [1]}]})
    assert r.partial
    s._compare_entry = lambda *a, **k: (_ for _ in ()).throw(TypeError("boom"))
    r = check(s, "Qwen/Qwen3-235B-A22B", input_cost_per_token=1.8e-7)
    assert r.partial and "adapter error" in r.notes[0]


def test_a_hostile_model_id_is_never_looked_up():
    from verify.tests.test_openrouter import HOSTILE_IDS
    s, fetch = source()
    for bad in HOSTILE_IDS + ["Qwen/Qwen3 235B"]:
        r = s.check("providers/deepinfra/x.yaml", {"model": bad, "costs": [{"region": "*", "input_cost_per_token": 1e-7}]})
        assert r.partial and r.checks == [], bad
        assert r.uncovered == ["costs.region=*.input_cost_per_token"], bad
        assert any("not allowed in a DeepInfra id" in n for n in r.notes), bad
    assert fetch.calls == [URL]
