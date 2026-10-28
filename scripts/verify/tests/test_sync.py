import io
import urllib.error
import urllib.parse

import pytest

from verify import sync
from verify.labels import MARKER, OWNED
from verify.textclean import safe_markdown
from verify.sync import GitHub, SyncError, ValidationError

SHA = "a" * 40
BASE = "b" * 40


def artifact(**over):
    data = {"version": 1, "base_sha": BASE, "head_sha": SHA, "skipped": None,
            "labels": ["gate:review", "kind:price-only", "risk:price", "shadow:auto", "verify:official"],
            "gate": "review", "kind": "price-only", "verify": "official", "shadow": True, "lane": "normal",
            "files": [{"path": "providers/p/m.yaml"}], "files_total": 1, "files_omitted": 0, "notes": [], "comment_md": f"{MARKER}\n## Catalog verify",
            "summary_md": "full table"}
    data.update(over)
    return data


NOTHING = dict(labels=[], gate=None, kind=None, verify=None, shadow=False, lane=None, files=[], files_total=0, comment_md=f"{MARKER}\nnothing", summary_md="x")


# ---------------------------------------------------------------------------- validation
def test_a_good_artifact_passes_and_every_label_the_cli_can_emit_is_owned():
    assert sync.validate(artifact())["gate"] == "review"
    sync.validate(artifact(**NOTHING))
    sync.validate(artifact(labels=["risk:price"], gate="hold", kind=None, verify=None, shadow=False, lane="hold"))


@pytest.mark.parametrize("over", [
    {"labels": ["gate:hold"], "gate": "hold"},                          # the tool never sets hold
    {"labels": ["gate:reviewed"]}, {"labels": ["bug"]}, {"labels": ["Gate:review"]}, {"labels": ["gate:review "]},
    {"labels": ["gate:review", "gate:escalate"]},
    {"labels": ["gate:review", "kind:price-only", "kind:mixed", "risk:price", "shadow:auto", "verify:official"]},
    {"labels": ["gate:review", "kind:price-only", "risk:price", "shadow:auto", "verify:official", "verify:none"]},
    {"labels": ["gate:review", "gate:review"]},
    {"labels": ["gate:review", "kind:price-only", "risk:price", "risk:price", "shadow:auto", "verify:official"]},
    {"labels": ["gate:review", "kind:price-only", "risk:price", "shadow:auto", "verify:official", "bug"]},
    {"labels": ["gate:review", "kind:price-only", "risk:price", "shadow:auto", "verify:official", "gate:hold"]},
    {"labels": ["gate:review", "kind:price-only", "risk:price", "shadow:auto", "verify:official", "id:7"]},
    {"labels": "gate:review"}, {"labels": [1]}, {"labels": ["x"] * 41},
    {"gate": "escalate"},                                               # label/gate mismatch
    {"gate": "bogus"}, {"kind": "mixed"}, {"verify": "none"}, {"shadow": False},
    {"labels": ["kind:price-only", "risk:price", "shadow:auto", "verify:official"]},  # gate set but no label
    {"head_sha": "xyz"}, {"base_sha": "A" * 40}, {"version": 2}, {"version": True},
    {"comment_md": "no marker"}, {"comment_md": MARKER * 2}, {"comment_md": ""},
    {"comment_md": MARKER + "x" * sync.MAX_COMMENT},
    {"summary_md": "x" * (sync.MAX_SUMMARY + 1)}, {"summary_md": None},
    {"files": [{"nopath": 1}]}, {"files": ["p"]}, {"files": [{"path": "x"}] * (sync.MAX_FILES + 1)},
    {"notes": ["x" * 3000]}, {"notes": "n"},
    {"skipped": "other"},
])
def test_rejected(over):
    with pytest.raises(ValidationError):
        sync.validate(artifact(**over))


def test_extra_and_missing_keys_rejected():
    with pytest.raises(ValidationError):
        sync.validate({**artifact(), "pr": 7})
    d = artifact()
    del d["notes"]
    with pytest.raises(ValidationError):
        sync.validate(d)
    for bad in (None, [], "x", 3):
        with pytest.raises(ValidationError):
            sync.validate(bad)


