# TrueFoundry Models

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](CONTRIBUTING.md)

A comprehensive, community-maintained registry of AI/LLM model configurations.

## Why Use This?

LLM model configs change often — prices drop, capabilities expand, limits shift. This repository provides up-to-date information across providers and makes updating stale data easy.

- **Unified Schema** — Consistent model configuration format across 17 providers
- **Up-to-Date Pricing** — Current cost information for input/output tokens, batch processing, and caching
- **Capability Tracking** — Know exactly what each model supports (vision, tools, structured output, etc.)
- **Open Source** — Community-driven updates ensure accuracy and coverage

## Supported Providers

| Provider | Models | Description |
|----------|--------|-------------|
| OpenAI | 81 | GPT-4, GPT-4o, GPT-5, o1, o3, DALL-E, Whisper, TTS |
| Anthropic | 21 | Claude 3, Claude 3.5, Claude 4 |
| AWS Bedrock | 139 | Claude, Llama, Titan, Mistral on AWS |
| Azure OpenAI | 77 | OpenAI models on Azure |
| Azure AI Foundry | 65 | Azure AI models |
| Google Vertex AI | 110 | Gemini, PaLM on GCP |
| Google Gemini | 25 | Gemini Pro, Ultra, Flash |
| Mistral AI | 37 | Mistral, Mixtral, Codestral |
| Cohere | 16 | Command, Embed models |
| Groq | 14 | Fast inference models |
| Together AI | 39 | Open source model hosting |
| DeepInfra | 67 | Open source model hosting |
| Perplexity | 25 | Search-augmented models |
| Cerebras | 8 | Fast inference models |
| Databricks | 28 | Databricks-hosted models |
| SambaNova | 16 | Enterprise AI models |
| AI21 | 13 | Jamba models |

## Installation

```bash
git clone https://github.com/truefoundry/models.git
```

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
│   ├── o1.yaml
│   └── ...
├── anthropic/
│   ├── default.yaml
│   ├── claude-3-5-sonnet.yaml
│   ├── claude-3-opus.yaml
│   └── ...
└── ...
```

## Model Configuration Template

Each model YAML file follows this schema:

```yaml
model: <model-identifier>           # Required: API model name

costs:
  input_cost_per_token: <number>    # Cost per input token (USD)
  output_cost_per_token: <number>   # Cost per output token (USD)
  input_cost_per_token_batches: <number>    # Batch API pricing
  output_cost_per_token_batches: <number>
  cache_read_input_token_cost: <number>     # Prompt caching cost

limits:
  max_input_tokens: <number>        # Maximum context window
  max_output_tokens: <number>       # Maximum generation length

capabilities:
  supports_chat: <boolean>          # Chat completions API
  supports_vision: <boolean>        # Image input support
  supports_tools: <boolean>         # Tool/function calling
  supports_function_calling: <boolean>
  supports_system_messages: <boolean>
  supports_response_schema: <boolean>   # Structured output/JSON mode
  supports_prompt_caching: <boolean>
  supports_pdf_input: <boolean>

mode: <chat|completion|embedding|image|audio>
original_provider: <provider-name>
is_deprecated: <boolean>
deprecation_date: <YYYY-MM-DD>
```

## Contributing

We welcome contributions! Please see our [Contributing Guide](CONTRIBUTING.md) for details.

### Quick Start

1. Clone the repository
2. Create a new branch (`git checkout -b add-new-model`)
3. Add or update model configurations
4. Validate your YAML files
5. Submit a pull request

### Adding a New Model

```bash
# Copy an existing model as a template
cp providers/openai/gpt-4o.yaml providers/openai/new-model.yaml

# Edit with your model's configuration
# Submit a PR!
```

## Updating Pricing

Model pricing changes frequently. If you notice outdated pricing:

1. Check the provider's official pricing page
2. Update the relevant YAML file
3. Submit a PR with a link to the source

## Validation

Validate your YAML files before submitting:

```bash
# Using Python
python -c "import yaml; yaml.safe_load(open('providers/openai/gpt-4o.yaml'))"

# Using yq
yq eval '.' providers/openai/gpt-4o.yaml
```

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
