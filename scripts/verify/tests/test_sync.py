import io
import json
import urllib.error
import urllib.parse

import pytest

from verify import sync
from verify.labels import MARKER, OWNED
from verify.sync import GitHub, SyncError, ValidationError

SHA = "a" * 40
BASE = "b" * 40


def artifact(**over):
    data = {"version": 1, "base_sha": BASE, "head_sha": SHA, "skipped": None,
            "labels": ["gate:review", "kind:price-only", "risk:price", "shadow:auto", "verify:official"],
            "gate": "review", "kind": "price-only", "verify": "official", "shadow": True,
            "files": [{"path": "providers/p/m.yaml"}], "notes": [], "comment_md": f"{MARKER}\n## Catalog verify",
            "summary_md": "full table"}
    data.update(over)
    return data


NOTHING = dict(labels=[], gate=None, kind=None, verify=None, shadow=False, files=[], comment_md=f"{MARKER}\nnothing", summary_md="x")


# ---------------------------------------------------------------------------- validation
def test_a_good_artifact_passes_and_every_label_the_cli_can_emit_is_owned():
    assert sync.validate(artifact())["gate"] == "review"
    sync.validate(artifact(**NOTHING))
    sync.validate(artifact(labels=["risk:price"], gate="hold", kind=None, verify=None, shadow=False))


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


def test_the_no_verifier_at_base_artifact_the_workflow_writes_is_valid_and_touches_nothing(tmp_path):
    raw = ('{"version":1,"base_sha":"%s","head_sha":"%s","skipped":"no-verifier-at-base","labels":[],"gate":null,'
           '"kind":null,"verify":null,"shadow":false,"files":[],"notes":[],"comment_md":"","summary_md":""}') % (BASE, SHA)
    (tmp_path / sync.ARTIFACT_FILE).write_text(raw)
    api = FakeApi()
    assert sync.sync(api, event(), tmp_path)["skipped"] == "no-verifier-at-base"
    assert api.calls == []


def test_load_artifact_file_rules(tmp_path):
    with pytest.raises(ValidationError):
        sync.load_artifact(tmp_path)
    f = tmp_path / sync.ARTIFACT_FILE
    f.write_text("{not json")
    with pytest.raises(ValidationError):
        sync.load_artifact(tmp_path)
    f.write_text(json.dumps(artifact()))
    assert sync.load_artifact(tmp_path)["head_sha"] == SHA
    f.write_text(" " * (sync.MAX_ARTIFACT_BYTES + 1))
    with pytest.raises(ValidationError):
        sync.load_artifact(tmp_path)
    f.unlink()
    target = tmp_path / "elsewhere.json"
    target.write_text(json.dumps(artifact()))
    f.symlink_to(target)
    with pytest.raises(ValidationError):
        sync.load_artifact(tmp_path)


def test_mentions_are_neutralised():
    out = sync.sanitize_md("hi @octocat and @org/team")
    assert "@octocat" not in out and "@org/team" not in out and out.count("@​") == 2


# ------------------------------------------------------------------------------ fake API
class FakeApi(GitHub):
    def __init__(self, labels=(), comments=(), head_sha=SHA, fork=False, fail=(), checks=()):
        super().__init__("tok", "o/r")
        self.labels, self.comments, self.head_sha, self.fork, self.fail, self.checks = list(labels), list(comments), head_sha, fork, fail, list(checks)
        self.calls = []

    def request(self, method, path, body=None, ok_missing=False):
        self.calls.append((method, urllib.parse.unquote(path.split("?")[0]), body))
        for m, frag in self.fail:
            if m == method and frag in path:
                raise SyncError(f"{method} {path} -> HTTP 403")
        p = path.split("?")[0]
        if method == "GET" and p == "/repos/o/r/pulls/7":
            return {"number": 7, "state": "open", "head": {"sha": self.head_sha}, "base": {"repo": {"full_name": "o/r"}}}
        if method == "GET" and p.endswith("/pulls"):
            return [{"number": 7}]
        if method == "GET" and p.endswith("/issues/7/labels"):
            page = int(path.split("&page=")[1]) if "&page=" in path else 1
            return [{"name": n} for n in self.labels][(page - 1) * 100: page * 100]
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
        return [(m, p) for m, p, _ in self.calls if m != "GET"]


def event(**run):
    base = {"head_sha": SHA, "head_branch": "feat/x", "event": "pull_request", "pull_requests": [{"number": 7}], "id": 1}
    base.update(run)
    return {"workflow_run": base}


def write(tmp_path, **over):
    (tmp_path / sync.ARTIFACT_FILE).write_text(json.dumps(artifact(**over)))
    return tmp_path


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
    posted = [b["labels"] for m, p, b in api.calls if m == "POST" and p.endswith("/labels")]
    assert posted == [["kind:price-only", "shadow:auto", "verify:official"]]
    assert not [1 for m, p in api.writes() if m == "DELETE"]


@pytest.mark.parametrize("hold", ["gate:hold", "id:42"])
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


def test_artifact_for_another_commit_is_rejected(tmp_path):
    api = FakeApi()
    with pytest.raises(ValidationError):
        sync.sync(api, event(head_sha="c" * 40), write(tmp_path))
    assert api.writes() == []


def test_the_pr_number_comes_from_the_event_never_the_artifact(tmp_path):
    api = FakeApi()
    d = artifact()
    d["pr"] = 9
    (tmp_path / sync.ARTIFACT_FILE).write_text(json.dumps(d))
    with pytest.raises(ValidationError):
        sync.sync(api, event(), tmp_path)
    assert api.writes() == []


def test_fork_pr_is_resolved_by_commit_lookup(tmp_path):
    api = FakeApi()
    sync.sync(api, event(pull_requests=[]), write(tmp_path))
    assert any(p.endswith(f"/commits/{SHA}/pulls") for _, p, _ in api.calls) and "gate:review" in api.labels


def test_trueforge_branch_and_skipped_artifacts_touch_nothing(tmp_path):
    api = FakeApi()
    assert sync.sync(api, event(head_branch="trueforge/x"), write(tmp_path))["skipped"] == "trueforge-branch"
    skipped = dict(NOTHING, skipped="trueforge-branch", comment_md="")
    assert sync.sync(api, event(), write(tmp_path, **skipped))["skipped"] == "trueforge-branch"
    assert api.calls == []


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
                     *(f"risk:{r}" for r in ("removal", "price", "params", "param-value", "feature", "limit", "mode", "dated", "other", "check-error")),
                     *(f"risk:rule-{r}" for r in ("max-tokens-below-limit", "max-tokens-inherited-cap", "max-completion-pair", "null-status", "deprecated-conflict", "deprecated-undated", "reasoning-enum", "reasoning-default", "reasoning-unsupported", "feature-enum")),
                     *(f"verify:{v}" for v in ("official", "partial", "conflict", "none")),
                     *(f"kind:{k}" for k in ("price-only", "lifecycle", "features-params", "mixed", "new-model"))}
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


def test_main_requires_env(monkeypatch):
    for k in ("GITHUB_TOKEN", "GH_TOKEN", "GITHUB_REPOSITORY", "GITHUB_EVENT_PATH", "ARTIFACT_DIR"):
        monkeypatch.delenv(k, raising=False)
    assert sync.main() == 2
