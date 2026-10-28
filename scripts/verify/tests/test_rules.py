"""Static rules. The fixtures/real files come from truefoundry/models history, the version BEFORE a
human fix ("after-" is the fixed one): 3834d22e (GATEWAY-3026, microsoft-foundry gpt-5.2-codex),
7905dd83 (databricks gemini deprecation fix), 10e0c51c (azure-openai gpt-5, o1-mini, o3-mini);
catalog-openai-chat-latest.yaml is the current catalog file at origin/main 788b1bea."""
import copy
from pathlib import Path

import pytest

from verify import cli, gates, labels, rules, yamlio
from verify.build import build_file
from verify.model import ADDED, MODIFIED
from verify.registry import Registry

from .helpers import FakeSource, base, mod, runner

REAL = Path(__file__).parent / "fixtures" / "real"
REPO = Path(__file__).resolve().parents[3]


def real(name):
    return yamlio.load((REAL / name).read_text())


def ids(findings):
    return sorted(f.id for f in findings)


def ctx(provider="p", defaults=None):
    return rules.Context(defaults or {}, provider, rules.Schema())


# ---- the rules against real history -------------------------------------------------
def test_real_inherited_cap_before_human_fix_3834d22e():
    # GATEWAY-3026 "Add max_completion_token to GPT models in Microsoft Foundry": the file had a
    # 128000 output limit and inherited the provider's low max_tokens cap.
    before, after = real("before-3834d22e-microsoft-foundry-gpt-5.2-codex.yaml"), real("after-3834d22e-microsoft-foundry-gpt-5.2-codex.yaml")
    c = ctx("microsoft-foundry", real("default-3834d22e-microsoft-foundry.yaml"))
    found = rules.evaluate(before, c)
    assert "max-tokens-inherited-cap" in ids(found)
    f = next(f for f in found if f.id == "max-tokens-inherited-cap")
    assert (f.severity, f.locator) == ("review", ("params", "key=max_tokens"))
    assert "max-tokens-inherited-cap" not in ids(rules.evaluate(after, c))  # the human fix clears it


def test_inherited_cap_only_applies_to_providers_that_normally_override():
    before = real("before-3834d22e-microsoft-foundry-gpt-5.2-codex.yaml")
    d = real("default-3834d22e-microsoft-foundry.yaml")
    assert ids(rules.evaluate(before, ctx("openrouter", d))) == []  # openrouter inherits the cap in 61% of files
    assert "max-tokens-inherited-cap" in ids(rules.evaluate(before, ctx("openai", d)))


def test_real_databricks_deprecation_conflict_7905dd83():
    before, after = real("before-7905dd83-databricks-gemini-2-5-flash.yaml"), real("after-7905dd83-databricks-gemini-2-5-flash.yaml")
    assert before["isDeprecated"] is True and before["status"] in ("active", "preview")
    found = rules.evaluate(before, ctx("databricks"))
    assert [(f.id, f.severity) for f in found if f.id == "deprecated-conflict"] == [("deprecated-conflict", "review")]
    assert "deprecated-conflict" not in ids(rules.evaluate(after, ctx("databricks")))


def test_real_azure_openai_gpt5_override_below_limit_10e0c51c():
    before, after = real("before-10e0c51c-azure-openai-gpt-5.yaml"), real("after-10e0c51c-azure-openai-gpt-5.yaml")
    c = ctx("azure-openai", real("default-10e0c51c-azure-openai.yaml"))
    f = [f for f in rules.evaluate(before, c) if f.id == "max-tokens-below-limit"]
    assert f and f[0].locator[-1] == "maxValue"
    assert "max-tokens-below-limit" not in ids(rules.evaluate(after, c))


def test_real_invalid_feature_name_10e0c51c():
    before = real("before-10e0c51c-azure-openai-o1-mini.yaml")
    assert "chat" in before["features"]
    f = [f for f in rules.evaluate(before, ctx("azure-openai")) if f.id == "feature-enum"]
    assert [(x.severity, x.locator) for x in f] == [("escalate", ("features", "chat"))]
    assert "feature-enum" not in ids(rules.evaluate(real("after-10e0c51c-azure-openai-o1-mini.yaml"), ctx("azure-openai")))


def test_real_reasoning_param_on_a_non_reasoning_model_10e0c51c():
    before = real("before-10e0c51c-azure-openai-o3-mini.yaml")
    assert not before.get("thinking")
    assert "reasoning-unsupported" in ids(rules.evaluate(before, ctx("azure-openai")))
    assert "reasoning-unsupported" not in ids(rules.evaluate(real("after-10e0c51c-azure-openai-o3-mini.yaml"), ctx("azure-openai")))