def test_comment_at_the_cap_is_accepted():
    sync.validate(artifact(comment_md=MARKER + "x" * (sync.MAX_COMMENT - len(MARKER))))


def test_skipped_run_carries_no_labels():
    sync.validate(artifact(skipped="trueforge-branch", **{**NOTHING, "comment_md": ""}))
    with pytest.raises(ValidationError):
        sync.validate(artifact(skipped="trueforge-branch"))


def test_mentions_are_neutralised():
    out = safe_markdown("hi @octocat and @org/team", 1000)
    assert "@octocat" not in out and "@org/team" not in out and out.count("@​") == 2


# ------------------------------------------------------------------------------ fake API
class FakeApi(GitHub):
    def __init__(self, labels=(), comments=(), head_sha=SHA, fork=False, fail=(), checks=(), pr=None):
        super().__init__("tok", "o/r")
        self.labels, self.comments, self.head_sha, self.fork, self.fail, self.checks = list(labels), list(comments), head_sha, fork, fail, list(checks)
        self.pr_override = pr or {}
        self.calls = []
        self.repo_labels: dict[str, dict] = {}  # label definitions that exist in the repo: name -> {color, description}

    def request(self, method, path, body=None, ok_missing=False):
        self.calls.append((method, urllib.parse.unquote(path.split("?")[0]), body))
        for m, frag in self.fail:
            if m == method and frag in path:
                raise SyncError(f"{method} {path} -> HTTP 403")
        p = path.split("?")[0]
        if method == "GET" and p == "/repos/o/r/pulls/7":
            pr = {"number": 7, "state": "open", "head": {"sha": self.head_sha, "ref": "feat/x", "repo": {"id": 77}},
                  "base": {"sha": BASE, "repo": {"full_name": "o/r"}}}
            return {**pr, **self.pr_override}
        if method == "GET" and p.endswith("/pulls"):
            return [{"number": 7}]
        if method == "GET" and p.endswith("/issues/7/labels"):
            page = int(path.split("&page=")[1]) if "&page=" in path else 1
            return [{"name": n} for n in self.labels][(page - 1) * 100: page * 100]
        if method == "GET" and p.startswith("/repos/o/r/labels/"):
            return self.repo_labels.get(urllib.parse.unquote(p.rsplit("/labels/", 1)[1]))
        if method == "POST" and p == "/repos/o/r/labels":
            if body["name"] in self.repo_labels:
                raise SyncError("POST /repos/o/r/labels -> HTTP 422")
            self.repo_labels[body["name"]] = {"name": body["name"], "color": body["color"], "description": body["description"]}
            return self.repo_labels[body["name"]]
        if method == "POST" and p.endswith("/issues/7/labels"):
            self.labels += [x for x in body["labels"] if x not in self.labels]
            return [{"name": n} for n in self.labels]
        if method == "DELETE" and "/issues/7/labels/" in p:
            self.labels.remove(urllib.parse.unquote(p.rsplit("/issues/7/labels/", 1)[1]))
            return None
        if method == "GET" and p.endswith("/issues/7/comments"):
            return self.comments
        if method == "POST" and p.endswith("/issues/7/comments"):
            self.comments.append({"id": 99, "body": body["body"], "user": {"login": "github-actions[bot]"}})
            return None
        if method == "PATCH" and "/issues/comments/" in p:
            next(c for c in self.comments if c["id"] == int(p.rsplit("/", 1)[1]))["body"] = body["body"]
            return None
        if method == "GET" and "check-runs" in p:
            return {"check_runs": self.checks}
        if method in ("POST", "PATCH") and "check-runs" in p:
            return None
        raise AssertionError(f"unexpected {method} {path}")

    def writes(self):
        """Every write to the PR, the comment and the check; label DEFINITIONS are in label_defs()."""
        return [(m, p) for m, p, _ in self.calls if m != "GET" and p != "/repos/o/r/labels"]

    def label_defs(self):
        return [b for m, p, b in self.calls if m == "POST" and p == "/repos/o/r/labels"]


def event(**run):
    base = {"head_sha": SHA, "head_branch": "feat/x", "event": "pull_request", "pull_requests": [{"number": 7}], "id": 1,
            "head_repository": {"id": 77}}
    base.update(run)
    return {"workflow_run": base}


