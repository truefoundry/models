"""Applying a verdict to a PR: validate it, sync labels, upsert one comment, write a check run.

Runs inside the TRUSTED label job (`verify-label.yml`, workflow_run, write token, default-branch
workflow and code). The verdict itself is computed there too (`labeljob.py`) from git objects of
the PR head that were fetched but never checked out; nothing the PR's own workflow produced is
used. What this module still defends against:
- the PR is resolved from the event and the API, and must match the run's head repository id,
  head branch and head sha (a fork can reuse a victim PR's head sha);
- the computed result is validated against a strict schema (exact keys, owned labels only, size
  caps) before anything is written: a bug in the tool must not post garbage or a 70k comment;
- labels first, then the comment (a rejected comment must never cost the labels), then the check;
- only owned labels are removed, by exact name; `gate:hold` makes every gate label
  unsettable (sticky) and are never removed;
- text is cleaned of control characters and `@` is neutralised BEFORE it is capped, so escaping
  can never push a comment over GitHub's limit.
Stdlib only.
"""
from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable

from .labels import (FAST_LANE, GATE_LABELS, GATES, KIND_LABELS, KINDS, LANES, MARKER, VERIFY, VERIFY_LABELS, SHADOW,
                     is_hold, is_owned, label_meta)
from .textclean import safe_markdown

MAX_COMMENT = 60_000
MAX_SUMMARY = 60_000
MAX_FILES = 5000
SKIP_BRANCH_PREFIX = "trueforge/"
SKIPPED = ("trueforge-branch", "no-verifier-at-base")
CHECK_NAME = "catalog-verify"
BOT_LOGIN = "github-actions[bot]"
_SHA = re.compile(r"^[0-9a-f]{40}$")
FAST_LANE_KINDS = ("features-params", "lifecycle")  # keep equal to gates.FAST_LANE_KINDS (this module is stdlib only)
_KEYS = {"version", "base_sha", "head_sha", "skipped", "labels", "gate", "kind", "verify", "shadow", "lane", "files",
         "files_total", "files_omitted", "notes", "comment_md", "summary_md"}


class ValidationError(ValueError):
    pass


class SyncError(RuntimeError):
    pass


# ------------------------------------------------------------------------------ validation

def _is_str(v) -> bool:
    return isinstance(v, str)


def validate(data) -> dict:
    """Return the result if it is exactly what cli.run produces, else raise ValidationError."""
    if not isinstance(data, dict):
        raise ValidationError("result is not a JSON object")
    if set(data) != _KEYS:
        raise ValidationError(f"result keys differ: missing {sorted(_KEYS - set(data))}, extra {sorted(set(data) - _KEYS)}")
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
    lane = data["lane"]
    if lane not in (None, *LANES):
        raise ValidationError("bad lane")
    if gate in ("hold", "escalate", None):  # the lane of these gates is the gate itself
        if lane != gate:
            raise ValidationError("lane does not match gate")
    elif lane not in ("fast-lane", "normal"):
        raise ValidationError("lane does not match gate")
    if (FAST_LANE in labels) != (lane == "fast-lane"):
        raise ValidationError("fast-lane label does not match lane")
    if lane == "fast-lane" and kind not in FAST_LANE_KINDS:
        raise ValidationError("fast-lane on a kind that is not features-params or lifecycle")
    if data["skipped"] and (labels or gate):
        raise ValidationError("a skipped run must carry no labels")
    if not (isinstance(data["files"], list) and len(data["files"]) <= MAX_FILES
            and all(isinstance(f, dict) and _is_str(f.get("path")) for f in data["files"])):
        raise ValidationError("bad files list")
    total, omitted = data["files_total"], data["files_omitted"]
    if not (all(isinstance(x, int) and not isinstance(x, bool) and x >= 0 for x in (total, omitted))
            and total == len(data["files"]) + omitted):
        raise ValidationError("files_total / files_omitted do not match the files list")
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
    """Hold is sticky: while `gate:hold` is on the PR no gate label of ours is set."""
    want = {x for x in artifact_labels if is_owned(x)}
    return want - GATE_LABELS if is_hold(live) else want


def ensure_labels(api: GitHub, names) -> list[str]:
    """Create each owned label that does not exist yet, with its colour and description (a label
    GitHub creates on first use has neither). An existing label is never edited. A failure here
    (a race that lost with 422, a token without the right) only costs the description: the label
    still gets added to the PR and GitHub creates it plain."""
    created: list[str] = []
    for name in sorted(names):
        meta = label_meta(name)
        if meta is None:
            continue
        try:
            if api.request("GET", f"/repos/{api.repo}/labels/{urllib.parse.quote(name, safe='')}", ok_missing=True) is not None:
                continue
            api.request("POST", f"/repos/{api.repo}/labels", {"name": name, "color": meta[0], "description": meta[1]})
            created.append(name)
        except SyncError:
            continue
    return created


