"""The contract between the source adapters (sources/*.py) and the verifier core.

Adapters know one provider's public data. The core knows nothing about any provider: it asks each
adapter that `covers()` a file to `check()` it, then turns the results into a risk, a gate and
labels. Nothing here may use the network, the LLM or the DB.

Rules every adapter follows:
- The official value wins. A value that matches is `verified`; any difference is a `conflict`.
- A discount or promotion is never a conflict: the catalog keeps the LIST price. Set
  `SourceResult.promo` and mark the field uncovered (partial).
- A file is only "official" when EVERY price field in it was compared. Anything not compared goes
  in `uncovered` and sets `partial=True`. Never guess.
- Prices compare within 0.5% relative; context windows and token limits within 2.5%.
- One network fetch per run per source (`prepare()` caches); an outage is `partial`, never a crash.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

PRICE_TOLERANCE = 0.005
LIMIT_TOLERANCE = 0.025

CheckStatus = Literal["verified", "conflict"]


@dataclass(frozen=True)
class Check:
    """One compared field."""

    # Where the field sits in the YAML, e.g. ("costs", "region=*", "input_cost_per_token") or
    # ("costs", "region=us-east-1", "tiered_pricing", "input", "from=200000", "cost_per_token").
    # A "key=value" token selects the list item whose `key` equals `value`. The sweep uses this
    # to write `source_value` back, so it must be exact.
    locator: tuple[str, ...]
    file_value: Any
    source_value: Any
    status: CheckStatus
    note: str = ""
    # False when `source_value` cannot be written at `locator` as-is (a derived or combined value).
    # The sweep must skip non-writable checks. Additive: older producers get True.
    writable: bool = True


@dataclass
class SourceResult:
    source: str  # "openrouter" | "deepinfra" | "aws-price-list" | ...
    checks: list[Check] = field(default_factory=list)
    # Price fields in the file that were NOT compared (locator strings joined with "."). Any entry
    # means the file can never be called fully verified.
    uncovered: list[str] = field(default_factory=list)
    partial: bool = False
    notes: list[str] = field(default_factory=list)
    # ISO date a promotion ends, only when the source gives a real one; None otherwise.
    promo: str | None = None
    # True whenever the source says a discount or promotion is active, with or without an end date.
    # Presence of either `promo` or `promo_active` marks the file partial. Additive.
    promo_active: bool = False

    @property
    def conflicts(self) -> list[Check]:
        return [c for c in self.checks if c.status == "conflict"]

    @property
    def fully_verified(self) -> bool:
        return (bool(self.checks) and not self.conflicts and not self.partial and not self.uncovered
                and not self.promo and not self.promo_active)


class Source(Protocol):
    name: str

    def covers(self, provider: str) -> bool:
        """True when this source can say something about files under providers/<provider>/."""

    def prepare(self) -> None:
        """Fetch what is needed, once. Cached; raising here is allowed (the core turns it into a
        partial result with a note)."""

    def check(self, repo_path: str, doc: dict) -> SourceResult:
        """`repo_path` is e.g. providers/openrouter/stepfun/x.yaml, `doc` the parsed YAML."""
