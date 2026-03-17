package model

// Shared definitions for model and default schemas

#ModelParamKey:
	"max_tokens" |
	"max_completion_tokens" |
	"temperature" |
	"top_p" |
	"top_k" |
	"response_format" |
	"json_schema" |
	"reasoning_effort" |
	"verbosity" |
	"reasoning" |
	"thinking" |
	"tool_choice" |
	"stream" |
	"stop" |
	"n" |
	"seed" |
	"min_tokens" |
	"parallel_tool_calls"

#ModelParamType:
	"string" |
	"boolean" |
	"array-of-strings" |
	"json" |
	"number"

#ModelParam: {
	key:             #ModelParamKey
	defaultValue?:   string | number | bool | null
	minValue?:       number
	maxValue?:       number
	type?:           #ModelParamType
}
