import json
import subprocess

import pytest
import yaml

from verify import cli, sources
from verify.sync import validate

from .helpers import IN, FakeSource, base, check, price, registry, result

BASE_SHA = "b" * 40
HEAD_SHA = "a" * 40


class FakeRepo:
    def __init__(self, changed, files):
        self._changed, self.files = changed, files

    def merge_base(self, base, head):
        return "MB"

    def changed(self, base, head):
        assert base == "MB"  # the diff is taken from the merge base
        return self._changed

    def show(self, ref, path):
        return self.files.get((ref, path))


def dump(d):
    return yaml.safe_dump(d, sort_keys=True)


def loader(src):
    return lambda names: [src] if src.name in names else []


def run(repo, src=None, **kw):
    return cli.run(repo, BASE_SHA, HEAD_SHA, registry=registry(("p", "fake")) if src else None,
                   load_sources=loader(src) if src else (lambda names: []), **kw)


PATH = "providers/p/m.yaml"


def one_file_repo(after):
    return FakeRepo([("M", PATH)], {("MB", PATH): dump(base()), (HEAD_SHA, PATH): dump(after)})


def test_result_shape_and_validates_against_the_label_schema():
    out = run(one_file_repo(price(input_cost_per_token=3.1e-6)), FakeSource(res=result(check(IN))))
    assert (out["gate"], out["kind"], out["verify"]) == ("review", "price-only", "official")
    assert out["labels"] == ["gate:review", "kind:price-only", "risk:price", "shadow:auto", "verify:official"]
    assert set(out) == {"version", "base_sha", "head_sha", "skipped", "labels", "gate", "kind", "verify", "shadow", "lane", "files",
                        "files_total", "files_omitted", "notes", "comment_md", "summary_md"}
    validate(json.loads(json.dumps(out)))  # exactly what the label job accepts


def test_trueforge_branch_is_skipped_entirely():
    repo = FakeRepo([], {})  # would assert if touched
    out = cli.run(repo, BASE_SHA, HEAD_SHA, head_ref="trueforge/models-update")
    assert out["skipped"] == "trueforge-branch" and out["labels"] == [] and out["comment_md"] == ""
    validate(json.loads(json.dumps(out)))
    out = run(one_file_repo(price(input_cost_per_token=3.1e-6)), head_ref="feat/trueforge/x")
    assert out["skipped"] is None  # only a PREFIX is skipped


def test_only_model_yaml_files_get_a_model_check_and_provider_wide_files_escalate():
    changed = [("M", p) for p in ("providers/p/default.yaml", "providers/p/provider-config.yaml", "providers/p/readme.md",
                                  "providers/p.yaml", "scripts/x.yaml", "providers/p/sub/m.yaml")]
    files = {("MB", "providers/p/sub/m.yaml"): dump(base()), (HEAD_SHA, "providers/p/sub/m.yaml"): dump(price(input_cost_per_token=3.1e-6))}
    out = run(FakeRepo(changed, files))
    assert [f["path"] for f in out["files"]] == ["providers/p/default.yaml", "providers/p/provider-config.yaml", "providers/p/sub/m.yaml"]
    assert out["gate"] == "escalate" and "risk:provider-default" in out["labels"]
    assert "Provider-wide change" in out["comment_md"] and "No model YAML" not in out["comment_md"]


def test_only_the_provider_level_default_counts_a_nested_one_changes_nothing():
    assert cli.is_provider_file("providers/p/default.yaml") and cli.is_provider_file("providers/p/provider-config.yaml")
    assert not cli.is_provider_file("providers/p/sub/default.yaml") and not cli.is_provider_file("providers/default.yaml")
    assert not cli.is_provider_file("providers/p/m.yaml") and not cli.is_model_file("providers/p/sub/default.yaml")
    out = run(FakeRepo([("M", "providers/p/sub/default.yaml")], {}))
    assert out["labels"] == [] and out["files"] == []


def test_a_default_yaml_only_pr_is_not_nothing_to_verify():
    out = run(FakeRepo([("M", "providers/openai/default.yaml")], {}))
    assert (out["gate"], out["kind"], out["verify"]) == ("escalate", "provider-default", "none")
    assert out["labels"] == ["gate:escalate", "kind:provider-default", "risk:provider-default", "verify:none"]
    assert "0 changed model file(s), 1 provider default file(s)" in out["comment_md"]
    assert "`openai`" in out["comment_md"] and "affects every model" in out["comment_md"]
    validate(json.loads(json.dumps(out)))
    deleted = run(FakeRepo([("D", "providers/openai/provider-config.yaml")], {}))
    assert (deleted["gate"], deleted["kind"]) == ("escalate", "provider-default")


