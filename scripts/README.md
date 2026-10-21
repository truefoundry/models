# Model identity scripts

Identity fields live on each provider model YAML and are reviewed in PRs:

- `canonical_model` — `<creator>/<foundation-model>`
- `external_ids` — optional verified Artificial Analysis `id` + `slug`
- `canonical_exceptions.yaml` — paths exempt from requiring `canonical_model`

## PR workflow

1. Edit `canonical_model` / `external_ids` on the model YAML in the PR.
2. CI runs:
   - `scripts/check_model_identity.py` — format, required fields, group consistency
   - `scripts/verify_changed_external_ids.py` — live AA check for changed files that set `external_ids`
3. Repository secret `AA_API_KEY` is required when a PR adds or changes `external_ids`.

## Optional local helpers

These never need to be committed as mapping sources of truth:

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
