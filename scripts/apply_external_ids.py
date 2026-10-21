#!/usr/bin/env python3
"""Apply reviewed canonical_external_ids.yaml to every file in each canonical group."""

from __future__ import annotations

import argparse
import sys

from model_identity_lib import (
    load_aliases,
    load_external_id_map,
    load_language_models,
    update_model_yaml_fields,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    aliases = load_aliases()
    external_map = load_external_id_map()
    if not external_map:
        print("No external IDs found in canonical_external_ids.yaml", file=sys.stderr)
        return 1

    updated = 0
    unchanged = 0
    skipped_no_canonical = 0

    for entry in load_language_models():
        canonical = aliases.get(entry.model) or entry.canonical_model
        if not canonical:
            skipped_no_canonical += 1
            continue
        ids = external_map.get(canonical)
        if not ids:
            # Reviewed source has no row — ensure provider file omits external_ids.
            if entry.external_ids:
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

        if entry.external_ids == ids and entry.canonical_model == canonical:
            unchanged += 1
            continue

        if args.dry_run:
            print(f"UPDATE {entry.rel_path}: {ids}")
            updated += 1
            continue

        if update_model_yaml_fields(
            entry.path,
            canonical_model=canonical if entry.canonical_model != canonical else None,
            external_ids=ids,
        ):
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
