#!/usr/bin/env python3
"""Propose canonical_model values. Never edits provider YAML files."""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

from model_identity_lib import (
    REPORTS_DIR,
    load_aliases,
    load_language_models,
    propose_canonical,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        type=Path,
        default=REPORTS_DIR / "canonical_proposals.json",
        help="Write the proposal report JSON here",
    )
    parser.add_argument(
        "--unmapped-only",
        action="store_true",
        help="Only propose for models that do not already have canonical_model set",
    )
    parser.add_argument(
        "--aliases-from",
        type=Path,
        default=None,
        help="Optional local YAML alias map to prefer over heuristics",
    )
    args = parser.parse_args()

    aliases = load_aliases(args.aliases_from) if args.aliases_from else {}
    entries = load_language_models()
    proposals = []
    groups: dict[str, list[str]] = defaultdict(list)

    for entry in entries:
        if args.unmapped_only and entry.canonical_model:
            continue
        if entry.model in aliases:
            proposed = aliases[entry.model]
            rule = "alias_exact"
            creator = proposed.split("/", 1)[0] if "/" in proposed else ""
            prop = {
                "path": entry.rel_path,
                "provider_id": entry.model,
                "creator": creator,
                "proposed_canonical": proposed,
                "rule": rule,
            }
        elif entry.canonical_model:
            proposed = entry.canonical_model
            prop = {
                "path": entry.rel_path,
                "provider_id": entry.model,
                "creator": proposed.split("/", 1)[0] if "/" in proposed else "",
                "proposed_canonical": proposed,
                "rule": "existing_yaml",
            }
        else:
            p = propose_canonical(entry.provider, entry.model, entry.path)
            prop = {
                "path": entry.rel_path,
                "provider_id": entry.model,
                "creator": p.creator,
                "proposed_canonical": p.proposed_canonical,
                "rule": p.rule,
            }
        proposals.append(prop)
        if prop["proposed_canonical"]:
            groups[prop["proposed_canonical"]].append(entry.rel_path)

    for prop in proposals:
        prop["group_paths"] = sorted(groups.get(prop["proposed_canonical"], [prop["path"]]))

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(proposals, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    missing_creator = sum(1 for p in proposals if not p["creator"])
    unique = len(groups)
    print(
        f"Wrote {len(proposals)} proposals ({unique} unique canonical names, "
        f"{missing_creator} missing creator) to {args.out}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
