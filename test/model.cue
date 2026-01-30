package model

// Schema for individual model YAML files (e.g., gpt-4o.yaml)
// Shared param definitions are in common.cue

#Feature: "function_calling" | "parallel_function_calling" | "vision" | "audio_input" | "audio_output" | "chat" | "image" | "pdf" | "doc" | "cache_control"

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

#Costs: {
	input_cost_per_token?:                  number
	output_cost_per_token?:                 number
	input_cost_per_token_batches?:          number
	output_cost_per_token_batches?:         number
	cache_read_input_token_cost?:           number
	cache_creation_input_token_cost?:       number
	input_cost_per_audio_token?:            number
	output_cost_per_audio_token?:           number
	cache_creation_input_audio_token_cost?: number
	input_cost_per_request?:                number
	input_cost_per_character?:              number
	input_cost_per_second?:                 number
	output_cost_per_second?:                number
	input_cost_per_query?:                  number
	input_cost_per_image?:                  number
	tiered_pricing?:                        #TieredPricing
}

#Limits: {
	max_tokens?:                    int
	max_input_tokens?:              int
	max_output_tokens?:             int
	max_query_tokens?:              int
	output_vector_size?:            int
	tool_use_system_prompt_tokens?: int
}

#ModelConfig: {
	// Required: Model identifier used by the provider's API
	model: string

	// Pricing information (required, can be empty {})
	costs: #Costs

	// Token limits (required, can be empty {})
	limits: #Limits

	// Feature flags (required, can be empty [])
	features: [...#Feature]

	// Configurable parameters (required, can be empty [])
	params: [...#Param]

	// Parameters to remove from defaults (required, can be empty [])
	removeParams: [...string]

	// Required parameters (required, can be empty [])
	requiredParams: [...string]

	// Model mode (required)
	mode: string

	// Default region (required, can be empty "")
	defaultRegion: string

	// Deprecation date (required, can be empty "")
	deprecation_date: string

	// Whether model is deprecated (required)
	is_deprecated: bool

	// Original provider name (required)
	original_provider: string

	// Messages configuration
	messages: {
		options: [...string]
		...
	}
}
