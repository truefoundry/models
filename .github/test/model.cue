package model

// ============================================================
// Section 1: Shared param definitions
// ============================================================

#ModelParam: {
	defaultValue?: string | number | bool | null
	key:           #ModelParamKey
	maxValue?:     number
	minValue?:     number
	supportedValues?: [...string]
	type?: #ModelParamType
}

#ModelParamKey:
	"json_schema" |
	"max_completion_tokens" |
	"max_tokens" |
	"min_tokens" |
	"n" |
	"parallel_tool_calls" |
	"reasoning" |
	"reasoning_effort" |
	"response_format" |
	"seed" |
	"stop" |
	"stream" |
	"temperature" |
	"thinking" |
	"tool_choice" |
	"top_k" |
	"top_p" |
	"verbosity"

#ModelParamType:
	"array-of-strings" |
	"boolean" |
	"json" |
	"number" |
	"string"

// ============================================================
// Section 2: Default provider config
// ============================================================

// Pricing per billing unit; value is the cost
#ToolCost: {
	// pricing in USD
	per_request?:           number & >= 0
	per_thousand_requests?: number & >= 0
}

// Pricing for built-in tools that can incur usage-based pricing beyond token costs
#ToolPricing: {
	web_search?: #ToolCost
}

// Schema for default.yaml files (provider-level defaults)
#DefaultConfig: {
	// Official documentation links for models, pricing, and deprecations
	documentation?: [...string]
	// Message types supported
	messages?: #MessageConfig
	// Configurable parameters with defaults
	params?: [...#ModelParam]
	// Pricing for built-in tools
	tool_pricing?: #ToolPricing
}

// One anthropic-beta column: clientToken -> providerToken, or null to drop
#BetaColumn: {[string]: string | null}

// Schema for provider-config.yaml files (provider-scoped, not per-model).
// Every field is optional so future provider-scoped settings can slot in.
#ProviderConfig: {
	// anthropic-beta translation keyed by provider flavor (e.g. invoke/converse, or default)
	anthropic_betas?: {[string]: #BetaColumn}
}

// ============================================================
// Section 3: Model config definitions
// ============================================================

// AWS region identifiers
#AWSRegion:
	"af-south-1" |
	"ap-east-1" |
	"ap-east-2" |
	"ap-northeast-1" |
	"ap-northeast-2" |
	"ap-northeast-3" |
	"ap-south-1" |
	"ap-south-2" |
	"ap-southeast-1" |
	"ap-southeast-2" |
	"ap-southeast-3" |
	"ap-southeast-4" |
	"ap-southeast-5" |
	"ap-southeast-6" |
	"ap-southeast-7" |
	"ca-central-1" |
	"ca-west-1" |
	"cn-north-1" |
	"cn-northwest-1" |
	"eu-central-1" |
	"eu-central-2" |
	"eu-north-1" |
	"eu-south-1" |
	"eu-south-2" |
	"eu-west-1" |
	"eu-west-2" |
	"eu-west-3" |
	"il-central-1" |
	"me-central-1" |
	"me-south-1" |
	"mx-central-1" |
	"sa-east-1" |
	"us-east-1" |
	"us-east-2" |
	"us-gov-east-1" |
	"us-gov-west-1" |
	"us-west-1" |
	"us-west-2"

#AzureRegion:
	"datazone_eu" |
	"datazone_us" |
	"global"

