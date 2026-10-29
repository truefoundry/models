---
title: Pricing
url: https://platform.claude.com/docs/en/about-claude/pricing
description: Learn about Anthropic's pricing structure for models and features
---

This page provides detailed pricing information for Anthropic’s models and features. All prices are in USD.

For the most current pricing information, visit [claude.com/pricing](https://claude.com/pricing).

## Model pricing

The following table shows pricing for all Claude models:

| Model                                                                                                                                                                  | Base input tokens     | 5m cache writes | 1h cache writes | Cache hits and refreshes | Output tokens          |
| :--------------------------------------------------------------------------------------------------------------------------------------------------------------------- | :-------------------- | :-------------- | :-------------- | :----------------------- | :--------------------- |
| Claude Fable 5.1                                                                                                                                                       | $10 / MTok            | $12.50 / MTok   | $20 / MTok      | $0.25 / MTok<sup>1</sup> | $50 / MTok             |
| Claude Mythos 5.1 ([limited availability](https://support.claude.com/en/articles/14604842))                                                                            | $10 / MTok            | $12.50 / MTok   | $20 / MTok      | $0.25 / MTok<sup>1</sup> | $50 / MTok             |
| Claude Fable 5                                                                                                                                                         | $10 / MTok            | $12.50 / MTok   | $20 / MTok      | $1 / MTok                | $50 / MTok             |
| Claude Mythos 5 ([limited availability](https://support.claude.com/en/articles/14604842))                                                                              | $10 / MTok            | $12.50 / MTok   | $20 / MTok      | $1 / MTok                | $50 / MTok             |
| Claude Opus 5.5                                                                                                                                                        | $4 / MTok             | $5 / MTok       | $8 / MTok       | $0.20 / MTok<sup>2</sup> | $20 / MTok             |
| Claude Opus 5                                                                                                                                                          | $5 / MTok             | $6.25 / MTok    | $10 / MTok      | $0.50 / MTok             | $25 / MTok             |
| Claude Opus 4.8                                                                                                                                                        | $5 / MTok             | $6.25 / MTok    | $10 / MTok      | $0.50 / MTok             | $25 / MTok             |
| Claude Opus 4.7                                                                                                                                                        | $5 / MTok             | $6.25 / MTok    | $10 / MTok      | $0.50 / MTok             | $25 / MTok             |
| Claude Opus 4.6                                                                                                                                                        | $5 / MTok             | $6.25 / MTok    | $10 / MTok      | $0.50 / MTok             | $25 / MTok             |
| Claude Opus 4.5                                                                                                                                                        | $5 / MTok             | $6.25 / MTok    | $10 / MTok      | $0.50 / MTok             | $25 / MTok             |
| Claude Opus 4.1 ([retired, except on Bedrock and Claude Models on Google Cloud (Google managed)](https://platform.claude.com/docs/en/about-claude/model-deprecations)) | $15 / MTok            | $18.75 / MTok   | $30 / MTok      | $1.50 / MTok             | $75 / MTok             |
| Claude Opus 4 ([retired, except on Claude Models on Google Cloud (Google managed)](https://platform.claude.com/docs/en/about-claude/model-deprecations))               | $15 / MTok            | $18.75 / MTok   | $30 / MTok      | $1.50 / MTok             | $75 / MTok             |
| Claude Sonnet 5.5                                                                                                                                                      | $2 / MTok             | $2.50 / MTok    | $4 / MTok       | $0.10 / MTok<sup>2</sup> | $10 / MTok             |
| Claude Sonnet 5                                                                                                                                                        | $2 / MTok<sup>3</sup> | $2.50 / MTok    | $4 / MTok       | $0.20 / MTok             | $10 / MTok<sup>3</sup> |
| Claude Sonnet 4.6                                                                                                                                                      | $3 / MTok             | $3.75 / MTok    | $6 / MTok       | $0.30 / MTok             | $15 / MTok             |
| Claude Sonnet 4.5                                                                                                                                                      | $3 / MTok             | $3.75 / MTok    | $6 / MTok       | $0.30 / MTok             | $15 / MTok             |
| Claude Sonnet 4 ([retired, except on Bedrock and Claude Models on Google Cloud (Google managed)](https://platform.claude.com/docs/en/about-claude/model-deprecations)) | $3 / MTok             | $3.75 / MTok    | $6 / MTok       | $0.30 / MTok             | $15 / MTok             |
| Claude Haiku 5.5 (for prompts up to 100,000 tokens)                                                                                                                    | $0.10 / MTok          | $0.125 / MTok   | $0.20 / MTok    | $0.01 / MTok             | $0.50 / MTok           |
| Claude Haiku 5.5 (for prompts over 100,000 tokens)                                                                                                                     | $0.50 / MTok          | $0.625 / MTok   | $1 / MTok       | $0.05 / MTok             | $2.50 / MTok           |
| Claude Haiku 4.5                                                                                                                                                       | $1 / MTok             | $1.25 / MTok    | $2 / MTok       | $0.10 / MTok             | $5 / MTok              |
| Claude Haiku 3.5 ([retired, except on Claude Models on Google Cloud (Google managed)](https://platform.claude.com/docs/en/about-claude/model-deprecations))            | $0.80 / MTok          | $1 / MTok       | $1.60 / MTok    | $0.08 / MTok             | $4 / MTok              |

*<sup>1 Cache hits and refreshes on Claude Fable 5.1 and Claude Mythos 5.1 are priced at 0.025x the base input price.</sup>*

*<sup>2 Cache hits and refreshes on Claude Opus 5.5 and Claude Sonnet 5.5 are priced at 0.05x the base input price.</sup>*

*<sup>All other models use the standard 0.1x multiplier.</sup>*

*<sup>3 The $2/$10 per million input/output token pricing for Claude Sonnet 5, announced at launch as introductory pricing through August 31, 2026, is now the standard price. The previously scheduled increase to $3/$15 per million input/output tokens on September 1, 2026 will not occur.</sup>*

* **MTok:** Million tokens. $5 / MTok is $5 for every million tokens.
* **5m cache writes:** Writing a prompt prefix to the 5-minute prompt cache.
* **1h cache writes:** Writing a prompt prefix to the 1-hour prompt cache.
* **Cache hits and refreshes:** Reading a prompt prefix from the prompt cache, which also refreshes it.
* **Limited access:** Available only to organizations verified through Anthropic’s verification programs, such as the [Cyber Verification Program](https://support.claude.com/en/articles/14604842). To request access, apply to the program that covers your use case.
* **Retired:** May still be available on other cloud platforms. See [Model deprecations](https://platform.claude.com/docs/en/about-claude/model-deprecations) for more.

Claude 4.7 and later models and Claude Mythos Preview use a newer tokenizer that contributes to their improved performance on a wide range of tasks. This tokenizer produces approximately 30% more tokens for the same text. The exact increase depends on the content and workload shape. Claude Sonnet 4.6 and earlier models use the previous tokenizer.

## Feature-specific pricing

### Prompt caching

Prompt caching reduces costs and latency by reusing previously processed portions of your prompt across API calls. Instead of reprocessing the same large system prompt, document, or conversation history on every request, the API reads from cache at a fraction of the standard input price.

There are two ways to enable prompt caching:

* **Automatic caching:** Add a single `cache_control` field at the top level of your request. The system automatically manages cache breakpoints as conversations grow. This is the recommended starting point for most use cases.
* **Explicit cache breakpoints:** Place `cache_control` directly on individual content blocks for fine-grained control over exactly what gets cached.

Prompt caching uses the following pricing multipliers relative to base input token rates:

| Cache operation      | Multiplier                                                                                                               | Duration                             |
| -------------------- | ------------------------------------------------------------------------------------------------------------------------ | ------------------------------------ |
| 5-minute cache write | 1.25x base input price                                                                                                   | Cache valid for 5 minutes            |
| 1-hour cache write   | 2x base input price                                                                                                      | Cache valid for 1 hour               |
| Cache read (hit)     | 0.1x base input price (0.025x on Claude Fable 5.1 and Claude Mythos 5.1; 0.05x on Claude Opus 5.5 and Claude Sonnet 5.5) | Same duration as the preceding write |

Cache write tokens are charged when content is first stored. Cache read tokens are charged when a subsequent request retrieves the cached content. A cache hit costs 10% of the standard input price, which means caching pays off after one cache read for the 5-minute duration (1.25x write), or after two cache reads for the 1-hour duration (2x write). On Claude Fable 5.1 and Claude Mythos 5.1, a cache hit costs 2.5% of the standard input price ($0.25 USD per million tokens). On Claude Opus 5.5 and Claude Sonnet 5.5, a cache hit costs 5% of the standard input price ($0.20 USD per million tokens on Claude Opus 5.5, $0.10 USD on Claude Sonnet 5.5).

These multipliers stack with other pricing modifiers, including the Batch API discount and data residency.

For implementation details, supported models, and code examples, see [Prompt caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching).

### Data residency pricing

For Claude 4.6 and later models, specifying US-only inference through the `inference_geo` parameter incurs a 1.1x multiplier on all token pricing categories, including input tokens, output tokens, cache writes, and cache reads. On Claude Haiku 5.5, the multiplier also applies to the higher prices for prompts over 100,000 tokens (see [Long context pricing](https://platform.claude.com/docs/en/about-claude/pricing#long-context-pricing)). Global routing (the default) uses standard pricing.

This applies to the Claude API (first-party), Claude Platform on AWS, and Claude Models on Google Cloud (Anthropic managed). On Claude in Microsoft Foundry, the same 1.1x multiplier applies to deployments that use the US Data Zone Standard deployment type (see [Inference geography](https://platform.claude.com/docs/en/about-claude/pricing#foundry-inference-geography)). Partner-operated platforms, Bedrock and Claude Models on Google Cloud (Google managed), have independent regional pricing. See [Bedrock pricing](https://aws.amazon.com/bedrock/pricing/) and [Google Cloud pricing](https://cloud.google.com/vertex-ai/generative-ai/pricing#claude-models) for details. Earlier models do not support the `inference_geo` parameter and always use standard pricing; requests that include the parameter on these models return a 400 error.

For more information, see [Data residency](https://platform.claude.com/docs/en/manage-claude/data-residency).

### Fast mode pricing

[Fast mode](https://platform.claude.com/docs/en/build-with-claude/fast-mode) provides significantly faster output for Claude Opus 5.5, Claude Opus 5, and Claude Opus 4.8 at premium pricing. Fast mode for Claude Opus 5 and Claude Opus 4.8 is in research preview. Fast mode pricing applies across the full context window, including requests over 200k input tokens. Fast mode is available on the Claude API (first-party) and, for Claude Opus 5.5, on [Claude Models on Google Cloud (Anthropic managed)](https://platform.claude.com/docs/en/build-with-claude/claude-models-on-google-cloud/anthropic-managed#billing) and on [Claude in Microsoft Foundry](https://platform.claude.com/docs/en/build-with-claude/claude-in-microsoft-foundry) for deployments hosted on Azure.

| Model                           | Input          | Output         |
| ------------------------------- | -------------- | -------------- |
| Claude Opus 5.5                 | $8 USD / MTok  | $40 USD / MTok |
| Claude Opus 5 / Claude Opus 4.8 | $10 USD / MTok | $50 USD / MTok |

Fast mode pricing stacks with other pricing modifiers:

* [Prompt caching multipliers](https://platform.claude.com/docs/en/about-claude/pricing#prompt-caching) apply on top of fast mode pricing.
* [Data residency](https://platform.claude.com/docs/en/manage-claude/data-residency) multipliers apply on top of fast mode pricing.

Fast mode is not available with the [Batch API](https://platform.claude.com/docs/en/about-claude/pricing#batch-processing).

For more information, see [Fast mode](https://platform.claude.com/docs/en/build-with-claude/fast-mode).

### Batch processing

The Batch API allows asynchronous processing of large volumes of requests with a 50 percent discount on both input and output tokens.

| Model                                                                                                                                                                  | Batch input  | Batch output  |
| :--------------------------------------------------------------------------------------------------------------------------------------------------------------------- | :----------- | :------------ |
| Claude Fable 5.1                                                                                                                                                       | $5 / MTok    | $25 / MTok    |
| Claude Mythos 5.1 ([limited availability](https://support.claude.com/en/articles/14604842))                                                                            | $5 / MTok    | $25 / MTok    |
| Claude Fable 5                                                                                                                                                         | $5 / MTok    | $25 / MTok    |
| Claude Mythos 5 ([limited availability](https://support.claude.com/en/articles/14604842))                                                                              | $5 / MTok    | $25 / MTok    |
| Claude Opus 5.5                                                                                                                                                        | $2 / MTok    | $10 / MTok    |
| Claude Opus 5                                                                                                                                                          | $2.50 / MTok | $12.50 / MTok |
| Claude Opus 4.8                                                                                                                                                        | $2.50 / MTok | $12.50 / MTok |
| Claude Opus 4.7                                                                                                                                                        | $2.50 / MTok | $12.50 / MTok |
| Claude Opus 4.6                                                                                                                                                        | $2.50 / MTok | $12.50 / MTok |
| Claude Opus 4.5                                                                                                                                                        | $2.50 / MTok | $12.50 / MTok |
| Claude Opus 4.1 ([retired, except on Bedrock and Claude Models on Google Cloud (Google managed)](https://platform.claude.com/docs/en/about-claude/model-deprecations)) | $7.50 / MTok | $37.50 / MTok |
| Claude Opus 4 ([retired, except on Claude Models on Google Cloud (Google managed)](https://platform.claude.com/docs/en/about-claude/model-deprecations))               | $7.50 / MTok | $37.50 / MTok |
| Claude Sonnet 5.5                                                                                                                                                      | $1 / MTok    | $5 / MTok     |
| Claude Sonnet 5                                                                                                                                                        | $1 / MTok    | $5 / MTok     |
| Claude Sonnet 4.6                                                                                                                                                      | $1.50 / MTok | $7.50 / MTok  |
| Claude Sonnet 4.5                                                                                                                                                      | $1.50 / MTok | $7.50 / MTok  |
| Claude Sonnet 4 ([retired, except on Bedrock and Claude Models on Google Cloud (Google managed)](https://platform.claude.com/docs/en/about-claude/model-deprecations)) | $1.50 / MTok | $7.50 / MTok  |
| Claude Haiku 5.5 (for prompts up to 100,000 tokens)                                                                                                                    | $0.05 / MTok | $0.25 / MTok  |
| Claude Haiku 5.5 (for prompts over 100,000 tokens)                                                                                                                     | $0.25 / MTok | $1.25 / MTok  |
| Claude Haiku 4.5                                                                                                                                                       | $0.50 / MTok | $2.50 / MTok  |
| Claude Haiku 3.5 ([retired, except on Claude Models on Google Cloud (Google managed)](https://platform.claude.com/docs/en/about-claude/model-deprecations))            | $0.40 / MTok | $2 / MTok     |

* **MTok:** Million tokens. $5 / MTok is $5 for every million tokens.
* **Limited access:** Available only to organizations verified through Anthropic’s verification programs, such as the [Cyber Verification Program](https://support.claude.com/en/articles/14604842). To request access, apply to the program that covers your use case.
* **Retired:** May still be available on other cloud platforms. See [Model deprecations](https://platform.claude.com/docs/en/about-claude/model-deprecations) for more.

For more information about batch processing, see [Batch processing](https://platform.claude.com/docs/en/build-with-claude/batch-processing).

### Long context pricing

Claude 4.6 and later models (except Claude Haiku 5.5) and [Claude Mythos Preview](https://anthropic.com/glasswing) include the full [1M token context window](https://platform.claude.com/docs/en/build-with-claude/context-windows) at standard pricing. (A 900k-token request is billed at the same per-token rate as a 9k-token request.) Prompt caching and batch processing discounts apply at standard rates across the full context window.

Claude Haiku 5.5 is priced by prompt length: a request whose prompt is over 100,000 tokens pays higher prices. A request’s prompt length counts all of its input tokens, including cache reads and cache writes. Each request is priced on its own: a request over the threshold pays the higher prices even when part of its prompt is a cache hit, and earlier requests keep the prices they were billed at. The [model pricing](https://platform.claude.com/docs/en/about-claude/pricing#model-pricing) and [batch processing pricing](https://platform.claude.com/docs/en/about-claude/pricing#batch-processing) sections list both sets of prices.
