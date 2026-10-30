"""The trusted label job: the PR head arrives as git objects only, never as files."""
import json
import subprocess
import sys

import pytest
import yaml

from verify import labeljob, sources
from verify.sync import Stale, SyncError

from .helpers import base, price


def git(root, *args, env=None):
    return subprocess.run(["git", "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@t", *args],
                          check=True, capture_output=True, text=True, env=env).stdout.strip()


def dump(d):
    return yaml.safe_dump(d, sort_keys=True)


@pytest.fixture
def world(tmp_path):
    """origin with main and a PR head under refs/pull/7/head; `trusted` is a clone of main."""
    origin = tmp_path / "origin"
    git(tmp_path, "init", "-q", "-b", "main", str(origin))
    git(origin, "config", "uploadpack.allowAnySHA1InWant", "true")
    (origin / "providers" / "p").mkdir(parents=True)
    (origin / "sources").mkdir()
    (origin / ".github" / "test").mkdir(parents=True)
    (origin / ".github" / "test" / "model.cue").write_text('#Feature:\n\t"function_calling" |\n\t"prompt_caching"\n\n#X: 1\n')
    (origin / "sources" / "registry.yaml").write_text("version: 1\nsources: []\n")
    (origin / "providers" / "p" / "m.yaml").write_text(dump(base()))
    git(origin, "add", "-A")
    git(origin, "commit", "-qm", "base")
    base_sha = git(origin, "rev-parse", "HEAD")
    git(origin, "checkout", "-q", "-b", "pr")
    # the PR: a price change, plus files that would be dangerous if they were ever checked out
    (origin / "providers" / "p" / "m.yaml").write_text(dump(price(input_cost_per_token=3.1e-6)))
    (origin / "scripts" / "yaml").mkdir(parents=True)
    (origin / "scripts" / "yaml" / "__init__.py").write_text("raise SystemExit('PR code ran')\n")
    (origin / "scripts" / "verify").mkdir()
    (origin / "scripts" / "verify" / "__init__.py").write_text("raise SystemExit('PR verifier ran')\n")
    (origin / "sources" / "registry.yaml").write_text("version: 1\nsources:\n  - {provider: p, kind: api, source: evil, fields: [price], added: 2026-10-27}\n")
    (origin / ".github" / "test" / "model.cue").write_text('#Feature:\n\t"function_calling" |\n\t"prompt_caching" |\n\t"bogus"\n\n#X: 1\n')
    git(origin, "add", "-A")
    git(origin, "commit", "-qm", "pr")
    head_sha = git(origin, "rev-parse", "HEAD")
    git(origin, "update-ref", "refs/pull/7/head", head_sha)
    git(origin, "checkout", "-q", "main")
    git(origin, "branch", "-D", "pr")
    trusted = tmp_path / "trusted"
    git(tmp_path, "clone", "-q", str(origin), str(trusted))
    return type("W", (), dict(origin=origin, trusted=trusted, base=base_sha, head=head_sha))


def pr_of(w, ref="feat/x", number=7):
    return {"number": number, "base": {"sha": w.base}, "head": {"sha": w.head, "ref": ref}}


def test_the_pr_head_is_fetched_as_objects_and_never_checked_out(world):
    labeljob.fetch_head(str(world.trusted), 7, world.head)
    assert subprocess.run(["git", "-C", str(world.trusted), "cat-file", "-e", world.head]).returncode == 0
    assert not (world.trusted / "scripts").exists()                      # no PR file on disk
    assert git(world.trusted, "rev-parse", "HEAD") == world.base          # HEAD did not move
    assert git(world.trusted, "status", "--porcelain") == ""
    assert git(world.trusted, "rev-parse", "refs/verify/pr-7") == world.head


def test_a_moved_head_is_stale_and_a_missing_ref_is_an_error(world):
    other = git(world.origin, "commit-tree", "-p", world.head, "-m", "x", f"{world.head}^{{tree}}")
    git(world.origin, "update-ref", "refs/pull/7/head", other)
    with pytest.raises(Stale):
        labeljob.fetch_head(str(world.trusted), 7, world.head)
    with pytest.raises(SyncError):
        labeljob.fetch_head(str(world.trusted), 99, world.head)


