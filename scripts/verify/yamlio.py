"""YAML loading that reads `2e-6` as a number, as YAML 1.2 (and the models repo's tooling) does.

PyYAML follows YAML 1.1, where a float needs a dot, so `2e-6` would load as a string and a pure
reformat would look like a price change.
"""
from __future__ import annotations

import re

import yaml


class _Refused(Exception):
    pass


class _Loader(yaml.SafeLoader):
    """SafeLoader that refuses what a small hostile file needs: anchors / aliases (and so merge
    keys), too many nodes, too deep. Checked while composing, so one pass."""
    max_nodes = 200_000
    max_depth = 60

    def __init__(self, stream):
        super().__init__(stream)
        self.nodes = self.depth = 0

    def compose_node(self, parent, index):
        ev = self.peek_event()
        if getattr(ev, "anchor", None):  # an anchor, or the name an alias points at
            raise _Refused("YAML anchors and aliases are not allowed")
        self.nodes += 1
        if self.nodes > self.max_nodes:
            raise _Refused("YAML has too many nodes")
        self.depth += 1
        try:
            if self.depth > self.max_depth:
                raise _Refused("YAML is nested too deeply")
            return super().compose_node(parent, index)
        finally:
            self.depth -= 1


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


MAX_TEXT = 2_000_000  # bytes of YAML per file
MAX_NODES = 200_000
MAX_DEPTH = 60


def _surrogates(value, budget: list[int]) -> bool:
    budget[0] -= 1
    if budget[0] < 0:
        return True
    if isinstance(value, str):
        return any("\ud800" <= ch <= "\udfff" for ch in value)
    if isinstance(value, dict):
        return any(_surrogates(k, budget) or _surrogates(v, budget) for k, v in value.items())
    if isinstance(value, list):
        return any(_surrogates(v, budget) for v in value)
    return False


def parse(text: str | None) -> tuple[dict | None, str | None]:
    """PR-controlled YAML is untrusted data. Returns (mapping, None) or (None, why).
    Refused: over MAX_TEXT, lone surrogates, anchors / aliases / merge keys (the catalog uses
    none; they are how a small file expands into a huge one), more than MAX_NODES nodes or
    MAX_DEPTH nesting, YAML errors, and anything that is not a mapping. Empty text is (None, None)."""
    if not text or not text.strip():
        return None, None
    if len(text) > MAX_TEXT:
        return None, "file is larger than 2 MB"
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        return None, "file contains a lone surrogate"
    loader = _Loader(text)
    loader.max_nodes, loader.max_depth = MAX_NODES, MAX_DEPTH
    try:
        doc = loader.get_single_data()
    except _Refused as e:
        return None, str(e)
    except (yaml.YAMLError, RecursionError, ValueError):
        return None, "not valid YAML"
    finally:
        loader.dispose()
    if not isinstance(doc, dict):
        return None, "not a YAML mapping"
    if _surrogates(doc, [MAX_NODES + 1]):
        return None, "file contains a lone surrogate"
    return doc, None


def load(text: str | None) -> dict | None:
    """The parsed mapping, or None (see `parse`)."""
    return parse(text)[0]
