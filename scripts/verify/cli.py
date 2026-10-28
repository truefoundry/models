"""python -m verify --base <sha> --head <sha> [--head-ref B] [--json out.json]  (run from scripts/)

Compares the model YAMLs changed between two commits and prints one JSON result:
{labels, gate, kind, verify, shadow, files, notes, comment_md, summary_md, ...}.
Report only: the exit code is 0 whatever the verdict. Only a crash of the tool itself fails.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections.abc import Callable, Iterable
from pathlib import Path, PurePosixPath
from typing import Protocol

from . import build, gates, report, rules, yamlio
from .model import ADDED, DELETED, MODIFIED, FileReport
from .registry import Registry, RegistryError
from .registry import load as load_registry
from .types import Source

VERSION = 1
SKIP_FILES = {"default.yaml", "provider-config.yaml"}
SKIP_BRANCH_PREFIX = "trueforge/"
MAX_BLOB = 2_000_000
_STATUS = {"A": ADDED, "M": MODIFIED, "D": DELETED, "T": MODIFIED}


class Repo(Protocol):
    def merge_base(self, base: str, head: str) -> str:
        """Where the PR branched off; the PR's own changes are head vs this, not vs a moved base tip."""

    def changed(self, base: str, head: str) -> list[tuple[str, str]]:
        """(status letter, path) of every file that differs, renames split into D + A."""

    def show(self, ref: str, path: str) -> str | None:
        """File text at a commit, None when absent."""


class GitRepo:
    def __init__(self, root: Path | str):
        self.root = str(root)

    def _git(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(["git", "-c", "core.quotepath=off", "-C", self.root, *args], capture_output=True, check=False)

    def merge_base(self, base: str, head: str) -> str:
        """Falls back to `base` itself when git cannot find one."""
        p = self._git("merge-base", base, head)
        return p.stdout.decode().strip() if p.returncode == 0 and p.stdout.strip() else base

    def changed(self, base: str, head: str) -> list[tuple[str, str]]:
        p = self._git("diff", "--name-status", "--no-renames", "-z", base, head, "--", "providers")
        if p.returncode != 0:
            raise RuntimeError(f"git diff failed: {p.stderr.decode(errors='replace').strip()}")
        parts = p.stdout.decode("utf-8", "replace").split("\0")
        return [(parts[i], parts[i + 1]) for i in range(0, len(parts) - 1, 2)]

    def show(self, ref: str, path: str) -> str | None:
        p = self._git("show", f"{ref}:{path}")
        if p.returncode != 0 or len(p.stdout) > MAX_BLOB:
            return None
        return p.stdout.decode("utf-8", "replace")


def is_model_file(path: str) -> bool:
    p = PurePosixPath(path)
    return len(p.parts) > 2 and p.parts[0] == "providers" and p.suffix == ".yaml" and p.name not in SKIP_FILES


def empty_result(base: str, head: str, skipped: str | None = None, notes: Iterable[str] = ()) -> dict:
    return {"version": VERSION, "base_sha": base, "head_sha": head, "skipped": skipped, "labels": [], "gate": None,
            "kind": None, "verify": None, "shadow": False, "files": [], "notes": list(notes),
            "comment_md": "", "summary_md": ""}


def run(repo: Repo, base: str, head: str, *, head_ref: str = "", current_labels: Iterable[str] = (),
        registry: Registry | None = None, registry_note: str | None = None, schema: rules.Schema | None = None,
        load_sources: Callable[[set[str]], list[Source]] = lambda names: []) -> dict:
    if head_ref.startswith(SKIP_BRANCH_PREFIX):
        return empty_result(base, head, "trueforge-branch")
    registry = registry or Registry()
    labels_now = list(current_labels)
    base_ref = repo.merge_base(base, head)
    paths = [(_STATUS[s[:1]], p) for s, p in repo.changed(base_ref, head) if s[:1] in _STATUS and is_model_file(p)]
    notes = [registry_note] if registry_note else []
    providers = {build.provider_of(p) for _, p in paths}
    wanted = registry.source_names(providers)
    adapters = {s.name: s for s in load_sources(wanted)} if wanted else {}
    runner = build.Runner(registry, adapters)
    schema = schema or rules.Schema()
    contexts: dict[str, rules.Context] = {}  # one default.yaml read per provider

    def context(provider: str) -> rules.Context:
        if provider not in contexts:
            defaults = yamlio.load(repo.show(head, f"providers/{provider}/default.yaml")) or {}
            contexts[provider] = rules.Context(defaults, provider, schema)
        return contexts[provider]
    files: list[FileReport] = []
    for status, path in sorted(paths, key=lambda sp: sp[1]):
        try:
            before = None if status == ADDED else repo.show(base_ref, path)
            after = None if status == DELETED else repo.show(head, path)
            files.append(build.build_file(path, status, before, after, runner, context(build.provider_of(path))))
        except Exception as e:  # noqa: BLE001 - a crash in one file must not lose the PR's gate
            files.append(build._crash(path, status, f"verifier crashed on this file ({type(e).__name__})"))
    verdict = gates.decide(files, labels_now)
    hold = verdict.gate == "hold"
    out = empty_result(base, head, None, notes)
    out.update({
        "labels": verdict.labels, "gate": verdict.gate, "kind": verdict.kind, "verify": verdict.verify,
        "shadow": verdict.shadow, "files": [report.file_json(f) for f in files],
        "comment_md": report.render_comment(verdict, files, notes, hold),
        "summary_md": report.render_summary(verdict, files, notes, hold),
    })
    return out


def _load_labels(raw: str) -> list[str]:
    try:
        data = json.loads(raw or "[]")
    except json.JSONDecodeError:
        return []
    if isinstance(data, list):
        return [x["name"] if isinstance(x, dict) and "name" in x else x for x in data if isinstance(x, (str, dict))]
    return []


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="verify", description=__doc__)
    ap.add_argument("--base", required=True)
    ap.add_argument("--head", required=True)
    ap.add_argument("--head-ref", default="", help="PR head branch; trueforge/* is skipped")
    ap.add_argument("--current-labels-json", default="[]", help="the PR's current labels, as a JSON list of names")
    ap.add_argument("--repo", default=None, help="repo root (default: git toplevel of the cwd)")
    ap.add_argument("--registry", default=None, help="default: <repo>/sources/registry.yaml")
    ap.add_argument("--json", dest="json_out", default=None, help="write the result here instead of stdout")
    ap.add_argument("--summary-md", default=None, help="also write the full summary markdown here")
    args = ap.parse_args(argv)

    root = args.repo or subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True,
                                       check=True).stdout.strip()
    reg_path = Path(args.registry) if args.registry else Path(root) / "sources" / "registry.yaml"
    registry, note = None, None
    try:
        registry = load_registry(reg_path, Path(root) / "providers")
    except RegistryError as e:
        note = f"source registry unusable, no source ran: {e}"

    def loader(names: set[str]) -> list[Source]:
        from .sources import load_sources
        return load_sources(names)

    result = run(GitRepo(root), args.base, args.head, head_ref=args.head_ref,
                 current_labels=[n for n in _load_labels(args.current_labels_json) if isinstance(n, str)],
                 registry=registry, registry_note=note, schema=rules.load_schema(root), load_sources=loader)
    text = json.dumps(result, indent=2, sort_keys=True)
    if args.summary_md:
        Path(args.summary_md).write_text(result["summary_md"])
    if args.json_out:
        Path(args.json_out).write_text(text + "\n")
        print(f"gate={result['gate']} kind={result['kind']} verify={result['verify']} labels={','.join(result['labels'])}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
