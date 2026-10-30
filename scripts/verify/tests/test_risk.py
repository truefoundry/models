import copy

import pytest

from verify import risk, yamlio
from verify.risk import assess

from .helpers import base, mod, price


def one(after, before=None):
    out = assess(before or base(), after)
    assert len(out) == 1, [r.reason for r in out]
    return out[0]


def labels(after, before=None):
    return sorted((r.label, r.escalate) for r in assess(before or base(), after))


def test_unchanged_has_no_risk():
    assert assess(base(), base()) == []


def test_formatting_only_is_not_a_change():
    a = yamlio.load("costs:\n  - region: '*'\n    input_cost_per_token: 0.000003\n    x: 2e-6\nmodel: m\nlimits: {a: 1}\n")
    b = yamlio.load("costs:\n  - region: '*'\n    input_cost_per_token: 3.0e-6\n    x: 2.0e-6\nmodel: m\nlimits: {a: 1}\n")
    assert assess(a, b) == []


def test_sources_list_change_is_nothing():
    assert assess(base(), mod(sources=["https://other"])) == []


def test_new_or_stub_before_has_no_risks():
    assert assess(None, base()) == []
    assert assess({"model": "m", "mode": "chat", "supportedModes": ["chat"]}, base()) == []


# ---- price thresholds -------------------------------------------------------------
@pytest.mark.parametrize("new,escalate", [
    (3.75e-6, False),    # exactly +25%
    (3.76e-6, True),     # just over
    (2.7e-6, False),     # exactly -10%
    (2.69e-6, True),     # just over -10%
    (3.3e-6, False),     # +10%
    (3.1e-6, False),     # small up
    (2.8e-6, False),     # -6.7%
    (6e-6, True),        # 2x (models#5499)
    (0, True),           # to zero
])
def test_price_thresholds(new, escalate):
    r = one(price(input_cost_per_token=new))
    assert (r.label, r.escalate) == ("risk:price", escalate)
    assert r.locator == ("costs", "region=*", "input_cost_per_token")
    assert r.group == "price"
    assert (r.change is None) == (new == 0)  # a move to zero has no relative size


def test_price_change_is_recorded_relative():
    assert one(price(input_cost_per_token=3.3e-6)).change == pytest.approx(0.10)
    assert one(price(input_cost_per_token=2.7e-6)).change == pytest.approx(-0.10)


def test_move_from_zero_escalates():
    before = price(input_cost_per_token=0)
    r = one(price(input_cost_per_token=1e-6), before)
    assert r.escalate and r.change is None


def test_nan_and_inf_are_not_numbers():
    assert risk.num(float("nan")) is None and risk.num(float("inf")) is None and risk.num(True) is None
    r = one(price(input_cost_per_token=float("nan")))
    assert r.escalate  # an unreadable new price must not slip through as "no move"


def test_string_price_change_escalates():
    assert one(price(input_cost_per_token="free")).escalate


def test_added_price_field_is_review_and_removed_one_escalates():
    r = one(price(cache_read_input_token_cost=1e-7))
    assert (r.label, r.escalate, r.locator[-1]) == ("risk:price", False, "cache_read_input_token_cost")
    after = base()
    del after["costs"][0]["output_cost_per_token"]
    r = one(after)
    assert (r.label, r.escalate) == ("risk:removal", True)


def test_region_removed_and_added():
    two = mod(lambda d: d["costs"].append({"region": "eu", "input_cost_per_token": 3e-6}))
    r = one(base(), two)
    assert (r.label, r.escalate, r.locator) == ("risk:removal", True, ("costs", "region=eu"))
    r = one(two)
    assert (r.label, r.escalate) == ("risk:price", False)
    assert ("costs", "region=eu", "input_cost_per_token") in r.needs  # a new region needs every leaf verified


@pytest.mark.parametrize("factor,escalate", [(99, False), (100, True), (1000, True)])
def test_new_region_priced_100x_others(factor, escalate):
    after = mod(lambda d: d["costs"].append({"region": "eu", "input_cost_per_token": 3e-6 * factor}))
    got = labels(after)
    assert (("risk:price", True) in got) is escalate
    assert ("risk:price", False) in got  # the region-added row itself


def test_100x_check_needs_a_nonzero_reference_region():
    zero = price(input_cost_per_token=0)
    after = copy.deepcopy(zero)
    after["costs"].append({"region": "eu", "input_cost_per_token": 5.0})
    assert all(not r.escalate for r in assess(zero, after))


