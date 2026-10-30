"""Per-file findings the core builds and the gates / report read."""
from __future__ import annotations

from dataclasses import dataclass, field, replace

from .risk import Locator, Risk
from .types import Check, SourceResult

ADDED, MODIFIED, DELETED, UNCHANGED = "added", "modified", "deleted", "unchanged"


@dataclass
class FileReport:
    path: str
    status: str = MODIFIED  # added | modified | deleted | unchanged (formatting / sources-only)
    is_new: bool = False  # added, or a stub before: nothing existed to compare against
    risks: list[Risk] = field(default_factory=list)
    # Fields a source must have verified. Modified file: every changed field. New file: its
    # price and limit fields.
    needs: list[Locator] = field(default_factory=list)
    results: list[SourceResult] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return self.status != UNCHANGED

    @property
    def checks(self) -> list[Check]:
        return [c for r in self.results for c in r.checks]

    def touches(self, locator) -> bool:
        """Is this field one this PR changed (or any field of a new file)?"""
        loc = tuple(locator)
        return self.is_new or any(loc[:len(n)] == tuple(n) for n in self.needs)

    @property
    def conflicts(self) -> list[Check]:
        """Conflicts in fields THIS PR changed (every field of a new file). Only these escalate."""
        return [c for c in self.all_conflicts if self.touches(c.locator)]

    @property
    def all_conflicts(self) -> list[Check]:
        return [c for r in self.results for c in r.conflicts]

    @property
    def drift(self) -> list[Check]:
        """Conflicts in fields the PR did not touch: existing catalog drift, not this PR's doing."""
        return [c for c in self.all_conflicts if not self.touches(c.locator)]

    def _own_results(self) -> list[SourceResult]:
        """The source results with the untouched-field conflicts taken out."""
        keep = [r if not r.conflicts else replace(r, checks=[c for c in r.checks if self.touches(c.locator) or c.status != "conflict"])
                for r in self.results]
        return keep

    @property
    def verified(self) -> set[Locator]:
        return {tuple(c.locator) for c in self.checks if c.status == "verified"}

    def covered(self, risk: Risk) -> bool:
        """Every field this risk stands for has a verified check."""
        needs = risk.needs
        return bool(needs) and all(n in self.verified for n in needs)

    @property
    def unverified_needs(self) -> list[Locator]:
        return [n for n in self.needs if n not in self.verified]

    @property
    def gate_state(self) -> str:
        """none | conflict | partial | official, judged on this PR's own fields only (drift is
        ignored): what the gate and shadow:auto use."""
        own = self._own_results()
        if not own:
            return "none"
        if self.conflicts:
            return "conflict"
        # fully_verified (types.py) is false for partial, uncovered, promo and promo_active results
        if all(r.fully_verified for r in own):
            return "official"
        return "partial"

    @property
    def source_state(self) -> str:
        """The same for the verify:* label: existing drift makes an otherwise official file partial."""
        state = self.gate_state
        return "partial" if state == "official" and self.drift else state

    @property
    def loud(self) -> bool:
        """Escalates: a risky change, or a conflict in a field this PR changed."""
        return any(r.escalate for r in self.risks) or bool(self.conflicts)

    @property
    def price_limit_unverified(self) -> list[Locator]:
        """Changed price / limit fields with no verified check."""
        return [n for n in self.unverified_needs if n[0] in ("costs", "limits")]

    @property
    def fully_verified(self) -> bool:
        """Every changed field has a verified check and the sources compared everything (existing
        drift in untouched fields does not count against it). A NEW file is never fully verified:
        its modalities, features and status are never source-checked. A modified file with nothing
        a source could check (only rule findings) and no source is not unverified."""
        # with no source, `unverified_needs` is every need, so "none" only passes when nothing needs one
        if self.is_new:
            return False
        return not self.unverified_needs and self.gate_state in ("official", "none")
