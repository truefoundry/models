"""Label names this tool owns. Stdlib only: the label workflow imports it too.

Ownership is by EXACT name. `gate:hold` (human / addition job) and every other label, e.g.
`gate:reviewed`, are never touched.
"""
from __future__ import annotations

from collections.abc import Iterable

MARKER = "<!-- catalog-verify -->"

GATES = ("review", "unverified", "escalate")  # set by this tool; `hold` is set by humans
RISKS = ("removal", "price", "params", "param-value", "feature", "limit", "mode", "dated", "other", "check-error")
VERIFY = ("official", "partial", "conflict", "none")
KINDS = ("price-only", "lifecycle", "features-params", "mixed", "new-model")
SHADOW = "shadow:auto"

GATE_LABELS = frozenset(f"gate:{g}" for g in GATES)
RISK_LABELS = frozenset(f"risk:{r}" for r in RISKS)
VERIFY_LABELS = frozenset(f"verify:{v}" for v in VERIFY)
KIND_LABELS = frozenset(f"kind:{k}" for k in KINDS)
OWNED = frozenset(GATE_LABELS | RISK_LABELS | VERIFY_LABELS | KIND_LABELS | {SHADOW})

HOLD = "gate:hold"
HOLD_PREFIX = "id:"


def is_owned(name: str) -> bool:
    """Exact match only: `gate:reviewed` and `gate:hold` are not ours."""
    return name in OWNED


def is_hold(labels: Iterable[str]) -> bool:
    """A human (or the addition job) put the PR on hold: `gate:hold` or any `id:*` label."""
    return any(name == HOLD or name.startswith(HOLD_PREFIX) for name in labels)
