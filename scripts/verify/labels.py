"""Label names this tool owns. Stdlib only: the label workflow imports it too.

Ownership is by EXACT name. `gate:hold` (a human), `id:*` and `verify:prices-from-source` (the
addition job) and every other label, e.g. `gate:reviewed`, are never touched.
"""
from __future__ import annotations

from collections.abc import Iterable

MARKER = "<!-- catalog-verify -->"

GATES = ("review", "unverified", "escalate")  # set by this tool; `hold` is set by humans
RISKS = ("removal", "price", "params", "param-value", "feature", "limit", "mode", "dated", "other", "check-error", "provider-default")
# Static rules (rules.py): one risk:rule-<id> label each. Keep in step with rules.RULES.
RULE_IDS = ("max-tokens-below-limit", "max-tokens-inherited-cap", "max-completion-pair", "null-status",
            "deprecated-conflict", "deprecated-undated", "reasoning-enum", "reasoning-default",
            "reasoning-unsupported", "feature-enum", "claude-feature-gaps")
VERIFY = ("official", "partial", "conflict", "none")
KINDS = ("price-only", "lifecycle", "features-params", "mixed", "new-model", "provider-default")
SHADOW = "shadow:auto"
FAST_LANE = "fast-lane"  # one look, review within 24 h; see gates.fast_lane_ok
LANES = ("fast-lane", "normal", "escalate", "hold")  # the "Review lane" line of the comment; only fast-lane is a label

GATE_LABELS = frozenset(f"gate:{g}" for g in GATES)
RISK_LABELS = frozenset({f"risk:{r}" for r in RISKS} | {f"risk:rule-{r}" for r in RULE_IDS})
VERIFY_LABELS = frozenset(f"verify:{v}" for v in VERIFY)
KIND_LABELS = frozenset(f"kind:{k}" for k in KINDS)
OWNED = frozenset(GATE_LABELS | RISK_LABELS | VERIFY_LABELS | KIND_LABELS | {SHADOW, FAST_LANE})

HOLD = "gate:hold"  # the ONLY hold: set by a human. No `id:*` label is a hold.
# Set by the addition job (which sets no gate:* label); they are INPUTS: the verifier turns them
# into gate:escalate with the reason below. Any other `id:*` label is ignored. Never removed here.
ADDITION_FLAGS = {
    "id:case-duplicate": "addition flagged: case duplicate of an existing file",
    "id:high-edit-provider": "provider has a high human-edit rate and no source price was written",
}
PRICES_FROM_SOURCE = "verify:prices-from-source"  # set by the addition job; not owned: this tool never touches it


# ------------------------------------------------------------------------------------ appearance
# A label GitHub creates on first use has no colour and no description, so the label job creates
# every missing owned label itself (sync.ensure_labels) from this table. Existing labels are never
# edited. GitHub caps a description at 100 characters.
DESCRIPTION_MAX = 100
_GATE = {
    "review": ("0e8a16", "Every changed field verified by an official source, nothing escalating"),
    "unverified": ("fbca04", "Some changed field has no verified source check"),
    "escalate": ("d93f0b", "Escalating risk or a conflict with an official source: look closely"),
}
_VERIFY = {
    "official": ("1d76db", "Every changed price and limit confirmed by an official source"),
    "partial": ("bfd4f2", "A source ran but did not cover everything"),
    "conflict": ("b60205", "An official source disagrees with a field this PR changed"),
    "none": ("ededed", "No official source covers the changed files"),
}
_KIND = {
    "price-only": "Only price fields changed",
    "lifecycle": "Only status or deprecation and retirement dates changed",
    "features-params": "Only features, params, limits or modalities changed",
    "mixed": "Several kinds of change, a deleted file or an unknown key",
    "new-model": "A new model file",
    "provider-default": "A provider default.yaml or provider-config.yaml changed",
}
_RISK = {
    "removal": "Something was removed from a model file",
    "price": "A price changed or was added",
    "params": "A param was added or removed, or removeParams changed",
    "param-value": "A param value or supported value changed",
    "feature": "A feature was added",
    "limit": "A limit was added or changed",
    "mode": "A mode, supported mode or modality changed",
    "dated": "A lifecycle field changed (status, deprecation or retirement date)",
    "other": "A key outside the usual fields changed, or the model id changed",
    "check-error": "A check crashed on this file: review by hand",
    "provider-default": "A provider-wide default.yaml or provider-config.yaml changed",
}
_LOUD_RISK = ("removal", "check-error", "provider-default")


def _meta() -> dict[str, tuple[str, str]]:
    out: dict[str, tuple[str, str]] = {}
    out.update({f"gate:{g}": v for g, v in _GATE.items()})
    out.update({f"verify:{x}": v for x, v in _VERIFY.items()})
    out.update({f"kind:{k}": ("5319e7", text) for k, text in _KIND.items()})
    out.update({f"risk:{r}": ("f9d0c4" if r in _LOUD_RISK else "fef2c0", text) for r, text in _RISK.items()})
    out.update({f"risk:rule-{rule}": ("fef2c0", f"Static rule {rule} fired: see the verify comment") for rule in RULE_IDS})
    out[SHADOW] = ("c2e0c6", "Measured only: a price move within 10% that an official source confirms")
    out[FAST_LANE] = ("006b75", "One look, review within 24 h: features, params or lifecycle only, nothing escalating")
    return out


META = _meta()


def label_meta(name: str) -> tuple[str, str] | None:
    """(colour hex without #, description) of an owned label, None for any other name."""
    return META.get(name)


def is_owned(name: str) -> bool:
    """Exact match only: `gate:reviewed` and `gate:hold` are not ours."""
    return name in OWNED


def is_hold(labels: Iterable[str]) -> bool:
    """A human put the PR on hold: `gate:hold`, and only that (no `id:*` label is a hold)."""
    return HOLD in labels


def addition_flags(labels: Iterable[str]) -> list[str]:
    """Reasons for the `id:*` labels the addition job sets that escalate the PR, in a stable order."""
    names = set(labels)
    return [reason for label, reason in ADDITION_FLAGS.items() if label in names]
