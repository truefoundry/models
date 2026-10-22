#!/usr/bin/env python3
"""Publish guard: check a freshly built ai-models.json against the one that is live.

Runs in the `upload` job of trigger-sync.yml, before anything is copied to S3, so a merge to
main cannot publish gross pricing errors straight to prod. It is a blunt net for large mistakes
(unit slips, mass removals, dropped pricing data, a price that moves several-fold), not a check
that a price is right: wrong prices that stay inside the limits are for review and the verifier.
It does not catch, among others: a uniform scaling of all rates below 3x, input and output rates
swapped on one model, a region renamed everywhere, model-level fields (mode, limits), or a new
model with a unit mistake below 0.1 per token.

Rules. The first four need no baseline; the rest compare with the live file.
  malformed      the new file is not a non-empty list of {provider, model, costs} entries
                 (never overridable: exit 2 whatever the flags)
  bad_rate       a negative or non-finite rate
  unit_slip      a per-token rate of 0.1 or more (the highest real rate is about 0.01)
  price_jump     a rate moved 10x or more in either direction
  price_to_zero  a rate that was above zero is now zero
  price_change   (warning only) a rate moved more than 3x but less than 10x
  field_dropped  a model that stays in a region lost its input or output rate and has no
                 per-image, per-second, per-character, per-page, per-query or per-request one
  removed        a provider lost 3 or more models and 20% of its live models, or the catalog lost 5%
  block_dropped  5 or more models lost the same pricing block (tiered, priority, flex, ultrafast)
  rate_dropped   5 or more models lost the same optional rate (cache read or creation, batches)
  regions_dropped  5 or more of one provider's multi-region models lost a region

Usage:
    python3 scripts/publish_guard.py --new ai-models.json [--live live-ai-models.json]
        [--report-only] [--summary "$GITHUB_STEP_SUMMARY"]
Exit status: 0 nothing blocking (or --report-only), 10 blocking findings, 2 the new file is
unreadable or malformed, 3 the guard crashed. Any other status means the guard did not run (an
interpreter or import error); the workflow treats 3 and unknown statuses as "not checked", never
as a reason to block. Warnings are listed in the report and as annotations but never block.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import traceback
import unicodedata
from collections import defaultdict
from dataclasses import dataclass

EXIT_OK = 0
EXIT_BAD_NEW_FILE = 2
EXIT_CRASH = 3
EXIT_BLOCKING = 10

PRICE_WARN_RATIO = 3.0    # a larger move is reported
PRICE_BLOCK_RATIO = 10.0  # a move this large (or more) blocks the publish
RATIO_EPSILON = 1e-9      # 4e-6 / 4e-7 is 10.000000000000002 or 9.99999... depending on the pair; a decimal 10x must block
UNIT_SLIP_RATE = 0.1
PROVIDER_REMOVAL_FRACTION = 0.20
PROVIDER_REMOVAL_MIN = 3
CATALOG_REMOVAL_FRACTION = 0.05
MASS_DROP_MIN_MODELS = 5
NESTED_BLOCKS = ("tiered_pricing", "priority_pricing", "flex_pricing", "ultrafast_pricing")
MASS_DROP_RATES = ("cache_read_input_token_cost", "cache_creation_input_token_cost",
                   "input_cost_per_token_batches", "output_cost_per_token_batches")
REQUIRED_RATES = ("input_cost_per_token", "output_cost_per_token")
# Units a model can be priced in instead of per token. A sibling rate such as `_batches` or
# `_audio_token` is not a replacement: the main rate disappearing next to one is still a loss.
REPLACEMENT_UNITS = ("image", "second", "character", "page", "annotated_page", "query", "request", "video_token")
TIER_KINDS = ("input", "output", "cache_read", "cache_write")
MAX_LISTED = 40


def _safe(text) -> str:
    """Make text from the data safe to print as one line of a log and of a markdown report.

    Provider and model names come from YAML files that anyone can propose in a PR, and the
    catalog already receives PRs with hostile names. A newline followed by `::error::` would be
    read by the runner as a workflow command, and a backtick would break out of the report's code
    spans. Control and line-separator characters become `?` and backticks become `'`.
    """
    cleaned = "".join("?" if unicodedata.category(c) in ("Cc", "Cf", "Zl", "Zp") else c for c in str(text))
    return cleaned.replace("`", "'")


@dataclass(frozen=True)
class Finding:
    rule: str
    where: str
    detail: str
    blocking: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "where", _safe(self.where))
        object.__setattr__(self, "detail", _safe(self.detail))

    def __str__(self) -> str:
        return f"[{self.rule}] {self.where}: {self.detail}"


def flatten_costs(costs) -> dict[str, float]:
    """Every numeric rate in a `costs` list as {"region|dotted.path": value}.

    Regions are the key of each cost entry. Tier steps are keyed by their threshold
    (`tiered_pricing.input@272000.cost_per_token`), not by position, so inserting a tier does not
    shift every later one.
    """
    out: dict[str, float] = {}
    if not isinstance(costs, list):
        return out
    for entry in costs:
        if not isinstance(entry, dict):
            continue
        region = str(entry.get("region", "?"))
        _walk(entry, region + "|", out, skip_region=True)
    return out


def _walk(value, prefix: str, out: dict[str, float], skip_region: bool = False, kind: str | None = None) -> None:
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return
    if isinstance(value, (int, float)):
        try:
            out[prefix.rstrip(".")] = float(value)
        except OverflowError:  # an integer literal too large for a float
            out[prefix.rstrip(".")] = float("inf")
        return
    if isinstance(value, dict):
        for key, child in value.items():
            if skip_region and key == "region":
                continue
            _walk(child, f"{prefix}{key}.", out, kind=key)
        return
    if isinstance(value, list):
        for i, step in enumerate(value):
            if kind in TIER_KINDS and isinstance(step, dict) and isinstance(step.get("from"), (int, float)):
                rest = {k: v for k, v in step.items() if k != "from"}
                _walk(rest, f"{prefix.rstrip('.')}@{step['from']}.", out)
            else:
                _walk(step, f"{prefix.rstrip('.')}[{i}].", out)


def _leaf(path: str) -> str:
    return path.rsplit(".", 1)[-1].split("|")[-1]


def _is_token_rate(path: str) -> bool:
    return "token" in _leaf(path)


def _top_level(path: str) -> str:
    """The rate name of a top-level path (`us|input_cost_per_token` -> `input_cost_per_token`)."""
    return path.split("|", 1)[-1]


def _is_entry(entry) -> bool:
    return (isinstance(entry, dict) and isinstance(entry.get("provider"), str) and bool(entry["provider"])
            and isinstance(entry.get("model"), str) and bool(entry["model"]))


def usable_entries(entries) -> list[dict]:
    """The entries that have a provider and a model, so one broken entry cannot disable the rest."""
    return [e for e in entries if _is_entry(e)] if isinstance(entries, list) else []


def _group(entries: list[dict]) -> dict[tuple[str, str], dict[str, list[float]]]:
    """{(provider, model): {path: [values]}}; a model listed twice contributes every value."""
    grouped: dict[tuple[str, str], dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for entry in entries:
        key = (entry["provider"], entry["model"])
        for path, value in flatten_costs(entry.get("costs")).items():
            grouped[key][path].append(value)
    return grouped


def check_structure(entries) -> list[Finding]:
    if not isinstance(entries, list) or not entries:
        return [Finding("malformed", "ai-models.json", "expected a non-empty list of model entries")]
    findings = []
    for i, entry in enumerate(entries):
        if not _is_entry(entry):
            findings.append(Finding("malformed", f"entry {i}", "missing provider or model"))
        elif not isinstance(entry.get("costs"), list) or not entry["costs"]:
            findings.append(Finding("malformed", f"{entry['provider']}/{entry['model']}", "costs must be a non-empty list"))
        if len(findings) >= MAX_LISTED:
            break
    return findings


def check_unit_slips(entries: list[dict]) -> list[Finding]:
    findings = []
    for entry in entries:
        for path, value in flatten_costs(entry.get("costs")).items():
            if _is_token_rate(path) and value >= UNIT_SLIP_RATE:
                findings.append(Finding(
                    "unit_slip", f"{entry['provider']}/{entry['model']}",
                    f"{path} = {value:g} per token (a rate this high is a unit mistake, e.g. per 1M tokens)",
                ))
    return findings


def check_bad_rates(entries: list[dict]) -> list[Finding]:
    findings = []
    for entry in entries:
        for path, value in flatten_costs(entry.get("costs")).items():
            if value < 0 or not math.isfinite(value):
                findings.append(Finding("bad_rate", f"{entry['provider']}/{entry['model']}", f"{path} = {value:g}"))
    return findings


def _ratio(old: float, new: float) -> float:
    """How far `new` is from `old`, as a factor >= 1. A priced rate going to zero is infinite."""
    if old == new or old <= 0:
        return 1.0  # unchanged, or free -> priced (a new price, not a move)
    if new <= 0:
        return float("inf")
    return max(new / old, old / new)


def _is_other_unit(path: str, direction: str) -> bool:
    """True for a top-level rate in a different unit of the same direction, e.g. output_cost_per_image."""
    prefix = f"{direction}_cost_per_"
    if not path.startswith(prefix):
        return False
    unit = path[len(prefix):]
    return any(unit == u or unit.startswith(u + "_") for u in REPLACEMENT_UNITS)


def check_prices(live: list[dict], new: list[dict]) -> list[Finding]:
    old_groups, new_groups = _group(live), _group(new)
    findings = []
    for key in sorted(old_groups.keys() & new_groups.keys()):
        old_paths, new_paths = old_groups[key], new_groups[key]
        where = f"{key[0]}/{key[1]}"
        for path, new_values in sorted(new_paths.items()):
            old_values = old_paths.get(path)
            if not old_values:
                continue
            for value in new_values:
                # A model listed twice has several old prices: compare with the closest one.
                reference = min(old_values, key=lambda old: _ratio(old, value))
                factor = _ratio(reference, value)
                if factor <= PRICE_WARN_RATIO + RATIO_EPSILON:
                    continue
                if value == 0:
                    findings.append(Finding("price_to_zero", where, f"{path}: {reference:g} -> 0"))
                elif factor >= PRICE_BLOCK_RATIO - RATIO_EPSILON:
                    findings.append(Finding("price_jump", where, f"{path}: {reference:g} -> {value:g} ({factor:.1f}x)"))
                else:
                    findings.append(Finding("price_change", where, f"{path}: {reference:g} -> {value:g} ({factor:.1f}x)", blocking=False))
                break
        for path in sorted(old_paths):
            region, _, rate = path.partition("|")
            if rate not in REQUIRED_RATES or path in new_paths or not old_paths[path] or max(old_paths[path]) <= 0:
                continue
            region_paths = [_top_level(p) for p in new_paths if p.startswith(region + "|")]
            if not region_paths:
                continue  # the whole region entry is gone: a region removal, not a dropped rate
            direction = rate.split("_", 1)[0]  # "input" or "output"
            if any(_is_other_unit(p, direction) for p in region_paths):
                continue  # priced another way (per image, per second, ...): a change of unit, not a loss
            findings.append(Finding("field_dropped", where, f"{path} was {old_paths[path][0]:g} and is gone"))
    return findings


def check_removals(live: list[dict], new: list[dict]) -> list[Finding]:
    live_keys = {(e["provider"], e["model"]) for e in live}
    new_keys = {(e["provider"], e["model"]) for e in new}
    removed = live_keys - new_keys
    findings = []
    by_provider_live: dict[str, int] = defaultdict(int)
    by_provider_removed: dict[str, list[str]] = defaultdict(list)
    for provider, _ in live_keys:
        by_provider_live[provider] += 1
    for provider, model in sorted(removed):
        by_provider_removed[provider].append(model)
    for provider, models in sorted(by_provider_removed.items()):
        total = by_provider_live[provider]
        if len(models) >= PROVIDER_REMOVAL_MIN and len(models) / total >= PROVIDER_REMOVAL_FRACTION:
            findings.append(Finding(
                "removed", provider,
                f"{len(models)} of {total} models removed ({len(models) / total:.0%}), e.g. {', '.join(models[:3])}",
            ))
    if live_keys and len(removed) / len(live_keys) >= CATALOG_REMOVAL_FRACTION:
        findings.append(Finding(
            "removed", "catalog",
            f"{len(removed)} of {len(live_keys)} models removed ({len(removed) / len(live_keys):.1%})",
        ))
    return findings


def _mass_drop_findings(rule: str, lost: dict[str, list[str]], what: str) -> list[Finding]:
    return [
        Finding(rule, name, f"{len(models)} models {what}, e.g. {', '.join(sorted(models)[:3])}")
        for name, models in sorted(lost.items()) if len(models) >= MASS_DROP_MIN_MODELS
    ]


def check_dropped_blocks(live: list[dict], new: list[dict]) -> list[Finding]:
    """Models that kept existing but lost a whole pricing block (the failure a generator bug causes)."""
    old_groups, new_groups = _group(live), _group(new)
    lost: dict[str, list[str]] = defaultdict(list)
    for key in old_groups.keys() & new_groups.keys():
        for block in NESTED_BLOCKS:
            had = any(f".{block}." in p or f"|{block}." in p for p in old_groups[key])
            has = any(f".{block}." in p or f"|{block}." in p for p in new_groups[key])
            if had and not has:
                lost[block].append(f"{key[0]}/{key[1]}")
    return _mass_drop_findings("block_dropped", lost, "lost the whole pricing block")


def check_dropped_rates(live: list[dict], new: list[dict]) -> list[Finding]:
    """Models that kept existing but lost an optional rate (cache read or creation, batches) everywhere."""
    old_groups, new_groups = _group(live), _group(new)
    lost: dict[str, list[str]] = defaultdict(list)
    for key in old_groups.keys() & new_groups.keys():
        for rate in MASS_DROP_RATES:
            had = any(_top_level(p) == rate and max(v) > 0 for p, v in old_groups[key].items())
            has = any(_top_level(p) == rate for p in new_groups[key])
            if had and not has:
                lost[rate].append(f"{key[0]}/{key[1]}")
    return _mass_drop_findings("rate_dropped", lost, "lost the rate in every region")


def check_dropped_regions(live: list[dict], new: list[dict]) -> list[Finding]:
    """Providers whose multi-region models lost a region, for many models at once."""
    old_groups, new_groups = _group(live), _group(new)
    lost: dict[str, list[str]] = defaultdict(list)
    for key in old_groups.keys() & new_groups.keys():
        old_regions = {p.split("|", 1)[0] for p in old_groups[key]}
        new_regions = {p.split("|", 1)[0] for p in new_groups[key]}
        if len(old_regions) >= 2 and old_regions - new_regions:
            lost[key[0]].append(key[1])
    return _mass_drop_findings("regions_dropped", lost, "of its multi-region models lost a region")


def compare(live: list[dict] | None, new) -> list[Finding]:
    """All findings for publishing `new` over `live` (None, or no usable entries, = no baseline)."""
    findings = check_structure(new)
    if findings:
        return findings
    findings = check_unit_slips(new) + check_bad_rates(new)
    baseline = usable_entries(live)
    if not baseline:
        return findings
    return (findings + check_removals(baseline, new) + check_prices(baseline, new)
            + check_dropped_blocks(baseline, new) + check_dropped_rates(baseline, new)
            + check_dropped_regions(baseline, new))


def render_summary(findings: list[Finding], live_count: int | None, new_count: int, report_only: bool,
                   ignored_live: int = 0) -> str:
    blocking = [f for f in findings if f.blocking]
    warnings = [f for f in findings if not f.blocking]
    malformed = any(f.rule == "malformed" for f in findings)
    lines = ["## Publish guard", ""]
    if live_count is None:
        lines += ["**No baseline: the live ai-models.json could not be read, so only the absolute checks ran** "
                  "(malformed output, bad rates, per-million unit slips). Price, removal and dropped-data checks did NOT run.", ""]
    else:
        lines += [f"Compared {new_count} new entries with {live_count} live entries.", ""]
    if ignored_live:
        lines += [f"{ignored_live} live entries were ignored because they have no provider and model.", ""]
    if not findings:
        lines.append("No findings.")
        return "\n".join(lines) + "\n"

    def item(f: Finding) -> str:
        # One code span: names come from data, and a code span renders them literally.
        return f"- `{f.rule}` `{f.where}: {f.detail}`"

    if blocking:
        if malformed:
            verdict = "**publish blocked** (a malformed file cannot be overridden)"
        else:
            verdict = "reported only (override is on)" if report_only else "**publish blocked**"
        lines += [f"{len(blocking)} blocking finding(s): {verdict}.", ""]
        lines += [item(f) for f in blocking[:MAX_LISTED]]
        if len(blocking) > MAX_LISTED:
            lines.append(f"- ... and {len(blocking) - MAX_LISTED} more")
        lines.append("")
    if warnings:
        lines += [f"{len(warnings)} warning(s) (a rate moved more than {PRICE_WARN_RATIO:g}x but less than {PRICE_BLOCK_RATIO:g}x; "
                  "these do not block):", ""]
        lines += [item(f) for f in warnings[:MAX_LISTED]]
        if len(warnings) > MAX_LISTED:
            lines.append(f"- ... and {len(warnings) - MAX_LISTED} more")
    return "\n".join(lines).rstrip("\n") + "\n"


def _load(path: str):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check a built ai-models.json against the live one.")
    parser.add_argument("--new", required=True, help="the freshly built ai-models.json")
    parser.add_argument("--live", help="the currently published ai-models.json (omit when it cannot be read)")
    parser.add_argument("--report-only", action="store_true", help="report findings but exit 0 (a malformed new file still exits 2)")
    parser.add_argument("--summary", help="append a markdown report to this file (GITHUB_STEP_SUMMARY)")
    args = parser.parse_args(argv)

    try:
        new = _load(args.new)
    except (OSError, ValueError) as e:
        print(f"publish guard: cannot read the new file {args.new}: {e}", file=sys.stderr)
        return EXIT_BAD_NEW_FILE

    live = None
    ignored = 0
    if args.live:
        try:
            live = _load(args.live)
        except (OSError, ValueError) as e:
            print(f"::warning::publish guard: live file unreadable ({e}); running the absolute checks only")
    if live is not None and not isinstance(live, list):
        print("::warning::publish guard: live file is not a list; running the absolute checks only")
        live = None
    if live is not None:
        usable = usable_entries(live)
        ignored = len(live) - len(usable)
        if ignored:
            print(f"::warning::publish guard: ignoring {ignored} live entries that have no provider and model")
        live = usable or None

    findings = compare(live, new)
    report = render_summary(findings, len(live) if live is not None else None,
                            len(new) if isinstance(new, list) else 0, args.report_only, ignored)
    print(report)
    if live is None:
        print("::warning::publish guard ran without a baseline: price, removal and dropped-data checks were skipped")
    if args.summary:
        with open(args.summary, "a", encoding="utf-8") as f:
            f.write(report)
    blocking = [f for f in findings if f.blocking]
    for finding in findings[:MAX_LISTED]:
        level = "error" if finding.blocking and not args.report_only else "warning"
        print(f"::{level} title=publish guard::{str(finding).replace('%', '%25')}")
    if any(f.rule == "malformed" for f in findings):
        return EXIT_BAD_NEW_FILE  # publishing an empty or garbage catalog is never acceptable
    return EXIT_BLOCKING if blocking and not args.report_only else EXIT_OK


def cli(argv: list[str] | None = None) -> int:
    """main(), but a bug in the guard exits 3 with a traceback instead of looking like a finding."""
    try:
        return main(argv)
    except SystemExit:
        raise
    except Exception:
        traceback.print_exc()
        print("::warning::publish guard crashed; nothing was checked", flush=True)
        return EXIT_CRASH


if __name__ == "__main__":
    sys.exit(cli())
