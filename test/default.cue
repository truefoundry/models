package model

// Schema for default.yaml files (provider-level defaults)

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
