# TrueFoundry Models

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](CONTRIBUTING.md)

A comprehensive, community-maintained registry of AI/LLM model configurations. This repository provides standardized model metadata including pricing, capabilities, token limits, and supported features across all major AI providers.

## Why Use This?

- **Unified Schema**: Consistent model configuration format across 17 providers
- **Up-to-Date Pricing**: Current cost information for input/output tokens, batch processing, and caching
- **Capability Tracking**: Know exactly what each model supports (vision, tools, structured output, etc.)
- **Open Source**: Community-driven updates ensure accuracy and coverage

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

### As a Git Submodule

```bash
git submodule add https://github.com/truefoundry/models.git
```

### Direct Clone

```bash
git clone https://github.com/truefoundry/models.git
```

### Via npm (coming soon)

```bash
npm install @truefoundry/models
```

## Usage

### Direct File Access

```python
import yaml

with open('providers/openai/gpt-4o.yaml', 'r') as f:
    model_config = yaml.safe_load(f)

print(f"Input cost: ${model_config['costs']['input_cost_per_token']} per token")
print(f"Max context: {model_config['limits']['max_input_tokens']} tokens")
print(f"Supports vision: {model_config['capabilities']['supports_vision']}")
```

### JavaScript/TypeScript

```typescript
import { readFileSync } from 'fs';
import { parse } from 'yaml';

const config = parse(readFileSync('providers/openai/gpt-4o.yaml', 'utf8'));
console.log(`Model: ${config.model}`);
console.log(`Supports tools: ${config.capabilities.supports_tools}`);
```

## Model Configuration Schema

Each model YAML file follows this schema:

```yaml
# Model identifier (required)
model: gpt-4o

# Pricing information
costs:
  input_cost_per_token: 0.0000025      # Cost per input token in USD
  output_cost_per_token: 0.00001       # Cost per output token in USD
  input_cost_per_token_batches: 0.00000125  # Batch API pricing
  output_cost_per_token_batches: 0.000005
  cache_read_input_token_cost: 0.00000125   # Prompt caching cost

# Token limits
limits:
  max_input_tokens: 128000             # Maximum context window
  max_output_tokens: 16384             # Maximum generation length

# Feature capabilities
capabilities:
  supports_chat: true                  # Chat completions API
  supports_vision: true                # Image input support
  supports_tools: true                 # Tool/function calling
  supports_function_calling: true      # Function calling (legacy)
  supports_parallel_function_calling: true
  supports_system_messages: true       # System prompt support
  supports_response_schema: true       # Structured output/JSON mode
  supports_prompt_caching: true        # Prompt caching support
  supports_pdf_input: true             # PDF document input

# Model mode
mode: chat                             # chat, completion, embedding, image, audio

# Provider information
original_provider: openai              # Original model provider

# Deprecation info
is_deprecated: false
deprecation_date: ''
```

## Directory Structure

```
providers/
├── ai21/
├── anthropic/
├── aws-bedrock/
├── azure-ai-foundry/
├── azure-openai/
├── cerebras/
├── cohere/
├── databricks/
├── deepinfra/
├── google-gemini/
├── google-vertex/
├── groq/
├── mistral-ai/
├── openai/
├── perplexity-ai/
├── sambanova/
└── together-ai/
```

> **Note**: File names are for organizational purposes and do not necessarily match the `model` field in the YAML. The `model` field contains the actual identifier used by the provider's API (e.g., a file `claude-sonnet-4.yaml` might contain `model: claude-sonnet-4-20250514`).

## Contributing

We welcome contributions! Please see our [Contributing Guide](CONTRIBUTING.md) for details.

### Quick Start

1. Fork the repository
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

## Related Projects

- [Portkey Models](https://github.com/Portkey-AI/models) - Similar model registry
- [LiteLLM](https://github.com/BerriAI/litellm) - Unified LLM API

## Community

- [GitHub Issues](https://github.com/truefoundry/models/issues) - Bug reports and feature requests
- [GitHub Discussions](https://github.com/truefoundry/models/discussions) - Questions and ideas

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Acknowledgments

- Thanks to all [contributors](https://github.com/truefoundry/models/graphs/contributors)
- Inspired by the open source AI community
