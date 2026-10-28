import pytest

from verify import gates, report
from verify.labels import MARKER
from verify.model import FileReport
from verify.risk import Risk

from .helpers import IN, FakeSource, base, check, mod, price, report_for, result


def many_files(n, risks_each=30):
    files = []
    for i in range(n):
        risks = [Risk("risk:removal", f"feature `f{j}-{'x' * 200}` removed", True, "features-params", ("features", f"f{j}"))
                 for j in range(risks_each)]
        files.append(FileReport(f"providers/p/model-{i:05d}.yaml", "modified", False, risks, [r.locator for r in risks]))
    return files


def test_comment_is_capped_and_keeps_the_marker_even_for_huge_prs():
    files = many_files(800)
    v = gates.decide(files)
    text = report.render_comment(v, files)
    assert len(text) <= report.COMMENT_LIMIT < 65_536
    assert text.startswith(MARKER) and text.count(MARKER) == 1
    assert "more file(s) not shown" in text
    assert len(report.render_summary(v, files)) <= report.SUMMARY_LIMIT


def test_one_enormous_file_still_fits():
    files = many_files(1, 5000)
    text = report.render_comment(gates.decide(files), files)
    assert len(text) <= report.COMMENT_LIMIT and "more risk(s)" in text


def test_summary_is_fuller_than_the_comment():
    files = many_files(3, 40)
    v = gates.decide(files)
    assert len(report.render_summary(v, files)) > len(report.render_comment(v, files))
    assert report.render_summary(v, files).count("- **escalate** `risk:removal`") == 120


def test_cap_cuts_at_a_line_and_respects_limit():
    text = "\n".join(f"line {i}" for i in range(1000))
    out = report.cap(text, 500)
    assert len(out) <= 500 and out.endswith("…truncated") and "line 0" in out
    assert report.cap("short", 500) == "short"
    for limit in (40, 80, 999):
        assert len(report.cap(text, limit)) <= limit


def test_loud_files_come_first_and_verified_rows_follow():
    quiet = report_for(base(), price(input_cost_per_token=3.1e-6), FakeSource(res=result(check(IN))), path="providers/p/a.yaml")
    loud = report_for(base(), price(input_cost_per_token=9e-6), FakeSource(res=result(check(IN, "conflict"))), path="providers/p/z.yaml")
    text = report.render_comment(gates.decide([quiet, loud]), [quiet, loud])
    assert text.index("providers/p/z.yaml") < text.index("providers/p/a.yaml")
    assert "conflict" in text and "**escalate**" in text


def test_header_states_gate_kind_verify_and_shadow():
    f = report_for(base(), price(input_cost_per_token=3.1e-6), FakeSource(res=result(check(IN))))
    text = report.render_comment(gates.decide([f]), [f])
    assert "`gate:review`" in text and "`kind:price-only`" in text and "`verify:official`" in text and "`shadow:auto`" in text
    assert "report only" in text


def test_hold_is_explained():
    f = report_for(base(), price(input_cost_per_token=3.1e-6), None)
    v = gates.decide([f], ["gate:hold"])
    assert "gate:hold" in report.render_comment(v, [f], hold=True)


def test_nothing_to_verify_message():
    text = report.render_comment(gates.decide([]), [])
    assert text.startswith(MARKER) and "No model YAML" in text


def test_untrusted_text_cannot_break_out_of_code_spans_or_tables():
    nasty = "a`b|c\n@octocat <img src=x>"
    assert "\n" not in report.code(nasty) and "|" not in report.code(nasty) and report.code(nasty).count("`") == 2
    after = mod(lambda d: d["costs"].append({"region": nasty, "input_cost_per_token": 3e-6}))
    f = report_for(base(), after, FakeSource(res=result(check(("costs", f"region={nasty}", "input_cost_per_token")))),
                   path="providers/p/we`ird|path.yaml")
    text = report.render_comment(gates.decide([f]), [f])
    for line in text.splitlines():
        if line.startswith("|"):
            assert line.count("|") == 6  # 5 columns, no injected pipe
    assert "@octocat" not in text.replace("`", "") or "`" in text  # only ever inside code spans


def test_notes_are_shown_as_code_and_limited():
    f = report_for(base(), price(input_cost_per_token=3.1e-6), None)
    text = report.render_comment(gates.decide([f]), [f], notes=[f"n{i}" for i in range(100)])
    assert text.count("> `n") == report.MAX_NOTES


def test_file_json_shape():
    f = report_for(base(), price(input_cost_per_token=3.1e-6), FakeSource(res=result(check(IN), notes=["hi"])))
    j = report.file_json(f)
    assert j["source_state"] == "official" and j["fully_verified"] and j["risks"][0]["covered"] is True
    assert j["checks"][0]["locator"] == list(IN) and j["notes"] == ["hi"]