def test_real_catalog_file_removing_max_tokens_without_a_pair():
    doc = real("catalog-openai-chat-latest.yaml")
    d = real("default-catalog-openai.yaml")
    assert "max_completion_tokens" not in rules.params_by_key(doc) and "max_completion_tokens" not in rules.params_by_key(d)
    f = [f for f in rules.evaluate(doc, ctx("openai", d)) if f.id == "max-completion-pair"]
    assert f and f[0].locator == ("removeParams", "max_tokens")


# ---- each rule, boundaries --------------------------------------------------------------
def test_null_status_escalates_and_absent_status_does_not():  # Bugbot: "Invalid null lifecycle status" (High)
    doc = yamlio.load("model: m\nmode: chat\nstatus:\n")
    assert "status" in doc and doc["status"] is None
    [f] = [f for f in rules.evaluate(doc, ctx()) if f.id == "null-status"]
    assert (f.severity, f.locator) == ("escalate", ("status",))
    assert not [f for f in rules.evaluate({"model": "m", "mode": "chat"}, ctx()) if f.id == "null-status"]
    assert not [f for f in rules.evaluate(mod(status="active"), ctx()) if f.id == "null-status"]


@pytest.mark.parametrize("doc,fires", [
    ({"isDeprecated": True, "status": "active"}, True), ({"isDeprecated": True, "status": "preview"}, True),
    ({"isDeprecated": True, "status": "deprecated"}, False), ({"isDeprecated": True, "status": "retired"}, False),
    ({"isDeprecated": False, "status": "active"}, False), ({"status": "active"}, False),
])
def test_deprecated_conflict(doc, fires):
    assert ("deprecated-conflict" in ids(rules.evaluate({"model": "m", **doc}, ctx()))) is fires


@pytest.mark.parametrize("extra,fires", [
    ({}, True),
    ({"status": "deprecated"}, False), ({"status": "active"}, False), ({"status": None}, False),
    ({"deprecationDate": "2026-01-01"}, False), ({"retirementDate": "2026-01-01"}, False),
    ({"sources": []}, False),
])
def test_deprecated_undated(extra, fires):
    doc = {"model": "m", "isDeprecated": True, "sources": ["https://x"], **extra}
    assert ("deprecated-undated" in ids(rules.evaluate(doc, ctx()))) is fires


def reasoning_doc(values, default="medium", **kw):
    return {"model": "m", "mode": "chat", "thinking": True, **kw,
            "params": [{"key": "reasoning_effort", "supportedValues": values, "defaultValue": default}]}


def test_reasoning_enum():  # Bugbot: "Unsupported reasoning_effort value listed"
    assert ids(rules.evaluate(reasoning_doc(["low", "medium", "high"]), ctx())) == []
    assert ids(rules.evaluate(reasoning_doc(sorted(rules.REASONING_VALUES), default="low"), ctx())) == []
    [f] = rules.evaluate(reasoning_doc(["low", "medium", "turbo"]), ctx())
    assert (f.id, f.severity, f.locator) == ("reasoning-enum", "escalate", ("params", "key=reasoning_effort", "supportedValues"))
    assert "turbo" in f.message and "low" not in f.message


def test_reasoning_default_must_be_a_supported_value():  # Bugbot: "Wrong reasoning_effort default value"
    [f] = rules.evaluate(reasoning_doc(["low", "high"], default="medium"), ctx())
    assert (f.id, f.severity) == ("reasoning-default", "review")
    assert ids(rules.evaluate(reasoning_doc(["low", "high"], default="high"), ctx())) == []
    assert ids(rules.evaluate(reasoning_doc(["low", "high"], default=None), ctx())) == []
    assert ids(rules.evaluate(reasoning_doc([], default="medium"), ctx())) == []  # nothing to compare with


@pytest.mark.parametrize("over,fires", [
    ({"thinking": True}, False), ({"thinking": False}, True), ({"thinking": None}, True),
    ({"thinking": True, "mode": "embedding"}, True), ({"thinking": True, "mode": "image"}, True),
    ({"thinking": True, "mode": "responses"}, False),
])
def test_reasoning_unsupported(over, fires):
    doc = reasoning_doc(["low", "medium"], **over)
    if doc["thinking"] is None:
        del doc["thinking"]
    assert ("reasoning-unsupported" in ids(rules.evaluate(doc, ctx()))) is fires


