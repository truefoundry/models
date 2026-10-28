"""The PR comment (capped) and the full summary for the check run / job summary.

GitHub rejects a comment over 65,536 characters, and the old tool lost its labels to that (labels
were applied after the comment). So: the comment is a capped digest (<= COMMENT_LIMIT) that the
label job posts AFTER the labels; the full per-file table goes to the summary (also capped, for
the check-run limit) and to the JSON artifact.

Everything that comes from the PR (paths, YAML values, adapter notes) is untrusted text: it is
only ever interpolated through `code()` (a code span with no backtick, newline or pipe).
"""
from __future__ import annotations

from collections.abc import Iterable

from .gates import Verdict, changed
from .labels import MARKER
from .model import FileReport
from .textclean import cap, clean_line
from .types import Check

COMMENT_LIMIT = 60_000  # GitHub's hard limit is 65,536
SUMMARY_LIMIT = 60_000  # a check run summary is capped at 65,535
RISKS_PER_FILE_COMMENT = 15
CHECKS_PER_FILE_COMMENT = 10
RESERVED_TAIL = 800
MAX_NOTES = 20


def code(value, limit: int = 120) -> str:
    """Untrusted text as an inline code span: no backtick, newline or pipe, so it can neither
    break out of the span nor break a table, and `@mentions` inside it do not notify."""
    text = clean_line(str(value).replace("`", "'").replace("|", "/"))
    if len(text) > limit:
        text = text[: limit - 1] + "…"
    return f"`{text}`"


def _val(v) -> str:
    return code(f"{v:g}" if isinstance(v, float) else v, 40)


def _field(locator: Iterable[str]) -> str:
    parts = list(locator)
    return ".".join(parts[1:] if parts[:1] == ["costs"] and len(parts) > 1 else parts)


def _check_row(c: Check, source: str, drift: bool = False) -> str:
    status = "drift (not this PR)" if drift else c.status
    return f"| {code(_field(c.locator), 80)} | {_val(c.file_value)} | {_val(c.source_value)} | {status} | {code(source, 40)} |"


_HEAD = ["| Field | PR | Source | Verdict | By |", "| --- | --- | --- | --- | --- |"]


def _source_line(f: FileReport) -> list[str]:
    lines = []
    for r in f.results:
        own = sum(1 for c in r.conflicts if f.touches(c.locator))
        bits = [f"{sum(c.status == 'verified' for c in r.checks)} verified", f"{own} conflict(s)"]
        if len(r.conflicts) > own:
            bits.append(f"{len(r.conflicts) - own} existing drift")
        if r.uncovered:
            bits.append(f"{len(r.uncovered)} uncovered")
        if r.partial:
            bits.append("partial")
        if r.promo:
            bits.append(f"promo until {code(r.promo, 30)}")
        elif r.promo_active:
            bits.append("promo active")
        lines.append(f"- source {code(r.source, 40)}: " + ", ".join(bits))
        lines += [f"  - note: {code(n, 200)}" for n in r.notes[:5]]
        if r.uncovered:
            lines.append("  - not compared: " + ", ".join(code(u, 80) for u in r.uncovered[:10])
                         + (f" (+{len(r.uncovered) - 10} more)" if len(r.uncovered) > 10 else ""))
    if not f.results and f.changed:
        lines.append("- no source covers this file")
    return lines


def file_block(f: FileReport, *, full: bool) -> str:
    title = f"### {code(f.path, 200)}" + (" (new)" if f.is_new else " (deleted)" if f.status == "deleted" else "")
    bullets: list[str] = []
    risks = sorted(f.risks, key=lambda r: (not r.escalate, r.label, r.reason))
    shown = risks if full else risks[:RISKS_PER_FILE_COMMENT]
    bullets += [f"- {'**escalate**' if r.escalate else 'review'} `{r.label}`: {r.reason}" for r in shown]
    if len(shown) < len(risks):
        bullets.append(f"- …and {len(risks) - len(shown)} more risk(s) in the check run summary")
    bullets += _source_line(f)
    drift = f.drift
    if drift:
        bullets.append(f"- existing drift (not from this PR): {len(drift)} field(s) in untouched fields differ from the "
                       "official source; they do not change the gate, e.g. "
                       + ", ".join(code(_field(c.locator), 80) for c in drift[:3]))
    missing = f.unverified_needs
    if missing and not f.is_new:
        bullets.append(f"- changed but not verified by a source: {len(missing)} field(s), e.g. "
                       + ", ".join(code(_field(m), 80) for m in missing[:3]))
    parts = [title, "\n".join(bullets)]
    rows = [(c, r.source) for r in f.results for c in r.checks]
    loud = [(c, s) for c, s in rows if c.status != "verified"]
    quiet = [(c, s) for c, s in rows if c.status == "verified"]
    table = loud + quiet if full else loud[:CHECKS_PER_FILE_COMMENT] + quiet[: max(0, CHECKS_PER_FILE_COMMENT - len(loud))]
    if table:
        drift_ids = {id(c) for c in f.drift}
        parts.append("\n".join(_HEAD + [_check_row(c, s, id(c) in drift_ids) for c, s in table]))
        if len(table) < len(rows):
            parts.append(f"_{len(rows) - len(table)} more compared field(s) in the check run summary_")
    return "\n\n".join(p for p in parts if p)


