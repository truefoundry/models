package model

// Supported feature flags a model can declare
#Feature:
	"function_calling" |           // Model supports tool/function calling
	"parallel_function_calling" |  // Model can invoke multiple tools in a single turn
	"chat" |                       // Model supports multi-turn conversational context
	"cache_control" |              // Caller can apply fine-grained cache breakpoints on content blocks
	"system_messages" |            // Model accepts a system prompt
	"tool_choice" |                // Caller can force or restrict which tool the model uses
	"prompt_caching" |             // Provider caches repeated prompt prefixes to reduce cost and latency
	"structured_output" |          // Model can return output conforming to a JSON schema
	"assistant_prefill" |          // Caller can seed the assistant turn to guide the response
	"tools" |                      // Model supports tool definitions in the request
	"code_execution"               // Model can execute code natively as part of its response

// Canonical mode values for a model
#Mode:
	"completion" |
	"embedding" |
	"rerank" |
	"realtime" |
	"audio_transcription" |
	"audio_translation" |
	"text_to_speech" |
	"moderation" |
	"image" |
	"video" |
	"unknown"

// Input/output modality types
#Modality:
	"text" |   // Plain or structured text
	"image" |  // Raster or vector images
	"audio" |  // Audio streams or files
	"pdf" |    // PDF documents
	"doc" |    // Office/word-processor documents
	"code" |   // Source code files or snippets
	"video"    // Video streams or files

#Modalities: {
	input?:  [...#Modality]
	output?: [...#Modality]
}

#PricingTier: {
	from:           number
	cost_per_token: number
}

#TieredPricing: {
	input?:       [...#PricingTier]
	output?:      [...#PricingTier]
	cache_read?:  [...#PricingTier]
	cache_write?: [...#PricingTier]
}

#Cost: {
	input_cost_per_token?:                  number
	output_cost_per_token?:                 number
	cache_read_input_token_cost?:           number
	cache_creation_input_token_cost?:       number
	input_cost_per_token_batches?:          number
	output_cost_per_token_batches?:         number
	input_cost_per_audio_token?:            number
	output_cost_per_audio_token?:           number
	cache_read_input_audio_token_cost?:     number
	cache_creation_input_audio_token_cost?: number
	cache_storage_cost_per_token_per_hour?: number
	input_cost_per_request?:               number
	input_cost_per_character?:             number
	input_cost_per_second?:                number
	output_cost_per_second?:               number
	input_cost_per_query?:                 number
	input_cost_per_image?:                 number
	output_cost_per_image?:                number
	input_cost_per_image_token?:           number
	output_cost_per_image_token?:          number
	input_cost_per_video_token?:           number
	output_cost_per_video_token?:          number
	input_cost_per_page?:                  number
	input_cost_per_annotated_page?:        number
	tiered_pricing?:                       #TieredPricing

	// Resolution-based video pricing: matches fields like output_cost_per_second_480p, output_cost_per_second_4k, etc.
	[=~"^output_cost_per_second_\\d+[pk]$"]: number
	// Resolution-based image pricing: matches fields like output_cost_per_image_1k, output_cost_per_image_4k, etc.
	[=~"^output_cost_per_image_\\d+[pk]$"]: number
}

// AWS region identifiers
#AWSRegion:
	"af-south-1" | "ap-east-1" | "ap-northeast-1" | "ap-northeast-2" | "ap-northeast-3" | "ap-south-1" |
	"ap-south-2" | "ap-southeast-1" | "ap-southeast-2" | "ap-southeast-3" | "ap-southeast-4" | "ap-southeast-5" |
	"ap-southeast-7" | "ca-central-1" | "ca-west-1" | "cn-north-1" | "cn-northwest-1" | "eu-central-1" | "eu-central-2" |
	"eu-north-1" | "eu-south-1" | "eu-south-2" | "eu-west-1" | "eu-west-2" | "eu-west-3" | "il-central-1" |
	"me-central-1" | "me-south-1" | "mx-central-1" | "sa-east-1" | "us-east-1" | "us-east-2" | "us-gov-east-1" |
	"us-gov-west-1" | "us-west-1" | "us-west-2" | "ap-southeast-6" | "ap-east-2"

// GCP region identifiers
#GCPRegion:
	"global" |
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
	"us-west4" |
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
	"me-central1" |
	"me-central2" |
	"me-west1"

// Pricing entry; "*" applies to all regions
#CostWithRegion: {
	region: "*" | #AWSRegion | #GCPRegion
	#Cost
}

#Limits: {
	context_window?:                int  // Maximum number of tokens the model can hold in its context at once
	max_tokens?:                    int  // Maximum tokens the model can generate in a response
	max_input_tokens?:              int  // Maximum tokens allowed in the input/prompt
	max_output_tokens?:             int  // Maximum tokens the model can produce in the output
	max_query_tokens?:              int  // Maximum tokens for the query in embedding/rerank requests
	output_vector_size?:            int  // Dimensionality of the embedding vector produced
	tool_use_system_prompt_tokens?: int  // Tokens consumed by the built-in system prompt when tools are enabled
}

// Message role values supported by a model or provider
#MessageOption: "system" | "user" | "assistant" | "developer"

#ModelConfig: {
	// Required: Model identifier used by the provider's API
	model: string
	// Required: Canonical mode describing the model's primary capability
	mode: #Mode

	// Pricing entries per region; use "*" for global/uniform pricing
	costs?: [...#CostWithRegion]
	// Token and context window limits
	limits?: #Limits
	// Feature flags for capabilities like function calling, prompt caching, etc.
	features?: [...#Feature]
	// Input/output modality support (e.g. text, image, audio)
	modalities?: #Modalities
	// Param overrides or additions relative to the provider default
	params?: [...#Param]
	// Param keys to remove from the provider default
	removeParams?: [...#ParamKey]
	// Param keys that must always be provided by callers
	requiredParams?: [...#ParamKey]
	// Whether the model is deprecated
	isDeprecated?: bool
	// Date after which the model is considered deprecated (YYYY-MM-DD)
	deprecationDate?: string
	// Whether the model supports extended thinking / reasoning
	thinking?: bool
	// Documentation or pricing source URLs
	sources?: [...string]
	// Additional modes this model can be accessed through beyond its primary mode
	supportedModes?: [...#Mode]
	// Message roles accepted by this model
	messages?: {
		options?: [...#MessageOption]
	}
}
