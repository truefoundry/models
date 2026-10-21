#!/usr/bin/env python3
"""Verify Artificial Analysis external_ids on provider YAML files changed in a PR.

Compares the working tree against a git base ref, and for every changed model
file that declares external_ids, checks that the id/slug pair exists in the
Artificial Analysis catalog.

Requires AA_API_KEY unless --aa-cache is provided.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from model_identity_lib import (
    REPO_ROOT,
    SKIP_FILENAMES,
    fetch_aa_language_models,
    is_valid_uuid,
    load_model_entry,
)


def git_changed_provider_files(base: str) -> list[Path]:
    cmd = [
        "git",
        "diff",
        "--name-only",
        "--diff-filter=ACMR",
        f"{base}...HEAD",
        "--",
        "providers",
    ]
    result = subprocess.run(
        cmd,
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    paths: list[Path] = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line.endswith(".yaml"):
            continue
        path = REPO_ROOT / line
        if path.name in SKIP_FILENAMES:
            continue
        if path.is_file():
            paths.append(path)
    return sorted(paths)


def index_aa_by_id(models: list[dict]) -> dict[str, dict]:
    by_id: dict[str, dict] = {}
    for row in models:
        aa_id = str(row.get("id") or "")
        if aa_id:
            by_id[aa_id] = row
    return by_id


def verify_entries(
    paths: list[Path],
    aa_by_id: dict[str, dict],
) -> tuple[list[str], int]:
    errors: list[str] = []
    checked = 0
    for path in paths:
        entry = load_model_entry(path)
        if entry is None or not entry.external_ids:
            continue
        checked += 1
        slug = str(entry.external_ids.get("artificial_analysis_slug") or "").strip()
        aa_id = str(entry.external_ids.get("artificial_analysis_id") or "").strip()
        rel = entry.rel_path

        if not slug:
            errors.append(f"{rel}: artificial_analysis_slug is empty")
            continue
        if not is_valid_uuid(aa_id):
            errors.append(f"{rel}: artificial_analysis_id is not a UUID ({aa_id!r})")
            continue

        row = aa_by_id.get(aa_id)
        if row is None:
            errors.append(
                f"{rel}: artificial_analysis_id {aa_id} not found in Artificial Analysis catalog"
            )
            continue

        catalog_slug = str(row.get("slug") or "")
        if catalog_slug != slug:
            errors.append(
                f"{rel}: slug mismatch for id {aa_id}: yaml has {slug!r}, "
                f"Artificial Analysis has {catalog_slug!r}"
            )

        if not entry.canonical_model:
            errors.append(f"{rel}: external_ids present without canonical_model")

    return errors, checked


def resolve_base_ref(base: str) -> str:
    if base.startswith("origin/") or base.startswith("refs/") or len(base) >= 40:
        return base
    return f"origin/{base}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base",
        default=os.environ.get("GITHUB_BASE_REF") or "origin/main",
        help="Git base ref to diff against (default: GITHUB_BASE_REF or origin/main)",
    )
    parser.add_argument(
        "--aa-cache",
        type=Path,
        default=None,
        help="Optional JSON cache of AA models (skips network)",
    )
    parser.add_argument(
        "--files",
        nargs="*",
        default=None,
        help="Explicit file list (skips git diff). Paths relative to repo root.",
    )
    args = parser.parse_args()

    if args.files is not None:
        paths = [REPO_ROOT / f for f in args.files]
        paths = [p for p in paths if p.is_file() and p.name not in SKIP_FILENAMES]
    else:
        base = resolve_base_ref(args.base)
        try:
            paths = git_changed_provider_files(base)
        except subprocess.CalledProcessError as exc:
            print(f"ERROR: git diff failed: {exc.stderr or exc}", file=sys.stderr)
            return 2

    with_ids = []
    for path in paths:
        entry = load_model_entry(path)
        if entry and entry.external_ids:
            with_ids.append(path)

    if not with_ids:
        print(
            f"No changed provider models with external_ids "
            f"({len(paths)} changed provider YAML files). Skipping AA API check."
        )
        return 0

    if args.aa_cache and args.aa_cache.exists():
        aa_models = json.loads(args.aa_cache.read_text(encoding="utf-8"))
    else:
        if not os.environ.get("AA_API_KEY"):
            print(
                "ERROR: AA_API_KEY is required to verify external_ids on changed files. "
                "Set the repository secret AA_API_KEY, or pass --aa-cache.",
                file=sys.stderr,
            )
            return 2
        try:
            aa_models = fetch_aa_language_models()
        except RuntimeError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 2

    aa_by_id = index_aa_by_id(aa_models)
    errors, checked = verify_entries(with_ids, aa_by_id)

    if errors:
        print(f"AA external_id verification FAILED ({len(errors)} issues):", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1

    print(
        f"AA external_id verification passed: checked {checked} changed model file(s) "
        f"against {len(aa_by_id)} Artificial Analysis rows"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
