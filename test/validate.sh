#!/bin/bash

# Validate YAML files against CUE schemas
# Usage: ./validate.sh [file.yaml] or ./validate.sh (validates all)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMMON_SCHEMA="$SCRIPT_DIR/common.cue"
MODEL_SCHEMA="$SCRIPT_DIR/model.cue"
DEFAULT_SCHEMA="$SCRIPT_DIR/default.cue"

# Check if cue is installed
if ! command -v cue &> /dev/null; then
    echo "Error: CUE is not installed."
    echo "Install with: brew install cue-lang/tap/cue"
    exit 1
fi

validate_file() {
    local file="$1"
    local filename=$(basename "$file")
    local schema
    local definition

    # Use different definition for default.yaml vs model files
    if [ "$filename" = "default.yaml" ]; then
        definition="#DefaultConfig"
    else
        definition="#ModelConfig"
    fi

    local result=0
    # Load common.cue + model.cue + default.cue together (same package)
    if cat "$file" | cue vet "$COMMON_SCHEMA" "$MODEL_SCHEMA" "$DEFAULT_SCHEMA" yaml: - -d "$definition" 2>/dev/null; then
        echo "✓ $file"
    else
        echo "✗ $file"
        cat "$file" | cue vet "$COMMON_SCHEMA" "$MODEL_SCHEMA" "$DEFAULT_SCHEMA" yaml: - -d "$definition" 2>&1 | head -10
        result=1
    fi

    return $result
}

if [ -n "$1" ]; then
    # Validate specific file
    validate_file "$1"
else
    # Validate all YAML files in providers/
    PROVIDERS_DIR="$SCRIPT_DIR/../providers"
    FAILED=0
    PASSED=0
    
    for file in $(find "$PROVIDERS_DIR" -name "*.yaml" -type f); do
        if validate_file "$file"; then
            ((PASSED++))
        else
            ((FAILED++))
        fi
    done
    
    echo ""
    echo "Results: $PASSED passed, $FAILED failed"
    
    if [ $FAILED -gt 0 ]; then
        exit 1
    fi
fi
