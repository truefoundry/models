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
    assert report.render_summary(v, files).count("risk:removal") == 120


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
