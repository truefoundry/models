#!/usr/bin/env python3
"""Validate optional canonical_model and external_ids across provider YAML files."""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict

from model_identity_lib import (
    is_valid_canonical,
    is_valid_uuid,
    load_language_models,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    args = parser.parse_args()
    del args

    entries = load_language_models()
    errors: list[str] = []
    groups: dict[str, list] = defaultdict(list)
    with_canonical = 0
    with_external = 0

    for entry in entries:
        if entry.external_ids and not entry.canonical_model:
            errors.append(f"{entry.rel_path}: external_ids present without canonical_model")

        if entry.canonical_model:
            with_canonical += 1
            if not is_valid_canonical(entry.canonical_model):
                errors.append(
                    f"{entry.rel_path}: invalid canonical_model {entry.canonical_model!r} "
                    f"(expected <creator>/<foundation-model>, lowercase)"
                )
            groups[entry.canonical_model].append(entry)

        if entry.external_ids:
            with_external += 1
            slug = entry.external_ids.get("artificial_analysis_slug")
            aa_id = entry.external_ids.get("artificial_analysis_id")
            if not slug or not str(slug).strip():
                errors.append(f"{entry.rel_path}: artificial_analysis_slug must be non-empty")
            if not aa_id or not is_valid_uuid(str(aa_id)):
                errors.append(
                    f"{entry.rel_path}: artificial_analysis_id must be a UUID (got {aa_id!r})"
                )

    for canonical, members in sorted(groups.items()):
        serialized = []
        for member in members:
            ext = member.external_ids
            if ext is None:
                serialized.append(None)
            else:
                serialized.append(
                    (
                        ext.get("artificial_analysis_slug"),
                        ext.get("artificial_analysis_id"),
                    )
                )
        if len(set(serialized)) > 1:
            detail = ", ".join(f"{m.rel_path}={m.external_ids!r}" for m in members)
            errors.append(
                f"canonical group {canonical!r} has inconsistent external_ids: {detail}"
            )

    if errors:
        print(f"Identity check FAILED ({len(errors)} issues):", file=sys.stderr)
        for err in errors[:200]:
            print(f"  - {err}", file=sys.stderr)
        if len(errors) > 200:
            print(f"  ... and {len(errors) - 200} more", file=sys.stderr)
        return 1

    print(
        f"Identity check passed: {len(entries)} language models, "
        f"{with_canonical} with canonical_model, {len(groups)} canonical groups, "
        f"{with_external} with external_ids"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