def test_the_footer_and_the_omitted_note_survive_when_files_do_not_fit():
    files = many_files(800)
    text = report.render_comment(gates.decide(files), files)
    assert text.endswith(report.FOOTER)                       # the tail is reserved, not cut off by cap()
    assert "more file(s) not shown" in text and len(text) <= report.COMMENT_LIMIT
    summary = report.render_summary(gates.decide(files), files)
    assert summary.endswith(report.FOOTER) and "more file(s) not shown" in summary


def test_blocks_fill_up_to_the_budget_but_never_into_the_reserved_tail():
    files = many_files(800, risks_each=2)
    v = gates.decide(files)
    text = report.render_comment(v, files)
    body_end = text.rindex("\n\n…")                           # where the omitted note starts
    assert body_end <= report.COMMENT_LIMIT - report.RESERVED_TAIL + 2
    assert len(text) - body_end <= report.RESERVED_TAIL


def test_cap_is_the_last_line_of_defence_when_even_the_header_is_too_long(monkeypatch):
    monkeypatch.setattr(report, "COMMENT_LIMIT", 900)
    files = many_files(3, risks_each=2)
    notes = [f"note {i} " + "x" * 280 for i in range(report.MAX_NOTES)]
    text = report.render_comment(gates.decide(files), files, notes=notes)
    assert len(text) <= 900 and text.startswith(MARKER)
    monkeypatch.setattr(report, "SUMMARY_LIMIT", 700)
    assert len(report.render_summary(gates.decide(files), files, notes=notes)) <= 700


def test_the_comment_limit_is_below_githubs_and_leaves_room_for_the_label_jobs_escaping():
    assert report.COMMENT_LIMIT == 60_000 and report.SUMMARY_LIMIT == 60_000
    assert report.RESERVED_TAIL >= len(report.FOOTER) + 300


def test_comment_stays_within_the_limit_for_many_block_sizes():
    for risks in (1, 3, 7, 12, 30):
        files = many_files(300, risks_each=risks)
        text = report.render_comment(gates.decide(files), files)
        assert len(text) <= report.COMMENT_LIMIT and text.endswith(report.FOOTER)


@pytest.mark.parametrize("raw", ["a\rb", "a\x00b", "a\u2028b", "a\u202eb", "a\ud800b", "a\nb", "a`b", "a|b"])
def test_code_spans_never_carry_control_characters_backticks_or_pipes(raw):
    out = report.code(raw)
    assert out.startswith("`") and out.endswith("`") and out.count("`") == 2 and "|" not in out
    assert not any(ch in out for ch in ("\r", "\n", "\x00", "\u2028", "\u202e", "\ud800"))


def test_existing_drift_is_listed_separately_and_counted_apart_from_conflicts():
    from .helpers import OUT
    f = report_for(base(), price(input_cost_per_token=3.1e-6), FakeSource(res=result(check(IN), check(OUT, "conflict"))))
    v = gates.decide([f])
    text = report.render_comment(v, [f])
    assert "Existing drift (not from this PR): 1 field(s) in 1 file(s)" in text
    assert "existing drift (not from this PR): 1 field(s) in untouched fields" in text
    assert "· 0 conflict(s) · report only" in text and "drift (not this PR)" in text and "| conflict |" not in text
    assert "1 existing drift" in text
    own = report_for(base(), price(input_cost_per_token=3.1e-6), FakeSource(res=result(check(IN, "conflict"))))
    t2 = report.render_comment(gates.decide([own]), [own])
    assert "· 1 conflict(s) · report only" in t2 and "| conflict |" in t2 and "Existing drift" not in t2
    j = report.file_json(f)
    assert j["source_state"] == "partial" and j["fully_verified"] is True


# ---- review lane line -----------------------------------------------------------------------------
from verify.model import FileReport as _FR  # noqa: E402
from verify.risk import FEATURES as _FEATURES, Risk as _Risk  # noqa: E402


def _lane_text(files, current=()):
    v = gates.decide(files, current)
    return report.render_comment(v, files, hold=v.gate == "hold"), v


def _lane_lines(text):
    """The `Review lane` heading and the bullet lines under it."""
    out = text.split("\n\n")
    block = next(b for b in out if b.startswith("**Review lane"))
    return block.split("\n")


def test_fast_lane_header_says_so_in_three_short_lines():
    f = report_for(base(), mod(features=["function_calling", "prompt_caching", "json_output"]), None)
    text, v = _lane_text([f])
    lines = _lane_lines(text)
    assert lines[0] == "**Review lane: fast-lane**" and v.lane == "fast-lane"
    assert len(lines) == 4 and all(x.startswith("- ") for x in lines[1:])
    assert "kind:features-params" in lines[1] and "1 model file(s)" in lines[1]
    assert "no escalating risk" in lines[2] and "within 24 h" in lines[3]
    assert text.index("Review lane") < text.index("changed model file(s)")      # before the counts: seen first
    assert text.index("Review lane") > text.index("## Catalog verify")


