import ast
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from verify import queue
from verify.sync import GitHub, SyncError

NOW = datetime(2026, 10, 28, 8, 0, tzinfo=timezone.utc)
BOT = "github-actions[bot]"


def pr(number, hours, *labels, ref="bot/update-x-20261001-000000", bot=True, draft=False, title="feat(p/m): update model YAMLs [bot]", state="open"):
    created = NOW - timedelta(hours=hours)
    return {"number": number, "state": state, "draft": draft, "title": title, "created_at": created.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "labels": [{"name": n} for n in labels], "head": {"ref": ref},
            "user": {"login": "models-bot[bot]" if bot else "someone", "type": "Bot" if bot else "User"},
            "base": {"repo": {"full_name": "o/r"}}}


class FakeApi(GitHub):
    def __init__(self, prs=(), issues=(), comments=None, fail=()):
        super().__init__("tok", "o/r")
        self.prs, self.issues, self.comments, self.fail = list(prs), [dict(i) for i in issues], dict(comments or {}), fail
        self.calls = []

    def request(self, method, path, body=None, ok_missing=False):
        self.calls.append((method, path.split("?")[0], body))
        for m, frag in self.fail:
            if m == method and frag in path:
                raise SyncError(f"{method} {path} -> HTTP 403")
        p = path.split("?")[0]
        if method == "GET" and p == "/repos/o/r/pulls":
            return self._page(self.prs, path)
        if method == "GET" and p == "/repos/o/r/issues":
            return self._page(self.issues, path)
        if method == "GET" and p.endswith("/comments"):
            return self._page(self.comments.get(int(p.split("/")[-2]), []), path)
        if method == "POST" and p == "/repos/o/r/issues":
            issue = {"number": 100 + len(self.issues), "title": body["title"], "body": body["body"], "user": {"login": BOT}}
            self.issues.append(issue)
            return issue
        if method == "PATCH" and p.startswith("/repos/o/r/issues/"):
            next(i for i in self.issues if i["number"] == int(p.rsplit("/", 1)[1]))["body"] = body["body"]
            return None
        if method == "POST" and p.endswith("/comments"):
            self.comments.setdefault(int(p.split("/")[-2]), []).append({"body": body["body"], "user": {"login": BOT}})
            return None
        raise AssertionError(f"unexpected {method} {path}")

    @staticmethod
    def _page(items, path):
        page = int(path.split("&page=")[1]) if "&page=" in path else 1
        return items[(page - 1) * 100: page * 100]

    def writes(self):
        return [(m, p) for m, p, _ in self.calls if m != "GET"]


def rows_of(*prs, now=NOW):
    return queue.overdue(list(prs), now)


# ----------------------------------------------------------------------------------- thresholds
def test_thresholds_are_24_and_72_hours():
    assert queue.FAST_LANE_AFTER == timedelta(hours=24) and queue.ESCALATE_AFTER == timedelta(hours=72)


@pytest.mark.parametrize("hours,label,listed", [
    (23.9, "fast-lane", False), (24, "fast-lane", False), (24.1, "fast-lane", True), (100, "fast-lane", True),
    (71.9, "gate:escalate", False), (72, "gate:escalate", False), (72.1, "gate:escalate", True),
    (30, "gate:escalate", False),                      # an escalate PR is not overdue at 30 h
])
def test_age_thresholds(hours, label, listed):
    assert bool(rows_of(pr(1, hours, label))) is listed


def test_lane_follows_the_label():
    out = rows_of(pr(1, 30, "fast-lane"), pr(2, 80, "gate:escalate"), pr(3, 90, "gate:review"), pr(4, 90))
    assert [(r["number"], r["lane"]) for r in out] == [(2, "escalate"), (1, "fast-lane")]


def test_a_pr_with_both_labels_is_listed_once_under_the_stricter_lane():
    assert [(r["number"], r["lane"]) for r in rows_of(pr(1, 80, "fast-lane", "gate:escalate"))] == [(1, "escalate")]
    assert [(r["number"], r["lane"]) for r in rows_of(pr(1, 30, "fast-lane", "gate:escalate"))] == [(1, "fast-lane")]


def test_fast_lane_only_counts_bot_prs_but_escalate_counts_any_pr():
    human = pr(1, 50, "fast-lane", bot=False, ref="feat/x")
    assert rows_of(human) == []
    assert rows_of(pr(2, 50, "fast-lane", bot=True, ref="feat/x")) == []              # a bot account, not the models bot branch
    assert [r["lane"] for r in rows_of(pr(3, 100, "gate:escalate", bot=False, ref="feat/x"))] == ["escalate"]


def test_drafts_closed_trueforge_and_held_prs_are_left_out():
    assert rows_of(pr(1, 100, "fast-lane", draft=True)) == []
    assert rows_of(pr(2, 100, "fast-lane", state="closed")) == []
    assert rows_of(pr(3, 100, "fast-lane", ref="trueforge/models-bot-x")) == []
    assert rows_of(pr(3, 100, "gate:escalate", ref="trueforge/models-bot-x", bot=False)) == []
    assert rows_of(pr(3, 100, "gate:escalate", ref="trueforge")) != []                  # only the exact prefix
    assert rows_of(pr(4, 100, "gate:escalate", "gate:hold")) == []
    assert rows_of(pr(5, 100, "gate:escalate", "id:12")) != []                         # id:* is no hold
    assert rows_of(pr(6, 100, "gate:escalate", "gate:holdup")) != []


