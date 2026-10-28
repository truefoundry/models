"""YAML loading that reads `2e-6` as a number, as YAML 1.2 (and the models repo's tooling) does.

PyYAML follows YAML 1.1, where a float needs a dot, so `2e-6` would load as a string and a pure
reformat would look like a price change.
"""
from __future__ import annotations

import re

import yaml


class _Loader(yaml.SafeLoader):
    pass


_Loader.add_implicit_resolver(
    "tag:yaml.org,2002:float",
    re.compile(r"^[-+]?(?:\d+\.?\d*|\.\d+)[eE][-+]?\d+$"),
    list("-+0123456789."),
)


def normalized(value):
    """Floats rounded to 12 significant digits, so `3e-7` and `3e-7 + 1e-22` compare equal."""
    if isinstance(value, float):
        return float(f"{value:.12g}")
    if isinstance(value, dict):
        return {k: normalized(v) for k, v in value.items()}
    if isinstance(value, list):
        return [normalized(v) for v in value]
    return value


def load(text: str | None) -> dict | None:
    """The parsed mapping, or None for empty text, a YAML error or a non-mapping document."""
    if not text:
        return None
    try:
        doc = yaml.load(text, Loader=_Loader)  # noqa: S506 - SafeLoader subclass
    except (yaml.YAMLError, RecursionError, ValueError):
        return None
    return doc if isinstance(doc, dict) else None
