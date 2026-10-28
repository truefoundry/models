import yaml

from verify.build import Runner, build_file, provider_of
from verify.model import ADDED, DELETED, MODIFIED, UNCHANGED
from verify.registry import Registry
from verify.types import SourceResult

from .helpers import IN, OUT, FakeSource, base, check, mod, price, registry, report_for, result, runner


def dump(d):
    return yaml.safe_dump(d, sort_keys=True)


def test_provider_of():
    assert provider_of("providers/openrouter/x/y.yaml") == "openrouter"
    assert provider_of("README.md") == ""


def test_unchanged_file_runs_no_source():
    src = FakeSource(res=result(check(IN)))
    f = build_file("providers/p/m.yaml", MODIFIED, dump(base()), dump(mod(sources=["x"])), runner(src))
    assert f.status == UNCHANGED and not f.changed and src.checked == [] and src.prepared == 0


def test_modified_needs_every_changed_field():
    f = report_for(base(), price(input_cost_per_token=3.1e-6, output_cost_per_token=1.6e-5), FakeSource(res=result(check(IN))))
    assert set(f.needs) == {IN, OUT}
    assert f.unverified_needs == [OUT]


def test_added_file_needs_price_and_limits_and_is_new():
    f = report_for(None, base(), None, status=ADDED)
    assert f.is_new and IN in f.needs and ("limits", "context_window") in f.needs and f.risks == []


def test_deleted_file_escalates():
    f = build_file("providers/p/m.yaml", DELETED, dump(base()), None, runner())
    assert f.status == DELETED and f.loud and f.risks[0].label == "risk:removal"


def test_unparsable_after_is_check_error():
    f = build_file("providers/p/m.yaml", MODIFIED, dump(base()), "a: [\n", runner())
    assert f.loud and f.risks[0].label == "risk:check-error"
    f = build_file("providers/p/m.yaml", ADDED, None, "- list\n", runner())
    assert f.loud and f.is_new


def test_unparsable_before_is_check_error_not_a_free_pass():
    f = build_file("providers/p/m.yaml", MODIFIED, "a: [\n", dump(base()), runner())
    assert f.loud and f.risks[0].label == "risk:check-error" and not f.is_new


def test_stub_before_is_treated_as_new():
    stub = {"model": "m", "mode": "chat", "supportedModes": ["chat"]}
    f = report_for(stub, base(), None)
    assert f.is_new and f.risks == [] and f.changed
    assert report_for(stub, stub, None).status == UNCHANGED


def test_only_registered_adapters_run_for_the_provider():
    other = FakeSource(name="other", res=result(check(IN), source="other"))
    mine = FakeSource(name="fake", res=result(check(IN)))
    r = Runner(registry(("p", "fake")), {"fake": mine, "other": other})
    build_file("providers/p/m.yaml", MODIFIED, dump(base()), dump(price(input_cost_per_token=3.1e-6)), r)
    build_file("providers/q/m.yaml", MODIFIED, dump(base()), dump(price(input_cost_per_token=3.1e-6)), r)
    assert mine.checked == ["providers/p/m.yaml"] and other.checked == []


def test_prepare_once_per_run_and_failure_is_partial_with_a_note_not_a_crash():
    src = FakeSource(prepare_error=RuntimeError("network down"))
    r = runner(src)
    for name in ("a", "b"):
        f = build_file(f"providers/p/{name}.yaml", MODIFIED, dump(base()), dump(price(input_cost_per_token=3.1e-6)), r)
        assert f.source_state == "partial" and "prepare failed" in f.results[0].notes[0]
    assert src.prepared == 1 and src.checked == []
    ok = FakeSource(res=result(check(IN)))
    r = runner(ok)
    for name in ("a", "b"):
        build_file(f"providers/p/{name}.yaml", MODIFIED, dump(base()), dump(price(input_cost_per_token=3.1e-6)), r)
    assert ok.prepared == 1 and len(ok.checked) == 2


def test_check_exception_is_partial():
    f = report_for(base(), price(input_cost_per_token=3.1e-6), FakeSource(check_error=ValueError("x")))
    assert f.source_state == "partial" and not f.conflicts


def test_registered_but_unavailable_adapter_is_partial():
    r = Runner(registry(("p", "gone")), {})
    f = build_file("providers/p/m.yaml", MODIFIED, dump(base()), dump(price(input_cost_per_token=3.1e-6)), r)
    assert f.source_state == "partial" and "not available" in f.results[0].notes[0]


