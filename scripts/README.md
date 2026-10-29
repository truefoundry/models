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
