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
  propose.py     python -m verify.propose: the prices a source gives for a NEW model (used by the addition job)
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

Never touched: `gate:hold`, the addition job's `id:*` labels and `verify:prices-from-source`,
`gate:reviewed`, any other label. What the labels this tool does not own mean:

| label | set by | meaning |
|---|---|---|
| `gate:hold` | a human | the ONLY hold: no gate is set, risks and verification are still reported; never removed |
| `id:case-duplicate` | the addition job | INPUT: the verifier sets `gate:escalate` and says "addition flagged: case duplicate of an existing file" |
| `id:high-edit-provider` | the addition job | INPUT: the verifier sets `gate:escalate` and says "provider has a high human-edit rate and no source price was written" |
| any other `id:*` | the addition job | ignored: not a hold, not an escalation |
| `verify:prices-from-source` | the addition job | its prices were written from the official source; the verifier never reads or touches it |

The addition job sets no `gate:*` label any more; the gate always comes from this tool.

### Gates (strongest first)

1. `gate:hold` (not ours): a human put `gate:hold` on the PR. Sticky; this tool then sets no gate
   and never removes it. It still reports risks and verification. No `id:*` label is a hold.
2. `gate:escalate`: an addition-job flag (`id:case-duplicate`, `id:high-edit-provider`, with the
   reason in the comment), any escalating risk, or a conflict with an official source in a field this PR
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
| `escalate` | `gate:escalate`: the lines name the addition flags, the conflict or the escalating risks |
| `hold` | `gate:hold`: no gate is set, the lines still name what would escalate |

A review-level rule finding (`risk:rule-*` that does not escalate) does not leave the fast lane. The
label job refuses a result whose `fast-lane` label, `lane`, gate and kind disagree.

