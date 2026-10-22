#!/usr/bin/env python3
"""Optional bulk helper: apply a local external-id map onto provider model YAML files.

Day-to-day workflow edits external_ids directly in provider YAML and reviews it
in the PR. Use this script only for bulk bootstrap from a local mapping file.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from model_identity_lib import (
    load_external_id_map,
    load_language_models,
    update_model_yaml_fields,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--from",
        dest="external_ids_path",
        type=Path,
        required=True,
        help="Local YAML mapping of canonical_model -> external_ids",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--clear-missing",
        action="store_true",
        help="Remove external_ids from models whose canonical_model is absent from the map",
    )
    args = parser.parse_args()

    external_map = load_external_id_map(args.external_ids_path)
    if not external_map:
        print(f"No external IDs found in {args.external_ids_path}", file=sys.stderr)
        return 1

    updated = 0
    unchanged = 0
    skipped_no_canonical = 0

    for entry in load_language_models():
        canonical = entry.canonical_model
        if not canonical:
            skipped_no_canonical += 1
            continue
        ids = external_map.get(canonical)
        if not ids:
            if args.clear_missing and entry.external_ids:
                if args.dry_run:
                    print(f"CLEAR {entry.rel_path}")
                    updated += 1
                elif update_model_yaml_fields(entry.path, clear_external_ids=True):
                    updated += 1
                else:
                    unchanged += 1
            else:
                unchanged += 1
            continue

        if entry.external_ids == ids:
            unchanged += 1
            continue

        if args.dry_run:
            print(f"UPDATE {entry.rel_path}: {ids}")
            updated += 1
            continue

        if update_model_yaml_fields(entry.path, external_ids=ids):
            updated += 1
        else:
            unchanged += 1

    print(
        f"external_ids apply: updated={updated} unchanged={unchanged} "
        f"no_canonical={skipped_no_canonical} dry_run={args.dry_run}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
