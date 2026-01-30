package model

// Shared definitions for model and default schemas

#ParamOption: {
	value: _
	name:  string
	...
}

#Param: {
	key:             string
	defaultValue?:   _
	minValue?:       number
	maxValue?:       number
	type?:           string
	options?:        [...#ParamOption]
	skipValues?:     [...]
	withdrawParams?: [...string]
	...
}
