from __future__ import annotations

import json

from verify.sources.openrouter import CHEAPEST, OpenRouterSource, source_id
from verify.types import PRICE_TOLERANCE

from .fx import FakeFetch, checks_by_field, outage, raw

URL = "https://openrouter.ai/api/v1/models"
STEP = "providers/openrouter/stepfun/step-3.5-flash.yaml"


def source(listing: bytes | None = None, **kw):
    fetch = FakeFetch({URL: listing if listing is not None else raw("openrouter-models.json")})
    return OpenRouterSource(fetch, **kw), fetch


def doc(limits=True, **costs):
    d = {"model": "x", "costs": [{"region": "*", **costs}]}
    if limits:
        d["limits"] = {"context_window": 262144, "max_output_tokens": 65536}
    return d


STEP_OK = dict(input_cost_per_token=1e-7, output_cost_per_token=3e-7)


def test_covers_only_openrouter():
    s, _ = source()
    assert s.covers("openrouter") and not s.covers("deepinfra") and not s.covers("aws-bedrock")


def test_fully_verified_price_context_and_max_output():
    s, _ = source()
    r = s.check(STEP, doc(**STEP_OK))
    assert r.fully_verified
    assert {c.locator for c in r.checks} == {
        ("costs", "region=*", "input_cost_per_token"), ("costs", "region=*", "output_cost_per_token"),
        ("limits", "context_window"), ("limits", "max_output_tokens")}
    assert r.uncovered == [] and r.promo is None and not r.promo_active


def test_every_check_says_the_listing_quotes_the_cheapest_endpoint():
    s, _ = source()
    r = s.check(STEP, doc(input_cost_per_token=5e-8, output_cost_per_token=3e-7))  # one verified, one below
    assert r.checks and all(CHEAPEST in c.note for c in r.checks)
    assert any(CHEAPEST in n for n in r.notes)


def test_catalog_string_numbers_are_numbers():
    s, _ = source()
    assert s.check(STEP, doc(input_cost_per_token="1e-7", output_cost_per_token="3e-7")).fully_verified


def test_file_below_every_endpoint_is_a_conflict():
    s, _ = source()
    r = s.check(STEP, doc(input_cost_per_token=1e-7, output_cost_per_token=1e-7))
    (c,) = r.conflicts
    assert c.locator == ("costs", "region=*", "output_cost_per_token")
    assert (c.file_value, c.source_value) == (1e-7, 3e-7)
    assert "below every endpoint" in c.note and c.writable
    assert not r.fully_verified


def test_file_above_the_cheapest_endpoint_is_uncovered_not_a_conflict():
    s, _ = source()
    r = s.check(STEP, doc(input_cost_per_token=1e-7, output_cost_per_token=6e-7))
    assert r.conflicts == [] and r.partial and not r.fully_verified
    assert r.uncovered == ["costs.region=*.output_cost_per_token"]
    assert any("above cheapest endpoint: may be first-party price" in n and "output_cost_per_token" in n for n in r.notes)


def test_price_tolerance_is_half_a_percent_on_both_sides():
    assert PRICE_TOLERANCE == 0.005
    s, _ = source()
    for ok in (1e-7 * 1.004, 1e-7 * 0.996):
        assert s.check(STEP, doc(input_cost_per_token=ok, output_cost_per_token=3e-7)).fully_verified
    assert [c.locator[-1] for c in s.check(STEP, doc(input_cost_per_token=1e-7 * 0.994, output_cost_per_token=3e-7)).conflicts] \
        == ["input_cost_per_token"]
    above = s.check(STEP, doc(input_cost_per_token=1e-7 * 1.006, output_cost_per_token=3e-7))
    assert above.conflicts == [] and above.uncovered == ["costs.region=*.input_cost_per_token"]


def test_limit_differences_are_uncovered_notes_never_conflicts():
    s, _ = source()
    d = doc(**STEP_OK)
    d["limits"] = {"context_window": 32768, "max_output_tokens": 1000}
    r = s.check(STEP, d)
    assert r.conflicts == [] and r.partial
    assert sorted(r.uncovered) == ["limits.context_window", "limits.max_output_tokens"]
    assert any("context_window differs from /models" in n for n in r.notes)