def test_a_default_yaml_plus_a_model_change_is_mixed_and_counts_both():
    files = {("MB", PATH): dump(base()), (HEAD_SHA, PATH): dump(price(input_cost_per_token=3.1e-6))}
    out = run(FakeRepo([("M", "providers/p/default.yaml"), ("M", PATH)], files))
    assert out["kind"] == "mixed" and "1 changed model file(s), 1 provider default file(s)" in out["comment_md"]


def test_a_modified_file_whose_base_blob_cannot_be_read_escalates_and_is_not_a_stub_fill():
    files = {(HEAD_SHA, PATH): dump(price(input_cost_per_token=3.1e-6))}      # show("MB", PATH) -> None
    out = run(FakeRepo([("M", PATH)], files))
    assert out["gate"] == "escalate" and "risk:check-error" in out["labels"] and out["kind"] != "new-model"
    assert "base version could not be read" in out["comment_md"] and "(new)" not in out["comment_md"]
    gone = run(FakeRepo([("M", PATH)], {("MB", PATH): dump(base())}))         # head unreadable
    assert gone["gate"] == "escalate" and "head version could not be read" in gone["comment_md"]
    empty = run(FakeRepo([("M", PATH)], {("MB", PATH): "", (HEAD_SHA, PATH): dump(base())}))   # a real empty file IS a stub fill
    assert "risk:check-error" not in empty["labels"] and empty["kind"] == "mixed"


def test_provider_wide_files_get_no_source_check():
    src = FakeSource(res=result(check(IN)))
    out = cli.run(FakeRepo([("M", "providers/p/default.yaml")], {}), BASE_SHA, HEAD_SHA, registry=registry(("p", "fake")),
                  load_sources=loader(src))
    assert src.checked == [] and src.prepared == 0 and out["gate"] == "escalate"


def test_is_model_file():
    assert cli.is_model_file("providers/aws-bedrock/anthropic/x.yaml")
    assert not cli.is_model_file("providers/aws-bedrock/default.yaml")
    assert not cli.is_model_file("providers/aws-bedrock/provider-config.yaml")
    assert not cli.is_model_file("providers/x.yaml")
    assert not cli.is_model_file("other/p/x.yaml")
    assert not cli.is_model_file("providers/p/x.yml")


def test_added_deleted_modified():
    files = {("MB", "providers/p/gone.yaml"): dump(base()), (HEAD_SHA, "providers/p/new.yaml"): dump(base()),
             ("MB", PATH): dump(base()), (HEAD_SHA, PATH): dump(price(input_cost_per_token=3.1e-6))}
    out = run(FakeRepo([("A", "providers/p/new.yaml"), ("D", "providers/p/gone.yaml"), ("M", PATH)], files))
    status = {f["path"]: f["status"] for f in out["files"]}
    assert status == {"providers/p/gone.yaml": "deleted", "providers/p/new.yaml": "added", PATH: "modified"}
    assert out["gate"] == "escalate" and out["kind"] == "mixed"


def test_current_labels_make_hold():
    out = run(one_file_repo(price(input_cost_per_token=3.1e-6)), current_labels=["gate:hold"])
    assert out["gate"] == "hold" and not any(x.startswith("gate:") for x in out["labels"])


def test_a_crash_in_one_file_still_gives_the_pr_a_gate(monkeypatch):
    monkeypatch.setattr(cli.build, "build_file", lambda *a: (_ for _ in ()).throw(RuntimeError("boom")))
    out = run(one_file_repo(price(input_cost_per_token=3.1e-6)))
    assert out["gate"] == "escalate" and "risk:check-error" in out["labels"]


def test_registry_note_is_carried_into_the_comment():
    out = run(one_file_repo(price(input_cost_per_token=3.1e-6)), registry_note="source registry unusable: x")
    assert out["notes"] == ["source registry unusable: x"] and "registry unusable" in out["comment_md"]


def test_adapters_not_in_the_registry_for_the_touched_providers_are_not_loaded():
    asked = []
    out = cli.run(one_file_repo(price(input_cost_per_token=3.1e-6)), BASE_SHA, HEAD_SHA,
                  registry=registry(("other", "x"), ("p", "fake")), load_sources=lambda names: asked.append(set(names)) or [])
    assert asked == [{"fake"}] and out["verify"] == "partial"  # registered but unavailable -> partial, not a crash