def write(_tmp_path=None, **over):
    """A `compute` function returning the result with `over` applied (what labeljob would compute)."""
    return lambda pr, live: artifact(**over)


def test_happy_path_adds_labels_then_comment_then_check(tmp_path):
    api = FakeApi(labels=["bug"])
    out = sync.sync(api, event(), write(tmp_path))
    assert sorted(api.labels) == sorted(["bug", "gate:review", "kind:price-only", "risk:price", "shadow:auto", "verify:official"])
    kinds = [("labels" if "/labels" in p else "comment" if "comments" in p else "check") for _, p in api.writes()]
    assert kinds == ["labels", "comment", "check"]
    assert out["prs"][0]["comment"] == "created"
    assert api.comments[0]["body"].startswith(MARKER)


def test_labels_are_written_before_the_comment_even_when_the_comment_is_rejected(tmp_path):
    api = FakeApi(fail=[("POST", "/comments")])
    with pytest.raises(SyncError):
        sync.sync(api, event(), write(tmp_path))
    assert "gate:review" in api.labels  # the old bug: a rejected comment cost the labels
    order = [p for _, p in api.writes()]
    assert "/labels" in order[0]


def test_a_label_failure_does_not_stop_the_comment_but_is_reported(tmp_path):
    api = FakeApi(fail=[("POST", "/labels")])
    with pytest.raises(SyncError):
        sync.sync(api, event(), write(tmp_path))
    assert api.comments and api.comments[0]["body"].startswith(MARKER)


def test_only_owned_labels_by_exact_name_are_removed(tmp_path):
    live = ["gate:reviewed", "gate:hold-ish", "risk:price-extra", "verify", "Gate:review", "bug", "id:5",
            "gate:escalate", "risk:removal", "kind:mixed", "verify:none", "shadow:auto"]
    api = FakeApi(labels=live)
    sync.sync(api, event(), write(tmp_path, **NOTHING))
    assert set(api.labels) == {"gate:reviewed", "gate:hold-ish", "risk:price-extra", "verify", "Gate:review", "bug", "id:5"}
    assert {p.rsplit("/", 1)[1] for m, p in api.writes() if m == "DELETE"} == {
        "gate:escalate", "risk:removal", "kind:mixed", "verify:none", "shadow:auto"}


def test_nothing_is_removed_that_is_wanted_and_nothing_is_added_twice(tmp_path):
    api = FakeApi(labels=["gate:review", "risk:price"])
    sync.sync(api, event(), write(tmp_path))
    posted = [b["labels"] for m, p, b in api.calls if m == "POST" and p.endswith("/issues/7/labels")]
    assert posted == [["kind:price-only", "shadow:auto", "verify:official"]]
    assert not [1 for m, p in api.writes() if m == "DELETE"]


@pytest.mark.parametrize("hold", ["gate:hold"])
def test_hold_is_sticky_no_gate_label_is_set_and_hold_is_never_removed(tmp_path, hold):
    api = FakeApi(labels=[hold, "gate:escalate"])
    sync.sync(api, event(), write(tmp_path))
    assert hold in api.labels
    assert not [x for x in api.labels if x.startswith("gate:") and x != "gate:hold"]
    assert "risk:price" in api.labels


def test_hold_set_after_the_run_started_is_honoured_from_live_labels(tmp_path):
    api = FakeApi(labels=["gate:hold"])  # the artifact was computed without it
    sync.sync(api, event(), write(tmp_path))
    assert "gate:review" not in api.labels


def test_existing_bot_comment_is_updated_in_place_other_users_marker_is_ignored(tmp_path):
    mine = {"id": 5, "body": MARKER + "\nold", "user": {"login": "github-actions[bot]"}}
    theirs = {"id": 6, "body": MARKER + "\nspoof", "user": {"login": "mallory"}}
    api = FakeApi(comments=[theirs, mine])
    sync.sync(api, event(), write(tmp_path))
    assert mine["body"].endswith("Catalog verify") and theirs["body"].endswith("spoof")
    assert not [1 for m, p in api.writes() if m == "POST" and p.endswith("/comments")]
    api = FakeApi(comments=[theirs])
    sync.sync(api, event(), write(tmp_path))
    assert len(api.comments) == 2  # a new one, the spoof untouched


