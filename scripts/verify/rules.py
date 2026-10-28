"""Static rules over one model YAML, from the most frequent Cursor Bugbot findings on bot PRs.

Each rule returns Findings: a stable id, a severity (review | escalate) and a field locator. The
core reports a finding as a `risk:rule-<id>` label and counts it in the gate: `escalate` severity
means gate:escalate, `review` never does. A finding is only reported when the PR INTRODUCES it
(the file's findings on the base commit are subtracted), so an old, accepted file is not re-flagged
when someone touches it.

Calibrated on the live catalog (every providers/**/*.yaml, `python -m verify.rules --calibrate`):
existing files are the ground truth of "accepted", so a rule that fires on more than 5% of them is
narrowed. What was narrowed, and why:
- max-tokens-inherited-cap: 16.7% of the catalog inherits a default cap below its output limit
  (openrouter alone is 509 of 827 files), so it only applies to the providers whose files almost
  always override it (CAP_OVERRIDE_PROVIDERS, >= 60% own override). There a missing override is
  the inconsistency Bugbot flags.
- deprecated-undated: `isDeprecated: true` with no status and no dates is 7% of the catalog; it
  only fires when the file also cites a source (0.5%), i.e. the page it cites should give a date.
- reasoning-unsupported only looks at a reasoning_effort param the model declares itself; a
  default.yaml inherited one is on 24% of chat files.
Rules that `status:`-null or break the CUE enums fire on 0 existing files (CUE already rejects
them), so they escalate.
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from . import yamlio
from .labels import RULE_IDS
from .risk import Risk, num

REVIEW, ESCALATE = "review", "escalate"
TEXT_MODES = ("chat", "completion", "responses")
NON_REASONING_MODES = ("embedding", "rerank", "image", "text_to_speech", "moderation", "ocr", "audio_transcription",
                       "audio_translation", "video")
# Providers where >= 60% of the files with an output limit above the default cap override it
# (n >= 10), measured on the catalog by `--calibrate`. Elsewhere inheriting the cap is the norm.
CAP_OVERRIDE_PROVIDERS = frozenset({"anthropic", "aws-bedrock", "azure-open-ai", "cohere", "groq", "microsoft-foundry",
                                    "openai", "truefoundry-managed", "xai"})
# Fallbacks, used when the CUE schema files cannot be read; tests keep them equal to the schema.
FEATURES = frozenset({"assistant_prefill", "cache_control", "code_execution", "function_calling", "json_output",
                      "mid_conversation_system_messages", "parallel_function_calling", "prompt_caching",
                      "structured_output", "system_messages", "tool_choice"})
REASONING_VALUES = frozenset({"default", "high", "low", "max", "medium", "minimal", "none", "xhigh"})


@dataclass(frozen=True)
class Finding:
    id: str
    severity: str  # review | escalate
    locator: tuple[str, ...]
    message: str


@dataclass(frozen=True)
class Schema:
    features: frozenset = FEATURES
    reasoning_values: frozenset = REASONING_VALUES


@dataclass
class Context:
    defaults: dict = field(default_factory=dict)  # the provider's default.yaml, parsed
    provider: str = ""
    schema: Schema = field(default_factory=Schema)


def _enum(text: str, name: str) -> frozenset | None:
    """The quoted values of a CUE disjunction `#Name:` ... up to the first blank line."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if re.match(rf"^{re.escape(name)}:\s*$", line):
            vals = []
            for nxt in lines[i + 1:]:
                if not nxt.strip():
                    break
                vals += re.findall(r'"([A-Za-z0-9_.-]+)"', nxt.split("//")[0])
            return frozenset(vals) or None
    return None


def load_schema(root: Path | str | None) -> Schema:
    """Valid features / reasoning_effort values from the repo's CUE files; the embedded copies
    when a file is missing or its enum cannot be found."""
    feats, reasoning = FEATURES, REASONING_VALUES
    if root:
        base = Path(root) / ".github" / "test"
        try:
            feats = _enum((base / "model.cue").read_text(), "#Feature") or feats
            reasoning = _enum((base / "model.rules.cue").read_text(), "#ReasoningEffortValue") or reasoning
        except OSError:
            pass
    return Schema(feats, reasoning)


