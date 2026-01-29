package model

// Schema for default.yaml files (provider-level defaults)

#ParamOption: {
	value:   _
	name:    string
	schema?: _
}

#ParamRule: {
	default?: {
		condition?: string
		then?:      _
		else?:      _
	}
}

#Param: {
	key:           string
	defaultValue?: _
	minValue?:     number
	maxValue?:     number
	type?:         string
	options?:      [...#ParamOption]
	skipValues?:   [...]
	rule?:         #ParamRule
}

#DefaultConfig: {
	// Configurable parameters with defaults
	params?: [...#Param]

	// Message types supported
	messages?: {
		options?: [...string]
	}

	// Model type configuration
	type?: {
		primary?:   string
		supported?: [...string]
	}
}
