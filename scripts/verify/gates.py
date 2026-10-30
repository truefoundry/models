"""Gate, verify:*, kind:* and shadow:auto for one PR.

Exactly one gate per PR, strongest first:
  hold        a human (or the addition job) set `gate:hold` / `id:*`; sticky, this tool sets no gate
  escalate    any escalating risk, or a conflict with an official source in a field THIS PR changed
              (every field of a new file). A conflict in a field the PR did not touch is existing
              catalog drift: reported, makes `verify:` partial at most, never changes the gate
  unverified  some changed field has no verified source check, or a source result is
              partial / uncovered / promo, or no source covers the file, or the file is new
  review      every changed field verified, nothing escalating

On top of the gate, `fast-lane` (fast_lane_ok) marks a features / params or lifecycle PR that needs
one look; the comment's "Review lane" line says fast-lane | normal | escalate | hold.

What "every changed field verified" means, exactly. For a MODIFIED file the changed fields are the
ones the risk assessment found (risk.assess). A price or limit leaf is verified when a source
returned a verified Check at that exact locator. Features, params, modalities, lifecycle and every
other key are never checked by any source, so changing one of them always leaves the file
`unverified`. Rule findings (rules.py) add nothing to verify. A NEW file is never `review`: its
price / limit leaves can be verified but its modalities, features and status cannot, so the best it
gets is `unverified` (and `verify:official` says how far the sources got).
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from . import classify
from .labels import FAST_LANE, SHADOW, is_hold
from .model import FileReport
from .risk import PRICE

SHADOW_PRICE_LIMIT = 0.10
FAST_LANE_KINDS = (classify.FEATURES_PARAMS, classify.LIFECYCLE)
FAST_LANE_GATES = ("review", "unverified")
FAST_LANE_MAX_FILES = 10


@dataclass
class Verdict:
    gate: str | None  # hold | escalate | unverified | review | None (nothing changed)
    kind: str | None
    verify: str | None  # official | partial | conflict | none | None (nothing changed)
    shadow: bool
    labels: list[str] = field(default_factory=list)
    lane: str | None = None  # fast-lane | normal | escalate | hold | None (nothing changed)


def changed(files: Iterable[FileReport]) -> list[FileReport]:
    return [f for f in files if f.changed]


def gate_of(files: Iterable[FileReport], current: Iterable[str] = ()) -> str | None:
    if is_hold(current):
        return "hold"
    files = changed(files)
    if not files:
        return None
    if any(f.loud for f in files):
        return "escalate"
    if any(not f.fully_verified for f in files):
        return "unverified"
    return "review"


def verify_of(files: Iterable[FileReport]) -> str | None:
    """official only when every changed file has a source, every source result is fully verified
    (no promo, partial or uncovered) and every changed price / limit field has a verified check.
    A PR mixing a verified file with a source-less one is partial; a PR no source covers at all
    is `none`; a conflict anywhere is `conflict`."""
    files = [f for f in changed(files) if f.status != "deleted"]
    if not files:
        return None
    states = [f.source_state for f in files]
    if "conflict" in states:
        return "conflict"
    if all(s == "none" for s in states):
        return "none"
    if all(f.source_state == "official" and not f.price_limit_unverified for f in files):
        return "official"
    return "partial"


def shadow_ok(files: Iterable[FileReport], current: Iterable[str] = ()) -> bool:
    """Measured only, never merges anything: a refresh whose every change is a price move within
    +-10% that the official source confirmed, on files that already existed."""
    files = changed(files)
    if not files or is_hold(current) or classify.pr_kind(files) != classify.PRICE_ONLY:
        return False
    for f in files:
        if f.gate_state != "official" or not f.risks:
            return False
        for r in f.risks:
            if r.label != "risk:price" or r.group != PRICE or r.change is None:
                return False
            if abs(r.change) > SHADOW_PRICE_LIMIT or not f.covered(r):
                return False
    return True


def fast_lane_ok(files: Iterable[FileReport], gate: str | None, kind: str | None) -> bool:
    """`fast-lane`: one look, review within 24 h. Only a features / params or a lifecycle change
    (never price, mixed, new-model or provider-default), only gate review or unverified (never
    escalate or hold), no escalating risk or rule finding and no source conflict in any file, and at
    most FAST_LANE_MAX_FILES changed files. Historically 79% (features / params) and 90% (lifecycle)
    of such update PRs merged with no human correction."""
    files = changed(files)
    if gate not in FAST_LANE_GATES or kind not in FAST_LANE_KINDS or not files:
        return False
    if len(files) > FAST_LANE_MAX_FILES:
        return False
    return not any(r.escalate for f in files for r in f.risks) and not any(f.conflicts for f in files)


def lane_of(gate: str | None, fast: bool) -> str | None:
    if gate is None:
        return None
    if gate in ("hold", "escalate"):
        return gate
    return "fast-lane" if fast else "normal"


def decide(files: list[FileReport], current: Iterable[str] = ()) -> Verdict:
    current = list(current)
    gate = gate_of(files, current)
    kind = classify.pr_kind(files)
    verify = verify_of(files)
    shadow = shadow_ok(files, current)
    fast = fast_lane_ok(files, gate, kind)
    labels: set[str] = set()
    if gate and gate != "hold":
        labels.add(f"gate:{gate}")
    if kind:
        labels.add(f"kind:{kind}")
    if verify:
        labels.add(f"verify:{verify}")
    if shadow:
        labels.add(SHADOW)
    if fast:
        labels.add(FAST_LANE)
    labels |= {r.label for f in changed(files) for r in f.risks}
    return Verdict(gate, kind, verify, shadow, sorted(labels), lane_of(gate, fast))
