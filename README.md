# TrueFoundry Models

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](CONTRIBUTING.md)

A comprehensive, community-maintained registry of AI/LLM model configurations. This repository provides standardized model metadata including pricing, features, and token limits across all major AI providers.

## Scope

This registry is **metadata only**, for providers the TrueFoundry LLM Gateway already integrates with. Every directory under `providers/` corresponds to an existing gateway integration, and the list of those integrations lives in the gateway, not here.

That means:

- **Adding or updating a model** under an existing provider is exactly what this repo is for. Pricing, limits, features, modalities, deprecations — open a PR.
- **Adding a new provider** is not. A new `providers/<name>/` directory has no effect on its own: without a gateway integration behind it, nothing reads those files at runtime. New provider support is gateway work, so [open an issue](../../issues) describing the provider and the use case instead of sending registry YAML.

See [Supported Providers](#supported-providers) below for the current list.

## Why Use This?

LLM model configs change often — prices drop, features expand, limits shift. This repository provides up-to-date information across providers and makes updating stale data easy.

- **Unified Schema** — Consistent model configuration format across 24 providers
- **Up-to-Date Pricing** — Current cost information for input/output tokens, batch processing, and caching
- **Feature Tracking** — Know exactly what each model supports (vision, tools, structured output, etc.)
- **Open Source** — Community-driven updates ensure accuracy and coverage

## Supported Providers

This is the complete set of providers the gateway supports. If a provider isn't listed here, the registry has no place to put its models yet. The table is generated from `providers/` by [`update-readme-counts.ts`](.github/scripts/update-readme-counts.ts), so don't edit it by hand.

| Provider | Models | Description |
|----------|--------|-------------|
| OpenRouter | 938 | Unified API for open source models |
| Google Vertex AI | 436 | Gemini, PaLM on GCP |
| Microsoft Foundry | 426 | OpenAI and Foundry catalog models on Microsoft Foundry |
| Together AI | 384 | Open source model hosting |
| DeepInfra | 262 | Open source model hosting |
| Azure OpenAI | 238 | OpenAI models on Azure |
| AWS Bedrock | 231 | Claude, Llama, Titan, Mistral on AWS |
| Azure AI Foundry | 221 | Azure AI models |
| OpenAI | 156 | GPT-4, GPT-4o, GPT-5, o1, o3, DALL-E, Whisper, TTS |
| Deepgram | 143 | Speech-to-text and text-to-speech models |
| Mistral AI | 104 | Mistral, Mixtral, Codestral |
| xAI | 92 | Grok models |
| Google Gemini | 82 | Gemini Pro, Ultra, Flash |
| Databricks | 68 | Databricks-hosted models |
| Aws Bedrock Mantle | 55 |  |
| Cohere | 39 | Command, Embed models |
| SambaNova | 31 | Enterprise AI models |
| Anthropic | 28 | Claude 3, Claude 3.5, Claude 4 |
| Groq | 24 | Fast inference models |
| Perplexity | 24 | Search-augmented models |
| Wafer | 18 |  |
| AI21 | 12 | Jamba models |
| ElevenLabs | 12 | Voice synthesis and text-to-speech models |
| Cerebras | 6 | Fast inference models |

## Installation

### Direct Clone

```bash
git clone https://github.com/truefoundry/models.git
```

## Model Configuration Schema

Each model YAML file follows this schema (validated by [CUE](.github/test/model.cue)):

```yaml
# Required
model: gpt-5.4-mini-2026-03-17        # Model identifier used by the provider's API
mode: chat                             # Primary capability (chat, embedding, image, text_to_speech, etc.)

# Pricing — array of cost entries, each with a region ("*" for global)
costs:
    - region: "*"
      input_cost_per_token: 7.5e-7
      output_cost_per_token: 0.0000045
      cache_read_input_token_cost: 7.5e-8

# Token and context window limits
limits:
    context_window: 400000
    max_output_tokens: 128000

# Feature flags
features: [function_calling, prompt_caching, structured_output, system_messages]

# Input/output modalities
modalities:
    input: [text, image]
    output: [text]

# Extended thinking / reasoning support
thinking: true

# Documentation or pricing source URLs
sources:
    - https://developers.openai.com/api/docs/pricing
```

See the [Contributing Guide](CONTRIBUTING.md) for the full list of fields, valid values, and more examples.

## Directory Structure

```
providers/
├── <provider>/
│   ├── default.yaml        # Default params for all models under this provider
│   ├── <model>.yaml
│   └── ...
```

**Example:**

```
providers/
├── openai/
│   ├── default.yaml
│   ├── gpt-4o.yaml
│   ├── gpt-4o-mini.yaml
│   └── ...
├── anthropic/
│   ├── default.yaml
│   ├── claude-3-5-sonnet.yaml
│   └── ...
└── ...
```

## Contributing

We welcome contributions! Whether it's adding a model under one of the [supported providers](#supported-providers), updating pricing, or fixing outdated information — see the [Contributing Guide](CONTRIBUTING.md) for details on the schema, examples, and PR process. For a provider that isn't on that list, read [Scope](#scope) first.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