def test_oldest_first_and_bad_rows_are_skipped():
    broken = pr(9, 100, "fast-lane")
    broken["created_at"] = "not a date"
    out = rows_of(pr(1, 30, "fast-lane"), pr(2, 60, "fast-lane"), broken, {"number": 5}, "junk", pr(3, 60, "fast-lane"))
    assert [r["number"] for r in out] == [2, 3, 1]


# ----------------------------------------------------------------------------------------- body
def test_body_lists_links_age_and_lane_and_no_people():
    body = queue.render_body(rows_of(pr(7, 30, "fast-lane", title="feat(p/m): x @octocat `evil` | row"),
                                     pr(8, 80, "gate:escalate")), NOW)
    assert body.startswith(queue.BODY_MARKER) and f"# {queue.TITLE}" in body
    assert "[#7](https://github.com/o/r/pull/7)" in body and "[#8](https://github.com/o/r/pull/8)" in body
    assert "| escalate | 80 h |" in body and "| fast-lane | 30 h |" in body
    assert "@octocat" not in body and "someone" not in body and "models-bot" not in body
    assert "2026-10-28" in body and "fast-lane` open more than 24 h: 1" in body and "gate:escalate` open more than 72 h: 1" in body


def test_an_empty_queue_says_so():
    assert "Nothing is over its review target." in queue.render_body([], NOW)


def test_body_is_a_pure_function_of_prs_and_now():
    prs = [pr(1, 30, "fast-lane"), pr(2, 80, "gate:escalate")]
    assert queue.render_body(rows_of(*prs), NOW) == queue.render_body(rows_of(*reversed(prs)), NOW)
    assert queue.render_body(rows_of(*prs), NOW) != queue.render_body(rows_of(*prs, now=NOW + timedelta(hours=5)), NOW + timedelta(hours=5))


def test_body_is_capped_and_says_how_many_more():
    prs = [pr(i, 30 + i, "fast-lane", title="x" * 500) for i in range(1, queue.MAX_ROWS + 40)]
    body = queue.render_body(rows_of(*prs), NOW)
    assert body.count("| fast-lane |") == queue.MAX_ROWS and "…39 more" in body and len(body) <= queue.MAX_BODY


# ---------------------------------------------------------------------------------- publishing
def test_creates_the_issue_when_missing_then_a_second_run_writes_nothing():
    api = FakeApi([pr(1, 30, "fast-lane")])
    first = queue.publish(api, rows_of(*api.prs), NOW)
    assert first == {"issue": "created", "number": 100, "comment": "created"}
    assert api.issues[0]["title"] == queue.TITLE
    writes = len(api.writes())
    second = queue.publish(api, rows_of(*api.prs), NOW)
    assert second == {"issue": "unchanged", "number": 100, "comment": "exists"}
    assert len(api.writes()) == writes                     # idempotent: no PATCH, no second comment
    assert len(api.comments[100]) == 1


def test_the_issue_body_is_edited_in_place_when_the_queue_changes_and_the_day_comment_stays_single():
    api = FakeApi([pr(1, 30, "fast-lane")])
    queue.publish(api, rows_of(*api.prs), NOW)
    api.prs.append(pr(2, 90, "gate:escalate"))
    out = queue.publish(api, rows_of(*api.prs), NOW)
    assert out["issue"] == "updated" and out["comment"] == "exists"
    assert "[#2]" in api.issues[0]["body"] and len(api.issues) == 1 and len(api.comments[100]) == 1


def test_a_new_day_gets_a_new_comment():
    api = FakeApi([pr(1, 30, "fast-lane")])
    queue.publish(api, rows_of(*api.prs), NOW)
    tomorrow = NOW + timedelta(days=1)
    assert queue.publish(api, rows_of(*api.prs, now=tomorrow), tomorrow)["comment"] == "created"
    assert len(api.comments[100]) == 2
    assert "2026-10-29" in api.comments[100][1]["body"] and "@" not in api.comments[100][1]["body"]


def test_no_comment_when_nothing_is_overdue_but_the_body_still_says_so():
    api = FakeApi([pr(1, 5, "fast-lane")])
    out = queue.publish(api, rows_of(*api.prs), NOW)
    assert out == {"issue": "created", "number": 100, "comment": "none"} and api.comments == {}
    assert "Nothing is over" in api.issues[0]["body"]


def test_the_issue_is_found_by_exact_title_and_bot_author_only():
    imposter = {"number": 3, "title": queue.TITLE, "body": "mine", "user": {"login": "someone"}}
    not_exact = {"number": 4, "title": queue.TITLE + " 2", "body": "x", "user": {"login": BOT}}
    a_pr = {"number": 5, "title": queue.TITLE, "body": "x", "user": {"login": BOT}, "pull_request": {}}
    api = FakeApi([pr(1, 30, "fast-lane")], issues=[imposter, not_exact, a_pr])
    out = queue.publish(api, rows_of(*api.prs), NOW)
    assert out["issue"] == "created" and imposter["body"] == "mine" and api.issues[0]["body"] == "mine"
    assert not [1 for m, p in api.writes() if m == "PATCH"]