def test_nothing_to_verify_creates_no_comment_but_updates_an_old_one_and_clears_labels(tmp_path):
    api = FakeApi(labels=["gate:review", "bug"])
    out = sync.sync(api, event(), write(tmp_path, **NOTHING))
    assert api.comments == [] and api.labels == ["bug"] and out["prs"][0]["comment"] == "skipped"
    old = {"id": 5, "body": MARKER + "\nstale", "user": {"login": "github-actions[bot]"}}
    api = FakeApi(comments=[old])
    sync.sync(api, event(), write(tmp_path, **NOTHING))
    assert old["body"].endswith("nothing")


def test_comment_text_is_sanitised(tmp_path):
    api = FakeApi()
    sync.sync(api, event(), write(tmp_path, comment_md=f"{MARKER}\nping @octocat"))
    assert "@octocat" not in api.comments[0]["body"]


def test_stale_run_is_skipped_without_writes(tmp_path):
    api = FakeApi(head_sha="c" * 40)
    out = sync.sync(api, event(), write(tmp_path))
    assert "skipped" in out and api.writes() == []


def test_a_result_for_another_commit_is_rejected():
    api = FakeApi()
    with pytest.raises(ValidationError):
        sync.sync(api, event(), lambda pr, live: artifact(head_sha="d" * 40))
    assert api.writes() == []


@pytest.mark.parametrize("pr", [
    {"head": {"sha": SHA, "ref": "feat/x", "repo": {"id": 999}}},            # a fork reusing the victim's head sha
    {"head": {"sha": SHA, "ref": "feat/x", "repo": None}},                    # head repository deleted
    {"head": {"sha": SHA, "ref": "other-branch", "repo": {"id": 77}}},       # same repo, different branch
    {"head": {"sha": "c" * 40, "ref": "feat/x", "repo": {"id": 77}}},        # head moved
    {"state": "closed"},
    {"state": "merged"},
    {"base": {"sha": BASE, "repo": {"full_name": "evil/fork"}}},            # PR into another repository
    {"base": {"sha": "not-a-sha", "repo": {"full_name": "o/r"}}},
])
def test_a_pr_that_does_not_match_the_run_is_never_touched(pr):
    api = FakeApi(pr=pr)
    out = sync.sync(api, event(), write())
    assert "skipped" in out and api.writes() == []


def test_the_run_without_a_head_repository_matches_nothing():
    api = FakeApi()
    ev = event()
    del ev["workflow_run"]["head_repository"]
    assert "skipped" in sync.sync(api, ev, write()) and api.writes() == []


def test_a_deleted_head_repository_cannot_match_a_run_that_reports_none_either():
    api = FakeApi(pr={"head": {"sha": SHA, "ref": "feat/x", "repo": None}})
    ev = event()
    ev["workflow_run"]["head_repository"] = None
    assert "skipped" in sync.sync(api, ev, write()) and api.writes() == []
    api = FakeApi(pr={"head": {"sha": SHA, "ref": "feat/x", "repo": {"id": 77}}})
    ev = event()
    ev["workflow_run"]["head_repository"] = {"id": True}   # a bool is not an id
    assert "skipped" in sync.sync(api, ev, write()) and api.writes() == []


def test_fork_resolution_through_the_commit_lookup_still_checks_repo_and_branch():
    api = FakeApi(pr={"head": {"sha": SHA, "ref": "feat/x", "repo": {"id": 5}}})
    assert "skipped" in sync.sync(api, event(pull_requests=[]), write()) and api.writes() == []
    api = FakeApi()
    assert "prs" in sync.sync(api, event(pull_requests=[]), write())


def test_the_trusted_base_and_head_come_from_the_api_not_the_event():
    seen = []
    api = FakeApi()
    sync.sync(api, event(), lambda pr, live: seen.append((pr["base"]["sha"], pr["head"]["sha"], list(live))) or artifact())
    assert seen == [(BASE, SHA, [])]