# ---- end to end against a real git repo ---------------------------------------------
def git(root, *args):
    return subprocess.run(["git", "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@t", *args],
                          check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    git(tmp_path, "init", "-q", "-b", "main")
    (tmp_path / "providers" / "p").mkdir(parents=True)
    (tmp_path / "sources").mkdir()
    (tmp_path / "sources" / "registry.yaml").write_text(
        "version: 1\nsources:\n  - {provider: p, kind: api, source: fake, fields: [price], added: 2026-10-27}\n")
    (tmp_path / "providers" / "p" / "m.yaml").write_text(dump(base()))
    (tmp_path / "providers" / "p" / "default.yaml").write_text("x: 1\n")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-qm", "base")
    return tmp_path


def commit_change(repo, **price_kw):
    git(repo, "checkout", "-q", "-b", "pr")
    (repo / "providers" / "p" / "m.yaml").write_text(dump(price(**price_kw)))
    git(repo, "commit", "-qam", "change")


def test_main_end_to_end_on_a_real_repo(repo, tmp_path_factory, monkeypatch, capsys):
    commit_change(repo, input_cost_per_token=3.1e-6)
    src = FakeSource(res=result(check(IN)))
    monkeypatch.setattr(sources, "SOURCES", {"fake": lambda: src})
    out = tmp_path_factory.mktemp("out") / "r.json"
    summary = out.parent / "s.md"
    rc = cli.main(["--base", git(repo, "rev-parse", "main"), "--head", git(repo, "rev-parse", "HEAD"), "--repo", str(repo),
                   "--json", str(out), "--summary-md", str(summary), "--current-labels-json", '["bug", {"name": "x"}]'])
    assert rc == 0
    data = json.loads(out.read_text())
    assert data["labels"] == ["gate:review", "kind:price-only", "risk:price", "shadow:auto", "verify:official"]
    assert [f["path"] for f in data["files"]] == ["providers/p/m.yaml"]
    assert summary.read_text() == data["summary_md"]
    assert "gate=review" in capsys.readouterr().out
    validate(data)


def test_main_prints_json_and_exits_zero_whatever_the_verdict(repo, monkeypatch, capsys):
    commit_change(repo, input_cost_per_token=9e-6)  # escalates
    monkeypatch.setattr(sources, "SOURCES", {})
    rc = cli.main(["--base", "main", "--head", "HEAD", "--repo", str(repo)])
    data = json.loads(capsys.readouterr().out)
    assert rc == 0 and data["gate"] == "escalate" and data["verify"] == "partial"  # adapter registered, none loaded


def test_main_uses_the_merge_base_not_a_moved_base_tip(repo, monkeypatch, capsys):
    commit_change(repo, input_cost_per_token=3.1e-6)
    git(repo, "checkout", "-q", "main")
    (repo / "providers" / "p" / "other.yaml").write_text(dump(base()))
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "main moved")
    monkeypatch.setattr(sources, "SOURCES", {})
    cli.main(["--base", "main", "--head", "pr", "--repo", str(repo)])
    data = json.loads(capsys.readouterr().out)
    assert [f["path"] for f in data["files"]] == ["providers/p/m.yaml"]  # not other.yaml "deleted"


def test_bad_registry_does_not_crash_the_run(repo, monkeypatch, capsys):
    (repo / "sources" / "registry.yaml").write_text("sources: [1]\n")
    commit_change(repo, input_cost_per_token=3.1e-6)
    cli.main(["--base", "main", "--head", "HEAD", "--repo", str(repo)])
    data = json.loads(capsys.readouterr().out)
    assert data["gate"] == "unverified" and "registry unusable" in data["comment_md"]


def test_bad_sha_is_a_crash_not_a_verdict(repo):
    with pytest.raises(RuntimeError):
        cli.main(["--base", "0" * 40, "--head", "1" * 40, "--repo", str(repo)])


def test_python_dash_m_entrypoint(repo, tmp_path):
    commit_change(repo, input_cost_per_token=3.1e-6)
    scripts = __import__("pathlib").Path(__file__).resolve().parents[2]
    p = subprocess.run([__import__("sys").executable, "-B", "-m", "verify", "--base", "main", "--head", "HEAD", "--repo", str(repo)],
                       cwd=scripts, capture_output=True, text=True)
    assert p.returncode == 0, p.stderr
    assert json.loads(p.stdout)["gate"] == "unverified"


def test_a_real_repo_default_yaml_change_escalates(repo, monkeypatch, capsys):
    git(repo, "checkout", "-q", "-b", "pr")
    (repo / "providers" / "p" / "default.yaml").write_text("x: 2\n")
    git(repo, "commit", "-qam", "default")
    monkeypatch.setattr(sources, "SOURCES", {})
    cli.main(["--base", "main", "--head", "HEAD", "--repo", str(repo)])
    data = json.loads(capsys.readouterr().out)
    assert data["gate"] == "escalate" and "risk:provider-default" in data["labels"]


