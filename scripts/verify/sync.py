"""The label job: validate the verify-pr artifact, then sync labels and one comment.

Runs in `verify-label.yml` (workflow_run, write token). Stdlib only, and it imports nothing from
the PR: the workflow checks out the DEFAULT branch, never the PR. The artifact is produced by
code a fork controls, so it is untrusted input:
- strict schema, exact keys and types, size caps, labels only from the owned allow-list;
- the PR number is NOT read from it: it comes from the workflow_run event / the commits API, and
  the artifact's head sha must equal the run's;
- labels first, then the comment (a rejected comment must never cost the labels), then the check;
- only owned labels are removed, by exact name; `gate:hold` / `id:*` make every gate label
  unsettable (sticky) and are never removed;
- `@` is neutralised in the comment so a PR cannot make the bot notify people.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from pathlib import Path

from .labels import (GATE_LABELS, GATES, KIND_LABELS, KINDS, MARKER, VERIFY, VERIFY_LABELS, SHADOW, is_hold,
                     is_owned)

ARTIFACT_FILE = "verify-result.json"
MAX_ARTIFACT_BYTES = 2_000_000
MAX_COMMENT = 60_000
MAX_SUMMARY = 60_000
MAX_FILES = 5000
SKIP_BRANCH_PREFIX = "trueforge/"
SKIPPED = ("trueforge-branch", "no-verifier-at-base")
CHECK_NAME = "catalog-verify"
BOT_LOGIN = "github-actions[bot]"
_SHA = re.compile(r"^[0-9a-f]{40}$")
_KEYS = {"version", "base_sha", "head_sha", "skipped", "labels", "gate", "kind", "verify", "shadow", "files", "notes",
         "comment_md", "summary_md"}


class ValidationError(ValueError):
    pass


class SyncError(RuntimeError):
    pass


# ------------------------------------------------------------------------------ validation

def _is_str(v) -> bool:
    return isinstance(v, str)


def validate(data) -> dict:
    """Return the artifact if it is exactly what verify-pr writes, else raise ValidationError."""
    if not isinstance(data, dict):
        raise ValidationError("artifact is not a JSON object")
    if set(data) != _KEYS:
        raise ValidationError(f"artifact keys differ: missing {sorted(_KEYS - set(data))}, extra {sorted(set(data) - _KEYS)}")
    if data["version"] != 1 or isinstance(data["version"], bool):
        raise ValidationError("unsupported version")
    for key in ("base_sha", "head_sha"):
        if not (_is_str(data[key]) and _SHA.match(data[key])):
            raise ValidationError(f"{key} must be a 40-hex sha")
    if data["skipped"] not in (None, *SKIPPED):
        raise ValidationError("bad skipped")
    labels = data["labels"]
    if not (isinstance(labels, list) and len(labels) <= 40 and all(_is_str(x) for x in labels)):
        raise ValidationError("labels must be a short list of strings")
    if len(set(labels)) != len(labels):
        raise ValidationError("duplicate label")
    bad = [x for x in labels if not is_owned(x)]
    if bad:
        raise ValidationError(f"label not owned by this tool: {bad[0][:60]!r}")
    for name, group in (("gate", GATE_LABELS), ("kind", KIND_LABELS), ("verify", VERIFY_LABELS)):
        if sum(x in group for x in labels) > 1:
            raise ValidationError(f"more than one {name} label")
    gate, kind, verify = data["gate"], data["kind"], data["verify"]
    if gate not in (None, "hold", *GATES):
        raise ValidationError("bad gate")
    if kind not in (None, *KINDS):
        raise ValidationError("bad kind")
    if verify not in (None, *VERIFY):
        raise ValidationError("bad verify")
    if sum(x in GATE_LABELS for x in labels) != (1 if gate in GATES else 0) or (gate in GATES and f"gate:{gate}" not in labels):
        raise ValidationError("gate label does not match gate")
    if (kind is None) != (not any(x in KIND_LABELS for x in labels)) or (kind and f"kind:{kind}" not in labels):
        raise ValidationError("kind label does not match kind")
    if (verify is None) != (not any(x in VERIFY_LABELS for x in labels)) or (verify and f"verify:{verify}" not in labels):
        raise ValidationError("verify label does not match verify")
    if not isinstance(data["shadow"], bool) or data["shadow"] != (SHADOW in labels):
        raise ValidationError("shadow does not match labels")
    if data["skipped"] and (labels or gate):
        raise ValidationError("a skipped run must carry no labels")
    if not (isinstance(data["files"], list) and len(data["files"]) <= MAX_FILES
            and all(isinstance(f, dict) and _is_str(f.get("path")) for f in data["files"])):
        raise ValidationError("bad files list")
    if not (isinstance(data["notes"], list) and len(data["notes"]) <= 50 and all(_is_str(n) and len(n) <= 2000 for n in data["notes"])):
        raise ValidationError("bad notes")
    for key, limit in (("comment_md", MAX_COMMENT), ("summary_md", MAX_SUMMARY)):
        if not _is_str(data[key]) or len(data[key]) > limit:
            raise ValidationError(f"{key} is not a string of at most {limit} characters")
    comment = data["comment_md"]
    if comment and (not comment.startswith(MARKER) or comment.count(MARKER) != 1):
        raise ValidationError("comment_md must start with the marker, once")
    if labels and not comment:
        raise ValidationError("labels without a comment")
    return data


def load_artifact(directory: Path | str) -> dict:
    path = Path(directory) / ARTIFACT_FILE
    if path.is_symlink() or not path.is_file():
        raise ValidationError(f"{ARTIFACT_FILE} missing or not a regular file")
    if path.stat().st_size > MAX_ARTIFACT_BYTES:
        raise ValidationError("artifact too large")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as e:
        raise ValidationError(f"artifact is not valid JSON ({type(e).__name__})") from e
    return validate(data)


def sanitize_md(text: str) -> str:
    """No `@mention` reaches GitHub: a zero-width space after every `@`."""
    return text.replace("@", "@​")


# --------------------------------------------------------------------------------- GitHub

class GitHub:
    """A minimal REST client. `opener` and `sleep` are injectable for tests."""

    def __init__(self, token: str, repo: str, api_url: str = "https://api.github.com",
                 opener: Callable = urllib.request.urlopen, sleep: Callable[[float], None] = time.sleep):
        self.token, self.repo, self.api_url, self.opener, self.sleep = token, repo, api_url.rstrip("/"), opener, sleep

    def request(self, method: str, path: str, body: dict | None = None, ok_missing: bool = False):
        url = path if path.startswith("http") else f"{self.api_url}{path}"
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method, headers={
            "Authorization": f"Bearer {self.token}", "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28", "Content-Type": "application/json", "User-Agent": "catalog-verify"})
        for attempt in range(3):
            try:
                with self.opener(req, timeout=30) as resp:
                    raw = resp.read()
                    return json.loads(raw) if raw else None
            except urllib.error.HTTPError as e:
                if e.code == 404 and ok_missing:
                    return None
                if e.code in (429, 500, 502, 503, 504) and attempt < 2:
                    self.sleep(2 * (attempt + 1))
                    continue
                raise SyncError(f"{method} {path} -> HTTP {e.code}") from e
        raise SyncError(f"{method} {path} failed")  # pragma: no cover

    def paginate(self, path: str) -> list:
        out: list = []
        sep = "&" if "?" in path else "?"
        for page in range(1, 31):
            chunk = self.request("GET", f"{path}{sep}per_page=100&page={page}")
            if not isinstance(chunk, list):
                break
            out += chunk
            if len(chunk) < 100:
                break
        return out


# ------------------------------------------------------------------------------- syncing

def desired_labels(artifact_labels: list[str], live: list[str]) -> set[str]:
    """Hold is sticky: while `gate:hold` / `id:*` is on the PR no gate label of ours is set."""
    want = {x for x in artifact_labels if is_owned(x)}
    return want - GATE_LABELS if is_hold(live) else want


def sync_labels(api: GitHub, number: int, want: set[str], live: list[str]) -> tuple[list[str], list[str]]:
    """Add what is missing, then remove OWNED labels no longer wanted (exact names). Anything
    else on the PR is left alone."""
    add = sorted(want - set(live))
    remove = sorted(x for x in live if is_owned(x) and x not in want)
    if add:
        api.request("POST", f"/repos/{api.repo}/issues/{number}/labels", {"labels": add})
    for name in remove:
        api.request("DELETE", f"/repos/{api.repo}/issues/{number}/labels/{urllib.parse.quote(name, safe='')}", ok_missing=True)
    return add, remove


def upsert_comment(api: GitHub, number: int, body: str, bot_login: str = BOT_LOGIN, create: bool = True) -> str:
    """One marker comment, authored by the bot; never edits someone else's. With create=False an
    existing comment is updated but a PR with nothing to verify does not get a new one."""
    existing = [c for c in api.paginate(f"/repos/{api.repo}/issues/{number}/comments")
                if isinstance(c, dict) and isinstance(c.get("body"), str) and c["body"].startswith(MARKER)
                and isinstance(c.get("user"), dict) and c["user"].get("login") == bot_login]
    if existing:
        api.request("PATCH", f"/repos/{api.repo}/issues/comments/{existing[0]['id']}", {"body": body})
        return "updated"
    if not body or not create:
        return "skipped"
    api.request("POST", f"/repos/{api.repo}/issues/{number}/comments", {"body": body})
    return "created"


def upsert_check(api: GitHub, head_sha: str, artifact: dict) -> str:
    if not artifact["summary_md"]:
        return "skipped"
    title = " · ".join(x for x in (f"gate:{artifact['gate']}" if artifact["gate"] else "",
                                   f"kind:{artifact['kind']}" if artifact["kind"] else "",
                                   f"verify:{artifact['verify']}" if artifact["verify"] else "") if x) or "nothing to verify"
    output = {"title": title, "summary": sanitize_md(artifact["summary_md"])}
    found = api.request("GET", f"/repos/{api.repo}/commits/{head_sha}/check-runs?check_name={CHECK_NAME}")
    runs = [r for r in (found or {}).get("check_runs", []) if isinstance(r, dict)
            and (r.get("app") or {}).get("slug") == "github-actions"]
    if runs:
        api.request("PATCH", f"/repos/{api.repo}/check-runs/{runs[0]['id']}",
                    {"status": "completed", "conclusion": "neutral", "output": output})
        return "updated"
    api.request("POST", f"/repos/{api.repo}/check-runs", {"name": CHECK_NAME, "head_sha": head_sha, "status": "completed",
                                                          "conclusion": "neutral", "output": output})
    return "created"


def resolve_prs(api: GitHub, run: dict) -> list[dict]:
    """The open PRs this workflow run is for. Never from the artifact. A fork PR has an empty
    `pull_requests` in the event, so fall back to the commit -> PRs lookup."""
    head_sha = run["head_sha"]
    numbers = [p["number"] for p in run.get("pull_requests") or [] if isinstance(p, dict) and isinstance(p.get("number"), int)]
    if not numbers:
        found = api.request("GET", f"/repos/{api.repo}/commits/{head_sha}/pulls") or []
        numbers = [p["number"] for p in found if isinstance(p, dict) and isinstance(p.get("number"), int)]
    out = []
    for n in sorted(set(numbers))[:5]:
        pr = api.request("GET", f"/repos/{api.repo}/pulls/{n}")
        if (isinstance(pr, dict) and pr.get("state") == "open" and (pr.get("head") or {}).get("sha") == head_sha
                and ((pr.get("base") or {}).get("repo") or {}).get("full_name") == api.repo):
            out.append(pr)
    return out


def sync(api: GitHub, event: dict, artifact_dir: Path | str, bot_login: str = BOT_LOGIN) -> dict:
    """Apply one verify-pr run. Raises SyncError after trying every step if any step failed."""
    run = event.get("workflow_run")
    if not isinstance(run, dict) or not _is_str(run.get("head_sha")) or not _SHA.match(run["head_sha"]):
        raise ValidationError("event has no workflow_run.head_sha")
    if str(run.get("head_branch") or "").startswith(SKIP_BRANCH_PREFIX):
        return {"skipped": "trueforge-branch"}
    artifact = load_artifact(artifact_dir)
    if artifact["head_sha"] != run["head_sha"]:
        raise ValidationError("artifact head_sha does not match the workflow run")
    if artifact["skipped"]:
        return {"skipped": artifact["skipped"]}
    prs = resolve_prs(api, run)
    if not prs:
        return {"skipped": "no open PR at this head (stale run)"}
    comment = sanitize_md(artifact["comment_md"])
    errors: list[str] = []
    done: list[dict] = []
    for pr in prs:
        number = pr["number"]
        step: dict = {"pr": number}
        live = [x["name"] for x in api.paginate(f"/repos/{api.repo}/issues/{number}/labels")
                if isinstance(x, dict) and isinstance(x.get("name"), str)]
        want = desired_labels(artifact["labels"], live)
        try:  # 1. labels, always first
            step["added"], step["removed"] = sync_labels(api, number, want, live)
        except SyncError as e:
            errors.append(str(e))
        try:  # 2. the comment, a failure here never undoes the labels
            step["comment"] = upsert_comment(api, number, comment, bot_login, create=bool(artifact["labels"] or artifact["gate"]))
        except SyncError as e:
            errors.append(str(e))
        done.append(step)
    try:  # 3. the full table as a check run
        check = upsert_check(api, run["head_sha"], artifact)
    except SyncError as e:
        errors.append(str(e))
        check = "failed"
    if errors:
        raise SyncError("; ".join(errors))
    return {"prs": done, "check": check, "gate": artifact["gate"], "labels": artifact["labels"]}


def main() -> int:
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or ""
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    event_path = os.environ.get("GITHUB_EVENT_PATH", "")
    artifact_dir = os.environ.get("ARTIFACT_DIR", "")
    if not (token and repo and event_path and artifact_dir):
        print("GITHUB_TOKEN, GITHUB_REPOSITORY, GITHUB_EVENT_PATH and ARTIFACT_DIR are required", file=sys.stderr)
        return 2
    event = json.loads(Path(event_path).read_text())
    try:
        result = sync(GitHub(token, repo), event, artifact_dir)
    except (ValidationError, SyncError) as e:
        print(f"verify-label: {e}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
