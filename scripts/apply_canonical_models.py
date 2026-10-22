#!/usr/bin/env python3
"""Optional bulk helper: apply a local alias map onto provider model YAML files.

Day-to-day workflow edits canonical_model directly in provider YAML and reviews
it in the PR. Use this script only for bulk bootstrap from a local mapping file.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from model_identity_lib import (
    load_aliases,
    load_language_models,
    update_model_yaml_fields,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--from",
        dest="aliases_path",
        type=Path,
        required=True,
        help="Local YAML mapping of provider model ID -> canonical_model",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report changes without writing files",
    )
    args = parser.parse_args()

    aliases = load_aliases(args.aliases_path)
    if not aliases:
        print(f"No aliases found in {args.aliases_path}", file=sys.stderr)
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
