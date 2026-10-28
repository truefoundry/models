"""Fakes and builders shared by the tests. Offline, deterministic."""
from __future__ import annotations

import copy

from verify import yamlio
from verify.build import Runner, build_file
from verify.model import ADDED, MODIFIED
from verify.registry import Entry, Registry
from verify.types import Check, SourceResult

BASE_TEXT = """
model: m
mode: chat
costs:
  - region: "*"
    input_cost_per_token: 3e-6
    output_cost_per_token: 1.5e-5
features: [function_calling, prompt_caching]
limits:
  context_window: 200000
  max_tokens: 8192
modalities:
  input: [text, image]
  output: [text]
params:
  - key: reasoning_effort
    defaultValue: medium
    supportedValues: [low, medium, high]
status: active
supportedModes: [chat]
sources:
  - https://example.com/a
"""

IN = ("costs", "region=*", "input_cost_per_token")
OUT = ("costs", "region=*", "output_cost_per_token")


def base() -> dict:
    return yamlio.load(BASE_TEXT)


def mod(fn=None, **top) -> dict:
    """BASE with `fn(doc)` applied and top-level keys replaced (a None value deletes the key)."""
    doc = copy.deepcopy(base())
    if fn:
        fn(doc)
    for k, v in top.items():
        if v is None:
            doc.pop(k, None)
        else:
            doc[k] = v
    return doc


def price(**kw) -> dict:
    """BASE with fields of the first cost entry replaced."""
    doc = copy.deepcopy(base())
    doc["costs"][0].update(kw)
    return doc


def check(locator, status="verified", fv=1.0, sv=1.0) -> Check:
    return Check(tuple(locator), fv, sv if status == "verified" else sv * 2, status)


def result(*checks, source="fake", uncovered=(), partial=False, promo=None, notes=()) -> SourceResult:
    return SourceResult(source=source, checks=list(checks), uncovered=list(uncovered), partial=partial,
                        promo=promo, notes=list(notes))


class FakeSource:
    def __init__(self, name="fake", providers=("p",), res=None, prepare_error=None, check_error=None):
        self.name = name
        self.providers = providers
        self.res = res
        self.prepare_error = prepare_error
        self.check_error = check_error
        self.prepared = 0
        self.checked: list[str] = []

    def covers(self, provider):
        return provider in self.providers

    def prepare(self):
        self.prepared += 1
        if self.prepare_error:
            raise self.prepare_error

    def check(self, repo_path, doc):
        self.checked.append(repo_path)
        if self.check_error:
            raise self.check_error
        return self.res(repo_path, doc) if callable(self.res) else self.res


def registry(*pairs) -> Registry:
    """registry(("p", "fake"), ...)"""
    return Registry(tuple(Entry(p, "api", s, ("price",), "2026-10-27") for p, s in pairs))


def runner(source=None, *, provider="p", name="fake") -> Runner:
    if source is None:
        return Runner(Registry(), {})
    return Runner(registry((provider, name)), {name: source})


def report_for(before, after, source=None, *, status=MODIFIED, path="providers/p/m.yaml"):
    """A FileReport for two docs, run through the real build path."""
    import yaml
    dump = lambda d: None if d is None else yaml.safe_dump(d, sort_keys=True)  # noqa: E731
    return build_file(path, status, None if status == ADDED else dump(before), dump(after), runner(source))
