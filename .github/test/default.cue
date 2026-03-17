package model

// Schema for default.yaml files (provider-level defaults)

#DefaultConfig: {
	// Configurable parameters with defaults
	params?: [...#Param]

	// Message types supported
	messages?: {
		options?: [...#MessageOption]
	}

	// Official documentation links for models, pricing, and deprecations
	documentation?: [...string]
}