def test_a_missing_base_commit_is_fetched(world, tmp_path):
    shallow = tmp_path / "shallow"
    subprocess.run(["git", "clone", "-q", "--depth", "1", f"file://{world.origin}", str(shallow)], check=True)
    # depth 1 of main: the base commit is the tip, fine; make a deeper base absent instead
    parent = git(world.origin, "commit-tree", "-m", "older", f"{world.base}^{{tree}}")
    assert subprocess.run(["git", "-C", str(shallow), "cat-file", "-e", parent]).returncode != 0
    git(world.origin, "update-ref", "refs/heads/older", parent)
    labeljob.fetch_head(str(shallow), 7, world.head, base_sha=parent)
    assert subprocess.run(["git", "-C", str(shallow), "cat-file", "-e", parent]).returncode == 0


def test_the_token_goes_in_the_environment_not_in_argv(world, monkeypatch):
    seen = []
    real = subprocess.run

    def spy(args, **kw):
        seen.append((list(args), kw.get("env") or {}))
        return real(args, **kw)
    monkeypatch.setattr(labeljob.subprocess, "run", spy)
    labeljob.fetch_head(str(world.trusted), 7, world.head, token="s3cr3t-token")
    assert not any("s3cr3t-token" in " ".join(a) or "x-access-token" in " ".join(a) for a, _ in seen)
    fetch_env = next(e for a, e in seen if "fetch" in a)
    assert fetch_env["GIT_CONFIG_COUNT"] == "1" and "AUTHORIZATION" in fetch_env["GIT_CONFIG_VALUE_0"]
    assert fetch_env["GIT_TERMINAL_PROMPT"] == "0"


def test_compute_runs_the_default_branch_verifier_and_reads_the_pr_only_as_blobs(world, monkeypatch):
    monkeypatch.setattr(sources, "SOURCES", {})
    result = labeljob.make_compute(str(world.trusted), "")(pr_of(world), ["bug"])
    assert result["head_sha"] == world.head and result["skipped"] is None
    assert [f["path"] for f in result["files"]] == ["providers/p/m.yaml"]
    assert "risk:price" in result["labels"]
    # the PR's registry (evil adapter) was NOT used: the trusted checkout's empty registry was
    assert not any("evil" in n for n in result["notes"]) and result["verify"] == "none"
    # the PR's CUE file (which allows a 'bogus' feature) was NOT used either
    assert not (world.trusted / "scripts").exists()
    assert str(world.trusted) not in (sys.modules["yaml"].__file__ or "")  # PyYAML is the installed one, not a PR shadow
    json.dumps(result)


def test_the_schema_for_the_enum_rules_is_the_default_branchs_not_the_prs(world, monkeypatch):
    monkeypatch.setattr(sources, "SOURCES", {})
    doc = price(input_cost_per_token=3.1e-6)
    doc["features"] = ["function_calling", "bogus"]
    git(world.origin, "checkout", "-q", "-b", "pr2", world.head)
    (world.origin / "providers" / "p" / "m.yaml").write_text(dump(doc))
    git(world.origin, "commit", "-qam", "bogus feature")
    head2 = git(world.origin, "rev-parse", "HEAD")
    git(world.origin, "update-ref", "refs/pull/8/head", head2)
    pr = {"number": 8, "base": {"sha": world.base}, "head": {"sha": head2, "ref": "feat/y"}}
    result = labeljob.make_compute(str(world.trusted), "")(pr, [])
    assert "risk:rule-feature-enum" in result["labels"] and result["gate"] == "escalate"  # PR's cue says bogus is fine; ours says no


def test_a_trueforge_branch_is_skipped_without_fetching(world, monkeypatch):
    monkeypatch.setattr(labeljob, "fetch_head", lambda *a, **k: pytest.fail("must not fetch"))
    result = labeljob.make_compute(str(world.trusted), "")(pr_of(world, ref="trueforge/models"), [])
    assert result["skipped"] == "trueforge-branch"


def test_main_requires_its_environment(monkeypatch):
    for k in ("GITHUB_TOKEN", "GH_TOKEN", "GITHUB_REPOSITORY", "GITHUB_EVENT_PATH", "VERIFY_ROOT", "GITHUB_WORKSPACE"):
        monkeypatch.delenv(k, raising=False)
    assert labeljob.main() == 2
