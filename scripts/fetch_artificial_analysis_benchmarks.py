#!/usr/bin/env python3
"""Fetch Artificial Analysis metrics and mirror matched provider model files."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

import yaml

from model_identity_lib import (
    PROVIDERS_DIR,
    REPO_ROOT,
    fetch_aa_language_models,
    load_language_models,
    match_aa_for_canonical,
    propose_canonical,
)

BENCHMARKS_DIR = REPO_ROOT / "benchmarks"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Mirror provider model paths under benchmarks/ for models found in "
            "the Artificial Analysis language-model catalog."
        )
    )
    parser.add_argument(
        "--catalog",
        type=Path,
        help="Read an AA data[] array or raw model array from a local JSON file.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=BENCHMARKS_DIR,
        help="Output directory (default: benchmarks/).",
    )
    return parser.parse_args()


def load_catalog(path: Path | None) -> list[dict[str, Any]]:
    if path is None:
        return fetch_aa_language_models()
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("data") if isinstance(payload, dict) else payload
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise ValueError("Catalog must be a JSON model array or an object with data[]")
    return rows


def index_catalog(
    rows: list[dict[str, Any]],
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    by_id: dict[str, dict[str, Any]] = {}
    by_slug: dict[str, dict[str, Any]] = {}
    for row in rows:
        aa_id = row.get("id")
        slug = row.get("slug")
        if not isinstance(aa_id, str) or not isinstance(slug, str):
            raise ValueError("Every AA catalog row must have string id and slug values")
        if aa_id in by_id:
            raise ValueError(f"Duplicate AA id in catalog: {aa_id}")
        if slug in by_slug:
            raise ValueError(f"Duplicate AA slug in catalog: {slug}")
        by_id[aa_id] = row
        by_slug[slug] = row
    return by_id, by_slug


def row_for_external_ids(
    external_ids: dict[str, str],
    by_id: dict[str, dict[str, Any]],
    by_slug: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    id_row = by_id.get(external_ids.get("artificial_analysis_id", ""))
    slug_row = by_slug.get(external_ids.get("artificial_analysis_slug", ""))
    if id_row is not None and slug_row is not None and id_row is not slug_row:
        raise ValueError(
            "Artificial Analysis id and slug resolve to different catalog models: "
            f"{external_ids}"
        )
    # IDs are stable when AA renames a slug, so prefer an ID-only match.
    return id_row or slug_row


def resolve_canonical_rows(
    rows: list[dict[str, Any]],
    by_id: dict[str, dict[str, Any]],
    by_slug: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    groups: dict[str, list[Any]] = defaultdict(list)
    for entry in load_language_models():
        if entry.canonical_model:
            groups[entry.canonical_model].append(entry)

    resolved: dict[str, dict[str, Any]] = {}
    for canonical, entries in groups.items():
        external_ids = next(
            (entry.external_ids for entry in entries if entry.external_ids),
            None,
        )
        row = (
            row_for_external_ids(external_ids, by_id, by_slug)
            if external_ids is not None
            else None
        )
        if row is None:
            _, match, _ = match_aa_for_canonical(canonical, rows)
            if match is not None:
                row = by_id[match["artificial_analysis_id"]]
        if row is not None:
            resolved[canonical] = row
    return resolved


def benchmark_document(entry: Any, row: dict[str, Any]) -> dict[str, Any]:
    evaluations = row.get("evaluations")
    if not isinstance(evaluations, dict):
        evaluations = {}
    return {
        "model": entry.model,
        "artificial_analysis_id": row["id"],
        "artificial_analysis_slug": row["slug"],
        "metrics": dict(sorted(evaluations.items())),
    }


def write_benchmarks(
    rows: list[dict[str, Any]],
    output_dir: Path,
) -> tuple[int, int, int]:
    by_id, by_slug = index_catalog(rows)
    canonical_rows = resolve_canonical_rows(rows, by_id, by_slug)
    entries = load_language_models()

    documents: dict[Path, dict[str, Any]] = {}
    matched_models: set[str] = set()
    for entry in entries:
        row = canonical_rows.get(entry.canonical_model or "")
        identity = entry.canonical_model
        if row is None and entry.canonical_model is None:
            proposal = propose_canonical(entry.provider, entry.model, entry.path)
            if proposal.proposed_canonical:
                _, match, _ = match_aa_for_canonical(
                    proposal.proposed_canonical,
                    rows,
                )
                if match is not None:
                    row = by_id[match["artificial_analysis_id"]]
                    identity = proposal.proposed_canonical
        if row is None:
            continue

        relative_path = entry.path.relative_to(PROVIDERS_DIR)
        documents[relative_path] = benchmark_document(entry, row)
        matched_models.add(identity or entry.model)

    if output_dir.exists():
        for path in output_dir.rglob("*.yaml"):
            path.unlink()
        for path in sorted(output_dir.rglob("*"), reverse=True):
            if path.is_dir() and not any(path.iterdir()):
                path.rmdir()
    for relative_path, document in sorted(documents.items()):
        destination = output_dir / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            yaml.safe_dump(
                document,
                sort_keys=False,
                allow_unicode=True,
                width=256,
                indent=4,
            ),
            encoding="utf-8",
        )

    models_with_metrics = {
        document["artificial_analysis_id"]
        for document in documents.values()
        if any(value is not None for value in document["metrics"].values())
    }

    return len(documents), len(matched_models), len(models_with_metrics)


def main() -> int:
    args = parse_args()
    rows = load_catalog(args.catalog)
    files, models, models_with_metrics = write_benchmarks(
        rows,
        args.output_dir.resolve(),
    )
    print(
        f"Wrote {files} benchmark files for {models} matched models "
        f"({models_with_metrics} with at least one non-null metric) "
        f"from {len(rows)} Artificial Analysis catalog rows."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
