import pytest

from verify import classify, gates
from verify.model import ADDED, DELETED, MODIFIED
from verify.build import build_file

from .helpers import IN, OUT, FakeSource, base, check, mod, price, report_for, result, runner


def pr(new=3.1e-6, res=None, **kw):
    """A one-file price change with a source that verified the input price."""
    src = FakeSource(res=res if res is not None else result(check(IN)))
    return report_for(base(), price(input_cost_per_token=new, **kw), src)


def decide(files, current=()):
    return gates.decide(files if isinstance(files, list) else [files], current)


def test_verified_small_price_move_is_review_official_shadow():
    v = decide(pr())
    assert (v.gate, v.kind, v.verify, v.shadow) == ("review", "price-only", "official", True)
    assert v.labels == ["gate:review", "kind:price-only", "risk:price", "shadow:auto", "verify:official"]


@pytest.mark.parametrize("new,shadow,gate", [
    (3.3e-6, True, "review"),      # +10% exactly
    (3.3000033e-6, False, "review"),   # a hair over +10%: still not escalating, not shadow
    (2.7e-6, True, "review"),      # -10% exactly
    (2.69e-6, False, "escalate"),  # over -10%
    (3.75e-6, False, "review"),    # +25% review but not shadow
    (3.76e-6, False, "escalate"),
])
def test_shadow_and_gate_thresholds(new, shadow, gate):
    v = decide(pr(new))
    assert (v.shadow, v.gate) == (shadow, gate)
    assert ("shadow:auto" in v.labels) is shadow


def test_unverified_when_no_source():
    v = decide(report_for(base(), price(input_cost_per_token=3.1e-6), None))
    assert (v.gate, v.verify, v.shadow) == ("unverified", "none", False)


def test_unverified_when_source_partial_uncovered_or_promo():
    for res in (result(check(IN), partial=True), result(check(IN), uncovered=["costs.x"]),
                result(check(IN), promo="2026-12-01"), result()):
        v = decide(pr(res=res))
        assert (v.gate, v.verify, v.shadow) == ("unverified", "partial", False), res


def test_unverified_when_a_changed_field_has_no_check():
    f = report_for(base(), price(input_cost_per_token=3.1e-6, output_cost_per_token=1.51e-5),
                   FakeSource(res=result(check(IN))))
    v = decide(f)
    assert v.gate == "unverified" and not v.shadow
    f = report_for(base(), price(input_cost_per_token=3.1e-6, output_cost_per_token=1.51e-5),
                   FakeSource(res=result(check(IN), check(OUT))))
    assert decide(f).gate == "review"


def test_a_check_on_another_field_does_not_verify():
    other = ("costs", "region=*", "cache_read_input_token_cost")
    assert decide(pr(res=result(check(other)))).gate == "unverified"


def test_conflict_escalates_and_is_never_official():
    v = decide(pr(res=result(check(IN, "conflict"))))
    assert (v.gate, v.verify, v.shadow) == ("escalate", "conflict", False)
    assert "risk:price" in v.labels


def test_a_conflict_in_a_field_the_pr_changed_escalates():
    v = decide(pr(res=result(check(IN, "conflict"))))
    assert (v.gate, v.verify, v.shadow) == ("escalate", "conflict", False)


def test_a_conflict_in_an_untouched_field_is_existing_drift_not_an_escalation():
    f = pr(res=result(check(IN), check(OUT, "conflict")))
    assert [c.locator for c in f.drift] == [OUT] and f.conflicts == [] and not f.loud
    v = decide(f)
    assert v.gate == "review" and "gate:escalate" not in v.labels
    assert v.verify == "partial"                       # visible in the label, never a conflict
    assert v.shadow                                    # and it does not block the shadow measurement
    assert f.source_state == "partial" and f.gate_state == "official"


def test_one_correct_field_fix_with_fifteen_old_drifts_is_not_escalated():  # the reviewer's Bedrock case
    other = [("costs", "region=*", f"drift_{i}") for i in range(15)]
    f = pr(res=result(check(IN), *[check(loc, "conflict") for loc in other]))
    assert len(f.drift) == 15
    v = decide(f)
    assert (v.gate, v.verify, v.shadow) == ("review", "partial", True)


def test_drift_does_not_hide_a_real_problem_in_the_same_file():
    f = pr(res=result(check(IN, "conflict"), check(OUT, "conflict")))
    assert [c.locator for c in f.conflicts] == [IN] and [c.locator for c in f.drift] == [OUT]
    assert decide(f).gate == "escalate"


