# Context windows

For added or modified models under `providers/**/*.yaml` supporting `chat`,
`completion`, or `responses`, flag a missing or invalid `limits.context_window`
unless a YAML comment explains why it is unknown and cites official docs.
The value must be a positive integer. Skip provider configuration files.

Compare models with the same `canonical_model` to spot omissions, but verify
values against official docs before suggesting a fix. Provider-specific limits
take precedence. If using the exact upstream model's spec, cite it and explain
that the host publishes no separate limit. Respect documented exceptions and
gated extensions; do not derive context windows from input/output token limits.