def test_limit_tolerance_is_two_and_a_half_percent():
    s, _ = source()
    d = doc(**STEP_OK)
    d["limits"] = {"context_window": round(262144 * 1.024)}
    assert s.check(STEP, d).fully_verified
    d["limits"] = {"context_window": round(262144 * 1.03)}
    assert s.check(STEP, d).uncovered == ["limits.context_window"]


def test_zero_official_price_with_field_missing_is_nothing_at_all():
    listing = json.dumps({"data": [{"id": "a/b:free", "context_length": 1000,
                                    "pricing": {"prompt": "0", "completion": "0"}}]}).encode()
    s, _ = source(listing)
    r = s.check("providers/openrouter/a/b:free.yaml", {"model": "a/b:free", "costs": [{"region": "*"}]})
    assert r.conflicts == [] and r.checks == [] and r.uncovered == []


def test_missing_nonzero_price_in_file_is_uncovered_not_a_conflict():
    s, _ = source()
    r = s.check(STEP, doc(input_cost_per_token=1e-7))
    assert r.conflicts == [] and r.uncovered == ["costs.region=*.output_cost_per_token"] and r.partial
    assert any(n.startswith("missing in file") and "output_cost_per_token" in n for n in r.notes)


def test_one_hour_cache_write_absent_is_the_openrouter_convention_not_a_flag():
    s, _ = source()
    d = doc(input_cost_per_token=3e-6, output_cost_per_token=1.5e-5, cache_read_input_token_cost=3e-7,
            cache_creation_input_token_cost=3.75e-6)
    d["limits"] = {"context_window": 1000000, "max_output_tokens": 64000}
    r = s.check("providers/openrouter/anthropic/claude-sonnet-4.5.yaml", d)
    assert not any("per_hour" in u for u in r.uncovered)
    assert not any("per_hour" in n for n in r.notes if n.startswith("missing in file"))


def test_unlisted_model_is_partial_with_note_and_everything_uncovered():
    s, _ = source()
    d = doc(input_cost_per_token=3e-6, output_cost_per_token=1.5e-5, cache_read_input_token_cost=3e-7)
    r = s.check("providers/openrouter/anthropic/claude-3.7-sonnet:beta.yaml", d)
    assert r.partial and r.checks == [] and not r.fully_verified
    assert "not in OpenRouter's /models listing" in r.notes[0]
    assert set(r.uncovered) == {f"costs.region=*.{k}" for k in
                                ("input_cost_per_token", "output_cost_per_token", "cache_read_input_token_cost")}


def test_unlisted_variant_is_not_priced_from_its_base_model():
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
    assert source_id("providers/openrouter/step.yaml", {"sources": 5, "model": "m"}) == "m"


def test_flat_file_resolves_through_its_sources_url():
    s, _ = source()
    d = {**doc(**STEP_OK), "model": "bare", "sources": ["https://openrouter.ai/stepfun/step-3.5-flash/api"]}
    assert s.check("providers/openrouter/step-3.5-flash.yaml", d).fully_verified


def sonnet_doc(**over):
    costs = dict(input_cost_per_token=3e-6, output_cost_per_token=1.5e-5, cache_read_input_token_cost=3e-7,
                 cache_creation_input_token_cost=3.75e-6, **over)
    d = doc(**costs)
    d["limits"] = {"context_window": 1000000, "max_output_tokens": 64000}
    return d


SONNET = "providers/openrouter/anthropic/claude-sonnet-4.5.yaml"


def test_canonical_slug_is_accepted():
    s, _ = source()
    r = s.check("providers/openrouter/anthropic/claude-4.5-sonnet-20250929.yaml", sonnet_doc())
    assert r.checks and r.conflicts == []


def test_cache_write_5m_and_1h_are_compared_when_the_file_has_them():
    s, _ = source()
    r = s.check(SONNET, sonnet_doc(cache_creation_input_token_cost_per_hour=3e-6))
    by = checks_by_field(r)
    assert by["cache_creation_input_token_cost"].status == "verified"
    assert by["cache_creation_input_token_cost_per_hour"].status == "conflict"  # below the 6e-6 listing


