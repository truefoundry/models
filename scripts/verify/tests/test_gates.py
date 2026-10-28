import pytest

from verify import classify, gates
from verify.model import ADDED, DELETED
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


def test_conflict_on_an_untouched_field_still_escalates():
    v = decide(pr(res=result(check(IN), check(OUT, "conflict"))))
    assert v.gate == "escalate"


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


def test_verify_official_ignores_files_without_a_source_literal_reading():
    verified = pr()
    unverified = report_for(base(), price(input_cost_per_token=3.1e-6), None)
    assert decide([verified, unverified]).verify == "official"
    partial = pr(res=result(check(IN), partial=True))
    assert decide([verified, partial]).verify == "partial"


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
    assert (v.kind, v.shadow, v.gate) == ("new-model", False, "review")
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
    assert kind(mod(thinking=True)) == "mixed"
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
