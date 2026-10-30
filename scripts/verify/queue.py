"""python -m verify.queue [--dry-run]: the "Bot PR review queue" tracking issue.

Review time is the bottleneck of the bot PRs (median 87 h for an update PR), so this finds what is
overdue and lists it in ONE issue titled `Bot PR review queue`:
  - an open bot PR labelled `fast-lane` older than 24 h (fast-lane means "one look, review in 24 h")
  - an open PR labelled `gate:escalate` older than 72 h
Age is from the PR's creation. Drafts, `trueforge/*` branches and `gate:hold` PRs are not
listed. Runs daily from `verify-stale.yml` (default branch code only).

Rules that keep it harmless:
- READ ONLY on PRs. The only writes are to the tracking issue (create it when missing, edit its
  body in place, one comment per UTC day while something is overdue). It never labels, comments on
  or edits a PR. (Linking a PR in the issue body makes GitHub show a cross-reference on that PR's
  timeline; that is GitHub's doing, not a write by this tool.)
- Idempotent: the body is a function of the open PRs and `--now`; an unchanged body is not written
  and the day's comment carries a marker, so re-running the same day posts nothing new.
- The issue is found by exact title AND author (the Actions bot), so nobody can make it edit an
  issue of theirs by giving it the same title.
- A human who CLOSES the tracking issue is respected: closed issues are looked at too, and when the
  newest one is closed nothing is written (no new issue, no comment, no reopening). Reopen it to
  restart the queue. An open issue always wins over a closed one.
- No @-mentions and no author names: PR titles are cleaned and shown as code spans, the whole body
  goes through safe_markdown.
Stdlib only.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone

from .labels import FAST_LANE, HOLD
from .sync import BOT_LOGIN, GitHub, SyncError
from .textclean import clean_line, safe_markdown

TITLE = "Bot PR review queue"
BODY_MARKER = "<!-- bot-pr-review-queue -->"
DAY_MARKER = "<!-- bot-pr-review-queue-day:{day} -->"
ESCALATE = "gate:escalate"
FAST_LANE_AFTER = timedelta(hours=24)
ESCALATE_AFTER = timedelta(hours=72)
SKIP_BRANCH_PREFIX = "trueforge/"
BOT_BRANCH_PREFIX = "bot/"
MAX_ROWS = 150
MAX_BODY = 60_000


def _utc(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc)


def _names(pr: dict) -> list[str]:
    return [x["name"] for x in pr.get("labels") or [] if isinstance(x, dict) and isinstance(x.get("name"), str)]


def _held(names: list[str]) -> bool:
    return HOLD in names


def is_bot_pr(pr: dict) -> bool:
    """Opened by a bot account on a `bot/` branch (the models bot's naming)."""
    user, head = pr.get("user") or {}, pr.get("head") or {}
    return user.get("type") == "Bot" and str(head.get("ref") or "").startswith(BOT_BRANCH_PREFIX)


def overdue(prs: list[dict], now: datetime) -> list[dict]:
    """Rows {number, url, title, lane, age} for what is over its target, oldest first."""
    rows = []
    for pr in prs:
        if not isinstance(pr, dict) or pr.get("state") != "open" or pr.get("draft"):
            continue
        if str((pr.get("head") or {}).get("ref") or "").lower().startswith(SKIP_BRANCH_PREFIX):
            continue
        names = _names(pr)
        if _held(names):
            continue
        try:
            age = now - _utc(pr["created_at"])
        except (KeyError, TypeError, ValueError):
            continue
        lane = None
        if ESCALATE in names and age > ESCALATE_AFTER:
            lane = "escalate"  # a PR that is both is listed once, under the stricter lane
        elif FAST_LANE in names and is_bot_pr(pr) and age > FAST_LANE_AFTER:
            lane = "fast-lane"
        if lane and isinstance(pr.get("number"), int):
            rows.append({"number": pr["number"], "url": _url(pr),
                         "title": str(pr.get("title") or ""), "lane": lane, "age": age})
    rows.sort(key=lambda r: (-r["age"].total_seconds(), r["number"]))
    return rows


def _url(pr: dict) -> str:
    """The PR page: the API's own link when it is a github.com one, else built from the base repo."""
    link = pr.get("html_url")
    if isinstance(link, str) and link.startswith("https://github.com/") and " " not in link and ")" not in link:
        return link
    repo = str(((pr.get("base") or {}).get("repo") or {}).get("full_name") or "")
    return f"https://github.com/{repo}/pull/{pr['number']}"


def _hours(age: timedelta) -> str:
    return f"{int(age.total_seconds() // 3600)} h"


def _code(text: str, limit: int = 90) -> str:
    text = clean_line(text.replace("`", "'").replace("|", "/"))
    return "`" + (text if len(text) <= limit else text[: limit - 1] + "…") + "`"


def render_body(rows: list[dict], now: datetime) -> str:
    """The issue body. Same rows and same `now`, same text."""
    day = now.strftime("%Y-%m-%d")
    out = [BODY_MARKER, f"# {TITLE}", "",
           f"Updated {day} by the `verify-stale` workflow. It only reads PRs and edits this issue: "
           "nothing on a PR is changed. Age counts from when the PR was opened.", ""]
    fast = [r for r in rows if r["lane"] == "fast-lane"]
    esc = [r for r in rows if r["lane"] == "escalate"]
    out += [f"- `fast-lane` open more than 24 h: {len(fast)}", f"- `gate:escalate` open more than 72 h: {len(esc)}", ""]
    if not rows:
        out.append("Nothing is over its review target.")
    else:
        out += ["| PR | Lane | Age |", "| --- | --- | --- |"]
        for r in rows[:MAX_ROWS]:
            out.append(f"| [#{r['number']}]({r['url']}) {_code(r['title'])} | {r['lane']} | {_hours(r['age'])} |")
        if len(rows) > MAX_ROWS:
            out.append(f"\n…{len(rows) - MAX_ROWS} more, oldest first above.")
    return safe_markdown("\n".join(out), MAX_BODY)


def day_comment(rows: list[dict], now: datetime) -> str:
    day = now.strftime("%Y-%m-%d")
    fast = sum(r["lane"] == "fast-lane" for r in rows)
    esc = len(rows) - fast
    return (f"{DAY_MARKER.format(day=day)}\n{day}: {len(rows)} PR(s) over their review target "
            f"({fast} fast-lane over 24 h, {esc} escalate over 72 h). The list is in the issue description.")


# ----------------------------------------------------------------------------------- GitHub

def open_prs(api: GitHub) -> list[dict]:
    return [p for p in api.paginate(f"/repos/{api.repo}/pulls?state=open") if isinstance(p, dict)]


def find_issue(api: GitHub, bot_login: str = BOT_LOGIN) -> dict | None:
    """The tracking issue: exact title, opened by the Actions bot, not a PR. The oldest OPEN one
    wins; with none open, the newest closed one (a human closed it: publish() leaves it alone)."""
    found = [i for i in api.paginate(f"/repos/{api.repo}/issues?state=all")
             if isinstance(i, dict) and i.get("title") == TITLE and "pull_request" not in i
             and (i.get("user") or {}).get("login") == bot_login and isinstance(i.get("number"), int)]
    opened = [i for i in found if i.get("state", "open") != "closed"]
    if opened:
        return min(opened, key=lambda i: i["number"])
    return max(found, key=lambda i: i["number"]) if found else None


def publish(api: GitHub, rows: list[dict], now: datetime, bot_login: str = BOT_LOGIN) -> dict:
    """Create or edit the issue and post the day's comment. Returns what it did."""
    body = render_body(rows, now)
    issue = find_issue(api, bot_login)
    did: dict = {}
    if issue is not None and issue.get("state") == "closed":
        return {"issue": "closed by a human: left alone", "number": issue["number"], "comment": "none"}
    if issue is None:
        issue = api.request("POST", f"/repos/{api.repo}/issues", {"title": TITLE, "body": body})
        did["issue"] = "created"
        if not isinstance(issue, dict) or not isinstance(issue.get("number"), int):
            raise SyncError("issue creation returned no number")
    elif issue.get("body") != body:
        api.request("PATCH", f"/repos/{api.repo}/issues/{issue['number']}", {"body": body})
        did["issue"] = "updated"
    else:
        did["issue"] = "unchanged"
    did["number"] = issue["number"]
    did["comment"] = "none"
    if rows:
        text = day_comment(rows, now)
        marker = DAY_MARKER.format(day=now.strftime("%Y-%m-%d"))
        have = [c for c in api.paginate(f"/repos/{api.repo}/issues/{issue['number']}/comments")
                if isinstance(c, dict) and isinstance(c.get("body"), str) and c["body"].startswith(marker)
                and (c.get("user") or {}).get("login") == bot_login]
        if have:
            did["comment"] = "exists"
        else:
            api.request("POST", f"/repos/{api.repo}/issues/{issue['number']}/comments", {"body": text})
            did["comment"] = "created"
    return did


def _token() -> str:
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or ""
    if token:
        return token
    p = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, check=False)  # read only: prints the token
    return p.stdout.strip() if p.returncode == 0 else ""


def main(argv: list[str] | None = None, api: GitHub | None = None, now: datetime | None = None) -> int:
    ap = argparse.ArgumentParser(prog="verify.queue", description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="print the issue body from the live open PRs; write nothing")
    ap.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""), help="OWNER/NAME (default $GITHUB_REPOSITORY)")
    ap.add_argument("--now", default=None, help="ISO time to measure ages at (default: now, UTC)")
    args = ap.parse_args(argv)
    if api is None:
        token = _token()
        if not (token and args.repo):
            print("verify.queue: needs a repository (--repo or GITHUB_REPOSITORY) and a token (GITHUB_TOKEN, or `gh auth login`)",
                  file=sys.stderr)
            return 2
        api = GitHub(token, args.repo)
    now = now or (_utc(args.now) if args.now else datetime.now(timezone.utc))
    try:
        rows = overdue(open_prs(api), now)
        if args.dry_run:
            print(render_body(rows, now))
            return 0
        print(publish(api, rows, now))
    except SyncError as e:
        print(f"verify.queue: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