def test_tier_overrides_are_noted_and_make_the_file_partial():
    s, _ = source()
    r = s.check(SONNET, sonnet_doc())
    assert r.conflicts == [] and r.partial and not r.fully_verified
    assert any("tier overrides" in n and "200000" in n and "no tiered_pricing" in n for n in r.notes)
    d = sonnet_doc()
    d["costs"][0]["tiered_pricing"] = {"input": [{"from": 200000, "cost_per_token": 6e-6}]}
    assert s.check(SONNET, d).uncovered == ["costs.region=*.tiered_pricing"]


def test_fields_the_api_does_not_cover_are_uncovered():
    s, _ = source()
    r = s.check(STEP, doc(input_cost_per_token_batches=5e-8, input_cost_per_video_token=1e-7, **STEP_OK))
    assert sorted(r.uncovered) == ["costs.region=*.input_cost_per_token_batches", "costs.region=*.input_cost_per_video_token"]
    assert r.partial and not r.fully_verified and r.conflicts == []


def test_web_search_audio_map_to_the_fields_the_file_has():
    s, _ = source()
    r = s.check("providers/openrouter/perplexity/sonar-pro-search.yaml",
                {**doc(input_cost_per_token=3e-6, output_cost_per_token=1.5e-5, input_cost_per_request=0.018),
                 "limits": {"context_window": 200000, "max_output_tokens": 8000}})
    assert r.fully_verified
    audio = {"context_window": 128000, "max_output_tokens": 16384}
    r = s.check("providers/openrouter/openai/gpt-audio.yaml",
                {**doc(input_cost_per_token=2.5e-6, output_cost_per_token=1e-5, input_cost_per_audio_token=3.2e-5,
                       output_cost_per_audio_token=6.4e-5), "limits": audio})
    assert r.fully_verified
    r = s.check("providers/openrouter/openai/gpt-audio.yaml",
                {**doc(input_cost_per_token=2.5e-6, output_cost_per_token=1e-5, input_cost_per_audio_token=1e-5),
                 "limits": audio})
    assert [c.locator[-1] for c in r.conflicts] == ["input_cost_per_audio_token"]


def test_image_price_unit_is_not_verified_so_it_is_never_compared():
    s, _ = source()
    d = {**doc(input_cost_per_token=7.5e-7, output_cost_per_token=3.75e-6, input_cost_per_image=7.5e-7),
         "limits": {"context_window": 1048576, "max_output_tokens": 65536}}
    r = s.check("providers/openrouter/google/gemini-3.6-flash.yaml", d)
    assert "costs.region=*.input_cost_per_image" in r.uncovered
    assert all(c.locator[-1] != "input_cost_per_image" for c in r.checks)
    assert any("`image` price not compared" in n for n in r.notes)


GLM = "providers/openrouter/z-ai/glm-5.2.yaml"


def test_first_party_price_above_a_cheap_listing_is_not_a_conflict():
    # the live listing for glm-5.2 is one cheap upstream's 1.06e-8; the catalog holds the first-party 1.4e-6
    s, _ = source()
    d = doc(input_cost_per_token=1.4e-6, output_cost_per_token=7e-6, cache_read_input_token_cost=9.6e-9)
    d["limits"] = {"context_window": 1048576}
    r = s.check(GLM, d)
    assert r.conflicts == [] and r.uncovered == ["costs.region=*.input_cost_per_token"]


def test_a_price_no_endpoint_offers_is_a_conflict():
    s, _ = source()
    d = doc(input_cost_per_token=5e-9, output_cost_per_token=7e-6, cache_read_input_token_cost=9.6e-9)
    d["limits"] = {"context_window": 1048576}
    assert [c.locator[-1] for c in s.check(GLM, d).conflicts] == ["input_cost_per_token"]


