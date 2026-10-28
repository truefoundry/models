"""python -m verify.propose --provider P --model-id ID [--mode chat] [--regions r1,r2] [--json]
(run from scripts/)

What do the official sources give for a model that has NO prices yet? The addition job writes the
answer into the new file before it opens the PR, so a person never types a price that a source
publishes. Uses the adapters' own `propose()` (same lookup, matching and units as `check()`), for
the sources `sources/registry.yaml` lists for the provider with `price` among their `fields`.

Report-only on failure: an unregistered provider, a source that is down or a model the source does
not list is a result with no values and a reason, never a crash. Exit code 0 whatever the answer;
2 for a bad argument, 3 for an unusable registry (the JSON still says so).

APPLY. A proposal is a lead; `apply` says whether the addition job may WRITE it:
  deepinfra, aws-price-list   yes: their prices are the provider's own (DeepInfra's list price, the
                              AWS Price List's on-demand price), the same ones the PR gate verifies.
  openrouter                  NO, report-only, unless --allow-listing-prices. The listing quotes the
                              cheapest endpoint, not the first-party price, and the addition job's own
                              fetcher already writes the same listing price into the stub. The sweep
                              keeps the same line (`SAFE_SOURCES`). Evidence: scripts/verify/README.md.
"""
from __future__ import annotations

import argparse
import copy
import datetime as _dt
import json
import sys
from pathlib import Path
from typing import Any

from .registry import Registry, RegistryError
from .registry import load as load_registry
from .types import Proposal

# Sources whose proposal may be written into a new file. Anything else is report-only.
APPLY_SOURCES = frozenset({"deepinfra", "aws-price-list"})
DEFAULT_DEADLINE_S = 300.0  # an AWS proposal reads up to 70 files of about 1 MB


def _scalar(text: str) -> Any:
    return int(text) if text.isdigit() else text


def set_at(doc: dict, locator: tuple[str, ...], value: Any) -> None:
    """Write `value` at a `Check.locator`-style path, creating what is missing: a `key=value` token
    selects (or appends) the list item whose `key` equals `value`; any other token is a mapping key."""
    node: Any = doc
    for i, token in enumerate(locator):
        last = i == len(locator) - 1
        if "=" in token:
            key, _, want = token.partition("=")
            item = next((x for x in node if isinstance(x, dict) and str(x.get(key)) == want), None)
            if item is None:
                item = {key: _scalar(want)}
                node.append(item)
            node = item
        elif last:
            node[token] = value
        else:
            child = node.get(token)
            if not isinstance(child, (dict, list)):
                child = [] if "=" in locator[i + 1] else {}
                node[token] = child
            node = child


def apply_to_doc(doc: dict, proposal: Proposal, *, prefix: tuple[str, ...] | None = None) -> dict:
    """A copy of `doc` with every proposed value written at its locator (only those under `prefix[0]` when
    given, e.g. ("costs",)). `check()` on the result verifies every value written."""
    out = copy.deepcopy(doc)
    for p in proposal.values:
        if prefix is None or p.locator[: len(prefix)] == prefix:
            set_at(out, p.locator, p.value)
    return out


def applicable(proposal: Proposal, *, allow_listing_prices: bool = False) -> bool:
    """May the addition job write this proposal? See APPLY in the module docstring."""
    if not proposal.values:
        return False
    return proposal.source in APPLY_SOURCES or (proposal.source == "openrouter" and allow_listing_prices)


def proposal_json(proposal: Proposal, *, allow_listing_prices: bool = False) -> dict:
    return {
        "source": proposal.source,
        "partial": proposal.partial,
        "apply": applicable(proposal, allow_listing_prices=allow_listing_prices),
        "values": [{"locator": list(p.locator), "value": p.value, **({"note": p.note} if p.note else {})}
                   for p in proposal.values],
        "notes": list(proposal.notes),
    }


def make_adapter(factory, deadline_s: float):
    try:
        return factory(deadline_s=deadline_s)
    except TypeError:
        return factory()