def test_the_oldest_of_two_tracking_issues_is_the_one_edited():
    mine = lambda n: {"number": n, "title": queue.TITLE, "body": "old", "user": {"login": BOT}}  # noqa: E731
    api = FakeApi([pr(1, 30, "fast-lane")], issues=[mine(40), mine(12)])
    assert queue.publish(api, rows_of(*api.prs), NOW)["number"] == 12


def test_a_comment_from_someone_else_with_the_marker_does_not_count_as_the_days_comment():
    api = FakeApi([pr(1, 30, "fast-lane")])
    queue.publish(api, rows_of(*api.prs), NOW)
    marker = queue.DAY_MARKER.format(day="2026-10-29")
    api.comments[100].append({"body": marker + " fake", "user": {"login": "someone"}})
    tomorrow = NOW + timedelta(days=1)
    assert queue.publish(api, rows_of(*api.prs, now=tomorrow), tomorrow)["comment"] == "created"


def test_it_never_writes_to_a_pr_only_to_the_tracking_issue():
    api = FakeApi([pr(1, 30, "fast-lane"), pr(2, 90, "gate:escalate")])
    queue.publish(api, rows_of(*api.prs), NOW)
    api.prs.append(pr(3, 50, "fast-lane"))
    queue.publish(api, rows_of(*api.prs), NOW)
    for method, path in api.writes():
        assert path == "/repos/o/r/issues" or path.startswith("/repos/o/r/issues/100"), (method, path)
        assert "/pulls" not in path and "/labels" not in path
    assert not [1 for m, p in api.writes() if m in ("PUT", "DELETE")]


# --------------------------------------------------------------------------------------- cli
def test_dry_run_prints_the_body_and_writes_nothing(capsys):
    api = FakeApi([pr(1, 30, "fast-lane"), pr(2, 90, "gate:escalate"), pr(3, 5, "fast-lane")])
    assert queue.main(["--dry-run", "--repo", "o/r"], api=api, now=NOW) == 0
    out = capsys.readouterr().out
    assert out.startswith(queue.BODY_MARKER) and "[#1]" in out and "[#2]" in out and "[#3]" not in out
    assert api.writes() == [] and all(m == "GET" for m, _, _ in api.calls)


def test_main_publishes_and_reports(capsys):
    api = FakeApi([pr(1, 30, "fast-lane")])
    assert queue.main(["--repo", "o/r"], api=api, now=NOW) == 0
    assert "'issue': 'created'" in capsys.readouterr().out and api.issues


def test_main_fails_cleanly_on_an_api_error(capsys):
    api = FakeApi([pr(1, 30, "fast-lane")], fail=[("POST", "/issues")])
    assert queue.main(["--repo", "o/r"], api=api, now=NOW) == 1
    assert "verify.queue:" in capsys.readouterr().err


def test_main_needs_a_token_and_a_repo(monkeypatch, capsys):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.setattr(queue.subprocess, "run", lambda *a, **k: type("P", (), {"returncode": 1, "stdout": ""})())
    assert queue.main(["--repo", "o/r"]) == 2
    assert "needs a repository" in capsys.readouterr().err


def test_now_flag_is_parsed(capsys):
    api = FakeApi([pr(1, 30, "fast-lane")])
    assert queue.main(["--dry-run", "--repo", "o/r", "--now", "2026-10-28T08:00:00Z"], api=api) == 0
    assert "Updated 2026-10-28" in capsys.readouterr().out


def test_queue_is_stdlib_and_the_label_job_modules_only():
    tree = ast.parse((Path(queue.__file__)).read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert all(a.name.split(".")[0] in sys.stdlib_module_names for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                assert node.module in ("labels", "sync", "textclean"), node.module
            else:
                assert (node.module or "").split(".")[0] in sys.stdlib_module_names


def test_the_link_is_the_apis_html_url_only_when_it_is_a_github_page():
    good = pr(1, 30, "fast-lane")
    good["html_url"] = "https://github.com/o/r/pull/1"
    odd = pr(2, 30, "fast-lane")
    odd["html_url"] = "https://evil.example/x) [click](https://evil.example"
    urls = {r["number"]: r["url"] for r in rows_of(good, odd)}
    assert urls == {1: "https://github.com/o/r/pull/1", 2: "https://github.com/o/r/pull/2"}


def test_a_pr_title_cannot_break_the_table_or_the_code_span():
    nasty = "a`b|c\nd\u202e @octocat [x](https://evil.example)"
    body = queue.render_body(rows_of(pr(7, 30, "fast-lane", title=nasty)), NOW)
    row = next(x for x in body.split("\n") if x.startswith("| [#7]"))
    assert row.count("|") == 4 and row.count("`") == 2 and "\u202e" not in body
    assert "a'b/c d" in row
