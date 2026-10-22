# Model identity scripts

Identity fields are optional on each provider model YAML and are reviewed in PRs:

- `canonical_model` — `<creator>/<foundation-model>` when known
- `external_ids` — optional verified Artificial Analysis `id` + `slug` (requires `canonical_model`)

## PR workflow

1. Optionally set `canonical_model` / `external_ids` on the model YAML in the PR.
2. CI runs:
   - `scripts/check_model_identity.py` — format and group consistency when fields are present
   - `scripts/verify_changed_external_ids.py` — live AA check for changed files that set `external_ids`
3. Repository secret `AA_API_KEY` enables live AA verification for changed `external_ids`.
   If the secret is missing, CI still passes identity structure checks and emits a warning.

## Optional local helpers

```bash
# Propose canonical names for review (writes reports/)
python3 scripts/propose_canonical_models.py

# Match YAML canonical_model values to AA (writes reports/; needs AA_API_KEY)
AA_API_KEY=... python3 scripts/match_artificial_analysis.py

# Bulk apply from a local mapping file you created while reviewing reports
python3 scripts/apply_canonical_models.py --from /tmp/aliases.yaml
python3 scripts/apply_external_ids.py --from /tmp/external_ids.yaml
```

Proposal and matching scripts never edit provider YAML.

# Publish guard

`publish_guard.py` runs in the `upload` job of `trigger-sync.yml`, before anything is copied to S3. It compares the freshly built `ai-models.json` with the one that is live (`llm-gateway/v2/prod/ai-models.json`) and catches large mistakes before a merge publishes them to prod. It is a blunt net, not a check that a price is right: a wrong price inside the limits still needs review.

| Rule | Fires when | Blocks |
|---|---|---|
| `malformed` | the new file is not a non-empty list of `{provider, model, costs}` entries | yes, and no flag overrides it |
| `bad_rate` | a negative or non-finite rate | yes |
| `unit_slip` | a per-token rate is 0.1 or more (the highest real rate is about 0.01) | yes |
| `price_jump` | a rate moved 10x or more, either way | yes |
| `price_to_zero` | a rate that was above zero is now zero | yes |
| `field_dropped` | a model that stays in a region lost its input or output rate and has no per-image, per-second, per-character, per-page, per-query or per-request one | yes |
| `removed` | a provider lost 3+ models and 20% of its live models, or the catalog lost 5% | yes |
| `block_dropped` | 5+ models lost the same pricing block (`tiered_pricing`, `priority_pricing`, `flex_pricing`, `ultrafast_pricing`) | yes |
| `rate_dropped` | 5+ models lost the same optional rate in every region (cache read, cache creation, batches) | yes |
| `regions_dropped` | 5+ of one provider's multi-region models lost a region | yes |
| `price_change` | a rate moved more than 3x but less than 10x | no, listed as a warning |

The first three need no baseline. The rest compare with the live file; one live entry without a provider and model is ignored (and counted in the summary) instead of switching the comparison off.

## Modes

- Repository variable `PUBLISH_GUARD_MODE=enforce` (case and spaces ignored) blocks the publish on blocking findings. Unset, or any other value, only reports them in the job summary. That is the default.
- In enforce mode, if the live file cannot be read after 3 tries (a missing `s3:GetObject` permission, an S3 error), the job fails rather than publishing unchecked. In report mode it warns and runs the first three rules only; the summary says so in bold.
- A manual run of `Build and Upload Model Configs` with `skip_publish_guard` on publishes despite findings. The guard still runs and reports. It never overrides `malformed`.
- Exit codes: 0 nothing blocking, 10 blocking findings, 2 the new file is unreadable or malformed, 3 the guard crashed. A crash or any other status means the guard did not run; the workflow continues and writes that into the job summary.

## When a publish is blocked

Prod keeps the old file. Check the guard's report in the job summary. If the change is right, start the workflow manually with `skip_publish_guard` on ("Run workflow"; the Re-run button keeps the original inputs, so it would be blocked again). A manual run builds the current head of the branch you pick, so it also ships anything merged since. While a blocked change sits on main, every later push is blocked too, because the live file is unchanged.

## What it does not catch

All rates scaled by less than 3x, input and output swapped on one model, a region renamed everywhere, tier thresholds doubled, model-level fields (`mode`, `limits`, `isDeprecated`), a rate going from 0 to priced, a provider losing fewer than 3 models, a catalog losing less than 5%, and a new model with a unit mistake below 0.1 per token (there is no baseline to compare it with). `provider-configs.json` is not checked.

## Replay on this repo's history

Replayed over the 684 merges that touched model files between 2026-09-04 and 2026-10-22, the guard would have blocked 9 (1.3%, about one in 76) and warned on 9 more. Seven of the nine are bot PRs with price moves of 10x or more; reading them, most look like genuine vendor price changes or corrections (one blocks the fix of an earlier wrong price), and a few are the bot's own flip-flops. The other two are the provider renames (`truerouter-curated` to `tfy-managed` to `TrueFoundry Managed`, which look like 22 of 22 models removed). So in enforce mode expect an occasional deliberate override; that is the cost of the net, and the reason it ships report-only first. The rules added after review (`bad_rate`, `rate_dropped`, `regions_dropped`) and the tightened `field_dropped` would have blocked none of the 684.

```bash
python3 scripts/publish_guard.py --new ai-models.json --live live-ai-models.json   # exit 10 on blocking findings
python3 scripts/test_publish_guard.py                                              # unit tests
```
