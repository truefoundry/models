# Model catalog review

## Context window completeness

For added or modified model files under `providers/**/*.yaml` whose primary or
supported modes include `chat`, `completion`, or `responses`:

- Flag a missing, null, zero, negative, or non-integer
  `limits.context_window` unless the file explains the omission with a specific
  YAML comment and official documentation URLs. Exclude `default.yaml` and
  `provider-config.yaml`; do not require context windows for unrelated modes.
- Compare entries with the same exact `canonical_model` to find likely missing
  metadata. Cite a matching file and value when useful, but treat it as a research
  lead: matching identity does not prove equal hosting limits. Never choose the
  largest value or infer identity from a similar display name.
- Require official evidence for a proposed value. Hosting-provider limits take
  precedence over upstream model specs. An upstream-spec fallback must identify
  the exact unchanged model, explain that the host publishes no separate limit,
  and cite the creator's official model spec. Respect smaller host limits,
  deployment/fine-tune variants, and beta/header-gated context extensions.
- Do not treat `max_input_tokens`, `max_output_tokens`, or `max_tokens` as an
  automatic substitute for the total context window, or add them together.
- Accept documented unknown/deployment-specific limits. Do not ask authors to
  invent values or backfill unrelated existing files. Preserve sourced values
  when a summary page merely omits them; flag removals without supporting evidence.

The CUE schema deliberately makes limits optional for heterogeneous model types.
Schema validation alone does not establish context-window completeness.