def test_tiers_priority_flex_are_checked_at_depth():
    tiers = {"input": [{"from": 200000, "cost_per_token": 6e-6}], "pricing_mode": "marginal"}
    before = price(tiered_pricing=tiers, priority_pricing={"input_cost_per_token": 5e-6, "tiered_pricing": copy.deepcopy(tiers)},
                   flex_pricing={"input_cost_per_token": 1e-6})
    # doubling a tier price
    after = copy.deepcopy(before)
    after["costs"][0]["tiered_pricing"]["input"][0]["cost_per_token"] = 1.2e-5
    r = one(after, before)
    assert r.escalate and r.locator == ("costs", "region=*", "tiered_pricing", "input", "from=200000", "cost_per_token")
    # doubling a tier price INSIDE priority pricing
    after = copy.deepcopy(before)
    after["costs"][0]["priority_pricing"]["tiered_pricing"]["input"][0]["cost_per_token"] = 1.2e-5
    assert one(after, before).escalate
    # flex price +50%
    after = copy.deepcopy(before)
    after["costs"][0]["flex_pricing"]["input_cost_per_token"] = 1.5e-6
    assert one(after, before).escalate
    # priority price +10%: review
    after = copy.deepcopy(before)
    after["costs"][0]["priority_pricing"]["input_cost_per_token"] = 5.5e-6
    assert not one(after, before).escalate


def test_reordered_tiers_are_not_a_change():
    t = {"input": [{"from": 1, "cost_per_token": 1e-6}, {"from": 2, "cost_per_token": 2e-6}]}
    before = price(tiered_pricing=t)
    after = copy.deepcopy(before)
    after["costs"][0]["tiered_pricing"]["input"].reverse()
    assert assess(before, after) == []


def test_dropped_tiers_priority_pricing_escalate_as_one_removal_each():  # models#5514, #5547
    t = {"input": [{"from": 200000, "cost_per_token": 6e-6}]}
    before = price(tiered_pricing=t, priority_pricing={"input_cost_per_token": 5e-6, "output_cost_per_token": 2e-5})
    out = assess(before, base())
    assert sorted((r.label, r.escalate, r.locator[-1]) for r in out) == [
        ("risk:removal", True, "priority_pricing"), ("risk:removal", True, "tiered_pricing")]


def test_one_tier_dropped_escalates():
    t = {"input": [{"from": 1, "cost_per_token": 1e-6}, {"from": 2, "cost_per_token": 2e-6}]}
    before = price(tiered_pricing=t)
    after = copy.deepcopy(before)
    del after["costs"][0]["tiered_pricing"]["input"][1]
    assert any(r.label == "risk:removal" and r.escalate for r in assess(before, after))


def test_pricing_mode_change_escalates():
    before = price(tiered_pricing={"pricing_mode": "cumulative", "input": [{"from": 1, "cost_per_token": 1e-6}]})
    after = copy.deepcopy(before)
    after["costs"][0]["tiered_pricing"]["pricing_mode"] = "marginal"
    r = one(after, before)
    assert (r.label, r.escalate, r.group) == ("risk:price", True, "price")


def test_costs_removed_entirely_escalates():
    r = one(mod(costs=None))
    assert (r.label, r.escalate) == ("risk:removal", True)


# ---- params / features / limits / modalities --------------------------------------
def test_param_removed_added_and_value_change():  # models#5546
    r = one(mod(params=[]))
    assert (r.label, r.escalate) == ("risk:params", True)
    new = mod(lambda d: d["params"].append({"key": "top_k"}))
    r = one(new)
    assert (r.label, r.escalate) == ("risk:params", False)
    r = one(mod(lambda d: d["params"][0].update(defaultValue="high")))
    assert (r.label, r.escalate) == ("risk:param-value", False)


def test_reasoning_effort_supported_value_removed_escalates():
    r = one(mod(lambda d: d["params"][0].update(supportedValues=["low", "medium"])))
    assert (r.label, r.escalate) == ("risk:param-value", True) and "high" in r.reason
    r = one(mod(lambda d: d["params"][0].update(supportedValues=["low", "medium", "high", "xhigh"])))
    assert (r.label, r.escalate) == ("risk:param-value", False)
    r = one(mod(lambda d: d["params"][0].pop("supportedValues")))
    assert r.escalate


def test_remove_params():
    r = one(mod(removeParams=["temperature"]))
    assert (r.label, r.escalate) == ("risk:params", True)
    r = one(base(), mod(removeParams=["temperature"]))
    assert (r.label, r.escalate) == ("risk:params", False)


def test_features():
    r = one(mod(features=["function_calling"]))
    assert (r.label, r.escalate) == ("risk:removal", True)
    r = one(mod(features=["function_calling", "prompt_caching", "vision"]))
    assert (r.label, r.escalate) == ("risk:feature", False)


