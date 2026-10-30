"""python -m verify.labeljob: the whole verdict, computed and applied by the trusted label job.

Runs from a checkout of the DEFAULT branch (verify-label.yml); that checkout is the only code and
the only registry / CUE schema that is ever executed or trusted. The PR head is fetched as git
OBJECTS into a private ref and never checked out: the verifier reads its blobs with `git show`
and parses them as untrusted data (yamlio.parse). Nothing from the PR's own workflow run is used.
"""
from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
from pathlib import Path

from . import cli
from .sync import GitHub, Stale, SyncError, ValidationError, sync


def _git(root: str, *args: str, env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", root, *args], capture_output=True, text=True, env=env, check=False)


def fetch_head(root: str, number: int, head_sha: str, token: str = "", base_sha: str = "") -> None:
    """Bring the PR head (and the base commit, if missing) into the object store of the trusted
    checkout. No working tree is touched. The token travels in the environment, not in argv."""
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0")
    if token:
        basic = base64.b64encode(f"x-access-token:{token}".encode()).decode()
        env.update(GIT_CONFIG_COUNT="1", GIT_CONFIG_KEY_0="http.https://github.com/.extraheader",
                   GIT_CONFIG_VALUE_0=f"AUTHORIZATION: basic {basic}")
    ref = f"refs/verify/pr-{int(number)}"
    p = _git(root, "fetch", "--no-tags", "--quiet", "origin", f"+refs/pull/{int(number)}/head:{ref}", env=env)
    if p.returncode != 0:
        raise SyncError(f"git fetch of the PR head failed: {p.stderr.strip()[:200]}")
    got = _git(root, "rev-parse", ref).stdout.strip()
    if got != head_sha:
        raise Stale(f"PR head moved to {got[:12]} while verifying {head_sha[:12]}")
    if base_sha and _git(root, "cat-file", "-e", f"{base_sha}^{{commit}}").returncode != 0:
        p = _git(root, "fetch", "--no-tags", "--quiet", "origin", base_sha, env=env)
        if p.returncode != 0:
            raise SyncError(f"git fetch of the base commit failed: {p.stderr.strip()[:200]}")


def make_compute(root: str, token: str):
    def compute(pr: dict, live: list[str]) -> dict:
        base, head = pr["base"]["sha"], pr["head"]["sha"]
        head_ref = str((pr.get("head") or {}).get("ref") or "")
        if not head_ref.lower().startswith(cli.SKIP_BRANCH_PREFIX):
            fetch_head(root, pr["number"], head, token, base)
        return cli.run_repo(root, base, head, head_ref=head_ref, current_labels=live)
    return compute


def main() -> int:
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or ""
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    event_path = os.environ.get("GITHUB_EVENT_PATH", "")
    root = os.environ.get("VERIFY_ROOT", "") or os.environ.get("GITHUB_WORKSPACE", "")
    if not (token and repo and event_path and root):
        print("GITHUB_TOKEN, GITHUB_REPOSITORY, GITHUB_EVENT_PATH and VERIFY_ROOT (or GITHUB_WORKSPACE) are required",
              file=sys.stderr)
        return 2
    event = json.loads(Path(event_path).read_text())
    try:
        result = sync(GitHub(token, repo), event, make_compute(root, token))
    except (ValidationError, SyncError) as e:
        print(f"verify-label: {e}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
