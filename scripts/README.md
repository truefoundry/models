# Model identity scripts

Human-reviewed sources of truth live at the repo root:

- `canonical_aliases.yaml` — provider API `model` ID → `canonical_model`
- `canonical_external_ids.yaml` — `canonical_model` → Artificial Analysis ids
- `canonical_exceptions.yaml` — language models exempt from `canonical_model`

Workflow:

1. `python3 scripts/propose_canonical_models.py` — proposals only (writes `reports/`)
2. Review and update `canonical_aliases.yaml`
3. `python3 scripts/apply_canonical_models.py` — idempotent apply
4. `AA_API_KEY=... python3 scripts/match_artificial_analysis.py` — match reports only
5. Review and update `canonical_external_ids.yaml` (unambiguous matches only)
6. `python3 scripts/apply_external_ids.py` — idempotent apply
7. `python3 scripts/check_model_identity.py` — validation

Proposal and matching scripts never edit provider YAML.
