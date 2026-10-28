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
    assert set(out) == {"version", "base_sha", "head_sha", "skipped", "labels", "gate", "kind", "verify", "shadow", "files",
                        "notes", "comment_md", "summary_md"}
    validate(json.loads(json.dumps(out)))  # exactly what the label job accepts


def test_trueforge_branch_is_skipped_entirely():
    repo = FakeRepo([], {})  # would assert if touched
    out = cli.run(repo, BASE_SHA, HEAD_SHA, head_ref="trueforge/models-update")
    assert out["skipped"] == "trueforge-branch" and out["labels"] == [] and out["comment_md"] == ""
    validate(json.loads(json.dumps(out)))
    out = run(one_file_repo(price(input_cost_per_token=3.1e-6)), head_ref="feat/trueforge/x")
    assert out["skipped"] is None  # only a PREFIX is skipped


def test_only_model_yaml_files_are_considered():
    changed = [("M", p) for p in ("providers/p/default.yaml", "providers/p/provider-config.yaml", "providers/p/readme.md",
                                  "providers/p.yaml", "scripts/x.yaml", "providers/p/sub/m.yaml")]
    files = {("MB", "providers/p/sub/m.yaml"): dump(base()), (HEAD_SHA, "providers/p/sub/m.yaml"): dump(price(input_cost_per_token=3.1e-6))}
    out = run(FakeRepo(changed, files))
    assert [f["path"] for f in out["files"]] == ["providers/p/sub/m.yaml"]


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
    (repo / "providers" / "p" / "default.yaml").write_text("x: 2\n")
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
    assert [f["path"] for f in data["files"]] == ["providers/p/m.yaml"]  # default.yaml is ignored
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