def test_registry_provider_the_adapter_does_not_cover_is_partial():
    f = report_for(base(), price(input_cost_per_token=3.1e-6), FakeSource(providers=("zzz",)))
    assert f.source_state == "partial"


def test_covers_exception_is_partial():
    class Bad(FakeSource):
        def covers(self, provider):
            raise RuntimeError
    assert report_for(base(), price(input_cost_per_token=3.1e-6), Bad()).source_state == "partial"


def test_garbage_result_is_partial():
    for garbage in (None, "x", object(), SourceResult("f", checks=["nope"])):
        f = report_for(base(), price(input_cost_per_token=3.1e-6), FakeSource(res=garbage))
        assert f.source_state == "partial", garbage


def test_no_registry_means_no_source():
    f = build_file("providers/p/m.yaml", MODIFIED, dump(base()), dump(price(input_cost_per_token=3.1e-6)),
                   Runner(Registry(), {"fake": FakeSource(res=result(check(IN)))}))
    assert f.results == [] and f.source_state == "none"


def test_source_states():
    one = price(input_cost_per_token=3.1e-6)
    assert report_for(base(), one, FakeSource(res=result(check(IN)))).source_state == "official"
    assert report_for(base(), one, FakeSource(res=result(check(IN), uncovered=["costs.x"]))).source_state == "partial"
    assert report_for(base(), one, FakeSource(res=result(check(IN), partial=True))).source_state == "partial"
    assert report_for(base(), one, FakeSource(res=result(check(IN), promo="2026-12-01"))).source_state == "partial"
    assert report_for(base(), one, FakeSource(res=result(check(IN), promo_active=True))).source_state == "partial"
    assert report_for(base(), one, FakeSource(res=result())).source_state == "partial"  # compared nothing
    assert report_for(base(), one, FakeSource(res=result(check(IN, "conflict")))).source_state == "conflict"


def test_two_sources_must_both_be_official():
    a = FakeSource(name="a", res=result(check(IN), source="a"))
    b = FakeSource(name="b", res=result(check(IN), source="b", partial=True))
    r = Runner(registry(("p", "a"), ("p", "b")), {"a": a, "b": b})
    f = build_file("providers/p/m.yaml", MODIFIED, dump(base()), dump(price(input_cost_per_token=3.1e-6)), r)
    assert f.source_state == "partial"


def test_covered_needs_every_leaf_and_only_verified_checks():
    from verify.model import FileReport
    from verify.risk import Risk
    leaf_a, leaf_b = ("costs", "region=eu", "a"), ("costs", "region=eu", "b")
    risk = Risk("risk:price", "r", False, "price", ("costs", "region=eu"), None, (leaf_a, leaf_b))
    f = FileReport("providers/p/m.yaml", MODIFIED, False, [risk], [leaf_a, leaf_b])
    f.results = [result(check(leaf_a))]
    assert not f.covered(risk)
    f.results = [result(check(leaf_a), check(leaf_b))]
    assert f.covered(risk)
    f.results = [result(check(leaf_a), check(leaf_b, "conflict"))]
    assert not f.covered(risk) and f.verified == {leaf_a}
    assert not f.covered(Risk("risk:removal", "gone", True, "price", ("costs", "region=eu")))
    assert not f.covered(Risk("risk:other", "x", False, "other", (), None, ()))


def test_an_active_promo_without_an_end_date_is_partial_never_official_and_never_a_conflict():
    one = price(input_cost_per_token=3.1e-6)
    f = report_for(base(), one, FakeSource(res=result(check(IN), promo_active=True)))
    assert f.source_state == "partial" and not f.conflicts and not f.fully_verified
    from verify import gates, report
    v = gates.decide([f])
    assert (v.verify, v.gate, v.shadow) == ("partial", "unverified", False)
    assert "promo active" in report.render_comment(v, [f]) and report.file_json(f)["partial"] is True
    ended = report_for(base(), one, FakeSource(res=result(check(IN))))
    assert gates.decide([ended]).verify == "official"


def test_the_writable_flag_survives_the_core():
    from verify.types import Check
    c = Check(IN, 1.0, 1.0, "verified", writable=False)
    f = report_for(base(), price(input_cost_per_token=3.1e-6), FakeSource(res=result(c)))
    assert f.checks[0].writable is False
