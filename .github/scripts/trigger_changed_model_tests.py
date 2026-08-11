#!/usr/bin/env python3
"""Fetch every provider yaml file changed in a PR (cumulative diff vs base),
group by provider, and trigger the gateway-test-job-v2 TrueFoundry job once
per affected provider.

The PR's content is never checked out or executed locally; we only ask the
GitHub API for the list of changed file paths. This means the script picks up
every change introduced by the PR regardless of how many commits made it, and
it cannot be tricked into running attacker-controlled code.

Required env vars:
    GATEWAY_TEST_JOB_V2_FQN  FQN of the deployed gateway-test-job-v2
    PR_NUMBER                GitHub PR number (passed through to run.py --pr-number;
                             the job resolves the head commit itself at run time)
    GITHUB_REPOSITORY        owner/repo (auto-set by GitHub Actions)
    GH_TOKEN or GITHUB_TOKEN Token used by `gh api`

Optional env vars:
    GITHUB_OUTPUT            If set, writes "triggered=<count>" for the workflow step

Assumes `gh` and `tfy` are installed; `tfy` is already logged in.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
from collections import defaultdict
from typing import Dict, List

_SAFE_PROVIDER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_SAFE_MODEL = re.compile(r"^[A-Za-z0-9~][A-Za-z0-9._@:/~-]*$")

# Yamls under providers/ that describe the provider itself, not a model. There is
# nothing per-model to test for these, so they never trigger a test run.
NON_MODEL_YAML = frozenset({"default.yaml", "provider-config.yaml"})


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        sys.exit(f"::error::{name} must be set")
    return value


def _run(cmd: List[str], check: bool = True) -> str:
    """Run a command and return its stdout, stripped."""
    result = subprocess.run(cmd, capture_output=True, text=True)
    if check and result.returncode != 0:
        sys.exit(
            f"::error::Command failed ({result.returncode}): {' '.join(cmd)}\n"
            f"stderr: {result.stderr.strip()}"
        )
    return result.stdout.strip()


def _fetch_pr_files(repo: str, pr_number: str) -> List[dict]:
    """Fetch all files changed in a PR via the GitHub REST API.

    The /pulls/{n}/files endpoint returns the cumulative diff between the PR
    head and its merge base — i.e. one entry per file regardless of how many
    commits in the PR touched it. We pass --paginate so `gh` walks past the
    100-entry per-page cap automatically and returns a single merged JSON
    array.
    """
    raw = _run([
        "gh", "api",
        "--paginate",
        f"/repos/{repo}/pulls/{pr_number}/files",
    ])
    return json.loads(raw)


def _changed_provider_yaml_paths(files: List[dict]) -> List[str]:
    """Filter the PR file list to model yamls that still exist post-PR.

    Removed files are skipped — there's nothing to test for a model the PR
    deletes. Non-yaml and non-providers paths are dropped entirely, as are
    provider-scoped yamls (see NON_MODEL_YAML), which name no model to test.
    """
    paths: List[str] = []
    for entry in files:
        if entry.get("status") == "removed":
            continue
        path = entry.get("filename", "")
        if not path.startswith("providers/") or not path.endswith(".yaml"):
            continue
        if os.path.basename(path) in NON_MODEL_YAML:
            print(f"Skipping provider-scoped yaml: {path}")
            continue
        paths.append(path)
    return paths


def _is_significant(_file: str) -> bool:
    """Stub for a future significance check.

    Replace with real logic later (e.g. inspect yaml keys that affect runtime
    behavior such as mode, features, messages, params).
    """
    return True


def _parse_provider_model(path: str) -> tuple[str, str]:
    """Parse providers/<provider>/<model...>.yaml into (provider, model).

    Raises ValueError with a specific reason if the path is malformed or
    contains unsafe characters.
    """
    if not path.startswith("providers/"):
        raise ValueError("not under providers/")
    rel = path[len("providers/"):]
    if "/" not in rel:
        raise ValueError("missing model segment")
    provider, _, model_with_ext = rel.partition("/")
    if not model_with_ext.endswith(".yaml"):
        raise ValueError("not a .yaml file")
    model = model_with_ext[: -len(".yaml")]
    if not _SAFE_PROVIDER.match(provider):
        raise ValueError(f"provider contains unsafe characters: {provider!r}")
    if not _SAFE_MODEL.match(model):
        raise ValueError(f"model contains unsafe characters: {model!r}")
    return provider, model


def _write_output(triggered: int) -> None:
    output_path = os.environ.get("GITHUB_OUTPUT")
    if not output_path:
        return
    with open(output_path, "a") as f:
        f.write(f"triggered={triggered}\n")


def main() -> None:
    job_fqn = _require_env("GATEWAY_TEST_JOB_V2_FQN")
    pr_number = _require_env("PR_NUMBER")
    repo = _require_env("GITHUB_REPOSITORY")

    files = _fetch_pr_files(repo, pr_number)
    changed = _changed_provider_yaml_paths(files)

    if not changed:
        print(f"No provider yaml files changed in PR #{pr_number}")
        _write_output(0)
        return

    provider_to_models: Dict[str, List[str]] = defaultdict(list)
    for path in changed:
        if not _is_significant(path):
            print(f"Skipping non-significant change: {path}")
            continue
        try:
            provider, model = _parse_provider_model(path)
        except ValueError as exc:
            sys.exit(f"::error::Cannot parse provider/model from {path}: {exc}")
        provider_to_models[provider].append(model)

    if not provider_to_models:
        print("No provider yaml changes")
        _write_output(0)
        return

    triggered = 0
    for provider, models in provider_to_models.items():
        # Build the command as an argv list and shell-quote each token. Keep
        # --model last so its nargs='+' consumer in run.py can't accidentally
        # swallow other flags. The leading-alphanumeric regex above already
        # rejects model names that would parse as argparse flags.
        argv = [
            "python", "run.py",
            "--pr-mode",
            "--pr-number", pr_number,
            "--provider", provider,
            "--model", *models,
        ]
        command = " ".join(shlex.quote(tok) for tok in argv)
        print(
            f"Triggering tests for provider={provider} "
            f"models={' '.join(models)} pr={pr_number}"
        )
        _run([
            "tfy", "trigger", "job",
            "--application-fqn", job_fqn,
            "--command", command,
        ])
        triggered += 1

    _write_output(triggered)


if __name__ == "__main__":
    main()
