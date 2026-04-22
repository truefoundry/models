#!/usr/bin/env python3
"""Diff the tip commit for changed provider yaml files, group by provider,
and trigger the gateway-test-job-v2 TrueFoundry job once per provider.

This script is intentionally executed from a TRUSTED checkout (the default
branch), while the PR's contents are exposed read-only via PR_CHECKOUT_DIR.
We never import or execute anything from the PR tree; we only run `git diff`
inside it to discover which provider yamls changed.

Required env vars:
    GATEWAY_TEST_JOB_V2_FQN  FQN of the deployed gateway-test-job-v2
    PR_NUMBER         GitHub PR number (passed through to run.py --pr-number;
                      the job resolves the head commit itself at run time)
    PR_CHECKOUT_DIR   Absolute path to the PR head checkout (untrusted data)

Optional env vars:
    GITHUB_OUTPUT     If set, writes "triggered=<count>" for the workflow step

Assumes `tfy` is installed and already logged in.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List

_SAFE_PROVIDER = re.compile(r"^[A-Za-z0-9._-]+$")
_SAFE_MODEL = re.compile(r"^[A-Za-z0-9._@:/-]+$")


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        sys.exit(f"::error::{name} must be set")
    return value


def _resolve_pr_dir() -> Path:
    """Return the PR checkout directory, validated to be an existing git repo.

    Refuses to fall back to CWD: this script must never operate on the trusted
    checkout, otherwise it would diff the wrong tree.
    """
    pr_dir = Path(_require_env("PR_CHECKOUT_DIR")).resolve()
    if not (pr_dir / ".git").exists():
        sys.exit(f"::error::PR_CHECKOUT_DIR is not a git checkout: {pr_dir}")
    return pr_dir


def _run(cmd: List[str], check: bool = True) -> str:
    """Run a command and return its stdout, stripped."""
    result = subprocess.run(cmd, capture_output=True, text=True)
    if check and result.returncode != 0:
        sys.exit(
            f"::error::Command failed ({result.returncode}): {' '.join(cmd)}\n"
            f"stderr: {result.stderr.strip()}"
        )
    return result.stdout.strip()


def _git(pr_dir: Path, *args: str, check: bool = True) -> str:
    """Run a git subcommand inside the PR checkout."""
    return _run(["git", "-C", str(pr_dir), *args], check=check)


def _diff_base(pr_dir: Path) -> str:
    """Return HEAD^ when it exists, else git's empty-tree SHA.

    On a brand-new branch with a single commit there is no parent. The empty
    tree makes git diff treat every file in HEAD as newly added.
    """
    has_parent = subprocess.run(
        ["git", "-C", str(pr_dir), "rev-parse", "--verify", "--quiet", "HEAD^"],
        capture_output=True,
    ).returncode == 0
    if has_parent:
        return "HEAD^"
    return _git(pr_dir, "hash-object", "-t", "tree", "/dev/null")


def _changed_provider_files(pr_dir: Path, base: str) -> List[str]:
    raw = _git(
        pr_dir,
        "diff", "--name-only", base, "HEAD", "--", "providers/**/*.yaml",
        check=False,
    )
    return [line for line in raw.splitlines() if line]


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
    pr_dir = _resolve_pr_dir()

    base = _diff_base(pr_dir)
    changed = _changed_provider_files(pr_dir, base)

    if not changed:
        print("No provider yaml files changed in tip commit")
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
            print(f"::warning::Skipping {path}: {exc}")
            continue
        provider_to_models[provider].append(model)

    if not provider_to_models:
        print("No provider yaml changes")
        _write_output(0)
        return

    triggered = 0
    for provider, models in provider_to_models.items():
        models_arg = " ".join(models)
        command = (
            f"python run.py --provider {provider} --model {models_arg} "
            f"--pr-mode --pr-number {pr_number}"
        )
        print(f"Triggering tests for provider={provider} models={models_arg} pr={pr_number}")
        _run([
            "tfy", "trigger", "job",
            "--application-fqn", job_fqn,
            "--command", command,
        ])
        triggered += 1

    _write_output(triggered)


if __name__ == "__main__":
    main()