# ---- very large PRs ------------------------------------------------------------------------------
def big_repo(n, escalate_every=0):
    changed, files = [], {}
    for i in range(n):
        path = f"providers/p/model-{i:05d}.yaml"
        changed.append(("M", path))
        after = price(input_cost_per_token=3.1e-6 * (3 if escalate_every and i % escalate_every == 0 else 1))
        files[("MB", path)] = dump(base())
        files[(HEAD_SHA, path)] = dump(after)
    return FakeRepo(changed, files)


def test_a_3000_file_pr_keeps_every_label_and_the_gate_and_only_the_file_list_is_cut():
    out = run(big_repo(3000, escalate_every=1000), FakeSource(res=result(check(IN))))
    assert out["gate"] == "escalate" and "risk:price" in out["labels"] and out["kind"] == "price-only"
    assert out["files_total"] == 3000 and len(out["files"]) == cli.MAX_FILES_LISTED
    assert out["files_omitted"] == 3000 - cli.MAX_FILES_LISTED
    paths = [f["path"] for f in out["files"]]
    assert paths == sorted(paths)
    # the most severe files are the ones kept
    assert {"providers/p/model-00000.yaml", "providers/p/model-01000.yaml", "providers/p/model-02000.yaml"} <= set(paths)
    assert len(json.dumps(out)) < 700_000
    assert len(out["comment_md"]) <= 60_000 and len(out["summary_md"]) <= 60_000
    assert "more file(s) not shown" in out["comment_md"]
    validate(json.loads(json.dumps(out)))  # the label job accepts it


def test_a_pr_under_the_list_limit_lists_every_file():
    out = run(big_repo(10))
    assert out["files_total"] == 10 and out["files_omitted"] == 0 and len(out["files"]) == 10


def test_the_list_keeps_loud_files_before_quiet_ones_when_cut(monkeypatch):
    monkeypatch.setattr(cli, "MAX_FILES_LISTED", 3)
    out = run(big_repo(50, escalate_every=25))   # files 0 and 25 escalate
    kept = [f["path"] for f in out["files"]]
    assert "providers/p/model-00000.yaml" in kept and "providers/p/model-00025.yaml" in kept and len(kept) == 3


def test_lone_surrogates_in_text_do_not_crash_writing_the_outputs(tmp_path):
    out = tmp_path / "o.md"
    cli.write_text(out, "ok \ud800 end")
    assert out.read_text(encoding="utf-8") == "ok ? end"
    cli.write_text(tmp_path / "p.json", "plain")


def test_an_addition_flag_label_reaches_the_comment_as_a_reason_line():
    out = run(one_file_repo(price(input_cost_per_token=3.1e-6)), FakeSource(res=result(check(IN))), current_labels=["id:case-duplicate"])
    assert out["gate"] == "escalate" and out["lane"] == "escalate" and "gate:escalate" in out["labels"]
    assert "addition flagged: case duplicate of an existing file" in out["comment_md"]
    assert "id:case-duplicate" not in out["labels"]
    validate(json.loads(json.dumps(out)))


# ---- the hold note is its own line, independent of the lane block ---------------------------------------
def test_a_hold_pr_gets_the_hold_note_in_the_header_and_other_prs_do_not():
    held = run(one_file_repo(price(input_cost_per_token=3.1e-6)), FakeSource(res=result(check(IN))), current_labels=["gate:hold"])
    assert held["gate"] == "hold" and "so no gate is set here. Remove it once checked." in held["comment_md"]
    free = run(one_file_repo(price(input_cost_per_token=3.1e-6)), FakeSource(res=result(check(IN))))
    assert "Remove it once checked" not in free["comment_md"]


def test_the_trueforge_skip_ignores_case():
    for ref in ("trueforge/x", "TrueForge/x", "TRUEFORGE/X"):
        assert cli.run(FakeRepo([], {}), BASE_SHA, HEAD_SHA, head_ref=ref)["skipped"] == "trueforge-branch", ref
    assert cli.run(one_file_repo(base()), BASE_SHA, HEAD_SHA, head_ref="trueforgery/x")["skipped"] is None


def test_an_oversized_blob_is_unreadable_not_truncated(repo, monkeypatch):
    git(repo, "checkout", "-q", "-b", "pr")
    (repo / "providers" / "p" / "m.yaml").write_text(dump(price(input_cost_per_token=3.1e-6)))
    git(repo, "commit", "-qam", "change")
    size = len((repo / "providers" / "p" / "m.yaml").read_bytes())
    g = cli.GitRepo(repo)
    monkeypatch.setattr(cli, "MAX_BLOB", size)                       # exactly at the cap: readable
    assert g.show("HEAD", "providers/p/m.yaml") is not None
    monkeypatch.setattr(cli, "MAX_BLOB", size - 1)                   # one byte over: None, never a cut-off text
    assert g.show("HEAD", "providers/p/m.yaml") is None
    assert g.show("HEAD", "providers/p/missing.yaml") is None
