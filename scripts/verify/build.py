"""Build one FileReport per changed model file: risks vs main, then the registered sources."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from pathlib import PurePosixPath

from . import rules, yamlio
from .model import ADDED, DELETED, MODIFIED, UNCHANGED, FileReport
from .registry import Registry
from .textclean import clean_line
from .risk import OTHER, PROVIDER, Risk, assess, is_stub, new_file_needs
from .types import Check, Source, SourceResult


def provider_of(repo_path: str) -> str:
    parts = PurePosixPath(repo_path).parts
    return parts[1] if len(parts) > 2 and parts[0] == "providers" else ""


def _why(e: BaseException) -> str:
    """The exception class and, for an HTTP error, its status (`HTTPError 429`). Never the message: it can carry
    text from the remote side, and the note is shown to reviewers."""
    code = getattr(e, "code", None)
    if isinstance(code, int) and not isinstance(code, bool) and 100 <= code <= 599:
        return f"{type(e).__name__} {code}"
    return type(e).__name__


def _partial(name: str, note: str) -> SourceResult:
    return SourceResult(source=name, partial=True, notes=[note])


class Runner:
    """Runs the adapters the registry lists for a provider. One `prepare()` per adapter per run
    (a failure is remembered, so an outage is one note, not one per file). Nothing here raises:
    a missing, failing or misbehaving adapter is a partial result, never a crash and never a
    conflict."""

    def __init__(self, registry: Registry, sources: Mapping[str, Source]):
        self.registry = registry
        self.sources = dict(sources)
        self._prepared: dict[str, str | None] = {}

    def _prepare(self, name: str) -> str | None:
        if name not in self._prepared:
            try:
                self.sources[name].prepare()
                self._prepared[name] = None
            except Exception as e:  # noqa: BLE001
                self._prepared[name] = f"prepare failed ({_why(e)})"
        return self._prepared[name]

    def run(self, repo_path: str, doc: dict) -> list[SourceResult]:
        provider = provider_of(repo_path)
        out: list[SourceResult] = []
        for entry in self.registry.for_provider(provider):
            name = entry.source
            src = self.sources.get(name)
            if src is None:
                out.append(_partial(name, "registered adapter is not available"))
                continue
            try:
                covers = bool(src.covers(provider))
            except Exception as e:  # noqa: BLE001
                out.append(_partial(name, f"covers() failed ({type(e).__name__})"))
                continue
            if not covers:
                out.append(_partial(name, "registry lists this provider but the adapter does not cover it"))
                continue
            failed = self._prepare(name)
            if failed:
                out.append(_partial(name, failed))
                continue
            try:
                out.append(self._clean(name, src.check(repo_path, doc)))
            except Exception as e:  # noqa: BLE001
                out.append(_partial(name, f"check failed ({_why(e)})"))
        return out

    @staticmethod
    def _clean(name: str, result) -> SourceResult:
        """Trust nothing about an adapter's return value: a bad shape is a partial result."""
        if not isinstance(result, SourceResult) or not all(isinstance(c, Check) for c in result.checks):
            return _partial(name, "adapter returned an unusable result")
        result.source = result.source or name
        result.checks = [replace(c, locator=tuple(c.locator)) for c in result.checks]  # keeps `writable`
        return result


def _crash(path: str, status: str, why: str, *, is_new: bool = False) -> FileReport:
    return FileReport(path, status, is_new, [Risk("risk:check-error", why, True, OTHER, ("file",))], [("file",)])


def build_file(repo_path: str, status: str, before_text: str | None, after_text: str | None, runner: Runner,
               ctx: rules.Context | None = None) -> FileReport:
    """`status` is the git status (added | modified | deleted). Never raises: an unreadable file
    still gets a report, so a run never leaves a PR without a gate."""
    if status == DELETED:
        return FileReport(repo_path, DELETED, False,
                          [Risk("risk:removal", "model file deleted", True, OTHER, ("file",))], [("file",)])
    if after_text is None:  # the blob was unreadable (missing object, over the size cap)
        return _crash(repo_path, status, "head version could not be read (missing or over 2 MB); compare by hand",
                      is_new=status == ADDED)
    after, why = yamlio.parse(after_text)
    if after is None:
        return _crash(repo_path, status, f"file is not usable: {why or 'not a YAML mapping'}", is_new=status == ADDED)
    if status == ADDED:
        report = FileReport(repo_path, ADDED, True, rules.to_risks(rules.evaluate(after, ctx)), new_file_needs(after))
        report.results = runner.run(repo_path, after)
        return report
    if before_text is None:  # NOT a stub fill-in: the base blob could not be read (missing object, over 2 MB)
        return _crash(repo_path, MODIFIED, "base version could not be read (missing or over 2 MB); compare by hand")
    before, why = yamlio.parse(before_text)
    if before is None and before_text and before_text.strip():
        return _crash(repo_path, MODIFIED, f"previous version is not usable ({why}); compare by hand")
    if is_stub(before):  # a stub filled in: nothing existed to compare against
        if yamlio.normalized(before or {}) == yamlio.normalized(after):
            return FileReport(repo_path, UNCHANGED)
        report = FileReport(repo_path, MODIFIED, True, rules.to_risks(rules.evaluate(after, ctx)), new_file_needs(after))
        report.results = runner.run(repo_path, after)
        return report
    risks = assess(before, after) + rules.to_risks(rules.introduced(before, after, ctx))
    if not risks:  # formatting-only, or only `sources:` changed, and no new rule finding
        return FileReport(repo_path, UNCHANGED)
    report = FileReport(repo_path, MODIFIED, False, risks, [n for r in risks for n in r.needs])
    report.results = runner.run(repo_path, after)
    return report


def build_provider_file(repo_path: str, status: str) -> FileReport:
    """providers/<p>/default.yaml or provider-config.yaml: it changes every model under the
    provider, so it always escalates. No source check runs on it."""
    provider = provider_of(repo_path) or repo_path
    name = "`" + clean_line(provider.replace("`", "'")) + "`"
    return FileReport(repo_path, status, False, [Risk(
        "risk:provider-default", f"provider-wide file changed: affects every model under {name}", True, PROVIDER,
        ("provider", provider))], [])