def test_drift_with_an_uncovered_changed_field_is_still_unverified():
    f = report_for(base(), price(input_cost_per_token=3.1e-6, output_cost_per_token=1.51e-5),
                   FakeSource(res=result(check(IN), check(("costs", "region=*", "cache_read_input_token_cost"), "conflict"))))
    assert decide(f).gate == "unverified"


def test_a_conflict_in_a_new_file_always_counts():
    src = FakeSource(res=lambda p, d: result(check(("costs", "region=*", "output_cost_per_token"), "conflict")))
    f = report_for(None, base(), src, status=ADDED)
    assert f.drift == [] and len(f.conflicts) == 1
    v = decide(f)
    assert (v.gate, v.verify) == ("escalate", "conflict")


def test_a_conflict_below_a_changed_block_counts_as_this_prs():
    after = mod(lambda d: d["costs"].append({"region": "eu", "input_cost_per_token": 3e-6}))
    f = report_for(base(), after, FakeSource(res=result(check(("costs", "region=eu", "input_cost_per_token"), "conflict"))))
    assert len(f.conflicts) == 1 and decide(f).gate == "escalate"



def test_escalating_risk_beats_verified():
    assert decide(pr(6e-6)).gate == "escalate"


@pytest.mark.parametrize("labels", [["gate:hold"], ["id:123"], ["bug", "gate:hold"], ["id:x", "gate:review"]])
def test_hold_is_sticky_and_sets_no_gate(labels):
    v = decide(pr(), labels)
    assert v.gate == "hold" and not v.shadow
    assert not [x for x in v.labels if x.startswith("gate:")]
    assert "risk:price" in v.labels and "verify:official" in v.labels  # still reports


def test_hold_outranks_escalate():
    assert decide(pr(6e-6), ["gate:hold"]).gate == "hold"


@pytest.mark.parametrize("labels", [["gate:reviewed"], ["gate:holdup"], ["identity"], ["gate:review"], []])
def test_near_miss_labels_are_not_hold(labels):
    assert decide(pr(), labels).gate == "review"


def test_precedence_escalate_over_unverified_over_review():
    verified = pr()
    unverified = report_for(base(), price(input_cost_per_token=3.1e-6), None)
    escalate = pr(6e-6)
    assert decide([verified, unverified]).gate == "unverified"
    assert decide([verified, unverified, escalate]).gate == "escalate"
    assert decide([verified]).gate == "review"


def test_one_unverified_file_blocks_shadow_for_the_pr():
    verified = pr()
    unverified = report_for(base(), price(input_cost_per_token=3.1e-6), None)
    assert not decide([verified, unverified]).shadow


def test_verified_file_plus_source_less_file_is_partial_not_official():
    verified = pr()
    unverified = report_for(base(), price(input_cost_per_token=3.1e-6), None)
    assert decide([verified, unverified]).verify == "partial"
    assert decide([unverified, unverified]).verify == "none"
    partial = pr(res=result(check(IN), partial=True))
    assert decide([verified, partial]).verify == "partial"
    assert decide([verified, verified]).verify == "official"


def test_official_needs_every_price_field_verified_even_when_the_source_is_clean():
    f = report_for(base(), price(input_cost_per_token=3.1e-6, output_cost_per_token=1.51e-5), FakeSource(res=result(check(IN))))
    assert f.source_state == "official" and f.price_limit_unverified == [OUT]
    assert decide(f).verify == "partial"


def test_an_unverified_limit_change_blocks_official_like_a_price_does():
    f = report_for(base(), mod(lambda d: d["costs"][0].update(input_cost_per_token=3.1e-6) or d["limits"].update(context_window=300000)),
                   FakeSource(res=result(check(IN))))
    assert f.source_state == "official" and f.price_limit_unverified == [("limits", "context_window")]
    assert decide(f).verify == "partial" and decide(f).gate == "unverified"
    g = report_for(base(), mod(lambda d: d["costs"][0].update(input_cost_per_token=3.1e-6) or d["limits"].update(context_window=300000)),
                   FakeSource(res=result(check(IN), check(("limits", "context_window")))))
    assert decide(g).verify == "official" and decide(g).gate == "review"


def test_a_deleted_file_does_not_break_official():
    deleted = build_file("providers/p/gone.yaml", DELETED, "model: m\n", None, runner())
    assert decide([pr(), deleted]).verify == "official"