#Cost: {
	cache_creation_input_audio_token_cost?:    number & >= 0
	cache_creation_input_token_cost?:          number & >= 0
	cache_creation_input_token_cost_per_hour?: number & >= 0
	cache_read_input_audio_token_cost?:        number & >= 0
	cache_read_input_token_cost?:              number & >= 0
	input_cost_per_annotated_page?:         number & >= 0
	input_cost_per_audio_token?:            number & >= 0
	input_cost_per_character?:              number & >= 0
	input_cost_per_image?:                 	number & >= 0
	input_cost_per_image_token?:           	number & >= 0
	input_cost_per_page?:                  	number & >= 0
	input_cost_per_query?:                 	number & >= 0
	input_cost_per_request?:               	number & >= 0
	input_cost_per_second?:                	number & >= 0
	input_cost_per_token?:                 	number & >= 0
	input_cost_per_token_batches?:         	number & >= 0
	input_cost_per_video_token?:           	number & >= 0
	output_cost_per_audio_token?:          	number & >= 0
	output_cost_per_image?:               	number & >= 0
	output_cost_per_image_token?:          	number & >= 0
	output_cost_per_second?:               	number & >= 0
	output_cost_per_token?:                	number & >= 0
	output_cost_per_token_batches?:      	number & >= 0
	output_cost_per_video_token?:          	number & >= 0
	tiered_pricing?:                       	#TieredPricing

	// Resolution-based image pricing: matches fields like output_cost_per_image_1k, output_cost_per_image_4k, etc.
	[=~"^output_cost_per_image_\\d+[pk]$"]: number & >= 0
	// Resolution-based video pricing: matches fields like output_cost_per_second_480p, output_cost_per_second_4k, etc.
	[=~"^output_cost_per_second_\\d+[pk]$"]: number & >= 0
}

// Pricing entry; "*" applies to all regions
#CostWithRegion: {
	region: "*" | #AWSRegion | #GCPRegion | #AzureRegion | #VertexRegion
	#Cost
	priority_pricing?: #Cost
}

// Provider-specific configuration that cannot be expressed through the generic
// fields above. Each key is owned by exactly one provider.
#ExtraConfiguration: {
	// Path segment AWS serves this model under on the bedrock-mantle endpoint,
	// injected before `/v1/...`. Taken from the bedrock-mantle row of the model
	// card's Programmatic Access table, and includes the leading slash.
	// Prefer omitting this field for models on the plain `/v1/...` path; "/" says
	// the same thing explicitly and the gateway treats the two identically.
	bedrock_mantle_adhoc_prefix?: "/" | "/anthropic" | "/openai"
}

// Supported feature flags a model can declare
#Feature:
	"assistant_prefill" |          // Caller can seed the assistant turn to guide the response
	"cache_control" |              // Caller can apply fine-grained cache breakpoints on content blocks
	"code_execution" |             // Model can execute code natively as part of its response
	"function_calling" |           // Model supports tool/function calling
	"json_output" |				   // Model can return output in JSON format
	"parallel_function_calling" |  // Model can invoke multiple tools in a single turn
	"prompt_caching" |			   // Provider caches repeated prompt prefixes to reduce cost and latency
	"structured_output" |          // Model can return output conforming to a JSON schema
	"system_messages" |            // Model accepts a system prompt
	"tool_choice"                  // Caller can force or restrict which tool the model uses

// GCP region identifiers
#GCPRegion:
	"asia-east1" |
	"asia-east2" |
	"asia-northeast1" |
	"asia-northeast2" |
	"asia-northeast3" |
	"asia-south1" |
	"asia-south2" |
	"asia-southeast1" |
	"asia-southeast2" |
	"australia-southeast1" |
	"australia-southeast2" |
	"europe-central2" |
	"europe-north1" |
	"europe-southwest1" |
	"europe-west1" |
	"europe-west2" |
	"europe-west3" |
	"europe-west4" |
	"europe-west6" |
	"europe-west8" |
	"europe-west9" |
	"global" |
	"me-central1" |
	"me-central2" |
	"me-west1" |
	"northamerica-northeast1" |
	"northamerica-northeast2" |
	"southamerica-east1" |
	"us-central1" |
	"us-east1" |
	"us-east4" |
	"us-east5" |
	"us-south1" |
	"us-west1" |
	"us-west2" |
	"us-west3" |
	"us-west4"

// Vertex region identifiers
#VertexRegion: 
	"us" |
	"eu"

#Limits: {
	context_window?:                int & >= 0   // Maximum number of tokens the model can hold in its context at once
	max_input_tokens?:              int & >= 0   // Maximum tokens allowed in the input/prompt
	max_output_tokens?:             int & >= 0   // Maximum tokens the model can produce in the output
	max_query_tokens?:              int & >= 0   // Maximum tokens for the query in embedding/rerank requests
	max_tokens?:                    int & >= 0   // Maximum tokens the model can generate in a response
	output_vector_size?:            int & >= 0   // Dimensionality of the embedding vector produced
	tool_use_system_prompt_tokens?: int & >= 0   // Tokens consumed by the built-in system prompt when tools are enabled
}

