#!/usr/bin/env python3
"""Validate canonical_model and external_ids across provider YAML files."""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict

from model_identity_lib import (
    is_valid_canonical,
    is_valid_uuid,
    load_exceptions,
    load_language_models,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    args = parser.parse_args()
    del args

    exceptions = load_exceptions()
    entries = load_language_models()
    errors: list[str] = []

    groups: dict[str, list] = defaultdict(list)

    for entry in entries:
        if entry.rel_path in exceptions:
            if entry.canonical_model:
                errors.append(
                    f"{entry.rel_path}: exception path must omit canonical_model "
                    f"(has {entry.canonical_model!r})"
                )
            if entry.external_ids:
                errors.append(f"{entry.rel_path}: exception path must omit external_ids")
            continue

        if not entry.canonical_model:
            errors.append(
                f"{entry.rel_path}: chat/completion model missing canonical_model "
                f"(model={entry.model!r})"
            )
            continue

        if not is_valid_canonical(entry.canonical_model):
            errors.append(
                f"{entry.rel_path}: invalid canonical_model {entry.canonical_model!r} "
                f"(expected <creator>/<foundation-model>, lowercase)"
            )

        if entry.external_ids and not entry.canonical_model:
            errors.append(f"{entry.rel_path}: external_ids present without canonical_model")

        if entry.external_ids:
            slug = entry.external_ids.get("artificial_analysis_slug")
            aa_id = entry.external_ids.get("artificial_analysis_id")
            if not slug or not str(slug).strip():
                errors.append(f"{entry.rel_path}: artificial_analysis_slug must be non-empty")
            if not aa_id or not is_valid_uuid(str(aa_id)):
                errors.append(
                    f"{entry.rel_path}: artificial_analysis_id must be a UUID (got {aa_id!r})"
                )

        groups[entry.canonical_model].append(entry)

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
            detail = ", ".join(
                f"{m.rel_path}={m.external_ids!r}" for m in members
            )
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
        f"{len(groups)} canonical groups, {len(exceptions)} exceptions"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