def _head(verdict: Verdict, files: list[FileReport], notes: Iterable[str], hold: bool) -> list[str]:
    ch = changed(files)
    checks = [c for f in ch for c in f.checks]
    gate = verdict.gate or "none"
    blocks = [f"{MARKER}\n## Catalog verify: `gate:{gate}`"
              + (f" · `kind:{verdict.kind}`" if verdict.kind else "")
              + (f" · `verify:{verdict.verify}`" if verdict.verify else "")]
    provider_files = [f for f in ch if any(r.label == "risk:provider-default" for r in f.risks)]
    own_conflicts = sum(len(f.conflicts) for f in ch)
    blocks.append(f"{len(ch) - len(provider_files)} changed model file(s), {len(provider_files)} provider default file(s) · "
                  f"{sum(c.status == 'verified' for c in checks)} field(s) verified against an official source · "
                  f"{own_conflicts} conflict(s) · report only: nothing is merged or blocked.")
    drift = sum(len(f.drift) for f in ch)
    if drift:
        blocks.append(f"Existing drift (not from this PR): {drift} field(s) in {sum(1 for f in ch if f.drift)} file(s) differ "
                      "from the official source in fields this PR did not change. Listed per file; they do not affect the gate.")
    wide = sorted({r.locator[1] for f in ch for r in f.risks if r.label == "risk:provider-default"})
    for provider in wide[:10]:
        blocks.append(f"**Provider-wide change**: {code(provider)} `default.yaml` / `provider-config.yaml` changed, "
                      "which affects every model under it.")
    if verdict.shadow:
        blocks.append("`shadow:auto`: every change is a price move within ±10% that the official source confirms. "
                      "Measured only: nothing is merged.")
    if hold:
        blocks.append("`gate:hold` (or an `id:*` label) is on this PR, so no gate is set here. Remove it once checked.")
    for note in list(notes)[:MAX_NOTES]:
        blocks.append(f"> {code(note, 300)}")
    if not ch:
        blocks.append("No model YAML in this PR needs verifying (nothing changed, or only formatting / `sources:`).")
    return blocks


FOOTER = "<sub>The official source wins: a value that differs from it is a conflict. Labels are applied before this comment.</sub>"


def _render(verdict: Verdict, files: list[FileReport], notes: Iterable[str], hold: bool, limit: int, *, full: bool,
            overflow_note: str) -> str:
    blocks = _head(verdict, files, notes, hold)
    text = "\n\n".join(blocks)
    ordered = sorted(changed(files), key=lambda f: (not f.loud, f.source_state == "official", f.path))
    omitted = 0
    for i, f in enumerate(ordered):
        block = file_block(f, full=full)
        if len(text) + 2 + len(block) > limit - RESERVED_TAIL:
            omitted = len(ordered) - i
            break
        text += "\n\n" + block
    if omitted:
        text += f"\n\n…{omitted} more file(s) not shown. {overflow_note}"
    text += "\n\n" + FOOTER
    return cap(text, limit)


def render_comment(verdict: Verdict, files: list[FileReport], notes: Iterable[str] = (), hold: bool = False) -> str:
    return _render(verdict, files, notes, hold, COMMENT_LIMIT, full=False,
                   overflow_note="The full table is in the check run summary and the `verify-result` artifact.")


def render_summary(verdict: Verdict, files: list[FileReport], notes: Iterable[str] = (), hold: bool = False) -> str:
    return _render(verdict, files, notes, hold, SUMMARY_LIMIT, full=True,
                   overflow_note="The complete list is in the `verify-result` artifact (`files`).")


def file_json(f: FileReport) -> dict:
    return {
        "path": f.path,
        "status": f.status,
        "new": f.is_new,
        "source_state": f.source_state,
        "fully_verified": f.fully_verified,
        "risks": [{"label": r.label, "escalate": r.escalate, "reason": r.reason, "change": r.change,
                   "locator": list(r.locator), "covered": f.covered(r)} for r in f.risks],
        "checks": [{"source": r.source, "locator": list(c.locator), "file_value": str(c.file_value),
                    "source_value": str(c.source_value), "status": c.status} for r in f.results for c in r.checks],
        "uncovered": [u for r in f.results for u in r.uncovered],
        "partial": any(r.partial or r.promo or r.promo_active for r in f.results),
        "notes": [n for r in f.results for n in r.notes],
    }
