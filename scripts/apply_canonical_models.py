#!/usr/bin/env python3
"""Apply reviewed canonical_aliases.yaml mappings to provider model YAML files."""

from __future__ import annotations

import argparse
import sys

from model_identity_lib import (
    load_aliases,
    load_language_models,
    update_model_yaml_fields,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report changes without writing files",
    )
    args = parser.parse_args()

    aliases = load_aliases()
    if not aliases:
        print("No aliases found in canonical_aliases.yaml", file=sys.stderr)
        return 1

    updated = 0
    skipped = 0
    missing = 0
    for entry in load_language_models():
        canonical = aliases.get(entry.model)
        if not canonical:
            missing += 1
            continue
        if entry.canonical_model == canonical:
            skipped += 1
            continue
        if args.dry_run:
            print(f"UPDATE {entry.rel_path}: {entry.canonical_model!r} -> {canonical!r}")
            updated += 1
            continue
        if update_model_yaml_fields(entry.path, canonical_model=canonical):
            updated += 1
        else:
            skipped += 1

    print(
        f"canonical apply: updated={updated} unchanged={skipped} "
        f"no_alias={missing} dry_run={args.dry_run}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