def test_an_inherited_reasoning_param_is_not_flagged():
    doc = {"model": "m", "mode": "chat"}
    assert ids(rules.evaluate(doc, rules.Context({"params": [{"key": "reasoning_effort"}]}, "p"))) == []


def test_feature_enum():
    [f] = rules.evaluate({"model": "m", "features": ["function_calling", "streaming"]}, ctx())
    assert (f.id, f.severity, f.locator) == ("feature-enum", "escalate", ("features", "streaming"))
    assert ids(rules.evaluate({"model": "m", "features": sorted(rules.FEATURES)}, ctx())) == []
    assert ids(rules.evaluate({"model": "m", "features": [{"x": 1}]}, ctx())) == ["feature-enum"]


CHAT = {"model": "m", "mode": "chat", "limits": {"max_output_tokens": 8000}}
CAPPED = {"params": [{"key": "max_tokens", "maxValue": 4096, "defaultValue": 128}]}


@pytest.mark.parametrize("over,fires", [
    ({}, True),                                                         # inherits 4096 < 8000
    ({"params": [{"key": "max_tokens", "maxValue": 8000}]}, False),     # overridden
    ({"params": [{"key": "max_tokens", "maxValue": 8001}]}, False),
    ({"removeParams": ["max_tokens"]}, False),                          # replaced by a different param
    ({"limits": {"max_output_tokens": 4096}}, False),                   # exactly the cap
    ({"limits": {"max_output_tokens": 4097}}, True),
    ({"limits": {"max_tokens": 9000}}, True),                           # falls back to limits.max_tokens
    ({"limits": {}}, False), ({"limits": {"max_output_tokens": "lots"}}, False),
    ({"mode": "embedding"}, False), ({"mode": "image"}, False), ({"mode": "responses"}, True),
])
def test_inherited_cap(over, fires):
    doc = {**CHAT, **over}
    assert ("max-tokens-inherited-cap" in ids(rules.evaluate(doc, ctx("openai", CAPPED)))) is fires


def test_inherited_cap_needs_a_default_cap():
    assert ids(rules.evaluate(CHAT, ctx("openai", {}))) == []
    assert ids(rules.evaluate(CHAT, ctx("openai", {"params": [{"key": "max_tokens"}]}))) == []  # no maxValue


@pytest.mark.parametrize("key,cap,fires", [("max_tokens", 4096, True), ("max_completion_tokens", 4096, True),
                                           ("max_tokens", 8000, False), ("max_completion_tokens", 8001, False), ("temperature", 1, False)])
def test_own_override_below_the_limit(key, cap, fires):
    doc = {**CHAT, "params": [{"key": key, "maxValue": cap}]}
    assert ("max-tokens-below-limit" in ids(rules.evaluate(doc, ctx()))) is fires


@pytest.mark.parametrize("over,fires", [
    ({"removeParams": ["max_tokens"]}, True),
    ({"removeParams": ["max_tokens"], "params": [{"key": "max_completion_tokens", "maxValue": 8000}]}, False),
    ({"removeParams": ["max_tokens", "max_completion_tokens"]}, False),
    ({"removeParams": ["stream"]}, False), ({}, False),
    ({"removeParams": ["max_tokens"], "mode": "embedding"}, False),
])
def test_missing_max_completion_pair(over, fires):
    assert ("max-completion-pair" in ids(rules.evaluate({**CHAT, **over}, ctx()))) is fires
    inherited = rules.Context({"params": [{"key": "max_completion_tokens"}]}, "p")
    assert "max-completion-pair" not in ids(rules.evaluate({**CHAT, "removeParams": ["max_tokens"]}, inherited))


def test_rules_never_raise_on_odd_shapes():
    for bad in (None, [], "x", {"params": "p", "features": 3, "limits": [1], "removeParams": 5, "status": {}},
                {"params": [None, 1, {"key": 5}], "mode": ["chat"], "isDeprecated": "yes", "sources": 7}):
        rules.evaluate(bad, ctx("openai", {"params": "zz"}))


# ---- plumbing ---------------------------------------------------------------------------
def test_rule_ids_and_labels_agree():
    assert tuple(rules.RULES) == labels.RULE_IDS
    assert {f"risk:rule-{i}" for i in labels.RULE_IDS} <= labels.OWNED
    for rid, fn in rules.RULES.items():
        assert callable(fn) and rid == rid.lower()


