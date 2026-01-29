package model

// Schema for individual model YAML files (e.g., gpt-4o.yaml)

#TieredPricing: {
	...
}

#Costs: {
	input_cost_per_token?:                       number
	output_cost_per_token?:                      number
	input_cost_per_token_batches?:               number
	output_cost_per_token_batches?:              number
	cache_read_input_token_cost?:                number
	cache_creation_input_token_cost?:            number
	input_cost_per_audio_token?:                 number
	output_cost_per_audio_token?:                number
	cache_creation_input_audio_token_cost?:      number
	input_cost_per_request?:                     number
	input_cost_per_character?:                   number
	input_cost_per_second?:                      number
	output_cost_per_second?:                     number
	input_cost_per_query?:                       number
	input_cost_per_image?:                       number
	tiered_pricing?:                             #TieredPricing
}

#Limits: {
	max_tokens?:                    int
	max_input_tokens?:              int
	max_output_tokens?:             int
	max_query_tokens?:              int
	output_vector_size?:            int
	tool_use_system_prompt_tokens?: int
}

#ParamOption: {
	value:   _
	name:    string
	schema?: _
	params?: _
}

#Param: {
	key:             string
	defaultValue?:   _
	minValue?:       number
	maxValue?:       number
	type?:           string
	options?:        [...#ParamOption]
	skipValues?:     [...]
	rule?:           _
	enum?:           [...]
	nestedOptions?:  _
	withdrawParams?: _
	properties?:     _
}

#ModelConfig: {
	// Required: Model identifier used by the provider's API
	model: string

	// Pricing information
	costs?: #Costs

	// Token limits
	limits?: #Limits

	// Feature flags (list of supported features)
	features?: [...string]

	// Configurable parameters
	params?: [...#Param]

	// Parameters to remove from defaults
	removeParams?: [...string]

	// Required parameters
	requiredParams?: [...string]

	// Model mode
	mode?: string

	// Default region
	defaultRegion?: string

	// Deprecation date (YYYY-MM-DD format)
	deprecation_date?: string

	// Whether model is deprecated
	is_deprecated?: bool

	// Original provider name
	original_provider?: string

	// Source URL for pricing/documentation
	source?: string

	// Messages configuration (some models have this)
	messages?: {
		options?: [...string]
		...
	}
}