def test_stale_during_compute_skips_that_pr_without_writes():
    def compute(pr, live):
        raise sync.Stale("moved")
    api = FakeApi()
    out = sync.sync(api, event(), compute)
    assert out["prs"][0]["skipped"] == "moved" and api.writes() == []


def test_comment_of_60000_ats_stays_under_the_limit_after_escaping():
    body = MARKER + "\n" + "@" * (sync.MAX_COMMENT - len(MARKER) - 1)
    sync.validate(artifact(comment_md=body))
    api = FakeApi()
    sync.sync(api, event(), write(comment_md=body))
    posted = api.comments[0]["body"]
    assert len(posted) <= sync.MAX_COMMENT and len(posted) < 65_536
    assert posted.startswith(MARKER) and "@@" not in posted


def test_control_characters_and_bidi_overrides_are_stripped_from_posted_text():
    nasty = MARKER + "\nline\r\x00\x07 \u202eevil \ud800 end @bob"
    api = FakeApi()
    sync.sync(api, event(), write(comment_md=nasty, summary_md=nasty))
    body = api.comments[0]["body"]
    assert all(ch not in body for ch in ("\r", "\x00", "\x07", "\u202e", "\ud800")) and "@bob" not in body
    post = [b for m, p, b in api.calls if m == "POST" and p.endswith("/check-runs")][0]
    assert len(post["output"]["summary"]) <= sync.MAX_SUMMARY and "\u202e" not in post["output"]["summary"]


def test_check_run_summary_is_capped_after_escaping():
    api = FakeApi()
    sync.sync(api, event(), write(summary_md="@" * sync.MAX_SUMMARY))
    post = [b for m, p, b in api.calls if m == "POST" and p.endswith("/check-runs")][0]
    assert len(post["output"]["summary"]) <= sync.MAX_SUMMARY


def test_files_total_must_add_up():
    sync.validate(artifact(files=[{"path": "a"}], files_total=301, files_omitted=300))
    for bad in ({"files_total": 5}, {"files_omitted": 1}, {"files_total": True}, {"files_total": -1, "files_omitted": -2}):
        with pytest.raises(ValidationError):
            sync.validate(artifact(**bad))


def test_trueforge_branch_and_skipped_results_touch_nothing():
    api = FakeApi()
    assert sync.sync(api, event(head_branch="trueforge/x"), write())["skipped"] == "trueforge-branch"
    skipped = dict(NOTHING, skipped="trueforge-branch", comment_md="")
    out = sync.sync(api, event(), write(**skipped))
    assert out["prs"] == [{"pr": 7, "skipped": "trueforge-branch"}] and out["check"] == "skipped"
    assert api.writes() == []


def test_check_run_is_neutral_and_updated_in_place(tmp_path):
    api = FakeApi()
    sync.sync(api, event(), write(tmp_path))
    post = [b for m, p, b in api.calls if m == "POST" and p.endswith("/check-runs")][0]
    assert post["conclusion"] == "neutral" and post["head_sha"] == SHA and post["name"] == "catalog-verify"
    assert post["output"]["title"] == "gate:review · kind:price-only · verify:official"
    api = FakeApi(checks=[{"id": 3, "app": {"slug": "github-actions"}}])
    sync.sync(api, event(), write(tmp_path))
    assert ("PATCH", "/repos/o/r/check-runs/3") in api.writes()
    patch = [b for m, p, b in api.calls if m == "PATCH" and "check-runs" in p][0]
    assert patch["conclusion"] == "neutral" and patch["status"] == "completed"
    api = FakeApi(checks=[{"id": 3, "app": {"slug": "someone-else"}}])
    sync.sync(api, event(), write(tmp_path))
    assert ("PATCH", "/repos/o/r/check-runs/3") not in api.writes()


def test_more_than_100_labels_are_paginated(tmp_path):
    api = FakeApi(labels=[f"l{i}" for i in range(150)] + ["gate:escalate"])
    sync.sync(api, event(), write(tmp_path))
    assert "gate:escalate" not in api.labels and len(api.labels) >= 150


