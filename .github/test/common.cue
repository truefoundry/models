package model

// Shared definitions for model and default schemas

#ParamKey:
	"max_tokens" |
	"max_completion_tokens" |
	"max_tokens_per_doc" |
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
	"frequency_penalty" |
	"presence_penalty" |
	"seed" |
	"min_tokens" |
	"creativity" |
	"grow_mask" |
	"output_format" |
	"safe_prompt" |
	"parallel_tool_calls" |
	"logit_bias" |
	"disable_reasoning" |
	"clear_thinking"

#ParamType:
	"string" |
	"boolean" |
	"array-of-strings" |
	"json" |
	"number" |
	"object" |
	"non-view-manage-data"

#ParamOption: {
	value:   string | null
	name:    string
	schema?: null | {
		type:        string
		properties?: {[string]: {type: string, value?: string}}
	}
	params?: #Param
	type?:   string
}

#Param: {
	key:             #ParamKey
	defaultValue?:   string | number | bool | null
	minValue?:       number
	maxValue?:       number
	type?:           #ParamType
	options?:        [...#ParamOption]
	skipValues?:     [...(string | bool | null | [...string])]
	withdrawParams?: [...string]
	properties?: {[string]: {
		type?:     string
		minValue?: number
		maxValue?: number
		enum?:     [...string]
	}}
	enum?:          [...(string | null)]
	nestedOptions?: [...{value: {[string]: string}, view: string}]
	rule?:          null | {default: {
		condition: string
		else:      string | bool | null
		then:      string | bool | null
	}}
}
