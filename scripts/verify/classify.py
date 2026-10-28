"""kind:* from what changed. A change to `sources:` counts as nothing."""
from __future__ import annotations

from collections.abc import Iterable

from .model import ADDED, DELETED, FileReport
from .risk import FEATURES, LIFE, PRICE

NEW, PRICE_ONLY, LIFECYCLE, FEATURES_PARAMS, MIXED = "new-model", "price-only", "lifecycle", "features-params", "mixed"


def file_kind(f: FileReport) -> str | None:
    """None when nothing changed that matters (formatting, `sources:`)."""
    if not f.changed:
        return None
    if f.is_new and f.status == ADDED:
        return NEW
    if f.status == DELETED or f.is_new:  # a deletion, or a stub filled in: a human decides
        return MIXED
    groups = {r.group for r in f.risks}
    if not groups:
        return None
    if groups == {PRICE}:
        return PRICE_ONLY
    if groups == {LIFE}:
        return LIFECYCLE
    if groups == {FEATURES}:
        return FEATURES_PARAMS
    return MIXED


def pr_kind(files: Iterable[FileReport]) -> str | None:
    kinds = {k for k in map(file_kind, files) if k}
    if not kinds:
        return None
    return kinds.pop() if len(kinds) == 1 else MIXED
