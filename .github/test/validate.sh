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
    local definition

    # Use different definition for default.yaml vs model files
    if [ "$filename" = "default.yaml" ]; then
        definition="#DefaultConfig"
    else
        definition="#ModelConfig"
    fi

    # Load common.cue + model.cue + default.cue together (same package)
    cat "$file" | cue vet "$COMMON_SCHEMA" "$MODEL_SCHEMA" "$DEFAULT_SCHEMA" yaml: - -d "$definition" 2>&1
}

if [ -n "$1" ]; then
    # Validate specific file
    if ! output=$(validate_file "$1"); then
        echo "$output"
        exit 1
    fi
else
    # Validate all YAML files in providers/
    PROVIDERS_DIR="$SCRIPT_DIR/../../providers"
    FAILED=0
    PASSED=0
    FAILED_FILES=()
    FAILED_ERRORS=()

    for file in $(find "$PROVIDERS_DIR" -name "*.yaml" -type f); do
        if output=$(validate_file "$file") && [ -z "$output" ]; then
            PASSED=$((PASSED + 1))
        else
            FAILED=$((FAILED + 1))
            FAILED_FILES+=("$file")
            FAILED_ERRORS+=("$output")
        fi
    done

    echo ""
    echo "Results: $PASSED passed, $FAILED failed"

    if [ $FAILED -gt 0 ]; then
        echo ""
        echo "Failed files:"
        for i in "${!FAILED_FILES[@]}"; do
            echo "  - ${FAILED_FILES[$i]}"
            if [ -n "${FAILED_ERRORS[$i]}" ]; then
                echo "${FAILED_ERRORS[$i]}" | sed 's/^/      /'
            fi
        done
        exit 1
    fi
fi
