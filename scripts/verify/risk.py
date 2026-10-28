"""What a changed model YAML changed versus main, and how risky each change is.

Every changed field gets exactly one risk; nothing changes silently. The escalate rules are the
mistakes a human had to fix on a bot PR in 2026-10:
- anything removed (price region, tier, priority pricing, rate, param, a supported value of a
  param, feature, limit, modality, supported mode): the agent drops what it did not re-find, and
  "not on the page I read" is not evidence that it is gone (models#5514, #5547, #5546);
- a price move over +25%, any drop over 10%, or a move to / from 0 (#5499 was 2x), at any depth:
  flat rates, `priority_pricing`, `flex_pricing`, `tiered_pricing` and tiers inside them;
- a NEW region priced >= 100x the existing regions (a per-million price in a per-token field);
- a changed `pricing_mode`, `mode` (other than filling in an unknown one), a removed supported mode or a changed model id, a shrinking limit, a value
  added to `removeParams`, a flip to deprecated / retired, a check that crashed.
Smaller price moves, added features / limits / params, param value changes, lifecycle dates and
any unknown key are review-level. Formatting-only changes (2e-6 vs 2.0e-6) are not changes.

A Risk carries the `locator` of the field in the same shape as `types.Check.locator`, so the core
can tell whether a source verified exactly that field.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass

from . import yamlio
from .textclean import clean_line

PRICE_UP_LIMIT = 0.25
PRICE_DOWN_LIMIT = 0.10
NEW_REGION_FACTOR = 100.0
LIFECYCLE = ("status", "isDeprecated", "deprecationDate", "retirementDate")
DEAD_STATUSES = ("deprecated", "retired")
STUB_KEYS = {"model", "mode", "supportedModes"}
# Top-level keys with their own rule below; any other changed key is `risk:other`.
COVERED = {"costs", "params", "removeParams", "features", "limits", "mode", "supportedModes",
           "modalities", "sources", "model", *LIFECYCLE}

PRICE, LIFE, FEATURES, OTHER = "price", "lifecycle", "features-params", "other"

Locator = tuple[str, ...]


@dataclass(frozen=True)
class Risk:
    label: str  # one of labels.RISK_LABELS
    reason: str
    escalate: bool
    group: str = OTHER  # price | lifecycle | features-params | other (drives kind:*)
    locator: Locator = ()
    change: float | None = None  # relative price change when both sides are numbers
    # Fields that must each have a verified source check for this risk to count as verified. A
    # new region lists every price leaf in it; default is the locator itself.
    leaves: tuple[Locator, ...] | None = None

    @property
    def needs(self) -> tuple[Locator, ...]:
        return self.leaves if self.leaves is not None else (self.locator,)


def num(value) -> float | None:
    """A finite number, else None. Booleans and NaN / inf are not numbers."""
    if isinstance(value, bool):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _as_list(value) -> list:
    if isinstance(value, list):
        return value
    return [] if value is None else [value]  # a scalar where a list belongs: one item


def _name(value) -> str:
    return value if isinstance(value, str) else json.dumps(value, sort_keys=True, default=str)


def _fmt(n: float) -> str:
    return f"{n:.4g}"


def _code(value) -> str:
    text = clean_line(str(value).replace("`", "'"))
    return f"`{text[:80]}`"


# -------------------------------------------------------------------------------- costs

def costs_by_region(doc: dict) -> dict[str, dict]:
    """Cost entries keyed by region; a repeated region gets `#2`, `#3` so none is lost."""
    out: dict[str, dict] = {}
    for entry in _as_list(doc.get("costs")):
        if isinstance(entry, dict):
            key, n = str(entry.get("region")), 2
            while key in out:
                key, n = f"{entry.get('region')}#{n}", n + 1
            out[key] = entry
    return out


def _unique(out: dict, key: Locator) -> Locator:
    n = 2
    base = key
    while key in out:
        key = base[:-1] + (f"{base[-1]}#{n}",)
        n += 1
    return key


def leaves(value, path: Locator = ()) -> dict[Locator, object]:
    """Every scalar (and every empty container) inside a value, by path tuple. List items are
    keyed `from=<threshold>` when they have one, so a reordered tier list is not a change."""
    out: dict[Locator, object] = {}
    if isinstance(value, dict) and value:
        for k, v in value.items():
            if not path and k == "region":
                continue
            out.update(leaves(v, path + (str(k),)))
    elif isinstance(value, list) and value:
        for i, item in enumerate(value):
            if isinstance(item, dict) and "from" in item:
                rest = {k: v for k, v in item.items() if k != "from"}
                base = path + (f"from={item['from']}",)
                for k, v in (leaves(rest, base) if rest else {base: {}}).items():
                    out[_unique(out, k)] = v
            else:
                out.update(leaves(item, path + (str(i),)))
    else:
        out[path] = value
    return out


def _loc(region: str, path: Locator) -> Locator:
    return ("costs", f"region={region}") + path


def _region_name(entry: dict, fallback: str) -> str:
    r = entry.get("region")
    return str(r) if r is not None else fallback


def _check_costs(before: dict, after: dict, out: list[Risk]) -> None:
    old, new = costs_by_region(before), costs_by_region(after)
    for key in sorted(set(old) - set(new)):
        region = _region_name(old[key], key)
        out.append(Risk("risk:removal", f"price region {_code(region)} removed", True, PRICE,
                        ("costs", f"region={region}")))
    existing = [leaves(old[k]) for k in sorted(set(old) & set(new))]
    for key in sorted(set(new) - set(old)):
        region = _region_name(new[key], key)
        found = leaves(new[key])
        prices = tuple(_loc(region, p) for p, v in found.items() if num(v) is not None)
        out.append(Risk("risk:price", f"price region {_code(region)} added", False, PRICE,
                        ("costs", f"region={region}"), None, prices))
        for path, value in sorted(found.items()):
            x = num(value)
            others = [num(e.get(path)) for e in existing]
            top = max((o for o in others if o is not None and o > 0), default=None)
            if x is not None and x > 0 and top is not None and x >= NEW_REGION_FACTOR * top:
                out.append(Risk("risk:price", f"new region {_code(region)}: {_code('.'.join(path))} {_fmt(x)} is "
                                f"{x / top:.0f}x the other regions ({_fmt(top)})", True, PRICE, _loc(region, path)))
    for key in sorted(set(old) & set(new)):
        region = _region_name(new[key], key)
        a, b = leaves(old[key]), leaves(new[key])
        gone_blocks = sorted({p[0] for p in a if p} - {p[0] for p in b if p})
        for block in gone_blocks:
            out.append(Risk("risk:removal", f"{_code(block)} removed in region {_code(region)}", True, PRICE,
                            _loc(region, (block,))))
        for path in sorted(a):
            if path and path[0] in gone_blocks:
                continue
            if path not in b:
                out.append(Risk("risk:removal", f"{_code('.'.join(path))} removed in region {_code(region)}", True,
                                PRICE, _loc(region, path)))
                continue
            _check_value(region, path, a[path], b[path], out)
        for path in sorted(set(b) - set(a)):
            out.append(Risk("risk:price", f"{_code('.'.join(path))} added in region {_code(region)}: {_code(b[path])}",
                            False, PRICE, _loc(region, path)))


def _check_value(region: str, path: Locator, was, now, out: list[Risk]) -> None:
    name, loc = '.'.join(path), _loc(region, path)
    x, y = num(was), num(now)
    if x is None or y is None:
        if was != now:  # e.g. pricing_mode cumulative -> marginal changes every bill above a tier
            out.append(Risk("risk:price", f"{_code(name)} [{_code(region)}] {_code(was)} → {_code(now)}", True, PRICE, loc))
        return
    if math.isclose(x, y, rel_tol=1e-9, abs_tol=0.0):  # formatting noise is not a price move
        return
    if x == 0 or y == 0:
        out.append(Risk("risk:price", f"{_code(name)} [{_code(region)}] {_fmt(x)} → {_fmt(y)}", True, PRICE, loc))
        return
    change = round(y / x - 1, 6)  # exactly +25% / -10% stay under the limits
    out.append(Risk("risk:price", f"{_code(name)} [{_code(region)}] {_fmt(x)} → {_fmt(y)} ({change:+.1%})",
                    change > PRICE_UP_LIMIT or change < -PRICE_DOWN_LIMIT, PRICE, loc, change))


# ------------------------------------------------------------------------------- params

def _params(doc: dict) -> tuple[dict[str, dict], list[str]]:
    keyed: dict[str, dict] = {}
    odd: list[str] = []
    for p in _as_list(doc.get("params")):
        if isinstance(p, dict) and isinstance(p.get("key"), str) and p["key"] not in keyed:
            keyed[p["key"]] = p
        else:
            odd.append(_name(p))
    return keyed, odd


def _check_params(before: dict, after: dict, out: list[Risk]) -> None:
    (old, odd_old), (new, odd_new) = _params(before), _params(after)
    for key in sorted(set(old) - set(new)):
        out.append(Risk("risk:params", f"param {_code(key)} removed", True, FEATURES, ("params", f"key={key}")))
    for key in sorted(set(new) - set(old)):
        out.append(Risk("risk:params", f"param {_code(key)} added", False, FEATURES, ("params", f"key={key}")))
    for key in sorted(set(old) & set(new)):
        for fld in sorted(set(old[key]) | set(new[key]), key=str):
            was, now = old[key].get(fld), new[key].get(fld)
            if yamlio.normalized(was) == yamlio.normalized(now):
                continue
            loc = ("params", f"key={key}", str(fld))
            lost = sorted({_name(v) for v in _as_list(was)} - {_name(v) for v in _as_list(now)}) \
                if isinstance(was, list) else []
            if lost:  # a supported value (e.g. a reasoning_effort level) disappeared
                out.append(Risk("risk:param-value", f"param {_code(key)} {_code(fld)}: removed {', '.join(map(_code, lost))}",
                                True, FEATURES, loc))
            else:
                out.append(Risk("risk:param-value", f"param {_code(key)} {_code(fld)}: {_code(was)} → {_code(now)}",
                                False, FEATURES, loc))
    if sorted(odd_old) != sorted(odd_new):
        out.append(Risk("risk:param-value", "params entries without a string `key` changed", False, FEATURES, ("params",)))
    was = {_name(v) for v in _as_list(before.get("removeParams"))}
    now = {_name(v) for v in _as_list(after.get("removeParams"))}
    for key in sorted(now - was):
        out.append(Risk("risk:params", f"{_code(key)} added to removeParams", True, FEATURES, ("removeParams", key)))
    for key in sorted(was - now):
        out.append(Risk("risk:params", f"{_code(key)} no longer in removeParams", False, FEATURES, ("removeParams", key)))


def _check_features(before: dict, after: dict, out: list[Risk]) -> None:
    was = {_name(v) for v in _as_list(before.get("features"))}
    now = {_name(v) for v in _as_list(after.get("features"))}
    for item in sorted(was - now):
        out.append(Risk("risk:removal", f"feature {_code(item)} removed", True, FEATURES, ("features", item)))
    for item in sorted(now - was):
        out.append(Risk("risk:feature", f"feature {_code(item)} added", False, FEATURES, ("features", item)))


def _check_supported_modes(before: dict, after: dict, out: list[Risk]) -> None:
    was = {_name(v) for v in _as_list(before.get("supportedModes"))}
    now = {_name(v) for v in _as_list(after.get("supportedModes"))}
    for item in sorted(was - now):
        # the placeholder `unknown` going away is the stub being filled in, not a lost capability
        out.append(Risk("risk:removal", f"supportedModes {_code(item)} removed", item != "unknown", OTHER, ("supportedModes", item)))
    for item in sorted(now - was):
        out.append(Risk("risk:mode", f"supportedModes {_code(item)} added", False, OTHER, ("supportedModes", item)))


def _check_limits(before: dict, after: dict, out: list[Risk]) -> None:
    old = before.get("limits") if isinstance(before.get("limits"), dict) else {}
    new = after.get("limits") if isinstance(after.get("limits"), dict) else {}
    for key in sorted(set(old) | set(new), key=str):
        was, now = old.get(key), new.get(key)
        loc = ("limits", str(key))
        if yamlio.normalized(was) == yamlio.normalized(now):
            continue
        if key not in new:
            out.append(Risk("risk:removal", f"limit {_code(key)} removed", True, FEATURES, loc))
        elif key not in old:
            out.append(Risk("risk:limit", f"limit {_code(key)} added: {_code(now)}", False, FEATURES, loc))
        else:
            x, y = num(was), num(now)
            shrinks = x is not None and y is not None and y < x
            # a non-numeric limit that changed cannot be compared: look at it
            out.append(Risk("risk:limit", f"limit {_code(key)} {_code(was)} → {_code(now)}",
                            shrinks or x is None or y is None, FEATURES, loc))


def _check_modalities(before: dict, after: dict, out: list[Risk]) -> None:
    old = before.get("modalities") if isinstance(before.get("modalities"), dict) else {}
    new = after.get("modalities") if isinstance(after.get("modalities"), dict) else {}
    for side in sorted(set(old) | set(new), key=str):
        was = {_name(v) for v in _as_list(old.get(side))}
        now = {_name(v) for v in _as_list(new.get(side))}
        for item in sorted(was - now):
            out.append(Risk("risk:removal", f"{_code(side)} modality {_code(item)} removed", True, FEATURES,
                            ("modalities", str(side), item)))
        for item in sorted(now - was):
            out.append(Risk("risk:mode", f"{_code(side)} modality {_code(item)} added", False, FEATURES,
                            ("modalities", str(side), item)))


def _dead(doc: dict, key: str) -> bool:
    if key == "isDeprecated":
        return doc.get("isDeprecated") is True
    return isinstance(doc.get("status"), str) and doc["status"].strip().lower() in DEAD_STATUSES


def _check_lifecycle(before: dict, after: dict, out: list[Risk]) -> None:
    for fld in LIFECYCLE:
        if yamlio.normalized(before.get(fld)) == yamlio.normalized(after.get(fld)):
            continue
        flip = fld in ("status", "isDeprecated") and _dead(after, fld) and not _dead(before, fld)
        out.append(Risk("risk:dated", f"lifecycle {_code(fld)}: {_code(before.get(fld))} → {_code(after.get(fld))}"
                        + (" (now deprecated / retired)" if flip else ""), flip, LIFE, (fld,)))


def _check_rest(before: dict, after: dict, out: list[Risk]) -> None:
    was, now = before.get("mode"), after.get("mode")
    if was != now:
        # filling in (or dropping) an unknown / absent placeholder mode (a bot stub) is review; any other change escalates
        fill_in = (was in (None, "unknown") and now not in (None, "unknown")) or (was == "unknown" and now is None)
        out.append(Risk("risk:mode", f"mode {_code(was)} → {_code(now)}", not fill_in, OTHER, ("mode",)))
    if before.get("model") != after.get("model"):
        out.append(Risk("risk:other", f"model id {_code(before.get('model'))} → {_code(after.get('model'))}", True, OTHER, ("model",)))
    for key in sorted((set(before) | set(after)) - COVERED, key=str):
        if yamlio.normalized(before.get(key)) != yamlio.normalized(after.get(key)):
            out.append(Risk("risk:other", f"{_code(key)} changed", False, OTHER, (str(key),)))


def is_stub(doc: dict | None) -> bool:
    """A stub (only `model` / `mode` / `supportedModes`) has nothing to protect."""
    return not doc or set(doc) <= STUB_KEYS


def assess(before: dict | None, after: dict) -> list[Risk]:
    """Risks of one modified file. `before` None (or a stub) means a new file: no risks, the
    caller treats it as new. Each check runs on its own, so one crash cannot hide the others;
    a crash is itself an escalating `risk:check-error`. Never raises."""
    if is_stub(before):
        return []
    out: list[Risk] = []
    checks = (_check_costs, _check_params, _check_features, _check_supported_modes, _check_limits,
              _check_modalities, _check_lifecycle, _check_rest)
    for check in checks:
        mark = len(out)
        try:
            check(before, after, out)
        except Exception as e:  # noqa: BLE001 - the check informs; it never fails an update
            del out[mark:]
            out.append(Risk("risk:check-error", f"{check.__name__.lstrip('_')} failed ({type(e).__name__}); "
                            "review by hand", True, OTHER, (check.__name__.lstrip("_"),)))
    return out


def new_file_needs(after: dict) -> list[Locator]:
    """For a new file: the price and limit fields a source must have verified."""
    out: list[Locator] = []
    for key, entry in costs_by_region(after).items():
        region = _region_name(entry, key)
        out += [_loc(region, p) for p, v in leaves(entry).items() if num(v) is not None]
    limits = after.get("limits")
    if isinstance(limits, dict):
        out += [("limits", str(k)) for k, v in limits.items() if num(v) is not None]
    return out
