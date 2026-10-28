# verify

Checks the model YAMLs a PR changes, against two things, and reports. Report only: it never
fails a PR for a verdict, a missing source or a partial one.

1. **Risk vs main.** Every changed field gets one risk. Removals and big price moves escalate.
2. **Official sources.** Per-provider adapters (`sources/*.py`) compare the file with what the
   provider publishes. The official value wins: a match is `verified`, any difference a `conflict`.

Nothing here uses an LLM, a database or a secret. Sources are public.

```
scripts/verify/
  types.py       contract between adapters and the core (Check, SourceResult, Source)
  risk.py        risk per changed field, vs main
  build.py       one FileReport per changed file; runs the registered adapters (never raises)
  classify.py    kind:*
  gates.py       gate:*, verify:*, shadow:auto
  report.py      capped PR comment + full summary
  registry.py    loader / validation for sources/registry.yaml (repo root)
  cli.py         python -m verify ...
  sync.py        the label job: validates the artifact, syncs labels, comment, check run (stdlib only)
  labels.py      the label names this tool owns
  sources/       adapters; each registers itself in SOURCES
```

## Run it

From `scripts/`:

```
python -m verify --base <sha> --head <sha> [--head-ref <branch>] [--json out.json] [--summary-md s.md]
```

Diffs `providers/**.yaml` (minus `default.yaml` / `provider-config.yaml`) from the merge base of
`--base` and `--head` to `--head`, and prints (or writes) one JSON object: `labels`, `gate`,
`kind`, `verify`, `shadow`, `files`, `notes`, `comment_md`, `summary_md`. Exit code 0 whatever
the verdict; only a crash of the tool fails. A `--head-ref` starting with `trueforge/` is skipped
(no labels, no comment). `--current-labels-json '["gate:hold"]'` tells it the PR's labels.

## Labels

This tool owns these names, matched **exactly**, and nothing else:

| Label | Meaning |
|---|---|
| `gate:review` `gate:unverified` `gate:escalate` | exactly one per PR, see Gates |
| `risk:removal` `risk:price` `risk:params` `risk:param-value` `risk:feature` `risk:limit` `risk:mode` `risk:dated` `risk:other` `risk:check-error` | one per kind of change found |
| `verify:official` `verify:partial` `verify:conflict` `verify:none` | how far the official sources got |
| `kind:price-only` `kind:lifecycle` `kind:features-params` `kind:mixed` `kind:new-model` | what the PR changes |
| `shadow:auto` | measured only; never merges anything |

Never touched: `gate:hold` (set by humans or the addition job), `id:*`, `gate:reviewed`, any other label.

### Gates (strongest first)

1. `gate:hold` (not ours): `gate:hold` or any `id:*` label is on the PR. Sticky; this tool then
   sets no gate and never removes it. It still reports risks and verification.
2. `gate:escalate`: any escalating risk, or any conflict with an official source.
3. `gate:unverified`: some changed field has no verified source check, a source result is
   partial / uncovered / promo, or no source covers the file.
4. `gate:review`: every changed field verified, nothing escalating.

### Escalating risks

Anything removed (price region, tier, priority/flex pricing, rate, param, a supported value of a
param such as a `reasoning_effort` level, feature, limit, modality, supported mode, the file);
a price move above +25%, any drop above 10%, or a move to / from 0 (also inside `tiered_pricing`
and `priority_pricing`); a NEW region priced >= 100x the existing regions; a value added to
`removeParams`; a changed `pricing_mode`, `mode`, `supportedModes` or model id; a shrinking limit;
a flip to deprecated / retired; a check that crashed (`risk:check-error`). Everything else that
changed is review-level, including any unknown key (`risk:other`). Formatting-only changes
(`2e-6` vs `2.0e-6`) and `sources:` changes are not changes.

### verify:*

- `verify:conflict`: some source disagrees with a value in a changed file.
- `verify:official`: every changed file that has a source is fully verified (every price field
  compared, no promo, nothing partial or uncovered).
- `verify:partial`: a source ran but did not cover everything: partial, uncovered fields, a
  promotion (the catalog keeps the list price), a failed fetch, or a registered adapter that is
  missing. Never a conflict, never "official".
- `verify:none`: no source covers any changed file.

### kind:*

`price-only` (only price fields), `lifecycle`, `features-params` (features, params, limits,
modalities, no price), `new-model` (added files only), `mixed` (anything else, price plus
other, several kinds, a deleted file).

### shadow:auto

Measured only. Set when: kind is `price-only`, every changed price moved within +-10%, every
changed price field has a verified check, no source result is partial / uncovered, no file is
new, and no hold.

## How a PR is judged

`verify-pr.yml` (`pull_request`, read-only token, no secrets) runs the CLI and uploads
`verify-result.json`. `verify-label.yml` (`workflow_run`, write token) never checks out the PR:
it checks out the default branch, downloads the artifact, validates it against a strict schema
(`sync.py`: exact keys, owned labels only, size caps, head sha must match the run), then:

1. syncs labels (adds what is missing, removes only owned labels no longer wanted),
2. upserts ONE marker comment (<= 60,000 chars; GitHub rejects 65,536),
3. writes the full per-file table to a neutral check run `catalog-verify`.

Labels go first so a rejected comment can never cost them. The artifact is untrusted: it is a
product of code a fork controls; the PR number is taken from the event, never from the artifact.
`verify-tests.yml` runs this package's pytest on PRs that touch it.

## Add a source

1. Write `sources/<name>.py` implementing `types.Source` (`name`, `covers(provider)`, `prepare()`,
   `check(repo_path, doc)`; read `types.py` for the rules: official wins, promo is never a
   conflict, uncovered means partial, one fetch per run) and register it:

   ```python
   from . import SOURCES
   SOURCES["my-source"] = MySource
   ```
2. Add a row to `sources/registry.yaml` (repo root): `provider`, `kind` (`api` | `pricelist` |
   `page`), `source` (the key above), `fields` (what it compares), `added`. The core runs only
   adapters registered there for a provider. A row naming an adapter that fails to import or does
   not cover the provider yields `verify:partial`, not a crash.
3. Add offline tests with recorded data; never call the network from a test.
4. `python -m pytest -q verify` from `scripts/`.

## Tests

```
cd scripts && python -m pytest -q -p no:cacheprovider verify
```

Offline and deterministic; adapters are replaced by fake sources.