def sync_labels(api: GitHub, number: int, want: set[str], live: list[str]) -> tuple[list[str], list[str]]:
    """Add what is missing, then remove OWNED labels no longer wanted (exact names). Anything
    else on the PR is left alone."""
    add = sorted(want - set(live))
    remove = sorted(x for x in live if is_owned(x) and x not in want)
    if add:
        ensure_labels(api, add)
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


def upsert_check(api: GitHub, head_sha: str, result: dict) -> str:
    if not result["summary_md"]:
        return "skipped"
    title = " · ".join(x for x in (f"gate:{result['gate']}" if result["gate"] else "",
                                   f"kind:{result['kind']}" if result["kind"] else "",
                                   f"verify:{result['verify']}" if result["verify"] else "") if x) or "nothing to verify"
    output = {"title": title, "summary": safe_markdown(result["summary_md"], MAX_SUMMARY)}
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


def _int(v):
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def resolve_prs(api: GitHub, run: dict) -> list[dict]:
    """The open PRs this workflow run is for, from the event and the API. A candidate must be
    open, in this repository, and match the run's head sha, head branch AND head repository id: a
    fork can push the sha of someone else's PR and a bare sha match would label that PR."""
    head_sha = run["head_sha"]
    head_repo = _int((run.get("head_repository") or {}).get("id"))
    numbers = [p["number"] for p in run.get("pull_requests") or [] if isinstance(p, dict) and isinstance(p.get("number"), int)]
    if not numbers:
        found = api.request("GET", f"/repos/{api.repo}/commits/{head_sha}/pulls") or []
        numbers = [p["number"] for p in found if isinstance(p, dict) and isinstance(p.get("number"), int)]
    out = []
    for n in sorted(set(numbers))[:5]:
        pr = api.request("GET", f"/repos/{api.repo}/pulls/{n}")
        if not isinstance(pr, dict):
            continue
        head, base = pr.get("head") or {}, pr.get("base") or {}
        if (pr.get("state") == "open" and head.get("sha") == head_sha and head.get("ref") == run.get("head_branch")
                and head_repo is not None and _int((head.get("repo") or {}).get("id")) == head_repo
                and (base.get("repo") or {}).get("full_name") == api.repo
                and isinstance(base.get("sha"), str) and _SHA.match(base["sha"])):
            out.append(pr)
    return out


class Stale(Exception):
    """The PR moved on while we worked (its head is no longer the run's)."""


def sync(api: GitHub, event: dict, compute: Callable[[dict, list[str]], dict], bot_login: str = BOT_LOGIN) -> dict:
    """Judge and label the PR(s) behind one verify-pr run. `compute(pr, live_labels)` returns the
    validated-below result for that PR; it runs only trusted code on git objects. Raises SyncError
    after trying every step if any step failed."""
    run = event.get("workflow_run")
    if not isinstance(run, dict) or not _is_str(run.get("head_sha")) or not _SHA.match(run["head_sha"]):
        raise ValidationError("event has no workflow_run.head_sha")
    if str(run.get("head_branch") or "").startswith(SKIP_BRANCH_PREFIX):
        return {"skipped": "trueforge-branch"}
    prs = resolve_prs(api, run)
    if not prs:
        return {"skipped": "no open PR at this head (stale run, or head repository / branch mismatch)"}
    errors: list[str] = []
    done: list[dict] = []
    first: dict | None = None
    for pr in prs:
        number = pr["number"]
        step: dict = {"pr": number}
        live = [x["name"] for x in api.paginate(f"/repos/{api.repo}/issues/{number}/labels")
                if isinstance(x, dict) and isinstance(x.get("name"), str)]
        try:
            result = validate(compute(pr, live))
        except Stale as e:
            done.append({**step, "skipped": str(e)})
            continue
        if result["head_sha"] != run["head_sha"]:
            raise ValidationError("result head_sha does not match the workflow run")
        if result["skipped"]:
            done.append({**step, "skipped": result["skipped"]})
            continue
        first = first or result
        want = desired_labels(result["labels"], live)
        try:  # 1. labels, always first
            step["added"], step["removed"] = sync_labels(api, number, want, live)
        except SyncError as e:
            errors.append(str(e))
        try:  # 2. the comment, a failure here never undoes the labels
            step["comment"] = upsert_comment(api, number, safe_markdown(result["comment_md"], MAX_COMMENT), bot_login,
                                             create=bool(result["labels"] or result["gate"]))
        except SyncError as e:
            errors.append(str(e))
        done.append(step)
    check = "skipped"
    if first is not None:
        try:  # 3. the full table as a check run
            check = upsert_check(api, run["head_sha"], first)
        except SyncError as e:
            errors.append(str(e))
            check = "failed"
    if errors:
        raise SyncError("; ".join(errors))
    return {"prs": done, "check": check, "gate": first["gate"] if first else None,
            "labels": first["labels"] if first else []}