def test_embedded_enums_equal_the_cue_schema_and_the_loader_reads_them():
    s = rules.load_schema(REPO)
    assert s.features == rules.FEATURES and s.reasoning_values == rules.REASONING_VALUES
    assert len(s.features) == 11 and len(s.reasoning_values) == 8


def test_loader_reads_a_changed_schema_and_falls_back_when_missing(tmp_path):
    cue = tmp_path / ".github" / "test"
    cue.mkdir(parents=True)
    (cue / "model.cue").write_text('#Feature:\n\t"alpha" | // "ignored in comment"\n\t"beta"\n\n#Other: "x"\n')
    (cue / "model.rules.cue").write_text('#ReasoningEffortValue:\n\t"a" |\n\t"b"\n\n#ModelParam: {}\n')
    s = rules.load_schema(tmp_path)
    assert s.features == {"alpha", "beta"} and s.reasoning_values == {"a", "b"}
    assert rules.load_schema(tmp_path / "nope") == rules.Schema()
    assert rules.load_schema(None) == rules.Schema()
    (cue / "model.cue").write_text("nothing here\n")
    assert rules.load_schema(tmp_path).features == rules.FEATURES


def test_a_schema_with_a_new_feature_accepts_it():
    c = rules.Context({}, "p", rules.Schema(features=frozenset({"alpha"})))
    assert ids(rules.evaluate({"model": "m", "features": ["alpha"]}, c)) == []
    assert ids(rules.evaluate({"model": "m", "features": ["function_calling"]}, c)) == ["feature-enum"]


def test_only_findings_the_change_introduces_are_reported():
    old = {**CHAT, "isDeprecated": True, "status": "active"}
    assert ids(rules.introduced(old, copy.deepcopy(old), ctx())) == []
    new = {**old, "features": ["bogus"]}
    assert ids(rules.introduced(old, new, ctx())) == ["feature-enum"]
    assert ids(rules.introduced(None, new, ctx())) == ["deprecated-conflict", "feature-enum"]
    fixed = {**old, "status": "deprecated"}
    assert rules.introduced(old, fixed, ctx()) == []


def test_a_second_finding_of_the_same_rule_at_a_new_locator_is_introduced():
    old = {"model": "m", "features": ["bogus"]}
    new = {"model": "m", "features": ["bogus", "bogus2"]}
    assert [f.locator for f in rules.introduced(old, new, ctx())] == [("features", "bogus2")]


def test_to_risks_maps_label_severity_group_and_no_source_needs():
    risks = rules.to_risks([rules.Finding("null-status", "escalate", ("status",), "m"),
                            rules.Finding("deprecated-conflict", "review", ("isDeprecated",), "m")])
    assert [(r.label, r.escalate, r.group, r.needs) for r in risks] == [
        ("risk:rule-null-status", True, "rule", ()), ("risk:rule-deprecated-conflict", False, "rule", ())]
    assert all(r.label in labels.OWNED for r in risks)


# ---- in the core --------------------------------------------------------------------------
def rule_ctx():
    return rules.Context({}, "p", rules.Schema())


def build(before, after, status=MODIFIED, source=None):
    import yaml
    dump = lambda d: None if d is None else yaml.safe_dump(d, sort_keys=True)  # noqa: E731
    return build_file("providers/p/m.yaml", status, None if status == ADDED else dump(before), dump(after), runner(source), rule_ctx())


def test_escalating_rule_finding_makes_the_gate_escalate_even_when_prices_are_verified():
    from .helpers import IN, check, result
    src = FakeSource(res=result(check(IN)))
    clean = build(base(), mod(lambda d: d["costs"][0].update(input_cost_per_token=3.1e-6)), source=src)
    assert gates.decide([clean]).gate == "review"
    after = mod(lambda d: d["costs"][0].update(input_cost_per_token=3.1e-6), features=["function_calling", "prompt_caching", "bogus"])
    g = build(base(), after, source=FakeSource(res=result(check(IN))))
    v = gates.decide([g])
    assert v.gate == "escalate" and "risk:rule-feature-enum" in v.labels
    assert any(r.label == "risk:rule-feature-enum" and r.escalate for r in g.risks)


def test_review_rule_finding_does_not_escalate_and_adds_nothing_for_a_source_to_verify():
    before = mod(isDeprecated=True, status="deprecated")
    after = mod(isDeprecated=True, status="active")
    g = build(before, after)
    rule_risks = [r for r in g.risks if r.group == "rule"]
    assert [r.label for r in rule_risks] == ["risk:rule-deprecated-conflict"]
    assert not rule_risks[0].escalate and rule_risks[0].needs == ()
    assert ("status",) in g.needs and len(g.needs) == len([r for r in g.risks if r.group != "rule"])
    v = gates.decide([g])
    assert v.gate == "unverified" and "risk:rule-deprecated-conflict" in v.labels  # the status change itself has no source