def test_owned_set_is_what_the_spec_lists():
    assert OWNED == {"gate:review", "gate:unverified", "gate:escalate", "shadow:auto",
                     *(f"risk:{r}" for r in ("removal", "price", "params", "param-value", "feature", "limit", "mode", "dated", "other", "check-error", "provider-default")),
                     *(f"risk:rule-{r}" for r in ("max-tokens-below-limit", "max-tokens-inherited-cap", "max-completion-pair", "null-status", "deprecated-conflict", "deprecated-undated", "reasoning-enum", "reasoning-default", "reasoning-unsupported", "feature-enum", "claude-feature-gaps")),
                     *(f"verify:{v}" for v in ("official", "partial", "conflict", "none")),
                     *(f"kind:{k}" for k in ("price-only", "lifecycle", "features-params", "mixed", "new-model", "provider-default")),
                     "fast-lane"}
    assert "gate:hold" not in OWNED


# --------------------------------------------------------------------------- http client
class Resp:
    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self.body


def http_error(code):
    return urllib.error.HTTPError("u", code, "x", {}, io.BytesIO(b""))


def test_http_retries_5xx_then_succeeds_and_sends_the_token():
    seen, sleeps = [], []
    script = [http_error(502), Resp(b'{"ok": 1}')]

    def opener(req, timeout):
        seen.append(req)
        item = script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item
    api = GitHub("tok", "o/r", opener=opener, sleep=sleeps.append)
    assert api.request("GET", "/x") == {"ok": 1}
    assert len(seen) == 2 and sleeps == [2]
    assert seen[0].get_header("Authorization") == "Bearer tok"


def test_http_403_is_a_sync_error_404_can_be_tolerated():
    def opener_for(code):
        def opener(req, timeout):
            raise http_error(code)
        return opener
    with pytest.raises(SyncError):
        GitHub("t", "o/r", opener=opener_for(403)).request("POST", "/x", {})
    assert GitHub("t", "o/r", opener=opener_for(404)).request("DELETE", "/x", ok_missing=True) is None
    with pytest.raises(SyncError):
        GitHub("t", "o/r", opener=opener_for(404)).request("DELETE", "/x")
    with pytest.raises(SyncError):
        GitHub("t", "o/r", opener=opener_for(500), sleep=lambda s: None).request("GET", "/x")


# ------------------------------------------------------------------------- fast-lane and label definitions
FAST = dict(labels=["fast-lane", "gate:unverified", "kind:features-params", "risk:feature", "verify:none"],
            gate="unverified", kind="features-params", verify="none", shadow=False, lane="fast-lane")


def test_a_fast_lane_result_validates():
    sync.validate(artifact(**FAST))
    sync.validate(artifact(**{**FAST, "labels": [x if x != "kind:features-params" else "kind:lifecycle" for x in FAST["labels"]], "kind": "lifecycle"}))
    sync.validate(artifact(**{**FAST, "labels": [x for x in FAST["labels"] if x != "fast-lane"], "lane": "normal"}))


@pytest.mark.parametrize("over", [
    {"lane": "normal"},                                                        # label without the lane
    {"labels": [x for x in FAST["labels"] if x != "fast-lane"]},               # lane without the label
    {"lane": "bogus"}, {"lane": "escalate"}, {"lane": "hold"}, {"lane": None},
    {"kind": "price-only", "labels": ["fast-lane", "gate:unverified", "kind:price-only", "risk:feature", "verify:none"]},
    {"kind": "mixed", "labels": ["fast-lane", "gate:unverified", "kind:mixed", "risk:feature", "verify:none"]},
    {"kind": "new-model", "labels": ["fast-lane", "gate:unverified", "kind:new-model", "risk:feature", "verify:none"]},
    {"gate": "escalate", "lane": "fast-lane", "labels": ["fast-lane", "gate:escalate", "kind:features-params", "risk:feature", "verify:none"]},
    {"gate": "hold", "lane": "fast-lane", "labels": ["fast-lane", "kind:features-params", "risk:feature", "verify:none"]},
])
def test_a_fast_lane_that_does_not_add_up_is_rejected(over):
    with pytest.raises(ValidationError):
        sync.validate(artifact(**{**FAST, **over}))


@pytest.mark.parametrize("gate,lane,ok", [("escalate", "escalate", True), ("escalate", "normal", False), ("review", "escalate", False),
                                         ("review", "hold", False), ("hold", "hold", True), ("hold", "normal", False),
                                         ("unverified", "normal", True), ("review", "normal", True)])
