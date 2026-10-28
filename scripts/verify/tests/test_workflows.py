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


def load(name):
    doc = yaml.safe_load((WF / name).read_text())
    doc["on"] = doc.pop(True, doc.get("on"))  # PyYAML reads `on:` as True
    return doc


def steps(doc, job):
    return doc["jobs"][job]["steps"]


def test_verify_pr_is_read_only_and_secretless():
    doc = load("verify-pr.yml")
    assert set(doc["on"]) == {"pull_request"}  # never pull_request_target
    assert doc["permissions"] == {"contents": "read"}
    assert "permissions" not in doc["jobs"]["verify"]  # no job widens it
    text = (WF / "verify-pr.yml").read_text()
    assert not re.search(r"\$\{\{\s*secrets", text) and "pull_request_target" not in text
    assert any(s.get("uses", "").startswith("actions/upload-artifact") for s in steps(doc, "verify"))
    checkout = next(s for s in steps(doc, "verify") if s.get("uses", "").startswith("actions/checkout"))
    assert checkout["with"]["fetch-depth"] == 0
    run = next(s for s in steps(doc, "verify") if "python -m verify" in s.get("run", ""))
    assert "continue-on-error" not in run and "|| true" not in run["run"]


def test_no_expression_is_interpolated_into_a_shell_script():
    for name in ("verify-pr.yml", "verify-label.yml", "verify-tests.yml"):
        doc = load(name)
        for job in doc["jobs"].values():
            for step in job["steps"]:
                assert "${{" not in step.get("run", ""), (name, step.get("name"))


def test_verify_label_never_checks_out_the_pr_and_has_the_minimum_permissions():
    doc = load("verify-label.yml")
    assert doc["on"] == {"workflow_run": {"workflows": ["Verify PR"], "types": ["completed"]}}
    assert load("verify-pr.yml")["name"] == "Verify PR"
    assert doc["permissions"] == {}
    job = doc["jobs"]["sync"]
    assert job["permissions"] == {"actions": "read", "contents": "read", "pull-requests": "write", "checks": "write"}
    text = (WF / "verify-label.yml").read_text()
    assert "pull_request_target" not in text
    for s in job["steps"]:
        if s.get("uses", "").startswith("actions/checkout"):
            assert s["with"]["ref"] == "${{ github.event.repository.default_branch }}"
            assert s["with"]["persist-credentials"] is False
            assert s["with"]["sparse-checkout"] == "scripts/verify"
        ref = str(s.get("with", {}).get("ref", ""))
        assert "head_sha" not in ref and "head_branch" not in ref and "pull_request" not in ref
    cond = job["if"]
    assert "conclusion == 'success'" in cond and "event == 'pull_request'" in cond and "trueforge/" in cond
    assert any("-m verify.sync" in s.get("run", "") for s in job["steps"])
    # the artifact is downloaded, never executed or imported
    dl = next(s for s in job["steps"] if s.get("uses", "").startswith("actions/download-artifact"))
    assert dl["with"]["name"] == "verify-result" and "run-id" in dl["with"]


def test_verify_tests_triggers_on_the_package_and_the_registry():
    doc = load("verify-tests.yml")
    paths = doc["on"]["pull_request"]["paths"]
    assert "scripts/verify/**" in paths and "sources/registry.yaml" in paths
    assert doc["permissions"] == {"contents": "read"}


def test_the_label_job_code_is_stdlib_only_and_does_not_import_the_verifier():
    for mod in ("sync.py", "labels.py"):
        tree = ast.parse((PKG / mod).read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                if node.level:  # relative: only the label constants
                    assert node.module == "labels", (mod, node.module)
                    continue
                names = [(node.module or "").split(".")[0]]
            else:
                continue
            assert all(n in sys.stdlib_module_names for n in names), (mod, names)


@pytest.mark.skipif(not (shutil.which("actionlint") or Path("/opt/homebrew/bin/actionlint").exists()), reason="no actionlint")
def test_actionlint_passes():
    exe = shutil.which("actionlint") or "/opt/homebrew/bin/actionlint"
    files = [str(WF / n) for n in ("verify-pr.yml", "verify-label.yml", "verify-tests.yml")]
    p = subprocess.run([exe, *files], capture_output=True, text=True)
    assert p.returncode == 0, p.stdout + p.stderr


def test_verify_pr_pins_nothing_to_a_moving_python():
    text = (WF / "verify-pr.yml").read_text()
    assert re.search(r"python-version: '3\.\d+'", text)
