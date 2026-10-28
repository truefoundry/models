#!/usr/bin/env python3
"""Validate rejected.yaml, the list of model ids the addition job must never open a PR for.

Same schema as models-agent's addition/job/utils/rejected.py (the job reads this file from its
clone of this repo; a malformed file stops the job and alerts Slack). Run here so a bad list is
caught in the PR that introduces it:

    python3 scripts/validate_rejected.py [path]        # default: rejected.yaml at the repo root

    - id: openrouter/vendor/some-model   # "<provider>/<model id>", exact and case-sensitive
      reason: bogus                      # not-released | bogus | duplicate | promo | other
      who: caio
      date: 2026-10-27                   # YYYY-MM-DD
      note: closed #4321 by hand         # optional; empty or a scalar like `no` / `12` is fine

`[]` means nothing is rejected. An empty file is an error (a truncated file must not read as an
empty list). An exact repeat of an entry (same id and reason) is a warning; the same id with a
different reason is an error. A provider with no folder under providers/ is a warning: it is
usually a typo, but a model can be rejected before its provider has one.

Exit 0 when valid, 1 when not (errors on stderr), 2 on bad usage. Needs PyYAML.
"""
from __future__ import annotations

import datetime
import re
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PATH = REPO_ROOT / "rejected.yaml"
REASONS = ("not-released", "bogus", "duplicate", "promo", "other")
_REQUIRED = ("id", "reason", "who", "date")
_ALLOWED = frozenset((*_REQUIRED, "note"))
_ID = re.compile(r"^[^/\s]+/\S+$")  # "<provider>/<model id>", no whitespace; the id may hold "/"
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_NOTE_TYPES = (str, int, float, bool, type(None))


def _real_date(value: object) -> bool:
    # An unquoted 2026-10-27 is a date to YAML; a quoted one is a string. A datetime is not a day.
    if isinstance(value, datetime.datetime):
        return False
    if isinstance(value, datetime.date):
        return True
    if isinstance(value, str) and _DATE.fullmatch(value):
        try:
            datetime.date.fromisoformat(value)
        except ValueError:
            return False
        return True
    return False


def validate(data: object, providers_dir: Path | None = None) -> tuple[list[str], list[str]]:
    """(errors, warnings) for a parsed rejected.yaml."""
    if not isinstance(data, list):
        return [f"top level must be a list of entries, got {type(data).__name__}"], []
    errors: list[str] = []
    warnings: list[str] = []
    first_at: dict[str, int] = {}
    reason_of: dict[str, object] = {}
    for n, entry in enumerate(data, 1):
        where = f"entry {n}"
        if not isinstance(entry, dict):
            errors.append(f"{where}: must be a mapping, got {type(entry).__name__}")
            continue
        for key in _REQUIRED:
            if key not in entry:
                errors.append(f"{where}: missing `{key}`")
        for key in sorted(set(entry) - _ALLOWED, key=str):
            errors.append(f"{where}: unknown key `{key}`")
        if "id" in entry:
            rid = entry["id"]
            if not isinstance(rid, str) or not _ID.fullmatch(rid):
                errors.append(f"{where}: `id` must be \"<provider>/<model id>\" without whitespace, got {rid!r}")
            elif rid in first_at:
                if entry.get("reason") == reason_of[rid]:
                    warnings.append(f"{where}: `{rid}` repeats entry {first_at[rid]} (same reason); the repeat is ignored")
                else:
                    errors.append(
                        f"{where}: duplicate id `{rid}` with a different reason "
                        f"({reason_of[rid]!r} at entry {first_at[rid]}, {entry.get('reason')!r} here)"
                    )
            else:
                first_at[rid] = n
                reason_of[rid] = entry.get("reason")
                provider = rid.split("/", 1)[0]
                if providers_dir is not None and not (providers_dir / provider).is_dir():
                    warnings.append(f"{where}: no folder providers/{provider}/ for `{rid}` (typo?)")
        if "reason" in entry and entry["reason"] not in REASONS:
            errors.append(f"{where}: `reason` must be one of {', '.join(REASONS)}, got {entry['reason']!r}")
        if "who" in entry and not (isinstance(entry["who"], str) and entry["who"].strip()):
            errors.append(f"{where}: `who` must be a non-empty string")
        if "date" in entry and not _real_date(entry["date"]):
            errors.append(f"{where}: `date` must be a real YYYY-MM-DD date, got {entry['date']!r}")
        if "note" in entry and not isinstance(entry["note"], _NOTE_TYPES):
            errors.append(f"{where}: `note` must be text, got {type(entry['note']).__name__}")
    return errors, warnings


def check_file(path: Path, providers_dir: Path | None = None) -> tuple[list[str], list[str]]:
    """(errors, warnings) for the file at `path`; an unreadable or unparsable file is an error."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        return [f"{path.name} cannot be read: {e}"], []
    try:
        data = yaml.safe_load(text)
    except (yaml.YAMLError, ValueError) as e:  # ValueError: an unquoted impossible date such as 2026-13-45
        return [f"{path.name} is not valid YAML: {e}"], []
    return validate(data, providers_dir)


def main(argv: list[str]) -> int:
    if len(argv) > 2:
        print("usage: validate_rejected.py [path]", file=sys.stderr)
        return 2
    path = Path(argv[1]) if len(argv) == 2 else DEFAULT_PATH
    errors, warnings = check_file(path, REPO_ROOT / "providers")
    for warning in warnings:
        print(f"WARNING: {warning}")
    for error in errors:
        print(f"ERROR: {error}", file=sys.stderr)
    if errors:
        print(f"{path.name}: {len(errors)} problem(s)", file=sys.stderr)
        return 1
    print(f"{path.name}: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