def test_limits():
    assert one(mod(lambda d: d["limits"].update(context_window=100000))).escalate  # shrinks
    r = one(mod(lambda d: d["limits"].update(context_window=400000)))
    assert (r.label, r.escalate) == ("risk:limit", False)
    r = one(mod(lambda d: d["limits"].pop("max_tokens")))
    assert (r.label, r.escalate) == ("risk:removal", True)
    r = one(mod(lambda d: d["limits"].update(max_input_tokens=1)))
    assert (r.label, r.escalate) == ("risk:limit", False)
    assert one(mod(lambda d: d["limits"].update(max_tokens="lots"))).escalate  # not comparable


def test_modalities():
    r = one(mod(lambda d: d["modalities"]["input"].remove("image")))
    assert (r.label, r.escalate) == ("risk:removal", True)
    r = one(mod(lambda d: d["modalities"]["output"].append("audio")))
    assert (r.label, r.escalate) == ("risk:mode", False)


# ---- identity / modes / lifecycle / other -----------------------------------------
def test_mode_and_supported_modes_and_model_id_escalate():
    assert one(mod(mode="embedding")).escalate
    r = one(mod(supportedModes=["chat", "responses"]))
    assert (r.label, r.escalate) == ("risk:mode", False)  # adding a mode is review
    r = one(mod(supportedModes=[]))
    assert (r.label, r.escalate) == ("risk:removal", True)
    r = one(mod(model="m2"))
    assert (r.label, r.escalate) == ("risk:other", True)


@pytest.mark.parametrize("change,escalate", [
    ({"status": "deprecated"}, True),
    ({"status": "retired"}, True),
    ({"isDeprecated": True}, True),
    ({"isDeprecated": False}, False),
    ({"deprecationDate": "2027-01-01"}, False),
    ({"retirementDate": "2027-06-01"}, False),
    ({"status": "preview"}, False),
])
def test_lifecycle(change, escalate):
    r = one(mod(**change))
    assert (r.label, r.escalate, r.group) == ("risk:dated", escalate, "lifecycle")


def test_already_deprecated_to_retired_is_review():
    before = mod(status="deprecated")
    r = one(mod(status="retired"), before)
    assert not r.escalate


@pytest.mark.parametrize("was,now,escalate", [
    ("unknown", "chat", False), (None, "chat", False), ("chat", "embedding", True), ("chat", "unknown", True),
    ("chat", None, True), ("unknown", None, False), ("embedding", "chat", True),
])
def test_mode_fill_in_is_review_any_other_change_escalates(was, now, escalate):
    before, after = mod(), mod()
    for doc, v in ((before, was), (after, now)):
        doc.pop("mode")
        if v is not None:
            doc["mode"] = v
    r = one(after, before)
    assert (r.label, r.escalate) == ("risk:mode", escalate)


def test_removing_the_unknown_placeholder_mode_is_review_but_a_real_mode_is_not():
    stub = mod(supportedModes=["unknown"])
    out = assess(stub, mod(supportedModes=["chat"]))
    assert [(x.label, x.escalate) for x in out] == [("risk:removal", False), ("risk:mode", False)]
    assert any(x.escalate for x in assess(mod(supportedModes=["chat", "responses"]), mod(supportedModes=["chat"])))


def test_supported_modes_removed_or_swapped_escalates():
    assert any(r.escalate for r in assess(base(), mod(supportedModes=["responses"])))  # chat removed, responses added
    assert one(mod(supportedModes=[])).escalate


def test_unknown_key_is_other_review():
    r = one(mod(provisioning="provisioned"))
    assert (r.label, r.escalate, r.group) == ("risk:other", False, "other")
    r = one(mod(canonical_model="x/y"))
    assert r.label == "risk:other"


def test_every_change_has_exactly_one_risk_and_a_locator():
    out = assess(base(), mod(lambda d: d["limits"].update(context_window=1), features=["function_calling", "prompt_caching", "x"], status="deprecated"))
    assert all(r.locator for r in out) and len(out) == 3


def test_a_crashing_check_is_an_escalating_check_error_and_others_still_run(monkeypatch):
    def boom(*a):
        raise RuntimeError("x")
    monkeypatch.setattr(risk, "_check_params", boom)
    out = assess(base(), mod(params=[], features=["function_calling"]))
    kinds = {(r.label, r.escalate) for r in out}
    assert ("risk:check-error", True) in kinds
    assert ("risk:removal", True) in kinds  # the feature check still ran


def test_odd_shapes_never_raise():
    for bad in ({"costs": "x"}, {"costs": [1, None]}, {"params": "p", "features": 3, "limits": [1]}, {"modalities": 5}):
        assess(base(), {**base(), **bad})
        assess({**base(), **bad}, base())


def test_new_file_needs_lists_price_and_limit_leaves():
    needs = risk.new_file_needs(base())
    assert ("costs", "region=*", "input_cost_per_token") in needs and ("limits", "context_window") in needs
    assert all(n[0] in ("costs", "limits") for n in needs)