def _list(v) -> list:
    return v if isinstance(v, list) else ([] if v is None else [v])


def params_by_key(doc: dict | None) -> dict[str, dict]:
    return {p["key"]: p for p in _list((doc or {}).get("params")) if isinstance(p, dict) and isinstance(p.get("key"), str)}


def output_limit(doc: dict) -> float | None:
    limits = doc.get("limits") if isinstance(doc.get("limits"), dict) else {}
    for key in ("max_output_tokens", "max_tokens"):
        v = num(limits.get(key))
        if v:
            return v
    return None


def _text_model(doc: dict) -> bool:
    return doc.get("mode") in TEXT_MODES


# ------------------------------------------------------------------------------- rules

def max_tokens_below_limit(doc, ctx):
    limit = output_limit(doc)
    if limit is None or not _text_model(doc):
        return []
    out = []
    for key in ("max_tokens", "max_completion_tokens"):
        cap = num(params_by_key(doc).get(key, {}).get("maxValue"))
        if cap is not None and cap < limit:
            out.append(Finding("max-tokens-below-limit", REVIEW, ("params", f"key={key}", "maxValue"),
                               f"{key} maxValue {cap:g} is below the model's output limit {limit:g}"))
    return out


def max_tokens_inherited_cap(doc, ctx):
    limit = output_limit(doc)
    if limit is None or not _text_model(doc) or ctx.provider not in CAP_OVERRIDE_PROVIDERS:
        return []
    cap = num(params_by_key(ctx.defaults).get("max_tokens", {}).get("maxValue"))
    if cap is None or cap >= limit or "max_tokens" in _list(doc.get("removeParams")):
        return []
    if num(params_by_key(doc).get("max_tokens", {}).get("maxValue")) is not None:
        return []
    return [Finding("max-tokens-inherited-cap", REVIEW, ("params", "key=max_tokens"),
                    f"inherits the provider max_tokens cap {cap:g}, below the model's output limit {limit:g}; "
                    "no max_tokens override")]


def max_completion_pair(doc, ctx):
    removed = _list(doc.get("removeParams"))
    if not _text_model(doc) or "max_tokens" not in removed or "max_completion_tokens" in removed:
        return []  # both removed on purpose (no token param at all) is not a missing pair
    if "max_completion_tokens" in {**params_by_key(ctx.defaults), **params_by_key(doc)}:
        return []
    return [Finding("max-completion-pair", REVIEW, ("removeParams", "max_tokens"),
                    "max_tokens is removed but no max_completion_tokens param replaces it")]


def null_status(doc, ctx):
    if "status" in doc and doc["status"] is None:
        return [Finding("null-status", ESCALATE, ("status",), "`status:` is present with no value (fails CUE validation)")]
    return []


def deprecated_conflict(doc, ctx):
    if doc.get("isDeprecated") is True and isinstance(doc.get("status"), str) and doc["status"] in ("active", "preview"):
        return [Finding("deprecated-conflict", REVIEW, ("isDeprecated",), f"isDeprecated is true but status is {doc['status']}")]
    return []


def deprecated_undated(doc, ctx):
    if (doc.get("isDeprecated") is True and "status" not in doc and not doc.get("deprecationDate")
            and not doc.get("retirementDate") and _list(doc.get("sources"))):
        return [Finding("deprecated-undated", REVIEW, ("isDeprecated",),
                        "isDeprecated is true with no status, deprecationDate or retirementDate")]
    return []


def reasoning_enum(doc, ctx):
    p = params_by_key(doc).get("reasoning_effort")
    if not p:
        return []
    bad = [v for v in _list(p.get("supportedValues")) if not isinstance(v, str) or v not in ctx.schema.reasoning_values]
    return [Finding("reasoning-enum", ESCALATE, ("params", "key=reasoning_effort", "supportedValues"),
                    f"reasoning_effort supportedValues not in the schema: {', '.join(map(str, bad))}")] if bad else []


def reasoning_default(doc, ctx):
    p = params_by_key(doc).get("reasoning_effort")
    if not p or not _list(p.get("supportedValues")) or p.get("defaultValue") is None:
        return []
    if p["defaultValue"] not in _list(p["supportedValues"]):
        return [Finding("reasoning-default", REVIEW, ("params", "key=reasoning_effort", "defaultValue"),
                        f"reasoning_effort default {p['defaultValue']} is not in its supportedValues")]
    return []


