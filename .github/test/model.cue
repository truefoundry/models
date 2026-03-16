package model

#Feature:
	"function_calling" |
	"parallel_function_calling" |
	"chat" |
	"cache_control" |
	"system_messages" |
	"tool_choice" |
	"prompt_caching" |
	"response_schema" |
	"assistant_prefill" |
	"tools" |
	// Legacy modality values kept for backward compatibility during migration
	"vision" |
	"audio_input" |
	"audio_output" |
	"image" |
	"pdf" |
	"doc" |
	"pdf_input" |
	"image_input" |
	"embedding_image_input" |
	"text" |
	"code"

#Modality:
	"text" |
	"image" |
	"audio" |
	"pdf" |
	"doc" |
	"code" |
	"video"

#Modalities: {
	input:  [...#Modality]
	output: [...#Modality]
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
  input_cost_per_token?:                   number
	output_cost_per_token?:                  number
	cache_read_input_token_cost?:            number
	cache_creation_input_token_cost?:        number
	input_cost_per_token_batches?:           number
	output_cost_per_token_batches?:          number
	input_cost_per_audio_token?:             number
	output_cost_per_audio_token?:            number
	cache_read_input_audio_token_cost?:      number
	cache_creation_input_audio_token_cost?:  number
	cache_storage_cost_per_token_per_hour?:  number
	input_cost_per_request?:                 number
	input_cost_per_character?:               number
	input_cost_per_second?:                  number
	output_cost_per_second?:                 number
	input_cost_per_query?:                   number
	input_cost_per_image?:                   number
	output_cost_per_image?:                  number
	input_cost_per_image_token?:             number
	output_cost_per_image_token?:            number
	input_cost_per_video_token?:             number
	output_cost_per_video_token?:            number
	input_cost_per_page?:                    number
	input_cost_per_annotated_page?:           number
	tiered_pricing?:                         #TieredPricing

	// Resolution-based video pricing: matches fields like output_cost_per_second_480p, output_cost_per_second_4k, etc.
	[=~"^output_cost_per_second_\\d+[pk]$"]:  number
	// Resolution-based image pricing: matches fields like output_cost_per_image_1k, output_cost_per_image_4k, etc.
	[=~"^output_cost_per_image_\\d+[pk]$"]:   number
}


#CostWithRegion: {
  region:                                   string
  #Cost
}

#Limits: {
	context_window?:                int
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
	mode:           string

	// Optional fields
	costs?:            [...#CostWithRegion]
	limits?:           #Limits
	features?:         [...#Feature]
	modalities?:       #Modalities
	params?:           [...#Param]
	removeParams?:     [...string]
	requiredParams?:   [...string]
	isDeprecated?:     bool
	thinking?:         bool
	sources?:          [...string]
	supportedEndpoints?: [...string]
	messages?: {
		options?: [...string]
		...
	}
}
