# Contributing to TrueFoundry Models Registry

Thank you for your interest in contributing to the TrueFoundry Models Registry! This document provides guidelines and instructions for contributing.

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [How to Contribute](#how-to-contribute)
- [Adding a New Model](#adding-a-new-model)
- [Updating an Existing Model](#updating-an-existing-model)
- [Adding a New Provider](#adding-a-new-provider)
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
model: <model-identifier>
costs:
  input_cost_per_token: <number>
  output_cost_per_token: <number>
limits:
  max_input_tokens: <number>
  max_output_tokens: <number>
capabilities:
  supports_chat: <boolean>
  supports_text: <boolean>
  supports_image: <boolean>
  supports_code: <boolean>
  supports_tools: <boolean>
  supports_function_calling: <boolean>
  supports_vision: <boolean>
  supports_system_messages: <boolean>
mode: <chat|completion|embedding|image|audio>
original_provider: <provider-name>
```

### 3. Optional Fields

```yaml
costs:
  input_cost_per_token_batches: <number>
  output_cost_per_token_batches: <number>
  cache_read_input_token_cost: <number>
  cache_creation_input_token_cost: <number>
capabilities:
  supports_pdf: <boolean>
  supports_doc: <boolean>
  supports_cache_control: <boolean>
  supports_parallel_function_calling: <boolean>
  supports_tool_choice: <boolean>
  supports_prompt_caching: <boolean>
  supports_response_schema: <boolean>
  supports_pdf_input: <boolean>
source: <url-to-pricing-page>
params: <array-of-configurable-parameters>
removeParams: <array>
requiredParams: <array>
defaultRegion: <string>
deprecation_date: <YYYY-MM-DD>
is_deprecated: <boolean>
```

### 4. Example

```yaml
model: gpt-4o
costs:
  input_cost_per_token: 0.0000025
  output_cost_per_token: 0.00001
  cache_read_input_token_cost: 0.00000125
limits:
  max_input_tokens: 128000
  max_output_tokens: 16384
capabilities:
  supports_chat: true
  supports_text: false
  supports_image: true
  supports_tools: true
  supports_function_calling: true
  supports_vision: true
  supports_system_messages: true
  supports_response_schema: true
mode: chat
original_provider: openai
is_deprecated: false
```

## Updating an Existing Model

When updating a model:

1. Find the model file in `providers/<provider>/` (note: file names may not exactly match the `model` field)
2. Update the relevant fields
3. Add a `source` field with a link to the official documentation/pricing page
4. Submit a PR with a clear description of what changed and why

Common updates include:
- Pricing changes
- New capabilities
- Token limit updates
- Deprecation notices

## Adding a New Provider

To add a new provider:

1. Create a new directory: `providers/<provider-name>/`
2. Add a `default.yaml` with provider-level defaults (optional)
3. Add individual model YAML files
4. Update the README.md to include the new provider in the structure section

### Naming Conventions

- Provider directory names should be lowercase with hyphens (e.g., `azure-openai`, `google-vertex`)
- Model file names should be descriptive and use lowercase with hyphens
- **Note**: File names do not necessarily match the `model` field in the YAML. The `model` field contains the actual model identifier used by the provider's API, while the file name is for organization purposes. For example:


## Pull Request Process

1. **Title**: Use a clear, descriptive title
   - `Add: provider/model-name`
   - `Update: provider/model-name pricing`
   - `Fix: provider/model-name capabilities`

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

- Use 2 spaces for indentation
- No trailing whitespace
- End files with a newline
- Use lowercase for boolean values (`true`/`false`)
- Use single quotes for strings only when necessary
- Keep fields in a consistent order (see examples above)

### Commit Messages

- Use present tense ("Add model" not "Added model")
- Use imperative mood ("Update pricing" not "Updates pricing")
- Keep the first line under 72 characters
- Reference issues when applicable

### Versioning for Dated Models

For models with version dates:
- Use the date format from the provider (e.g., `gpt-4-0613.yaml`)
- Create aliases without dates that point to the latest version

## Questions?

If you have questions about contributing, feel free to:
- Open an issue with the `question` label
- Reach out to the maintainers

Thank you for contributing!
