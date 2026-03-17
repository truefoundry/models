package model

// Shared definitions for model and default schemas

#ParamKey:
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

#ParamType:
	"string" |
	"boolean" |
	"array-of-strings" |
	"json" |
	"number"

#Param: {
	key:             #ParamKey
	defaultValue?:   string | number | bool | null
	minValue?:       number
	maxValue?:       number
	type?:           #ParamType
}
