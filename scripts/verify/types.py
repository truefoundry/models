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


@dataclass(frozen=True)
class Proposed:
    """One value a source would give for a model that has none yet. `locator` has exactly the
    meaning of `Check.locator`, and `check()` on a doc holding `value` at `locator` must say
    `verified` (the round trip is a permanent test)."""

    locator: tuple[str, ...]
    value: float | int | str
    note: str = ""


@dataclass
class Proposal:
    """What a source gives for a NEW model (no prices yet). Never a guess: a field the source cannot
    state unambiguously is left out and said in `notes`."""

    source: str
    values: list[Proposed] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    # True when the source cannot say it has given EVERY price the model has (a field was left out
    # as ambiguous, a tier the source cannot describe exists, or the source quotes a listing price
    # that may differ from first-party). A partial proposal is still the source's value.
    partial: bool = False


class Source(Protocol):
    """An adapter. Optionally it also has `propose(repo_path, doc) -> Proposal | None` (see
    `ProposingSource`); an adapter without it simply gives no proposals. Additive."""

    name: str

    def covers(self, provider: str) -> bool:
        """True when this source can say something about files under providers/<provider>/."""

    def prepare(self) -> None:
        """Fetch what is needed, once. Cached; raising here is allowed (the core turns it into a
        partial result with a note)."""

    def check(self, repo_path: str, doc: dict) -> SourceResult:
        """`repo_path` is e.g. providers/openrouter/stepfun/x.yaml, `doc` the parsed YAML."""


class ProposingSource(Source, Protocol):
    def propose(self, repo_path: str, doc: dict) -> Proposal | None:
        """The price / limit values this source gives for a model with NO prices yet. `doc` holds at
        least `model` and `mode` (and, for a per-region provider, optional `costs: [{region: ...}]`
        entries naming the regions wanted). `repo_path` is `providers/<provider>/<model>.yaml`. Uses the
        same lookup, matching and unit logic as `check()`. None when the model is not in the source;
        never raises."""
