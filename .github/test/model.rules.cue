package model

#ReasoningEffortValue:
	"high" |
	"low" |
	"max" |
	"medium" |
	"minimal" |
	"none" |
	"xhigh"

#ModelParam: {
	key: string
	if key == "reasoning_effort" {
		supportedValues?: [...#ReasoningEffortValue]
	}

	// If the key is not reasoning_effort, supportedValues must be absent
	if key != "reasoning_effort" {
		supportedValues?: _|_
	}
}
