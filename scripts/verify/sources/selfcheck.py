"""Live self-check: run every source adapter over the whole current catalog and print the numbers.

    cd scripts && python -m verify.sources.selfcheck [--sources openrouter,deepinfra,aws-price-list]
                                                     [--root ..] [--top-conflicts 5] [--json out.json]

Hits the real public endpoints (OpenRouter /models, DeepInfra /models/list, the AWS Price List
region files), one fetch per URL. Prints, per source and per provider: files, fully verified,
partial, conflict, then the uncovered-field counts, the 10 most common uncovered field names, and
the runtime and request count. Report only; the exit code is always 0 unless an adapter crashes.
"""
from __future__ import annotations

import argparse
import collections
import json
import sys
import time
from pathlib import Path

import yaml

from . import SOURCES, load_sources
from ._common import NotFound, http_get, provider_of

try:  # the C loader is ~10x faster over 4,500 files
    _Loader = yaml.CSafeLoader
except AttributeError:  # pragma: no cover
    _Loader = yaml.SafeLoader

NON_MODEL = {"provider-config.yaml"}


def load_catalog(root: Path) -> list[tuple[str, dict]]:
    out = []
    for path in sorted((root / "providers").rglob("*.yaml")):
        if path.name in NON_MODEL:
            continue
        doc = yaml.load(path.read_text(), Loader=_Loader)
        if isinstance(doc, dict) and "model" in doc:
            out.append((path.relative_to(root).as_posix(), doc))
    return out


class CountingFetch:
    def __init__(self):
        self.requests = 0
        self.bytes = 0
        self.errors = 0
        self.not_found = 0

    def __call__(self, url: str) -> bytes:
        self.requests += 1
        try:
            body = http_get(url)
        except NotFound:
            self.not_found += 1
            raise
        except Exception:
            self.errors += 1
            raise
        self.bytes += len(body)
        return body


def run_source(name: str, catalog: list[tuple[str, dict]], top_conflicts: int, dump: dict, deadline_s: float) -> None:
    fetch = CountingFetch()
    source = SOURCES[name](fetch=fetch, deadline_s=deadline_s)
    started = time.monotonic()
    try:
        source.prepare()
    except Exception as e:
        print(f"[{name}] prepare() failed: {type(e).__name__}: {e}")
    per_provider: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    uncovered = collections.Counter()
    notes = collections.Counter()
    conflicts: list[tuple[float, str, object]] = []
    missing_in_file = 0
    for repo_path, doc in catalog:
        provider = provider_of(repo_path)
        if not source.covers(provider):
            continue
        result = source.check(repo_path, doc)
        c = per_provider[provider]
        c["files"] += 1
        if result.checks:
            c["compared"] += 1
        if result.conflicts:
            c["conflict"] += 1
        elif result.fully_verified:
            c["verified"] += 1
        else:
            c["partial"] += 1
        if result.promo or result.promo_active:
            c["promo"] += 1
        if result.uncovered:
            c["with_uncovered"] += 1
        c["checks"] += len(result.checks)
        for u in result.uncovered:
            uncovered[u.split(".")[-1]] += 1
        if any(n.startswith("missing in file") for n in result.notes):
            missing_in_file += 1
        for n in result.notes:
            notes[n.split(":")[0][:70] if "`" in n else n[:70]] += 1
        for chk in result.conflicts:
            ratio = (max(chk.file_value, chk.source_value) / min(chk.file_value, chk.source_value)
                     if chk.file_value and chk.source_value else 0.0)  # missing-in-file sorts last
            conflicts.append((ratio, repo_path, chk))
        dump[repo_path] = {
            "source": name, "verified": result.fully_verified, "partial": result.partial, "promo": result.promo,
            "conflicts": [[".".join(k.locator), k.file_value, k.source_value, k.note] for k in result.conflicts],
            "writable": [[".".join(k.locator), k.source_value] for k in result.checks if k.writable],
            "uncovered": result.uncovered, "notes": result.notes, "n_checks": len(result.checks),
        }
    elapsed = time.monotonic() - started
    print(f"\n=== {name}: {fetch.requests} requests ({fetch.bytes / 1e6:.1f} MB, {fetch.not_found} x 404, {fetch.errors} failed), {elapsed:.1f}s")
    print(f"{'provider':<22}{'files':>7}{'verified':>10}{'partial':>9}{'conflict':>10}{'promo':>7}{'w/ uncovered':>14}{'compared':>10}{'checks':>8}")
    total: collections.Counter = collections.Counter()
    for provider, c in sorted(per_provider.items()):
        total.update(c)
        print(f"{provider:<22}{c['files']:>7}{c['verified']:>10}{c['partial']:>9}{c['conflict']:>10}{c['promo']:>7}"
              f"{c['with_uncovered']:>14}{c['compared']:>10}{c['checks']:>8}")
    if len(per_provider) > 1:
        print(f"{'TOTAL':<22}{total['files']:>7}{total['verified']:>10}{total['partial']:>9}{total['conflict']:>10}"
              f"{total['promo']:>7}{total['with_uncovered']:>14}{total['compared']:>10}{total['checks']:>8}")
    print(f"conflict checks: {len(conflicts)}; files with a price missing in the file (uncovered): {missing_in_file}")
    print("10 most common uncovered field names:", ", ".join(f"{k} ({v})" for k, v in uncovered.most_common(10)) or "none")
    print("most common notes:", "; ".join(f"{k} ({v})" for k, v in notes.most_common(6)) or "none")
    conflicts.sort(key=lambda t: -t[0])
    for ratio, repo_path, chk in conflicts[:top_conflicts]:
        print(f"  biggest: {repo_path} {'.'.join(chk.locator)} file={chk.file_value} source={chk.source_value}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    load_sources()  # imports every adapter module, which registers it in SOURCES
    ap.add_argument("--sources", default=",".join(sorted(SOURCES)))
    ap.add_argument("--deadline", type=float, default=60.0, help="run-level time budget per source, seconds")
    ap.add_argument("--root", default=str(Path(__file__).resolve().parents[3]), help="repo root holding providers/")
    ap.add_argument("--top-conflicts", type=int, default=5)
    ap.add_argument("--json", help="write every per-file result to this path")
    args = ap.parse_args(argv)
    catalog = load_catalog(Path(args.root))
    print(f"catalog: {len(catalog)} model files under {args.root}/providers")
    dump: dict = {}
    for name in args.sources.split(","):
        run_source(name.strip(), catalog, args.top_conflicts, dump, args.deadline)
    if args.json:
        Path(args.json).write_text(json.dumps(dump, indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