def test_a_file_with_only_rule_findings_is_review_and_has_no_kind():
    from verify import classify
    from verify.model import FileReport
    f = FileReport("providers/p/m.yaml", MODIFIED, False, rules.to_risks([rules.Finding("reasoning-default", "review", ("params",), "m")]))
    assert classify.file_kind(f) is None and f.fully_verified
    v = gates.decide([f])
    assert (v.gate, v.kind, v.verify) == ("review", None, "none") and v.labels == ["gate:review", "risk:rule-reasoning-default", "verify:none"]
    f.risks = rules.to_risks([rules.Finding("feature-enum", "escalate", ("features", "x"), "m")])
    assert gates.decide([f]).gate == "escalate"
    from verify.types import SourceResult
    f.results = [SourceResult("fake", partial=True)]  # a partial source result is never verified, needs or not
    assert not f.fully_verified


def test_new_file_findings_are_all_reported_and_kind_stays_new_model():
    doc = mod(features=["bogus"], status=None)
    doc["status"] = None
    f = build(None, doc, status=ADDED)
    assert {"risk:rule-feature-enum", "risk:rule-null-status"} <= {r.label for r in f.risks}
    v = gates.decide([f])
    assert (v.kind, v.gate) == ("new-model", "escalate")


def test_a_pre_existing_finding_is_not_reported_when_the_file_is_touched():
    before = mod(features=["function_calling", "bogus"])
    after = mod(lambda d: d["costs"][0].update(input_cost_per_token=3.1e-6), features=["function_calling", "bogus"])
    f = build(before, after)
    assert {r.label for r in f.risks} == {"risk:price"}


def test_cli_reads_the_provider_default_and_the_schema():
    import yaml
    fake_defaults = yaml.safe_dump({"params": [{"key": "max_tokens", "maxValue": 4096}]})
    small = {**base(), "limits": {"max_output_tokens": 1000}}
    chat = {**base(), "limits": {"max_output_tokens": 128000}}
    path = "providers/openai/m.yaml"
    files = {("MB", path): yaml.safe_dump(small), ("H", path): yaml.safe_dump(chat), ("H", "providers/openai/default.yaml"): fake_defaults}

    class Repo:
        def merge_base(self, b, h): return "MB"
        def changed(self, b, h): return [("M", path)]
        def show(self, ref, p): return files.get((ref, p))

    out = cli.run(Repo(), "B", "H", registry=Registry())
    assert "risk:rule-max-tokens-inherited-cap" in out["labels"]
    out = cli.run(Repo(), "B", "H", registry=Registry(), schema=rules.Schema())
    assert "risk:rule-max-tokens-inherited-cap" in out["labels"]


# ---- calibration ------------------------------------------------------------------------------
def test_calibrate_counts_findings_per_rule_on_a_tree(tmp_path):
    prov = tmp_path / "providers"
    (prov / "openai").mkdir(parents=True)
    (prov / "openai" / "default.yaml").write_text("params:\n  - {key: max_tokens, maxValue: 4096}\n")
    (prov / "openai" / "a.yaml").write_text("model: a\nmode: chat\nlimits: {max_output_tokens: 9000}\n")
    (prov / "openai" / "b.yaml").write_text("model: b\nmode: chat\nfeatures: [bogus]\n")
    (prov / "openai" / "c.yaml").write_text("model: c\nmode: chat\n")
    (prov / "openai" / "bad.yaml").write_text("a: [\n")
    total, counts, examples = rules.calibrate(prov)
    assert total == 4 and counts == {"max-tokens-inherited-cap": 1, "feature-enum": 1}
    assert examples["feature-enum"] == ["openai/b.yaml"]


def test_calibrate_cli_prints_every_rule_and_flags_over_5_percent(tmp_path, capsys):
    prov = tmp_path / "providers"
    (prov / "p").mkdir(parents=True)
    (prov / "p" / "a.yaml").write_text("model: a\nfeatures: [bogus]\n")
    assert rules.main(["--calibrate", "--providers", str(prov)]) == 0
    out = capsys.readouterr().out
    assert all(rid in out for rid in labels.RULE_IDS) and "over 5%" in out
    with pytest.raises(SystemExit):
        rules.main([])