def test_conflict_anywhere_wins_verify():
    assert decide([pr(), pr(res=result(check(IN, "conflict")))]).verify == "conflict"


def test_no_changed_files_means_no_labels():
    unchanged = report_for(base(), mod(sources=["x"]), None)
    v = decide(unchanged)
    assert (v.gate, v.kind, v.verify, v.labels, v.shadow) == (None, None, None, [], False)
    assert decide([]).labels == []


def test_new_file_is_never_shadow_and_is_new_model():
    src = FakeSource(res=lambda p, d: result(*[check(n) for n in __import__("verify.risk").risk.new_file_needs(d)]))
    f = report_for(None, base(), src, status=ADDED)
    v = decide(f)
    assert (v.kind, v.shadow, v.gate, v.verify) == ("new-model", False, "unverified", "official")
    assert decide(report_for(None, base(), None, status=ADDED)).gate == "unverified"


def test_deleted_file_escalates_and_is_mixed():
    f = build_file("providers/p/m.yaml", DELETED, "model: m\n", None, runner())
    v = decide(f)
    assert (v.gate, v.kind) == ("escalate", "mixed")


# ---- kind -----------------------------------------------------------------------
def kind(after, before=None):
    return classify.file_kind(report_for(before or base(), after, None))


def test_kinds():
    assert kind(price(input_cost_per_token=3.1e-6)) == "price-only"
    assert kind(mod(status="deprecated")) == "lifecycle"
    assert kind(mod(deprecationDate="2027-01-01")) == "lifecycle"
    assert kind(mod(features=["function_calling"])) == "features-params"
    assert kind(mod(lambda d: d["limits"].update(context_window=1))) == "features-params"
    assert kind(mod(lambda d: d["modalities"]["output"].append("audio"))) == "features-params"
    assert kind(mod(params=[])) == "features-params"
    assert kind(mod(provisioning="provisioned")) == "mixed"
    assert kind(mod(mode="embedding")) == "mixed"
    assert kind(mod(lambda d: d["costs"][0].update(input_cost_per_token=3.1e-6), features=["function_calling"])) == "mixed"
    assert kind(mod(lambda d: d["costs"][0].update(input_cost_per_token=3.1e-6), status="deprecated")) == "mixed"
    assert kind(mod(sources=["x"])) is None


def test_pr_kind_combines_files():
    a = report_for(base(), price(input_cost_per_token=3.1e-6), None)
    b = report_for(base(), price(input_cost_per_token=3.2e-6), None)
    c = report_for(base(), mod(status="deprecated"), None)
    n = report_for(None, base(), None, status=ADDED)
    assert classify.pr_kind([a, b]) == "price-only"
    assert classify.pr_kind([a, c]) == "mixed"
    assert classify.pr_kind([n]) == "new-model"
    assert classify.pr_kind([n, a]) == "mixed"
    assert classify.pr_kind([a, report_for(base(), mod(sources=["x"]), None)]) == "price-only"
    assert classify.pr_kind([]) is None


def test_price_only_with_added_region_shadow_off():
    after = mod(lambda d: d["costs"].append({"region": "eu", "input_cost_per_token": 3e-6}))
    f = report_for(base(), after, FakeSource(res=result(check(("costs", "region=eu", "input_cost_per_token")))))
    v = decide(f)
    assert v.kind == "price-only" and not v.shadow  # an added region is not a small move
    assert v.gate == "review"  # but its only price leaf is verified


def test_added_region_needs_all_its_leaves():
    after = mod(lambda d: d["costs"].append({"region": "eu", "input_cost_per_token": 3e-6, "output_cost_per_token": 1.5e-5}))
    f = report_for(base(), after, FakeSource(res=result(check(("costs", "region=eu", "input_cost_per_token")))))
    assert decide(f).gate == "unverified"


# ---- stubs --------------------------------------------------------------------------------------
STUB = {"model": "new-model", "mode": "unknown", "supportedModes": ["unknown"]}


def test_a_new_stub_file_is_unverified_new_model_never_review():
    for stub in (STUB, {"model": "m", "mode": "chat"}, {"model": "m", "mode": "chat", "features": ["function_calling"]}):
        v = decide(report_for(None, stub, None, status=ADDED))
        assert (v.gate, v.kind) == ("unverified", "new-model"), stub
    even_with_a_clean_source = FakeSource(res=result(check(IN)))
    v = decide(report_for(None, STUB, even_with_a_clean_source, status=ADDED))
    assert v.gate == "unverified"