def reasoning_unsupported(doc, ctx):
    if "reasoning_effort" not in params_by_key(doc):
        return []
    if doc.get("mode") in NON_REASONING_MODES:
        why = f"a {doc['mode']} model"
    elif doc.get("thinking") is not True:
        why = "a model without `thinking: true`"
    else:
        return []
    return [Finding("reasoning-unsupported", REVIEW, ("params", "key=reasoning_effort"),
                    f"reasoning_effort param on {why}")]


def feature_enum(doc, ctx):
    bad = sorted({str(f) for f in _list(doc.get("features")) if not isinstance(f, str) or f not in ctx.schema.features}, key=str)
    return [Finding("feature-enum", ESCALATE, ("features", f), f"feature `{f}` is not in the schema") for f in bad]


RULES = {
    "max-tokens-below-limit": max_tokens_below_limit,
    "max-tokens-inherited-cap": max_tokens_inherited_cap,
    "max-completion-pair": max_completion_pair,
    "null-status": null_status,
    "deprecated-conflict": deprecated_conflict,
    "deprecated-undated": deprecated_undated,
    "reasoning-enum": reasoning_enum,
    "reasoning-default": reasoning_default,
    "reasoning-unsupported": reasoning_unsupported,
    "feature-enum": feature_enum,
}
assert tuple(RULES) == RULE_IDS


def evaluate(doc: dict | None, ctx: Context | None = None) -> list[Finding]:
    """Every finding of one file. Never raises: a rule that crashes is skipped."""
    if not isinstance(doc, dict):
        return []
    ctx = ctx or Context()
    out: list[Finding] = []
    for rule in RULES.values():
        try:
            out += rule(doc, ctx)
        except Exception:  # noqa: BLE001 - a rule informs; it never fails an update
            continue
    return out


def introduced(before: dict | None, after: dict | None, ctx: Context | None = None) -> list[Finding]:
    """Findings in `after` that `before` did not already have (same rule and locator)."""
    old = {(f.id, f.locator) for f in evaluate(before, ctx)}
    return [f for f in evaluate(after, ctx) if (f.id, f.locator) not in old]


def to_risks(findings: list[Finding]) -> list[Risk]:
    """Findings as core risks: `risk:rule-<id>`; group `rule` (ignored by kind:*); nothing for a
    source to verify."""
    return [Risk(f"risk:rule-{f.id}", f.message, f.severity == ESCALATE, "rule", f.locator, None, ()) for f in findings]


# ------------------------------------------------------------------------- calibration

def calibrate(root: Path) -> tuple[int, Counter, dict]:
    """Run every rule over providers/**/*.yaml at `root`. Returns (files, counts, examples)."""
    defaults = {d.parent.name: (yamlio.load(d.read_text()) or {}) for d in root.glob("*/default.yaml")}
    schema = load_schema(root.parent)
    counts: Counter = Counter()
    examples: dict[str, list[str]] = {}
    files = [p for p in sorted(root.rglob("*.yaml")) if p.name not in ("default.yaml", "provider-config.yaml")]
    for f in files:
        doc = yamlio.load(f.read_text())
        if doc is None:
            continue
        provider = f.relative_to(root).parts[0]
        for rid in {x.id for x in evaluate(doc, Context(defaults.get(provider, {}), provider, schema))}:
            counts[rid] += 1
            examples.setdefault(rid, []).append(str(f.relative_to(root)))
    return len(files), counts, examples


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="verify.rules")
    ap.add_argument("--calibrate", action="store_true", help="count findings per rule over providers/**/*.yaml")
    ap.add_argument("--providers", default="providers")
    args = ap.parse_args(argv)
    if not args.calibrate:
        ap.error("nothing to do: pass --calibrate")
    total, counts, examples = calibrate(Path(args.providers))
    print(f"{total} files")
    for rid in RULE_IDS:
        n = counts[rid]
        print(f"{rid:28} {n:5} {100 * n / max(total, 1):5.2f}%  {'(over 5%: narrow it)' if n / max(total, 1) > 0.05 else ''}"
              f"  e.g. {examples.get(rid, [''])[0]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