// Message role values supported by a model or provider
#MessageOption: "assistant" | "developer" | "system" | "user"

#MessageConfig: {
	options?: [...#MessageOption]
}

// Input/output modality types
#Modality:
	"audio" |      // Audio streams or files
	"code" |       // Source code files or snippets
	"doc" |        // Office/word-processor documents
	"embedding" |  // Dense vector embeddings
	"image" |      // Raster or vector images
	"pdf" |        // PDF documents
	"text" |       // Plain or structured text
	"video"        // Video streams or files

#Modalities: {
	input?:  [...#Modality]
	output?: [...#Modality]
}

// Canonical mode values for a model
#Mode:
	"audio_transcription" |
	"audio_translation" |
	"chat" |
	"completion" |
	"embedding" |
	"image" |
	"moderation" |
	"ocr" |
	"realtime" |
	"rerank" |
	"responses" |
	"text_to_speech" |
	"unknown" |
	"unsupported" | // Model is not supported by the gateway
	"video"

#ModelConfig: {
	// Pricing entries per region; use "*" for global/uniform pricing
	costs?: [...#CostWithRegion]
	// Date after which the model is considered deprecated (YYYY-MM-DD)
	deprecationDate?: string & =~"^\\d{4}-\\d{2}-\\d{2}$"
	// Provider-specific escape-hatch configuration
	extra_configuration?: #ExtraConfiguration
	// Feature flags for capabilities like function calling, prompt caching, etc.
	features?: [...#Feature]
	// Whether the model is deprecated
	isDeprecated?: bool
	// Token and context window limits
	limits?: #Limits
	// Message roles accepted by this model
	messages?: #MessageConfig
	// Input/output modality support (e.g. text, image, audio)
	modalities?: #Modalities
	// Required: Canonical mode describing the model's primary capability
	mode: #Mode
	// Required: Model identifier used by the provider's API
	model: string
	// Param overrides or additions relative to the provider default
	params?: [...#ModelParam]
	// How the model is made available: serverless API or dedicated/deployed capacity
	provisioning?: #Provisioning
	// Param keys to remove from the provider default
	removeParams?: [...#ModelParamKey]
	// Param keys that must always be provided by callers
	requiredParams?: [...#ModelParamKey]
	// Retirement date of the model (YYYY-MM-DD)
	retirementDate?: string & =~"^\\d{4}-\\d{2}-\\d{2}$"
	// Documentation or pricing source URLs
	sources?: [...string]
	// Lifecycle status of the model
	status?: #Status
	// Additional modes this model can be accessed through beyond its primary mode
	supportedModes?: [...#Mode]
	// Whether the model supports extended thinking / reasoning
	thinking?: bool
}

#PricingTier: {
	cost_per_token: number & >= 0
	from:           int & >= 0
}

// How the model prices long context tokens
// marginal: remaining tokens after long context are priced under long context pricing
// cumulative: all input tokens are priced under long context pricing
#PricingMode:
	*"marginal" | "cumulative"
	// defaults to "marginal"

// How the model is made available to callers
#Provisioning:
	"serverless" |   // Managed API, pay-per-token/request
	"provisioned"    // Dedicated capacity or user-deployed instance

// Lifecycle status of a model
#Status:
	"active" |      // Model is fully supported and recommended for use (aka stable, ga)
	"deprecated" |  // Model is deprecated and may be removed in the future (aka legacy)
	"preview" |     // Model is in early access and may change or have limited support (aka beta, experimental)
	"retired"       // Model has been fully removed and is no longer accessible (aka removed, deleted, end-of-life)

#TieredPricing: {
	cache_read?:  [...#PricingTier]
	cache_write?: [...#PricingTier]
	input?:       [...#PricingTier]
	output?:      [...#PricingTier]
	pricing_mode?: #PricingMode
}
