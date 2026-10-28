"""Structural checks on the three workflows: the security properties must not regress."""
import ast
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[3]
WF = REPO / ".github" / "workflows"
PKG = REPO / "scripts" / "verify"
FILES = ("verify-pr.yml", "verify-label.yml", "verify-tests.yml", "verify-stale.yml")
SHA = re.compile(r"^[A-Za-z0-9._-]+/[A-Za-z0-9._/-]+@[0-9a-f]{40}( #.*)?$")


def load(name):
    doc = yaml.safe_load((WF / name).read_text())
    doc["on"] = doc.pop(True, doc.get("on"))  # PyYAML reads `on:` as True
    return doc


def steps(doc, job):
    return doc["jobs"][job]["steps"]


def all_steps():
    for name in FILES:
        for job in load(name)["jobs"].values():
            for step in job["steps"]:
                yield name, step


def test_verify_pr_is_a_thin_trigger_that_runs_nothing_from_the_pr():
    doc = load("verify-pr.yml")
    assert set(doc["on"]) == {"pull_request"}  # never pull_request_target
    # a human setting / removing gate:hold, or the addition job flagging later, re-runs the verdict
    assert doc["on"]["pull_request"]["types"] == ["opened", "synchronize", "reopened", "labeled", "unlabeled"]
    assert doc["permissions"] == {}
    st = steps(doc, "trigger")
    assert all("uses" not in s for s in st)  # no checkout, no action, no PR code
    text = (WF / "verify-pr.yml").read_text()
    assert not re.search(r"\$\{\{\s*secrets", text) and "pull_request_target" not in text
    assert "python" not in text and "scripts/" not in text and "upload-artifact" not in text
    assert "permissions" not in doc["jobs"]["trigger"]


def test_no_expression_is_interpolated_into_a_shell_script():
    for name, step in all_steps():
        assert "${{" not in step.get("run", ""), (name, step.get("name"))


def test_verify_label_checks_out_only_the_default_branch_and_fetches_nothing_else():
    doc = load("verify-label.yml")
    assert doc["on"] == {"workflow_run": {"workflows": ["Verify PR"], "types": ["completed"]}}
    assert load("verify-pr.yml")["name"] == "Verify PR"
    assert doc["permissions"] == {}
    job = doc["jobs"]["sync"]
    assert job["permissions"] == {"contents": "read", "pull-requests": "write", "checks": "write"}
    assert job["timeout-minutes"] <= 20
    text = (WF / "verify-label.yml").read_text()
    assert "pull_request_target" not in text and "download-artifact" not in text and "actions: read" not in text
    checkouts = [s for s in job["steps"] if s.get("uses", "").startswith("actions/checkout")]
    assert len(checkouts) == 1
    w = checkouts[0]["with"]
    assert w["ref"] == "${{ github.event.repository.default_branch }}"
    assert w["persist-credentials"] is False and w["fetch-depth"] == 0
    for s in job["steps"]:
        for v in (s.get("with") or {}).values():
            assert "head_sha" not in str(v) and "head_branch" not in str(v) and "pull_request" not in str(v)
        assert "checkout" not in s.get("run", "") and "pull/" not in s.get("run", "")  # the PR head is fetched by labeljob.py, objects only
    run = [s for s in job["steps"] if "python -m verify.labeljob" in s.get("run", "")]
    assert len(run) == 1 and run[0]["working-directory"] == "scripts"
    assert "pip install" in "".join(s.get("run", "") for s in job["steps"])
    cond = job["if"]
    assert "event == 'pull_request'" in cond and "trueforge/" in cond


def test_verify_label_has_a_per_pr_concurrency_group_that_does_not_cancel():
    job = load("verify-label.yml")["jobs"]["sync"]
    group = job["concurrency"]["group"]
    assert "workflow_run.pull_requests[0].number" in group and "head_repository.id" in group and "head_branch" in group
    assert job["concurrency"]["cancel-in-progress"] is False


def test_verify_tests_triggers_on_the_package_the_registry_and_the_schema():
    doc = load("verify-tests.yml")
    paths = doc["on"]["pull_request"]["paths"]
    for p in ("scripts/verify/**", "sources/registry.yaml", ".github/test/model.cue", ".github/test/model.rules.cue"):
        assert p in paths
    assert doc["permissions"] == {"contents": "read"}


