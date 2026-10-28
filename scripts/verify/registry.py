"""Loader and validation for `sources/registry.yaml` (repo root): which provider has which source.

The core only runs adapters registered here for a provider. The registry never fails a PR: a bad
file raises RegistryError, which the CLI turns into a `verify:partial` run with a note.
"""
from __future__ import annotations

import datetime as _dt
import re
from dataclasses import dataclass
from pathlib import Path

import yaml

KINDS = ("api", "pricelist", "page")
# `price-report`: the adapter compares prices but they are REPORT-ONLY. Unlike `price` it does not make
# the provider price-owned for the sweep / agent, and `verify.propose` does not consult it.
FIELDS = ("price", "price-report", "limits", "features", "modalities", "lifecycle")
_PROVIDER = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
_SOURCE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_KEYS = {"provider", "kind", "source", "fields", "added"}


class RegistryError(ValueError):
    pass


@dataclass(frozen=True)
class Entry:
    provider: str
    kind: str
    source: str
    fields: tuple[str, ...]
    added: str


@dataclass(frozen=True)
class Registry:
    entries: tuple[Entry, ...] = ()

    def for_provider(self, provider: str) -> list[Entry]:
        return [e for e in self.entries if e.provider == provider]

    def source_names(self, providers: set[str] | None = None) -> set[str]:
        return {e.source for e in self.entries if providers is None or e.provider in providers}


def _date(value) -> str | None:
    if isinstance(value, _dt.datetime):
        return None
    if isinstance(value, _dt.date):
        return value.isoformat()
    if isinstance(value, str):
        try:
            return _dt.date.fromisoformat(value).isoformat()
        except ValueError:
            return None
    return None


def parse(data, providers_dir: Path | None = None) -> Registry:
    """Validate parsed YAML; every problem is listed in one RegistryError."""
    problems: list[str] = []
    if not isinstance(data, dict):
        raise RegistryError("registry must be a mapping with a `sources` list")
    for key in sorted(set(data) - {"version", "sources"}, key=str):
        problems.append(f"unknown top-level key {key!r}")
    if data.get("version", 1) != 1:
        problems.append("`version` must be 1")
    rows = data.get("sources")
    if not isinstance(rows, list):
        raise RegistryError("`sources` must be a list")
    entries: list[Entry] = []
    seen: set[tuple[str, str]] = set()
    for i, row in enumerate(rows):
        where = f"sources[{i}]"
        if not isinstance(row, dict):
            problems.append(f"{where}: must be a mapping")
            continue
        for key in sorted(set(row) - _KEYS, key=str):
            problems.append(f"{where}: unknown key {key!r}")
        for key in sorted(_KEYS - set(row)):
            problems.append(f"{where}: missing `{key}`")
        provider, kind, source, fields, added = (row.get(k) for k in ("provider", "kind", "source", "fields", "added"))
        if "provider" in row and not (isinstance(provider, str) and _PROVIDER.fullmatch(provider)):
            problems.append(f"{where}: bad provider {provider!r}")
        elif providers_dir is not None and isinstance(provider, str) and not (providers_dir / provider).is_dir():
            problems.append(f"{where}: providers/{provider} does not exist")
        if "kind" in row and kind not in KINDS:
            problems.append(f"{where}: kind must be one of {', '.join(KINDS)}")
        if "source" in row and not (isinstance(source, str) and _SOURCE.fullmatch(source)):
            problems.append(f"{where}: bad source name {source!r}")
        ok_fields = isinstance(fields, list) and bool(fields) and all(f in FIELDS for f in fields) \
            and len(set(fields)) == len(fields)
        if "fields" in row and not ok_fields:
            problems.append(f"{where}: fields must be a non-empty list of unique values from {', '.join(FIELDS)}")
        iso = _date(added)
        if "added" in row and iso is None:
            problems.append(f"{where}: `added` must be an ISO date")
        if isinstance(provider, str) and isinstance(source, str):
            if (provider, source) in seen:
                problems.append(f"{where}: duplicate ({provider}, {source})")
            seen.add((provider, source))
        if not problems and ok_fields and iso:
            entries.append(Entry(provider, kind, source, tuple(fields), iso))
    if problems:
        raise RegistryError("; ".join(problems))
    return Registry(tuple(entries))


def load(path: Path | str, providers_dir: Path | str | None = None) -> Registry:
    path = Path(path)
    try:
        data = yaml.safe_load(path.read_text())
    except OSError as e:
        raise RegistryError(f"cannot read {path}: {e.strerror}") from e
    except (yaml.YAMLError, ValueError) as e:  # ValueError: an unquoted impossible date such as 2026-13-45
        raise RegistryError(f"{path} is not valid YAML: {str(e).splitlines()[0][:120] if str(e) else type(e).__name__}") from e
    return parse(data, Path(providers_dir) if providers_dir else None)
