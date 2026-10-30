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
  rules.py       static rules from recurring review findings (risk:rule-*)
  build.py       one FileReport per changed file; runs the registered adapters (never raises)
  classify.py    kind:*
  gates.py       gate:*, verify:*, shadow:auto
  report.py      capped PR comment + full summary
  registry.py    loader / validation for sources/registry.yaml (repo root)
  cli.py         python -m verify ...
  sync.py        applies a verdict: validation, labels, comment, check run (stdlib only)
  labeljob.py    the trusted label job entry point: fetch the PR head as objects, run, apply
  textclean.py   cleaning of untrusted text (stdlib only)
  labels.py      the label names this tool owns, with their colours and descriptions
  queue.py       python -m verify.queue: the "Bot PR review queue" issue (verify-stale.yml)
  sources/       adapters; each registers itself in SOURCES
```

## Run it

From `scripts/`:

```
python -m verify --base <sha> --head <sha> [--head-ref <branch>] [--json out.json] [--summary-md s.md]
```

Diffs `providers/**.yaml` from the merge base of
`--base` and `--head` to `--head`. Model files get the risk and source checks; a changed provider-level
`default.yaml` / `provider-config.yaml` is not source-checked but is reported as `risk:provider-default`
(`gate:escalate`, `kind:provider-default`), since it affects every model under the provider. It prints (or writes) one JSON object: `labels`, `gate`,
`kind`, `verify`, `shadow`, `files`, `notes`, `comment_md`, `summary_md`. Exit code 0 whatever
the verdict; only a crash of the tool fails. A PR whose head branch starts with `trueforge/` is skipped
(no labels, no comment). That is decided by the branch name alone: a fork branch named `trueforge/x`
evades the labels. Accepted: the tool is report-only. `--current-labels-json '["gate:hold"]'` tells it the PR's labels. (The label job calls the same code in-process; this CLI is for local runs.) A PR with more than 300 changed files lists the 300 most severe in `files` (`files_total` / `files_omitted` say how many); labels and the gate always cover all of them.

## Labels

This tool owns these names, matched **exactly**, and nothing else:

| Label | Meaning |
|---|---|
| `gate:review` `gate:unverified` `gate:escalate` | exactly one per PR, see Gates |
| `risk:removal` `risk:price` `risk:params` `risk:param-value` `risk:feature` `risk:limit` `risk:mode` `risk:dated` `risk:other` `risk:check-error` | one per kind of change found |
| `risk:rule-<id>` | a static rule fired, see Static rules |
| `risk:provider-default` | a `default.yaml` / `provider-config.yaml` changed: escalates, it affects every model under the provider |
| `verify:official` `verify:partial` `verify:conflict` `verify:none` | how far the official sources got |
| `kind:price-only` `kind:lifecycle` `kind:features-params` `kind:mixed` `kind:new-model` `kind:provider-default` | what the PR changes |
| `shadow:auto` | measured only; never merges anything |
| `fast-lane` | one look, target review within 24 h, see Review lanes |

Every owned label has a colour and a short description in `labels.py`. The label job creates a
missing one with them (`sync.ensure_labels`, before it adds the label to the PR); a label that
already exists is never edited. Without it GitHub would create the label plain.

Never touched: `gate:hold` (set by humans or the addition job), `id:*`, `gate:reviewed`, any other label.

### Gates (strongest first)

1. `gate:hold` (not ours): `gate:hold` or any `id:*` label is on the PR. Sticky; this tool then
   sets no gate and never removes it. It still reports risks and verification.
2. `gate:escalate`: any escalating risk, or a conflict with an official source in a field this PR
   changed (every field of a new file). A conflict in a field the PR did not touch is existing
   catalog drift: listed under "existing drift (not from this PR)", it makes `verify:` partial at
   most and never changes the gate or `shadow:auto`.
3. `gate:unverified`: some changed field has no verified source check, a source result is
   partial / uncovered / promo, or no source covers the file. A NEW file is never `gate:review`:
   its modalities, features and status are never source-checked, so the best it gets is
   `gate:unverified` (with `kind:new-model`).
4. `gate:review`: every changed field verified, nothing escalating. "Every changed field" means
   the fields the risk assessment found: a price or limit counts as verified when a source
   returned a verified check at that exact locator; features, params, modalities, lifecycle and
   every other key are never source-checked, so changing one always leaves a file `unverified`.

### Review lanes

Every comment starts with `**Review lane: fast-lane | normal | escalate | hold**` and at most three
lines saying why, so a reviewer knows in five seconds how much attention the PR needs. The lane is
in the result as `lane`; only `fast-lane` is also a label.

| lane | when |
|---|---|
| `fast-lane` | kind is `features-params` or `lifecycle` (never price, mixed, new-model, provider-default), gate is `review` or `unverified`, no risk or static rule at escalate level, no conflict with an official source, and at most 10 changed model files. Meaning: one look, target review within 24 h |
| `normal` | gate `review` or `unverified`, not fast-lane: the first line says why (kind, or more than 10 files) |
| `escalate` | `gate:escalate`: the lines name the conflict or the escalating risks |
| `hold` | `gate:hold` / `id:*`: no gate is set, the lines still name what would escalate |

A review-level rule finding (`risk:rule-*` that does not escalate) does not leave the fast lane. The
label job refuses a result whose `fast-lane` label, `lane`, gate and kind disagree.

`verify-stale.yml` (daily 08:00 UTC, default branch code, `pull-requests: read` + `issues: write`)
runs `python -m verify.queue`: it lists the open bot PRs labelled `fast-lane` that are older than
24 h and the open PRs labelled `gate:escalate` older than 72 h (drafts, `trueforge/*`, `gate:hold`
and `id:*` left out) in one issue, `Bot PR review queue`: created when missing (found by exact title
and the Actions bot as author), body edited in place, one comment per day while something is
overdue. It never labels, comments on or edits a PR, mentions nobody and writes nothing when
nothing changed. `python -m verify.queue --dry-run` prints the body from the live open PRs and writes
nothing (needs `GITHUB_TOKEN` or `gh auth login`, and `--repo` or `GITHUB_REPOSITORY`).

### Escalating risks

Anything removed (price region, tier, priority/flex pricing, rate, param, a supported value of a
param such as a `reasoning_effort` level, feature, limit, modality, supported mode, the file);
a price move above +25%, any drop above 10%, or a move to / from 0 (also inside `tiered_pricing`
and `priority_pricing`); a NEW region priced >= 100x the existing regions; a value added to
`removeParams`; a changed `pricing_mode`, a changed model id, a `mode` change other than filling in an unknown / absent one (that is review), a removed `supportedModes` entry (adding one is review); a shrinking limit;
a flip to deprecated / retired; a check that crashed (`risk:check-error`). Everything else that
changed is review-level, including any unknown key (`risk:other`). Formatting-only changes
(`2e-6` vs `2.0e-6`) and `sources:` changes are not changes.

### verify:*

- `verify:conflict`: some source disagrees with a value in a field this PR changed (or in a new
  file). A disagreement in an untouched field is existing drift and only makes the file `partial`.
- `verify:official`: every changed file has a source, every source result is fully verified
  (every price field compared, no promo, nothing partial or uncovered) and every changed price /
  limit field has a verified check. One verified file plus a source-less file is `verify:partial`.
- `verify:partial`: a source ran but did not cover everything: partial, uncovered fields, a
  promotion (the catalog keeps the list price), a failed fetch, or a registered adapter that is
  missing. Never a conflict, never "official".
- `verify:none`: no source covers any changed file.

### Static rules

`rules.py` checks a file against patterns that Cursor Bugbot flagged again and again on bot PRs
(579 threads). A finding has a stable id, a severity and a field locator, and becomes a
`risk:rule-<id>` label. `escalate` severity makes `gate:escalate`; `review` never does. Only
findings the PR **introduces** are reported (the base commit's findings are subtracted), and a
rule finding adds nothing for a source to verify. Rules do not affect `kind:*`.

| id | severity | fires when |
|---|---|---|
| `max-tokens-below-limit` | review | the model's own `max_tokens` / `max_completion_tokens` `maxValue` is below `limits.max_output_tokens` |
| `max-tokens-inherited-cap` | review | in a provider that normally overrides it, the model inherits `default.yaml`'s `max_tokens` cap, which is below its output limit, with no override |
| `max-completion-pair` | review | `max_tokens` is removed and no `max_completion_tokens` param (own or default) replaces it |
| `null-status` | escalate | `status:` is present with no value |
| `deprecated-conflict` | review | `isDeprecated: true` with `status` active / preview |
| `deprecated-undated` | review | `isDeprecated: true`, no status, no dates, and the file cites a source |
| `reasoning-enum` | escalate | a `reasoning_effort` `supportedValues` entry is not in the CUE enum (`.github/test/model.rules.cue`) |
| `reasoning-default` | review | the `reasoning_effort` `defaultValue` is not in its own `supportedValues` |
| `reasoning-unsupported` | review | the model declares a `reasoning_effort` param without `thinking: true`, or on a non-text mode |
| `feature-enum` | escalate | a `features` entry is not in the CUE `#Feature` enum (`.github/test/model.cue`) |
| `claude-feature-gaps` | review | a Claude >= 4.8 chat model in `CLAUDE_MID_PROVIDERS` (anthropic, aws-bedrock, aws-bedrock-mantle, azure-ai-foundry, google-vertex, microsoft-foundry) lacks `mid_conversation_system_messages`, or a Claude >= 4.6 lists `assistant_prefill` (those models reject a prefilled assistant turn) |

Calibration: `python -m verify.rules --calibrate --providers providers` runs every rule over the
catalog and flags any rule above 5% of files, since existing files are the ground truth of
"accepted". On origin/main (4,523 files): below-limit 0.42%, inherited-cap 2.87%, completion-pair
0.04%, null-status 0, deprecated-conflict 0.13%, deprecated-undated 0.49%, reasoning-enum 0,
reasoning-default 0, reasoning-unsupported 0.20%, feature-enum 0, claude-feature-gaps 0.31% (14 files). Narrowed to get there: the
inherited cap fired on 16.7% (openrouter inherits it in 61% of its files), so it only applies to
`CAP_OVERRIDE_PROVIDERS`, the providers where at least 60% of files override it; the undated
deprecation fired on 7%, so it needs a cited source; an inherited `reasoning_effort` (24% of chat
files) is never flagged. The two enum rules and `null-status` fire nowhere today because CUE
already rejects them; they stay as an early, labelled warning. `claude-feature-gaps` only checks the providers where at least 60% of the Claude >= 4.8 chat files carry the
flag (the resellers openrouter 2/18, perplexity-ai 1/8 and deepinfra 0/6 never do), and has no `tool_choice`
check: Claude 5.1 / 5.5 files disagree on it (2/9, 15/45), so the catalog has no convention to enforce.
Re-run `--calibrate` after a large
catalog change and refresh `CAP_OVERRIDE_PROVIDERS` if a provider's convention moved.

### kind:*

`price-only` (only price fields), `lifecycle`, `features-params` (features, params, limits,
modalities, no price), `new-model` (added files only), `provider-default` (only `default.yaml` /
`provider-config.yaml` changed), `mixed` (anything else, price plus other, several kinds, a
deleted file).

### fast-lane

See Review lanes. Replayed on the bot's own last commit of every bot PR merged in the 90 days to
2026-10-28, 45 of 1,214 merged bot PRs (17% of the 268 update PRs, none of the add PRs) would have been
`fast-lane`; 38 of them (84%, Wilson 95% CI 71-92%) merged with no human correction of what the bot
wrote, against 59% for the other update PRs. In the last 100 merged PRs 6 were fast-lane and none was
corrected. The replay ran without the source adapters (no network), so every fast-lane PR is
`gate:unverified` and the conflict condition never fired; a conflict can only remove PRs from the lane.

### shadow:auto

Measured only. Set when: kind is `price-only`, every changed price moved within +-10%, every
changed price field has a verified check, no source result is partial / uncovered, no file is
new, and no hold.

## How a PR is judged, and what is trusted

Everything is decided by **`verify-label.yml`**, which runs on `workflow_run` of "Verify PR". A
`workflow_run` workflow is always the **default branch's** definition, with a write token, so
nothing the PR changed can alter how it runs.

1. It checks out the **default branch** (never the PR) with full history and installs a pinned
   PyYAML (`setup-python`, actions pinned to commit SHAs).
2. It resolves the open PR from the event and the API, requiring the PR's head **sha, branch and
   head-repository id** to match the run (a fork can reuse a victim PR's head sha).
3. It fetches the PR head as **git objects only** (`refs/pull/N/head` into a private ref); nothing is
   checked out, nothing from the PR is on the Python path.
4. It runs the **default branch's** verifier on `merge-base(base, head)..head`, reading blobs with
   `git show`. PR YAML is parsed as untrusted data (`yamlio.parse`): anchors, aliases and merge keys
   are refused (the catalog uses none: about 4,500 files scanned in October 2026), as are files over 2 MB, more than
   200,000 nodes, nesting deeper than 60 and lone surrogates; such a file becomes an escalating
   `risk:check-error`.
5. `sync.py` validates the result against a strict schema (exact keys, owned labels only, size caps),
   then syncs labels (adds what is missing, removes only owned labels no longer wanted), upserts
   ONE marker comment (<= 60,000 chars; GitHub rejects 65,536; text is cleaned and `@` escaped
   BEFORE the cap), and writes the full per-file table to a neutral check run `catalog-verify`.
   Labels go first so a rejected comment can never cost them. A per-PR concurrency group stops two
   runs from creating two comments.

`verify-pr.yml` is only a trigger: it has no permissions, checks out nothing and runs no code.

| Trusted (default branch) | Untrusted (the PR) |
|---|---|
| the workflow definition of `verify-label.yml` | `verify-pr.yml` as changed by the PR (it can only stop labels from appearing) |
| `scripts/verify/**`, `sources/registry.yaml` | the YAML files under `providers/**` at base and head (parsed as data) |
| `.github/test/model.cue`, `model.rules.cue` (enum rules) | `providers/<p>/default.yaml` at head (data, read by the cap rules) |
| the PR number, base sha, head sha, head repo / branch from the GitHub API | anything inside the YAML (all text is cleaned and code-spanned before it is shown) |

Consequences: a PR that edits the verifier, the registry or the schema is judged by the old
versions and relies on `verify-tests.yml` (which runs on those paths, incl. the two CUE files) to
test the new ones; the label job only fires when the trigger workflow "Verify PR" runs, and a PR controls that
workflow's definition: a PR that stops it from running is not re-verified, so labels from an
earlier head can stay on the new head. Labels are advisory; this tool only reports. Adapters fetch public sources keyed by provider; they
must never use a URL taken from a PR file.

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