def test_every_action_is_pinned_to_a_full_commit_sha_with_the_tag_in_a_comment():
    text = {n: (WF / n).read_text() for n in FILES}
    for name, body in text.items():
        for line in body.splitlines():
            m = re.search(r"uses:\s*(\S.*)$", line)
            if m:
                assert SHA.match(m.group(1).strip()) and re.search(r"# v\d+\.\d+\.\d+$", m.group(1).strip()), (name, line)


def test_dependencies_are_pinned_in_every_workflow_that_installs_any():
    for name in ("verify-label.yml", "verify-tests.yml"):
        for s in steps(load(name), next(iter(load(name)["jobs"]))):
            for m in re.finditer(r"pip install (.*)", s.get("run", "")):
                pkgs = re.findall(r'"([^"]+)"', m.group(1))
                assert pkgs and all("==" in p for p in pkgs), (name, m.group(0))


def test_the_apply_module_is_stdlib_only_and_only_the_label_job_entrypoint_imports_the_verifier():
    for mod in ("sync.py", "labels.py", "textclean.py", "queue.py"):
        tree = ast.parse((PKG / mod).read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                if node.level:  # relative: only the label constants and text helpers (the queue also reads sync's client)
                    assert node.module in ("labels", "textclean") or (mod == "queue.py" and node.module == "sync"), (mod, node.module)
                    continue
                names = [(node.module or "").split(".")[0]]
            else:
                continue
            assert all(n in sys.stdlib_module_names for n in names), (mod, names)


@pytest.mark.skipif(not (shutil.which("actionlint") or Path("/opt/homebrew/bin/actionlint").exists()), reason="no actionlint")
def test_actionlint_passes():
    exe = shutil.which("actionlint") or "/opt/homebrew/bin/actionlint"
    p = subprocess.run([exe, *[str(WF / n) for n in FILES]], capture_output=True, text=True)
    assert p.returncode == 0, p.stdout + p.stderr


def test_verify_stale_is_a_daily_default_branch_job_that_can_only_write_issues():
    doc = load("verify-stale.yml")
    assert doc["on"] == {"schedule": [{"cron": "0 8 * * *"}], "workflow_dispatch": None}
    assert doc["permissions"] == {}
    job = doc["jobs"]["queue"]
    assert job["permissions"] == {"contents": "read", "pull-requests": "read", "issues": "write"}
    assert job["timeout-minutes"] <= 20
    assert job["concurrency"]["cancel-in-progress"] is False
    text = (WF / "verify-stale.yml").read_text()
    assert "pull_request" not in text.replace("pull-requests", "") and "workflow_run" not in text
    # a manual run on another branch must not execute that branch's code with a write token
    assert "default_branch" in job["if"] and "github.ref" in job["if"]
    checkouts = [s for s in job["steps"] if s.get("uses", "").startswith("actions/checkout")]
    assert len(checkouts) == 1 and checkouts[0]["with"]["ref"] == "${{ github.event.repository.default_branch }}"
    assert checkouts[0]["with"]["persist-credentials"] is False
    run = [s for s in job["steps"] if "python -m verify.queue" in s.get("run", "")]
    assert len(run) == 1 and run[0]["working-directory"] == "scripts" and "--dry-run" not in run[0]["run"]
    assert "pip install" not in text                      # stdlib only
    assert doc["jobs"]["queue"]["steps"][-1]["env"] == {"GITHUB_TOKEN": "${{ secrets.GITHUB_TOKEN }}"}


def test_verify_stale_never_runs_for_a_pull_request_event():
    assert set(load("verify-stale.yml")["on"]) == {"schedule", "workflow_dispatch"}


def test_label_writes_cannot_loop_and_runs_collapse_per_pr():
    """The label job writes with GITHUB_TOKEN (events it causes never start a workflow run), reads the
    PR's live labels, and both workflows serialise per PR so a burst of label events is one verdict."""
    pr, label = load("verify-pr.yml"), load("verify-label.yml")
    assert pr["concurrency"]["group"].endswith("${{ github.event.pull_request.number }}") and pr["concurrency"]["cancel-in-progress"] is True
    assert label["jobs"]["sync"]["concurrency"]["cancel-in-progress"] is False
    text = (WF / "verify-label.yml").read_text()
    assert "secrets.GITHUB_TOKEN" in text and not re.search(r"secrets\.(?!GITHUB_TOKEN)", text)   # no PAT / app token that would re-trigger
    assert "trueforge/" in label["jobs"]["sync"]["if"]
