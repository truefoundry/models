"""PR-controlled input is data: YAML limits and text hygiene."""
import pytest

from verify import build, yamlio
from verify.model import ADDED, MODIFIED
from verify.textclean import cap, clean_block, clean_line, has_surrogate, neutralise_mentions, safe_markdown

from .helpers import base, runner


@pytest.mark.parametrize("text,why", [
    ("a: &x 1\nb: *x\n", "anchors"),
    ("a: &x {k: 1}\nb:\n  <<: *x\n", "anchors"),            # merge key through an alias
    ("a: &x 1\n", "anchors"),                                # an anchor alone
    ("a: !!python/object/apply:os.system [x]\n", "valid"),   # not a safe tag
    ("a: [\n", "valid"),
    ("- a\n- b\n", "mapping"),
    ("just a string\n", "mapping"),
    ("a: \"\\ud800\"\n", "surrogate"),                       # lone surrogate through an escape
    ("a:\n  - \"\\udfff\"\n", "surrogate"),
    ("\"\\ud800\": 1\n", "surrogate"),                       # ... as a key
])
def test_untrusted_yaml_is_refused(text, why):
    doc, reason = yamlio.parse(text)
    assert doc is None and why in reason
    assert yamlio.load(text) is None


def test_a_raw_lone_surrogate_in_the_text_is_refused():
    doc, reason = yamlio.parse("a: \ud800\n")
    assert doc is None and "surrogate" in reason


def test_size_node_and_depth_limits(monkeypatch):
    big = "a: " + "x" * (yamlio.MAX_TEXT + 1)
    assert yamlio.parse(big) == (None, "file is larger than 2 MB")
    assert yamlio.parse("a: " + "x" * 1000)[0] == {"a": "x" * 1000}
    many = "".join(f"k{i}: 1\n" for i in range(yamlio.MAX_NODES // 2 + 10))
    doc, reason = yamlio.parse(many)
    assert doc is None and "too many nodes" in reason
    deep = "a: " + "[" * (yamlio.MAX_DEPTH + 5) + "]" * (yamlio.MAX_DEPTH + 5) + "\n"
    assert "deeply" in yamlio.parse(deep)[1]
    ok = "a: " + "[" * 10 + "]" * 10 + "\n"
    assert yamlio.parse(ok)[0] is not None
    monkeypatch.setattr(yamlio, "MAX_NODES", 5)
    assert "too many nodes" in yamlio.parse("a: 1\nb: 2\nc: 3\nd: 4\n")[1]


def test_empty_and_normal_documents():
    assert yamlio.parse(None) == (None, None) and yamlio.parse("  \n") == (None, None) and yamlio.parse("") == (None, None)
    assert yamlio.parse("a: 2e-6\nb: [1, 2]\n") == ({"a": 2e-6, "b": [1, 2]}, None)
    assert yamlio.load("a: ünïcode ✓\n") == {"a": "ünïcode ✓"}  # real unicode is fine


def test_an_unusable_file_is_a_check_error_that_says_why():
    for text, frag in (("a: &x 1\nb: *x\n", "anchors"), ("a: \"\\ud800\"\n", "surrogate"), ("- x\n", "mapping")):
        f = build.build_file("providers/p/m.yaml", ADDED, None, text, runner())
        assert f.loud and f.risks[0].label == "risk:check-error" and frag in f.risks[0].reason
        g = build.build_file("providers/p/m.yaml", MODIFIED, "model: m\nmode: chat\ncosts: []\n", text, runner())
        assert g.loud and frag in g.risks[0].reason
    h = build.build_file("providers/p/m.yaml", MODIFIED, "a: &x 1\nb: *x\n", "model: m\n", runner())
    assert h.loud and "previous version" in h.risks[0].reason and "anchors" in h.risks[0].reason


# ---- text hygiene -------------------------------------------------------------------------
@pytest.mark.parametrize("raw", ["a\rb", "a\x00b", "a\x07b", "a\u2028b", "a\u2029b", "a\x85b", "a\u202eb", "a\u200bb",
                                 "a\ud800b", "a\tb", "a\nb", "a  \r\n  b"])
def test_clean_line_collapses_whitespace_and_drops_control_and_format_characters(raw):
    out = clean_line(raw)
    assert out in ("a b", "ab") and "\n" not in out and "\r" not in out and not has_surrogate(out)


def test_clean_line_keeps_ordinary_text_and_strips_the_ends():
    assert clean_line("  hello  world  ") == "hello world" and clean_line("price: 1e-6 ✓") == "price: 1e-6 ✓"
    assert clean_line("") == "" and clean_line("\x00\x01") == ""


def test_clean_block_keeps_newlines_and_tabs_only():
    assert clean_block("a\r\nb\tc\x00\u202e\ud800d") == "a\nb\tcd"


def test_mentions_are_escaped_and_the_result_is_capped_afterwards():
    assert neutralise_mentions("@a @b") == "@\u200ba @\u200bb"
    out = safe_markdown("@" * 1000, 1500)
    assert len(out) <= 1500 and "@@" not in out
    body = "<!-- m -->\n" + "@" * 60_000
    out = safe_markdown(body, 60_000)
    assert len(out) <= 60_000 and out.startswith("<!-- m -->\n")  # the marker line survives the cap


def test_cap_handles_tiny_limits_and_never_exceeds():
    for limit in (0, 1, 5, 11, 12, 30):
        assert len(cap("x" * 500, limit)) <= limit
    assert cap("short", 10) == "short"


def test_untrusted_values_in_a_risk_reason_cannot_break_out():
    from verify.risk import assess
    from .helpers import mod
    after = mod(features=["function_calling", "evil\r\n@mallory\u202e`x`|y", "prompt_caching"])
    reasons = " ".join(r.reason for r in assess(base(), after))
    assert "\r" not in reasons and "\n" not in reasons and "\u202e" not in reasons and reasons.count("`") % 2 == 0
