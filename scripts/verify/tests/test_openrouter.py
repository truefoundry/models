from __future__ import annotations

import json

from verify.sources.openrouter import OpenRouterSource, source_id
from verify.sources._common import compare
from verify.types import PRICE_TOLERANCE

from .fx import FakeFetch, checks_by_field, outage, raw

URL = "https://openrouter.ai/api/v1/models"


def source(listing: bytes | None = None):
    fetch = FakeFetch({URL: listing if listing is not None else raw("openrouter-models.json")})
    return OpenRouterSource(fetch), fetch


def doc(**costs):
    entry = {"region": "*", **costs}
    return {"model": "x", "costs": [entry], "limits": {"context_window": 262144}}


STEP = "providers/openrouter/stepfun/step-3.5-flash.yaml"


def test_covers_only_openrouter():
    s, _ = source()
    assert s.covers("openrouter") and not s.covers("deepinfra") and not s.covers("aws-bedrock")


def test_fully_verified_price_and_context():
    s, _ = source()
    r = s.check(STEP, doc(input_cost_per_token=1e-7, output_cost_per_token=3e-7))
    assert r.fully_verified
    assert {c.locator for c in r.checks} == {
        ("costs", "region=*", "input_cost_per_token"), ("costs", "region=*", "output_cost_per_token"),
        ("limits", "context_window")}
    assert r.uncovered == [] and r.promo is None


def test_catalog_string_numbers_are_numbers():
    s, _ = source()
    r = s.check(STEP, doc(input_cost_per_token="1e-7", output_cost_per_token="3e-7"))
    assert r.fully_verified


def test_price_conflict_names_both_values_and_locator():
    s, _ = source()
    r = s.check(STEP, doc(input_cost_per_token=1e-7, output_cost_per_token=6e-7))
    (c,) = r.conflicts
    assert c.locator == ("costs", "region=*", "output_cost_per_token")
    assert (c.file_value, c.source_value) == (6e-7, 3e-7)
    assert not r.fully_verified


def test_price_tolerance_is_half_a_percent():
    assert PRICE_TOLERANCE == 0.005
    s, _ = source()
    inside = s.check(STEP, doc(input_cost_per_token=1e-7 * 1.004, output_cost_per_token=3e-7))
    outside = s.check(STEP, doc(input_cost_per_token=1e-7 * 1.006, output_cost_per_token=3e-7))
    assert inside.fully_verified
    assert [c.locator[-1] for c in outside.conflicts] == ["input_cost_per_token"]


def test_context_window_tolerance_is_two_and_a_half_percent():
    s, _ = source()
    base = dict(input_cost_per_token=1e-7, output_cost_per_token=3e-7)
    ok = {**doc(**base), "limits": {"context_window": round(262144 * 1.024)}}
    bad = {**doc(**base), "limits": {"context_window": round(262144 * 1.03)}}
    assert s.check(STEP, ok).fully_verified
    (c,) = s.check(STEP, bad).conflicts
    assert c.locator == ("limits", "context_window")


def test_zero_official_price_with_field_missing_is_not_a_conflict():
    listing = json.dumps({"data": [{"id": "a/b:free", "context_length": 1000,
                                    "pricing": {"prompt": "0", "completion": "0"}}]}).encode()
    s, _ = source(listing)
    r = s.check("providers/openrouter/a/b:free.yaml", {"model": "a/b:free", "costs": [{"region": "*"}]})
    assert r.conflicts == [] and r.checks == []


def test_missing_nonzero_price_in_file_is_a_conflict_with_none():
    s, _ = source()
    r = s.check(STEP, doc(input_cost_per_token=1e-7))
    (c,) = r.conflicts
    assert c.locator[-1] == "output_cost_per_token" and c.file_value is None and c.source_value == 3e-7


def test_unlisted_model_is_partial_with_note_and_everything_uncovered():
    s, _ = source()
    d = doc(input_cost_per_token=3e-6, output_cost_per_token=1.5e-5, cache_read_input_token_cost=3e-7)
    r = s.check("providers/openrouter/anthropic/claude-3.7-sonnet:beta.yaml", d)
    assert r.partial and r.checks == [] and not r.fully_verified
    assert "not in OpenRouter's /models listing" in r.notes[0]
    assert set(r.uncovered) == {f"costs.region=*.{k}" for k in
                                ("input_cost_per_token", "output_cost_per_token", "cache_read_input_token_cost")}


def test_unlisted_variant_is_not_priced_from_its_base_model():
    # the path id (with `:beta`) is the only id tried; `model:` naming a listed model must not rescue it
    s, _ = source()
    d = {**doc(input_cost_per_token=3e-6, output_cost_per_token=1.5e-5), "model": "anthropic/claude-sonnet-4.5"}
    r = s.check("providers/openrouter/anthropic/claude-sonnet-4.5:beta.yaml", d)
    assert r.checks == [] and r.partial


def test_id_from_path_then_sources_then_model():
    assert source_id("providers/openrouter/stepfun/step-3.5-flash.yaml", {"model": "other/x"}) == "stepfun/step-3.5-flash"
    assert source_id("providers/openrouter/step-3.5-flash.yaml",
                     {"model": "bare", "sources": ["https://openrouter.ai/stepfun/step-3.5-flash/api"]}) == "stepfun/step-3.5-flash"
    assert source_id("providers/openrouter/step.yaml", {"model": "stepfun/step-3.5-flash"}) == "stepfun/step-3.5-flash"
    assert source_id("providers/openrouter/step.yaml", {"sources": ["https://openrouter.ai/step/api"]}) is None


