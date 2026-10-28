"""Per-file findings the core builds and the gates / report read."""
from __future__ import annotations

from dataclasses import dataclass, field

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

    @property
    def conflicts(self) -> list[Check]:
        return [c for r in self.results for c in r.conflicts]

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
    def source_state(self) -> str:
        """none (no source covers the file) | conflict | partial | official."""
        if not self.results:
            return "none"
        if self.conflicts:
            return "conflict"
        if all(r.fully_verified and not r.promo for r in self.results):
            return "official"
        return "partial"

    @property
    def loud(self) -> bool:
        """Escalates: a risky change, or a conflict with an official source."""
        return any(r.escalate for r in self.risks) or bool(self.conflicts)

    @property
    def fully_verified(self) -> bool:
        """Every changed field has a verified check and the sources compared everything."""
        return self.source_state == "official" and not self.unverified_needs