def test_a_new_file_is_never_review_even_with_every_price_verified():
    src = FakeSource(res=lambda p, d: result(*[check(n) for n in __import__("verify.risk").risk.new_file_needs(d)]))
    f = report_for(None, base(), src, status=ADDED)
    assert f.source_state == "official" and f.unverified_needs == [] and not f.fully_verified
    assert decide(f).gate == "unverified"
    stub = report_for({"model": "m", "mode": "unknown"}, base(), src, status=MODIFIED)
    assert stub.is_new and decide(stub).gate == "unverified"


def test_filling_in_a_stub_is_a_review_level_mode_change_not_an_escalation():
    from verify.risk import assess
    out = assess(dict(STUB, costs=[{"region": "*", "input_cost_per_token": 1e-6}]), dict(base(), model="new-model"))
    assert not any(r.escalate and r.label in ("risk:mode", "risk:removal") and r.locator[0] in ("mode", "supportedModes") for r in out)


def test_provider_default_kind():
    from verify.build import build_provider_file
    d = build_provider_file("providers/p/default.yaml", MODIFIED)
    gone = build_provider_file("providers/p/provider-config.yaml", DELETED)
    assert classify.file_kind(d) == classify.file_kind(gone) == "provider-default"
    assert classify.pr_kind([d, gone]) == "provider-default"
    assert classify.pr_kind([d, pr()]) == "mixed"
    v = decide([d])
    assert (v.gate, v.kind) == ("escalate", "provider-default") and "kind:provider-default" in v.labels
    assert "kind:provider-default" in __import__("verify.labels").labels.OWNED


def test_touches_matches_a_changed_block_by_prefix_and_everything_in_a_new_file():
    from verify.model import FileReport
    f = FileReport("providers/p/m.yaml", MODIFIED, False, [], [("costs", "region=eu")])
    assert f.touches(("costs", "region=eu", "input_cost_per_token")) and f.touches(("costs", "region=eu"))
    assert not f.touches(("costs", "region=us", "input_cost_per_token")) and not f.touches(("costs",))
    new = FileReport("providers/p/m.yaml", ADDED, True, [], [])
    assert new.touches(("anything", "at", "all"))
    assert not FileReport("providers/p/m.yaml", MODIFIED, False, [], []).touches(("costs", "region=*", "x"))


def test_a_new_file_conflict_counts_even_outside_the_listed_needs():
    odd = ("costs", "region=*", "pricing_mode")                       # not a numeric leaf, so not in new_file_needs
    src = FakeSource(res=result(check(odd, "conflict")))
    f = report_for(None, base(), src, status=ADDED)
    assert odd not in f.needs and len(f.conflicts) == 1 and f.drift == []


# ---- fast-lane ------------------------------------------------------------------------------------
from verify.model import FileReport  # noqa: E402
from verify.risk import FEATURES, Risk  # noqa: E402

ADD_FEATURE = ["function_calling", "prompt_caching", "json_output"]


def feat(path="providers/p/m.yaml", **kw):
    return report_for(base(), mod(features=ADD_FEATURE, **kw), None, path=path)


def life(path="providers/p/m.yaml"):
    return report_for(base(), mod(deprecationDate="2027-01-01"), None, path=path)


def clean_file(path="providers/p/m.yaml", risks=None):
    """A modified file whose only risks are review level."""
    risks = risks if risks is not None else [Risk("risk:feature", "feature `x` added", False, FEATURES, ("features", "x"))]
    return FileReport(path, MODIFIED, False, risks, [r.locator for r in risks])


def test_features_and_lifecycle_prs_are_fast_lane_even_when_unverified():
    for f, kind in ((feat(), "features-params"), (life(), "lifecycle")):
        v = decide(f)
        assert (v.gate, v.kind, v.lane) == ("unverified", kind, "fast-lane")
        assert "fast-lane" in v.labels and "gate:unverified" in v.labels


@pytest.mark.parametrize("make,kind", [
    (lambda: pr(), "price-only"),
    (lambda: report_for(base(), mod(provisioning="provisioned"), None), "mixed"),
    (lambda: report_for(base(), mod(lambda d: d["costs"][0].update(input_cost_per_token=3.1e-6), features=ADD_FEATURE), None), "mixed"),
    (lambda: report_for(None, base(), None, status=ADDED), "new-model"),
])
def test_other_kinds_are_never_fast_lane(make, kind):
    v = decide(make())
    assert v.kind == kind and v.lane == "normal" and "fast-lane" not in v.labels


