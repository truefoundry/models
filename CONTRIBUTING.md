# Contributing to TrueFoundry Models Registry

Thank you for your interest in contributing to the TrueFoundry Models Registry! This document provides guidelines and instructions for contributing.

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [How to Contribute](#how-to-contribute)
- [Adding a New Model](#adding-a-new-model)
- [Updating an Existing Model](#updating-an-existing-model)
- [Pull Request Process](#pull-request-process)
- [Style Guide](#style-guide)

## Code of Conduct

By participating in this project, you agree to abide by our [Code of Conduct](CODE_OF_CONDUCT.md). Please read it before contributing.

## How to Contribute

### Reporting Issues

- Check if the issue already exists in the [Issues](../../issues) section
- If not, create a new issue with a clear title and description
- Include relevant details like model name, provider, and what needs to be updated

### Submitting Changes

1. Clone the repository (`git clone https://github.com/truefoundry/models.git`)
2. Create a new branch (`git checkout -b feature/add-new-model`)
3. Make your changes
4. Commit your changes (`git commit -m 'Add new model: provider/model-name'`)
5. Push to the branch (`git push origin feature/add-new-model`)
6. Open a Pull Request

## Adding a New Model

To add a new model, create a YAML file in the appropriate provider directory:

### 1. File Location

```
providers/<provider-name>/<model-name>.yaml
```

### 2. Required Fields

```yaml
model: <model-identifier>   # The model identifier used by the provider's API
mode: <mode>                 # The model's primary capability (see values below)
```

Valid `mode` values:

`audio_transcription`, `audio_translation`, `chat`, `completion`, `embedding`, `image`, `moderation`, `realtime`, `rerank`, `text_to_speech`, `unknown`, `video`

### 3. Optional Fields

```yaml
# Pricing — an array of cost entries, each with a region ("*" for global pricing)
costs:
    - region: "*"
      input_cost_per_token: <number>
      output_cost_per_token: <number>
      input_cost_per_token_batches: <number>
      output_cost_per_token_batches: <number>
      cache_read_input_token_cost: <number>
      # See the CUE schema for all supported cost fields (audio, image, video, etc.)

# Token and context window limits
limits:
    context_window: <number>
    max_input_tokens: <number>
    max_output_tokens: <number>
    max_tokens: <number>
    max_query_tokens: <number>              # For embedding/rerank models
    output_vector_size: <number>            # For embedding models
    tool_use_system_prompt_tokens: <number>

# Supported features/capabilities
features:
    - <feature>
# Valid features: assistant_prefill, cache_control, code_execution,
#   function_calling, parallel_function_calling, prompt_caching,
#   structured_output, system_messages, tool_choice, tools

# Input/output modalities
modalities:
    input: [text, image, audio, video, code, doc, pdf, embedding]
    output: [text, image, audio, video, code, doc, pdf, embedding]

# Whether the model supports extended thinking / reasoning
thinking: <boolean>

# Additional modes this model can be accessed through
supportedModes: [<mode>, ...]

# Lifecycle status
status: <active|preview|deprecated|retired>

# Deprecation date (YYYY-MM-DD format)
deprecationDate: <date-string>

# Whether the model is deprecated (prefer using status instead)
isDeprecated: <boolean>

# Documentation or pricing source URLs
sources:
    - <url>

# Message roles accepted by this model
messages:
    options: [system, user, assistant, developer]

# Parameter overrides relative to the provider default
params:
    - key: <param-key>
      defaultValue: <value>
      minValue: <number>
      maxValue: <number>
      type: <number|string|boolean|json|array-of-strings>

# Param keys to remove from the provider default
removeParams: [<param-key>, ...]

# Param keys that must always be provided by callers
requiredParams: [<param-key>, ...]

# Provider-specific escape-hatch configuration. Only set a key here when the
# behaviour cannot be expressed through the generic fields above, and only on
# models belonging to the provider that owns the key.
extra_configuration:
    # aws-bedrock-mantle only. The path segment AWS serves the model under,
    # injected before /v1/... Copy it from the bedrock-mantle row of the model
    # card's Programmatic Access table: an In-Region endpoint URL of
    # https://bedrock-mantle.{region}.api.aws/openai/v1 means "/openai", while
    # a plain .../v1 means the key should be omitted entirely.
    bedrock_mantle_adhoc_prefix: /openai
```

### 4. Examples

A chat model with some details:

```yaml
model: gpt-5.4-mini-2026-03-17
mode: chat
costs:
    - region: "*"
      input_cost_per_token: 7.5e-7
      output_cost_per_token: 0.0000045
      cache_read_input_token_cost: 7.5e-8
      input_cost_per_token_batches: 3.75e-7
      output_cost_per_token_batches: 0.00000225
features:
    - function_calling
    - parallel_function_calling
    - tool_choice
    - prompt_caching
    - structured_output
    - system_messages
limits:
    context_window: 400000
    max_output_tokens: 128000
    max_tokens: 128000
modalities:
    input:
        - text
        - image
    output:
        - text
thinking: true
params:
    - key: max_tokens
      defaultValue: 128
      maxValue: 128000
      minValue: 1
    - key: reasoning_effort
      defaultValue: medium
sources:
    - https://developers.openai.com/api/docs/pricing
    - https://developers.openai.com/api/docs/deprecations
```

A minimal model definition (e.g., audio transcription or TTS):

```yaml
model: nova-3-general
mode: audio_transcription
```

## Updating an Existing Model

When updating a model:

1. Find the model file in `providers/<provider>/` (note: file names may not exactly match the `model` field)
2. Update the relevant fields
3. Add `sources` with links to the official documentation/pricing pages
4. Submit a PR with a clear description of what changed and why

Common updates include:

- Pricing changes
- New features
- Token limit updates
- Deprecation notices

## Pull Request Process

1. **Title**: Use a clear, descriptive title
  - `Add: provider/model-name`
  - `Update: provider/model-name pricing`
  - `Fix: provider/model-name features`
2. **Description**: Include
  - What changes were made
  - Source/reference for the changes (official docs, pricing pages)
  - Any breaking changes
3. **Review**:
  - All PRs require at least one review
  - Maintainers may request changes or clarifications
4. **Merge**:
  - PRs are merged once approved
  - Squash merge is preferred for clean history

## Style Guide

### YAML Formatting

Run `npm run lint:yaml:fix` to auto-format your YAML files before submitting.

### Commit Messages

- Use present tense ("Add model" not "Added model")
- Use imperative mood ("Update pricing" not "Updates pricing")
- Keep the first line under 72 characters
- Reference issues when applicable

### Versioning for Dated Models

For models with version dates:

- Use the date format from the provider (e.g., `gpt-4-0613.yaml`)

## Questions?

If you have questions about contributing, feel free to:

- Open an issue with the `question` label
- Reach out to the maintainers

Thank you for contributing!