def test_flat_file_resolves_through_its_sources_url():
    s, _ = source()
    d = {**doc(input_cost_per_token=1e-7, output_cost_per_token=3e-7), "model": "bare",
         "sources": ["https://openrouter.ai/stepfun/step-3.5-flash/api"]}
    assert s.check("providers/openrouter/step-3.5-flash.yaml", d).fully_verified


def test_canonical_slug_is_accepted():
    s, _ = source()
    d = doc(input_cost_per_token=3e-6, output_cost_per_token=1.5e-5, cache_read_input_token_cost=3e-7,
            cache_creation_input_token_cost=3.75e-6, cache_creation_input_token_cost_per_hour=6e-6)
    d["limits"] = {"context_window": 1000000}
    r = s.check("providers/openrouter/anthropic/claude-4.5-sonnet-20250929.yaml", d)
    assert r.checks and r.conflicts == []


def test_cache_write_5m_and_1h_are_compared_when_the_api_lists_them():
    s, _ = source()
    d = doc(input_cost_per_token=3e-6, output_cost_per_token=1.5e-5, cache_read_input_token_cost=3e-7,
            cache_creation_input_token_cost=3.75e-6, cache_creation_input_token_cost_per_hour=9e-6)
    d["limits"] = {"context_window": 1000000}
    r = s.check("providers/openrouter/anthropic/claude-sonnet-4.5.yaml", d)
    by = checks_by_field(r)
    assert by["cache_creation_input_token_cost"].status == "verified"
    assert by["cache_creation_input_token_cost_per_hour"].status == "conflict"


def test_tier_overrides_are_noted_and_make_the_file_partial():
    s, _ = source()
    d = doc(input_cost_per_token=3e-6, output_cost_per_token=1.5e-5, cache_read_input_token_cost=3e-7,
            cache_creation_input_token_cost=3.75e-6, cache_creation_input_token_cost_per_hour=6e-6)
    d["limits"] = {"context_window": 1000000}
    r = s.check("providers/openrouter/anthropic/claude-sonnet-4.5.yaml", d)
    assert r.conflicts == [] and r.partial and not r.fully_verified
    assert any("tier overrides" in n and "200000" in n and "no tiered_pricing" in n for n in r.notes)
    d["costs"][0]["tiered_pricing"] = {"input": [{"from": 200000, "cost_per_token": 6e-6}]}
    r = s.check("providers/openrouter/anthropic/claude-sonnet-4.5.yaml", d)
    assert r.uncovered == ["costs.region=*.tiered_pricing"]


def test_fields_the_api_does_not_cover_are_uncovered():
    s, _ = source()
    r = s.check(STEP, doc(input_cost_per_token=1e-7, output_cost_per_token=3e-7,
                          input_cost_per_token_batches=5e-8, input_cost_per_video_token=1e-7))
    assert sorted(r.uncovered) == ["costs.region=*.input_cost_per_token_batches", "costs.region=*.input_cost_per_video_token"]
    assert r.partial and not r.fully_verified and r.conflicts == []


def test_web_search_audio_and_image_map_to_the_fields_the_file_has():
    s, _ = source()
    r = s.check("providers/openrouter/perplexity/sonar-pro-search.yaml",
                {**doc(input_cost_per_token=3e-6, output_cost_per_token=1.5e-5, input_cost_per_request=0.018),
                 "limits": {"context_window": 200000}})
    assert r.fully_verified
    r = s.check("providers/openrouter/openai/gpt-audio.yaml",
                {**doc(input_cost_per_token=2.5e-6, output_cost_per_token=1e-5, input_cost_per_audio_token=3.2e-5,
                       output_cost_per_audio_token=6.4e-5), "limits": {"context_window": 128000}})
    assert r.fully_verified
    r = s.check("providers/openrouter/openai/gpt-audio.yaml",
                {**doc(input_cost_per_token=2.5e-6, output_cost_per_token=1e-5, input_cost_per_audio_token=1e-5),
                 "limits": {"context_window": 128000}})
    assert [c.locator[-1] for c in r.conflicts] == ["input_cost_per_audio_token"]


def test_openrouter_quote_wins_over_the_catalog_even_when_it_looks_odd():
    s, _ = source()
    d = doc(input_cost_per_token=1.4e-6, output_cost_per_token=7e-6, cache_read_input_token_cost=9.6e-9)
    d["limits"] = {"context_window": 1048576}
    r = s.check("providers/openrouter/z-ai/glm-5.2.yaml", d)
    assert [c.locator[-1] for c in r.conflicts] == ["input_cost_per_token"]


def test_outage_is_partial_with_a_note_not_a_crash():
    fetch = FakeFetch({URL: outage()})
    s = OpenRouterSource(fetch)
    r = s.check(STEP, doc(input_cost_per_token=1e-7))
    assert r.partial and r.checks == [] and "unreachable" in r.notes[0]
    assert r.uncovered == ["costs.region=*.input_cost_per_token"]


def test_prepare_may_raise_and_check_still_never_does():
    s = OpenRouterSource(FakeFetch({URL: outage()}))
    try:
        s.prepare()
    except Exception:
        pass
    else:
        raise AssertionError("prepare() should surface the outage")
    assert s.check(STEP, doc()).partial


def test_one_fetch_per_run():
    s, fetch = source()
    s.prepare()
    for _ in range(5):
        s.check(STEP, doc(input_cost_per_token=1e-7, output_cost_per_token=3e-7))
    assert fetch.calls == [URL]


def test_compare_helper_zero_and_missing():
    assert compare(("a",), None, 0.0) is None
    assert compare(("a",), 0, 0.0).status == "verified"
    assert compare(("a",), None, 1e-6).status == "conflict"
