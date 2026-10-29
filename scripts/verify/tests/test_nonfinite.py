"""A non-finite file value ('1e999', .inf, nan) is never a price: same(inf, x) used to be True, so such a file
came out `verified`. Every adapter family goes through `_common.num` / `same`; the catalog has none."""
from __future__ import annotations

import math
from pathlib import Path

import pytest
import yaml

from verify.sources._common import num, same

from . import test_aws_price_list as aws
from . import test_deepinfra as di
from . import test_openrouter as orr
from .test_anthropic_pricing import OPUS55, opus55, source as anthropic_source

BAD = ["1e999", "-1e999", float("inf"), float("-inf"), float("nan"), "inf", "nan", ".inf"]


def test_num_and_same_reject_non_finite():
    for v in BAD:
        assert num(v) is None, v
    assert num("5e-9") == 5e-9
    for a, b in ((float("inf"), 1.0), (1.0, float("inf")), (float("inf"), float("inf")), (float("nan"), 1.0),
                 (float("nan"), float("nan"))):
        assert not same(a, b)
    assert not same(float("inf"), float("inf"), 1e9)


def _assert_not_verified(r, field):
    assert not r.fully_verified
    assert not [c for c in r.checks if c.locator[-1] == field], field
    assert any(u.endswith(field) for u in r.uncovered), (field, r.uncovered)


@pytest.mark.parametrize("bad", BAD)
def test_openrouter_deepinfra_aws_anthropic_never_verify_a_non_finite_price(bad):
    s, _ = orr.source()
    r = s.check(orr.STEP, orr.doc(**{**orr.STEP_OK, "input_cost_per_token": bad}))
    _assert_not_verified(r, "input_cost_per_token")
    s, _ = di.source()
    r = di.check(s, di.GLM, **{**di.GLM_LIST, "cache_read_input_token_cost": bad})
    _assert_not_verified(r, "cache_read_input_token_cost")
    s, _ = aws.source()
    r = s.check(*aws.cl("global.anthropic.claude-sonnet-4-5-20250929-v1:0", **{**aws.SONNET45_GLOBAL, "output_cost_per_token": bad}))
    _assert_not_verified(r, "output_cost_per_token")
    s, _ = anthropic_source()
    r = opus55(s, input_cost_per_token=bad)
    _assert_not_verified(r, "input_cost_per_token")


def test_no_catalog_file_holds_a_non_finite_number():
    root = Path(__file__).resolve().parents[3] / "providers"
    def walk(node, path):
        if isinstance(node, dict):
            for k, v in node.items():
                yield from walk(v, f"{path}.{k}")
        elif isinstance(node, list):
            for i, v in enumerate(node):
                yield from walk(v, f"{path}[{i}]")
        elif isinstance(node, float) and not math.isfinite(node):
            yield path
        elif isinstance(node, str) and node.strip().lower() in ("inf", "-inf", "+inf", ".inf", "nan", ".nan", "infinity"):
            yield path
        elif isinstance(node, str):
            try:
                if not math.isfinite(float(node)):
                    yield path
            except ValueError:
                pass
    bad = []
    for f in sorted(root.rglob("*.yaml")):
        bad += [f"{f.relative_to(root)}{p}" for p in walk(yaml.load(f.read_text(), Loader=getattr(yaml, "CSafeLoader", yaml.SafeLoader)), "")]
    assert bad == []