`verify-stale.yml` (daily 08:00 UTC, default branch code, `pull-requests: read` + `issues: write`)
runs `python -m verify.queue`: it lists the open bot PRs labelled `fast-lane` that are older than
24 h and the open PRs labelled `gate:escalate` older than 72 h (drafts, `trueforge/*` and
`gate:hold` left out; a PR the addition job flagged is `gate:escalate` and so is listed) in one issue, `Bot PR review queue`: created when missing (found by exact title
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

## Propose: prices for a new model

The addition job opens a PR for every model a provider lists that has no file yet. 47% of the human
edits on those PRs were price fixes, so when the provider has an official price source the new file is
written WITH the source's prices. An adapter may implement `propose(repo_path, doc) -> Proposal | None`
(`types.ProposingSource`; optional, an adapter without it gives nothing). It uses the same lookup,
matching, units and guards as `check()`, so `apply the proposal to an empty doc, then check()` is
`verified` for every proposed field (a permanent test over recorded live data, `tests/test_propose.py`).

```
cd scripts && python -m verify.propose --provider aws-bedrock --model-id global.anthropic.claude-sonnet-4-5-20250929-v1:0 \
    [--mode chat] [--regions us-east-1,eu-west-1] [--allow-listing-prices] [--json]
```

It reads `sources/registry.yaml` (the sources listed for the provider with `price` in `fields`) and prints
one object: `proposals: [{source, partial, unreachable, apply, values: [{locator, value}], notes}]` and a `reason` when
there is none. Exit 0 whatever the answer (3 for an unusable registry, still JSON). A source that is down or
does not list the model is an empty proposal with a note; `unreachable` is true only when the source could not be READ
(the addition job stops asking a source that is down), never for "read fine, model not there".

| Source | Gives | Leaves out (and says so) |
|---|---|---|
| `aws-price-list` | per region: input, output, cache read, cache write 5m / 1h, batch, flex, priority. Regions: the ones named in `doc.costs`, else every region of the Price List's `region_index.json`. `global.` ids take the global price, all other ids the regional one | two SKUs with two prices, a unit it does not read, a 5x source outlier, a $0 SKU, anything long-context / latency-optimized / custom-model (`tiered_pricing` is never proposed), and token SKUs of another modality (Nova 2 Omni / Pro audio, image, video; Nova Sonic speech) or of a family the parser has no grammar for (listed as unread). `partial` when any of those, a failed region, a requested region with no price, or such a SKU exists |
| `deepinfra` | the LIST price as `check` maps it: input / output / cache read / cache write 5m / 1h, per-second, per-character | `image_units` (input or output per image is a catalog convention), `input_tokens` of a generator (input vs output image / video token), `time`, `frame_units`, zero prices. An active discount: list price proposed, `partial`, the note gives the percentage and end date. Priority / flex service-tier rates (the API publishes them as multipliers, `rate_per_service_tier_*`) are not read: `partial` and a note, nothing written. Cache prices derived from the API's 8-decimal ratios are rounded to 6 significant digits |
| `openrouter` | prompt, completion, cache read, cache write (5m), context window, max output | the 1h cache write, negative (variable) prices, tier overrides, image / audio / request prices. ALWAYS `partial`: the listing quotes the cheapest endpoint |

`apply` says whether the addition job may WRITE a proposal: `deepinfra` and `aws-price-list` yes,
`openrouter` no unless `--allow-listing-prices`.

**Why OpenRouter is report-only.** (1) The addition job's own fetcher already writes the listing price into the
stub, so a proposal adds nothing: of the last 30 merged OpenRouter addition PRs, 27 files kept the stub's costs
untouched to merge and the 3 that changed only added `tiered_pricing`. (2) The listing is the cheapest endpoint,
not first-party: today's /models against 30 random existing `providers/openrouter` files that are listed:
17 equal, 9 below the listing, 4 above it (file prices above the listing are first-party prices, below it are
older cheapest-endpoint prices). The price sweep keeps the same line (`SAFE_SOURCES`). Turn it on only with a range check.

## Page-based sources

`sources/anthropic_pricing.py` (Anthropic pricing docs, Markdown) is the pilot for a provider with no price API. Page
adapters parse deterministically (no LLM) and fail closed: an unexpected header, column count, unit or model name makes
every file `partial` with one note. Cells are cross-checked against the page's own multipliers, and the fetch is pinned to
the page's host over https. `python -m verify.sources.anthropic_pricing --fingerprints` prints versioned per-row hashes
for change detection (the page's raw hash is not a stable signal); the sweep and the schedule should consume that, not
re-parse the page. Registry row: `provider: anthropic`, `kind: page`, `source: anthropic-pricing-page`.

## azure-retail-prices (azure-open-ai, azure-ai-foundry, microsoft-foundry)

Public Azure Retail Prices API, one filter (Foundry Models, Consumption, five reference regions), at most 12 pages
and 8 MB per run, a wall-clock deadline. Details and the SKU grammar are in `sources/azure_retail.py`. What a reviewer
must know about `*`, the catalog's default cost entry, which has no Azure deployment type of its own:

- `global`, `datazone_us`, `datazone_eu` are compared with the Global / Data Zone meters of their own reference regions.
- `*` next to a `global` entry is the **Regional** price. If Azure has no Regional meter for the model, `*` is
  `uncovered` with a note (it is not compared with Global).
- `*` with **no** `global` entry is taken as **Global**. When Azure also has a Regional price that differs (usually
  about 10% higher), a `*` equal to the Global price is **verified as Global**, and every such check carries the note
  "assumes `*` = Global (...)". A `*` equal to the Regional price is `uncovered`, and a `*` equal to neither is a
  conflict that is not writable (which price to write is a guess).
- Claude on Foundry (Marketplace-billed), tiered / audio / image / realtime / fine-tune prices stay `uncovered`.

## Tests

```
cd scripts && python -m pytest -q -p no:cacheprovider verify
```

Offline and deterministic; adapters are replaced by fake sources.