def test_lane_must_follow_the_gate(gate, lane, ok):
    labels = [] if gate == "hold" else [f"gate:{gate}"]
    data = artifact(labels=labels + ["risk:price"], gate=gate, kind=None, verify=None, shadow=False, lane=lane)
    if ok:
        sync.validate(data)
    else:
        with pytest.raises(ValidationError):
            sync.validate(data)


def test_fast_lane_label_is_applied_and_removed_by_exact_name(tmp_path):
    api = FakeApi(labels=["fast-lane-ish", "fast_lane"])
    sync.sync(api, event(), write(tmp_path, **FAST))
    assert "fast-lane" in api.labels and {"fast-lane-ish", "fast_lane"} <= set(api.labels)
    api2 = FakeApi(labels=["fast-lane", "gate:unverified", "kind:features-params", "risk:feature", "verify:none"])
    sync.sync(api2, event(), write(tmp_path))                      # the next run is not fast-lane any more
    assert "fast-lane" not in api2.labels


def test_missing_labels_are_created_with_colour_and_description_before_they_are_added(tmp_path):
    api = FakeApi(labels=["bug"])
    sync.sync(api, event(), write(tmp_path, **FAST))
    defs = {b["name"]: b for b in api.label_defs()}
    assert set(defs) == set(FAST["labels"])
    for name, body in defs.items():
        assert body["color"] and body["description"], name
    assert defs["fast-lane"]["color"] == "006b75" and "24 h" in defs["fast-lane"]["description"]
    order = [(m, p) for m, p, _ in api.calls if m == "POST"]
    assert order.index(("POST", "/repos/o/r/labels")) < order.index(("POST", "/repos/o/r/issues/7/labels"))


def test_an_existing_label_definition_is_never_edited_or_recreated(tmp_path):
    api = FakeApi()
    api.repo_labels = {"fast-lane": {"name": "fast-lane", "color": "ffffff", "description": "mine"}}
    sync.sync(api, event(), write(tmp_path, **FAST))
    assert "fast-lane" not in {b["name"] for b in api.label_defs()}
    assert api.repo_labels["fast-lane"]["description"] == "mine"
    assert not [1 for m, p, _ in api.calls if m in ("PATCH", "PUT") and "/labels" in p]


def test_a_second_run_creates_no_label_definition(tmp_path):
    api = FakeApi()
    sync.sync(api, event(), write(tmp_path, **FAST))
    n = len(api.label_defs())
    sync.sync(api, event(), write(tmp_path, **FAST))
    assert n == 5 and len(api.label_defs()) == n


def test_labels_that_are_already_on_the_pr_are_not_looked_up(tmp_path):
    api = FakeApi(labels=FAST["labels"])
    sync.sync(api, event(), write(tmp_path, **FAST))
    assert not [1 for m, p, _ in api.calls if p.startswith("/repos/o/r/labels")]


def test_a_failed_label_definition_costs_only_the_description(tmp_path):
    api = FakeApi(fail=[("POST", "o/r/labels")])    # the definition call fails, the add call (".../issues/7/labels") must still run
    sync.sync(api, event(), write(tmp_path, **FAST))
    assert set(FAST["labels"]) <= set(api.labels) and api.comments


def test_ensure_labels_ignores_names_it_does_not_own():
    api = FakeApi()
    assert sync.ensure_labels(api, ["bug", "gate:hold", "id:3"]) == [] and api.calls == []
    assert sync.ensure_labels(api, ["fast-lane"]) == ["fast-lane"]


def test_the_addition_jobs_labels_survive_a_sync_and_the_verifier_escalation_is_applied(tmp_path):
    live = ["id:case-duplicate", "id:high-edit-provider", "verify:prices-from-source", "gate:review", "bug"]
    api = FakeApi(labels=live)
    sync.sync(api, event(), write(tmp_path, labels=["gate:escalate"], gate="escalate", kind=None, verify=None, shadow=False, lane="escalate"))
    assert {"id:case-duplicate", "id:high-edit-provider", "verify:prices-from-source", "bug", "gate:escalate"} <= set(api.labels)
    assert "gate:review" not in api.labels