def test_provider_default_is_never_fast_lane():
    from verify.build import build_provider_file
    v = decide([build_provider_file("providers/p/default.yaml", MODIFIED)])
    assert (v.kind, v.lane) == ("provider-default", "escalate") and "fast-lane" not in v.labels
    # and the kind alone is enough to refuse it, whatever the gate
    assert not gates.fast_lane_ok([clean_file()], "review", "provider-default")


def test_an_escalating_change_is_not_fast_lane():
    removed = report_for(base(), mod(features=["function_calling"]), None)        # a feature removed
    v = decide(removed)
    assert (v.kind, v.gate, v.lane) == ("features-params", "escalate", "escalate") and "fast-lane" not in v.labels
    shrunk = report_for(base(), mod(lambda d: d["limits"].update(context_window=1000)), None)
    assert decide(shrunk).lane == "escalate"
    dead = report_for(base(), mod(status="deprecated"), None)                     # flip to deprecated
    assert (decide(dead).kind, decide(dead).lane) == ("lifecycle", "escalate")


def test_a_static_rule_escalation_blocks_fast_lane():
    loud_rule = Risk("risk:rule-null-status", "`status:` is present with no value", True, "rule", ("status",))
    f = clean_file(risks=[Risk("risk:feature", "feature `x` added", False, FEATURES, ("features", "x")), loud_rule])
    v = decide(f)
    assert (v.kind, v.gate, v.lane) == ("features-params", "escalate", "escalate")
    assert not gates.fast_lane_ok([f], "unverified", "features-params")   # the guard holds even if the gate were wrong


def test_a_review_level_rule_finding_does_not_block_fast_lane():
    soft = Risk("risk:rule-max-tokens-below-limit", "cap below the limit", False, "rule", ("params", "key=max_tokens"))
    f = clean_file(risks=[Risk("risk:feature", "feature `x` added", False, FEATURES, ("features", "x")), soft])
    assert decide(f).lane == "fast-lane"


def test_fast_lane_ok_needs_review_or_unverified_gate():
    files = [clean_file()]
    for gate, ok in (("review", True), ("unverified", True), ("escalate", False), ("hold", False), (None, False)):
        assert gates.fast_lane_ok(files, gate, "features-params") is ok, gate
    for kind, ok in (("features-params", True), ("lifecycle", True), ("price-only", False), ("mixed", False),
                     ("new-model", False), ("provider-default", False), (None, False)):
        assert gates.fast_lane_ok(files, "unverified", kind) is ok, kind


def test_a_source_conflict_blocks_fast_lane():
    f = clean_file()
    f.results = [result(check(("limits", "context_window"), "conflict"))]
    f.needs = [("limits", "context_window")]
    assert f.conflicts and not gates.fast_lane_ok([f], "unverified", "features-params")


def test_hold_is_lane_hold_and_never_fast_lane():
    v = decide(feat(), ["gate:hold"])
    assert (v.gate, v.lane) == ("hold", "hold") and "fast-lane" not in v.labels
    assert decide(feat(), ["id:5"]).lane == "hold"


def test_ten_files_are_fast_lane_eleven_are_not():
    ten = [feat(path=f"providers/p/m{i:02d}.yaml") for i in range(gates.FAST_LANE_MAX_FILES)]
    eleven = ten + [feat(path="providers/p/m99.yaml")]
    assert gates.FAST_LANE_MAX_FILES == 10
    assert decide(ten).lane == "fast-lane"
    v = decide(eleven)
    assert (v.gate, v.lane) == ("unverified", "normal") and "fast-lane" not in v.labels


def test_unchanged_files_do_not_count_toward_the_file_limit():
    noise = [report_for(base(), mod(sources=["x"]), None, path=f"providers/p/n{i}.yaml") for i in range(30)]
    assert decide([feat()] + noise).lane == "fast-lane"


def test_nothing_changed_has_no_lane():
    v = decide([])
    assert v.lane is None and not gates.fast_lane_ok([], "unverified", "features-params")


def test_lane_of():
    assert gates.lane_of(None, False) is None
    assert gates.lane_of("hold", True) == "hold" and gates.lane_of("escalate", True) == "escalate"
    assert gates.lane_of("review", True) == "fast-lane" and gates.lane_of("unverified", False) == "normal"