def test_escalate_header_names_the_reasons_most_telling_first():
    conflict = report_for(base(), price(input_cost_per_token=3.1e-6), FakeSource(res=result(check(IN, "conflict"))), path="providers/p/a.yaml")
    removed = report_for(base(), mod(features=["function_calling"]), None, path="providers/p/b.yaml")
    text, _ = _lane_text([removed, conflict])
    lines = _lane_lines(text)
    assert lines[0] == "**Review lane: escalate**"
    assert "official source disagrees" in lines[1] and "providers/p/a.yaml" in lines[1]
    assert "risk:removal" in lines[2] and "providers/p/b.yaml" in lines[2]


def test_a_flood_of_escalations_still_fits_in_three_lines_and_says_how_many_more():
    files = many_files(5, 3)
    risks = [_Risk(f"risk:{k}", f"{k} thing", True, _FEATURES, ("x", k)) for k in ("removal", "params", "limit", "mode", "dated")]
    files[0].risks += risks
    text, v = _lane_text(files)
    lines = _lane_lines(text)
    assert report.LANE_REASONS == 3
    assert v.lane == "escalate" and len(lines) == 4
    assert lines[-1].startswith("- +") and "more finding(s)" in lines[-1]


def test_hold_lane_explains_hold_and_keeps_reporting_escalations():
    f = report_for(base(), mod(features=["function_calling"]), None)
    text, v = _lane_text([f], ["gate:hold"])
    lines = _lane_lines(text)
    assert lines[0] == "**Review lane: hold**" and "gate:hold" in lines[1] and "risk:removal" in lines[2]
    quiet = report_for(base(), mod(features=["function_calling", "prompt_caching", "json_output"]), None)
    assert "nothing in the diff would escalate" in "\n".join(_lane_lines(_lane_text([quiet], ["gate:hold"])[0]))


def test_normal_lane_says_why_it_is_not_fast_lane():
    f = report_for(base(), price(input_cost_per_token=3.1e-6), FakeSource(res=result(check(IN))))
    lines = _lane_lines(_lane_text([f])[0])
    assert lines[0] == "**Review lane: normal**"
    assert "`kind:price-only` is not a fast-lane kind" in lines[1]
    assert "every changed field verified" in lines[2] and "shadow:auto" in lines[3]
    many = [report_for(base(), mod(features=["function_calling", "prompt_caching", "json_output"]), None, path=f"providers/p/m{i:02d}.yaml") for i in range(11)]
    lines = _lane_lines(_lane_text(many)[0])
    assert lines[0] == "**Review lane: normal**" and "11 changed model files" in lines[1] and "10" in lines[1]
    unverified = report_for(base(), price(input_cost_per_token=3.1e-6), None)
    assert "no verified source check" in "\n".join(_lane_lines(_lane_text([unverified])[0]))


def test_no_lane_line_when_nothing_changed():
    text = report.render_comment(gates.decide([]), [])
    assert "Review lane" not in text


def test_lane_lines_are_short_and_cannot_break_out_of_a_code_span():
    nasty = "a`b\n@octocat " + "x" * 400
    f = _FR("providers/p/m.yaml", "modified", False, [_Risk("risk:removal", f"feature `{nasty}` removed", True, _FEATURES, ("features", "x"))], [("features", "x")])
    lines = _lane_lines(_lane_text([f])[0])
    assert all("\n" not in x and len(x) <= report.LANE_LINE + 3 for x in lines)
    assert all(x.count("`") % 2 == 0 for x in lines)


def test_the_lane_line_is_in_the_full_summary_and_the_comment_stays_under_the_cap():
    files = many_files(800)
    v = gates.decide(files)
    assert "Review lane: escalate" in report.render_summary(v, files)
    assert len(report.render_comment(v, files)) <= report.COMMENT_LIMIT


def test_escalate_lane_names_the_addition_flags_first():
    f = report_for(base(), price(input_cost_per_token=3.1e-6), None)
    text, v = _lane_text([f], ["id:case-duplicate", "id:high-edit-provider"])
    lines = _lane_lines(text)
    assert lines[0] == "**Review lane: escalate**"
    assert lines[1].endswith("addition flagged: case duplicate of an existing file")
    assert lines[2].endswith("provider has a high human-edit rate and no source price was written")
    assert v.gate == "escalate"


def test_the_hold_line_names_gate_hold_only():
    text, _ = _lane_text([report_for(base(), mod(features=["function_calling"]), None)], ["gate:hold"])
    assert "`gate:hold` is on the PR" in text and "id:*" not in text


def test_an_addition_flag_is_named_before_the_diffs_own_escalations():
    f = report_for(base(), mod(features=["function_calling"]), None)          # a removal: escalates by itself
    text, v = _lane_text([f], ["id:case-duplicate"])
    lines = _lane_lines(text)
    assert lines[1].endswith("addition flagged: case duplicate of an existing file") and "risk:removal" in lines[2]
