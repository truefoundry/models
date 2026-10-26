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

# Reasoning effort

For added or modified model YAMLs, check whether the exact model and host support
configurable reasoning effort. When supported, require an explicit model-level
`params` entry with `key: reasoning_effort`, `type: string`, and the complete,
nonempty `supportedValues` list, even when it matches `default.yaml`. Catalog
clients need model-level metadata to discover this control; provider inheritance
alone is insufficient. A model entry replaces the entire param entry.

Verify values and defaults against official host/model docs and cite the source.
Use `defaultValue` only for a documented effort default, and ensure it belongs
to `supportedValues`. Dynamic/automatic thinking is not evidence of a `medium`
default. Distinguish API defaults from recommended settings. Respect host-specific
restrictions and endpoint differences; do not copy an upstream enum blindly.

`thinking: true`, an always-on reasoning trace, or a token-budget control alone
does not prove effort support. If the host rejects or ignores effort, flag an
explicit effort entry or an inherited default that needs `removeParams`.
Do not add an entry and remove the same key. Preserve documented gateway aliases
such as a `none` value that the adapter maps to disabled thinking; do not confuse
them with native effort levels or invent such mappings.

Compare the same exact model across aliases, snapshots, regional inference
profiles, and hosts to spot omissions, then verify each host's contract. Check
both `aws-bedrock` and `aws-bedrock-mantle`; their endpoints and support differ.
