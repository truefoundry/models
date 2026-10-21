#!/usr/bin/env python3
"""Match canonical_model values to Artificial Analysis IDs. Never edits provider YAML."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from model_identity_lib import (
    REPORTS_DIR,
    fetch_aa_language_models,
    load_aliases,
    load_external_id_map,
    load_language_models,
    match_aa_for_canonical,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, default=REPORTS_DIR)
    parser.add_argument(
        "--aa-cache",
        type=Path,
        default=None,
        help="Optional JSON file of AA models (skips network when present)",
    )
    parser.add_argument(
        "--write-cache",
        type=Path,
        default=None,
        help="Write fetched AA models JSON to this path",
    )
    args = parser.parse_args()

    aliases = load_aliases()
    reviewed = load_external_id_map()
    entries = load_language_models()

    canonicals: set[str] = set()
    for entry in entries:
        if entry.model in aliases:
            canonicals.add(aliases[entry.model])
        elif entry.canonical_model:
            canonicals.add(entry.canonical_model)

    if args.aa_cache and args.aa_cache.exists():
        aa_models = json.loads(args.aa_cache.read_text(encoding="utf-8"))
    else:
        try:
            aa_models = fetch_aa_language_models()
        except RuntimeError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 2

    if args.write_cache:
        args.write_cache.parent.mkdir(parents=True, exist_ok=True)
        args.write_cache.write_text(json.dumps(aa_models, indent=2) + "\n", encoding="utf-8")

    matched = []
    ambiguous = []
    unmatched = []
    reviewed_rows = []

    for canonical in sorted(canonicals):
        status, ids, candidates = match_aa_for_canonical(canonical, aa_models, reviewed)
        row = {
            "canonical_model": canonical,
            "status": status,
            "external_ids": ids,
            "candidates": [
                {
                    "id": c.get("id"),
                    "slug": c.get("slug"),
                    "name": c.get("name"),
                    "creator": (c.get("model_creator") or {}).get("name"),
                    "release_date": c.get("release_date"),
                }
                for c in candidates
            ],
        }
        if status == "reviewed":
            reviewed_rows.append(row)
        elif status == "matched":
            matched.append(row)
        elif status == "ambiguous":
            ambiguous.append(row)
        else:
            unmatched.append(row)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    for name, rows in (
        ("aa_reviewed.json", reviewed_rows),
        ("aa_matched.json", matched),
        ("aa_ambiguous.json", ambiguous),
        ("aa_unmatched.json", unmatched),
    ):
        path = args.out_dir / name
        path.write_text(json.dumps(rows, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(
        f"AA match: reviewed={len(reviewed_rows)} matched={len(matched)} "
        f"ambiguous={len(ambiguous)} unmatched={len(unmatched)} "
        f"(reports in {args.out_dir})",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