def test_variable_negative_prices_are_not_compared_and_said():
    s, _ = source()
    r = s.check("providers/openrouter/openrouter/auto.yaml",
                {"model": "openrouter/auto", "costs": [{"region": "*", "input_cost_per_token": 1e-6,
                                                         "output_cost_per_token": 0.0}]})
    assert r.checks == [] and r.conflicts == []
    assert any("variable" in n and "prompt" in n for n in r.notes)
    assert sorted(r.uncovered) == ["costs.region=*.input_cost_per_token", "costs.region=*.output_cost_per_token"]


def test_outage_is_partial_with_a_note_not_a_crash():
    s = OpenRouterSource(FakeFetch({URL: outage()}))
    r = s.check(STEP, doc(input_cost_per_token=1e-7))
    assert r.partial and r.checks == [] and "unreachable" in r.notes[0]
    assert r.uncovered == ["costs.region=*.input_cost_per_token"]


def test_a_failed_fetch_is_cached_one_attempt_per_run():
    fetch = FakeFetch({URL: outage()})
    s = OpenRouterSource(fetch)
    for _ in range(6):
        r = s.check(STEP, doc(**STEP_OK))
        assert r.partial and "unreachable" in r.notes[0]
    assert fetch.calls == [URL]
    try:
        s.prepare()
    except Exception:
        pass
    else:
        raise AssertionError("prepare() must keep raising the cached failure")
    assert fetch.calls == [URL]


def test_one_fetch_per_run():
    s, fetch = source()
    s.prepare()
    for _ in range(5):
        s.check(STEP, doc(**STEP_OK))
    assert fetch.calls == [URL]


def test_run_deadline_stops_a_hung_source():
    clock = [0.0]

    def slow(url):
        clock[0] += 100.0
        raise TimeoutError("hung")

    s = OpenRouterSource(slow, deadline_s=60.0, clock=lambda: clock[0])
    r = s.check(STEP, doc(**STEP_OK))
    assert r.partial and "unreachable" in r.notes[0]


def test_junk_values_never_raise():
    s, _ = source()
    junk = {"model": "x", "sources": [None, 5, {"a": 1}], "costs": [{"region": "*", "input_cost_per_token": [1],
                                                                    "output_cost_per_token": {"x": 1}}],
            "limits": "no"}
    for path in ("providers/openrouter/step.yaml", STEP):
        r = s.check(path, junk)
        assert r.partial
    r = s.check(STEP, {"model": "x", "costs": "junk", "limits": None})
    assert r.partial is not None


def test_check_wraps_any_exception_in_a_partial_result():
    s, _ = source()
    s._compare = lambda *a, **k: (_ for _ in ()).throw(TypeError("boom"))
    r = s.check(STEP, doc(**STEP_OK))
    assert r.partial and "adapter error" in r.notes[0] and "TypeError" in r.notes[0]


HOSTILE_IDS = ["../x", "a/../b", "//evil.example/x", "http://evil/x", "a/b%2fc", "a/b?x=1", "a/b#c", "a b/c", "a/b\\n",
               "stepfun/step-3.5-fläsh", "/abs/path", "a/b\\\\c", "a/b;c", "a/b<c>"]


def test_a_hostile_model_id_is_never_looked_up_or_fetched():
    s, fetch = source()
    for bad in HOSTILE_IDS:
        r = s.check("providers/openrouter/x.yaml", {"model": bad, "costs": [{"region": "*", "input_cost_per_token": 1e-7}]})
        assert r.partial and r.checks == [], bad
        assert r.uncovered == ["costs.region=*.input_cost_per_token"], bad
        assert any("not allowed in an OpenRouter id" in n for n in r.notes), bad
    assert fetch.calls == [URL]  # only the one fixed listing URL, ever


def test_real_openrouter_ids_pass_the_validator():
    from verify.sources._common import safe_id
    for ok in ("stepfun/step-3.5-flash", "step-3.5-flash:free", "~anthropic/claude-opus-latest", "openai/gpt-oss-120b:batch",
               "a@b/c_d.e"):
        assert safe_id(ok), ok
    assert not safe_id(None) and not safe_id(5) and not safe_id("")
