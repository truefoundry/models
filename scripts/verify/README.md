# verify

Checks changed model YAMLs against what each provider publishes, and reports. Report only: it
never fails a PR for a missing or partial source (the check ends `neutral`).

- `types.py` is the contract between `sources/*` (one adapter per official source) and the core.
- Nothing in this package uses an LLM, a database or a secret. Sources are public.