def propose_for(registry: Registry, provider: str, model_id: str, mode: str = "chat", *,
                regions: list[str] | None = None, allow_listing_prices: bool = False,
                deadline_s: float = DEFAULT_DEADLINE_S, sources: dict | None = None) -> dict:
    """The result object the CLI prints. `sources` (name -> factory) is for tests; default: the adapters."""
    result: dict[str, Any] = {"version": 1, "provider": provider, "model": model_id, "mode": mode,
                              "fetched_on": _dt.date.today().isoformat(), "proposals": [], "reason": None}
    entries = [e for e in registry.for_provider(provider) if "price" in e.fields]
    if not entries:
        result["reason"] = "no price source is registered for this provider"
        return result
    if sources is None:
        from .sources import SOURCES, load_sources
        load_sources(set())  # imports every adapter module so SOURCES is filled
        sources = SOURCES
    doc: dict = {"model": model_id, "mode": mode}
    if regions:
        doc["costs"] = [{"region": r} for r in regions]
    repo_path = f"providers/{provider}/{model_id}.yaml"
    for entry in entries:
        factory = sources.get(entry.source)
        if factory is None:
            result["proposals"].append({"source": entry.source, "partial": True, "apply": False, "values": [],
                                        "notes": ["registered adapter is not available"]})
            continue
        try:
            adapter = make_adapter(factory, deadline_s)
            if not adapter.covers(provider) or not callable(getattr(adapter, "propose", None)):
                result["proposals"].append({"source": entry.source, "partial": True, "apply": False, "values": [],
                                            "notes": ["this adapter does not propose for the provider"]})
                continue
            proposal = adapter.propose(repo_path, copy.deepcopy(doc))
        except Exception as e:  # noqa: BLE001 - never crash the caller
            result["proposals"].append({"source": entry.source, "partial": True, "apply": False, "values": [],
                                        "notes": [f"source failed ({type(e).__name__}): nothing proposed"]})
            continue
        if proposal is None:
            continue
        result["proposals"].append(proposal_json(proposal, allow_listing_prices=allow_listing_prices))
    if not result["proposals"]:
        result["reason"] = "no source had anything for this model"
    return result


def render(result: dict) -> str:
    lines = [f"{result['provider']}/{result['model']} (mode {result['mode']}), fetched {result['fetched_on']}"]
    if result.get("reason"):
        lines.append(f"  {result['reason']}")
    for p in result["proposals"]:
        lines.append(f"  source {p['source']}: {len(p['values'])} value(s)"
                     f"{', partial' if p['partial'] else ''}, {'APPLY' if p['apply'] else 'report-only'}")
        for v in p["values"]:
            lines.append(f"    {'.'.join(v['locator'])} = {v['value']!r}")
        for n in p["notes"]:
            lines.append(f"    note: {n}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="verify.propose", description=__doc__.split("\n\n")[0])
    ap.add_argument("--provider", required=True)
    ap.add_argument("--model-id", required=True)
    ap.add_argument("--mode", default="chat")
    ap.add_argument("--regions", default="", help="comma separated; default: every region the source has")
    ap.add_argument("--repo", default=None, help="repo root with sources/registry.yaml (default: this checkout)")
    ap.add_argument("--registry", default=None)
    ap.add_argument("--allow-listing-prices", action="store_true",
                    help="let an OpenRouter listing price be marked `apply` (default: report-only)")
    ap.add_argument("--deadline", type=float, default=DEFAULT_DEADLINE_S, help="seconds of network per source")
    ap.add_argument("--json", dest="as_json", action="store_true")
    args = ap.parse_args(argv)

    root = Path(args.repo) if args.repo else Path(__file__).resolve().parents[2]
    regions = [r.strip() for r in args.regions.split(",") if r.strip()]
    try:
        registry = load_registry(Path(args.registry) if args.registry else root / "sources" / "registry.yaml",
                                 root / "providers")
    except RegistryError as e:
        out = {"version": 1, "provider": args.provider, "model": args.model_id, "mode": args.mode,
               "fetched_on": _dt.date.today().isoformat(), "proposals": [], "reason": f"registry unusable: {e}"[:300]}
        print(json.dumps(out, sort_keys=True) if args.as_json else render(out))
        return 3
    result = propose_for(registry, args.provider, args.model_id, args.mode, regions=regions or None,
                         allow_listing_prices=args.allow_listing_prices, deadline_s=args.deadline)
    print(json.dumps(result, sort_keys=True, ensure_ascii=True) if args.as_json else render(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
