#!/bin/bash

# Validate YAML files against CUE schemas
# Usage: ./validate.sh [file.yaml] or ./validate.sh (validates all)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODEL_SCHEMA="$SCRIPT_DIR/model.cue"
# Validation-only constraints; not used by type generation (see model.rules.cue)
MODEL_RULES="$SCRIPT_DIR/model.rules.cue"

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

    # Provider-scoped yamls each have their own definition; everything else is a model
    case "$filename" in
        default.yaml)         definition="#DefaultConfig" ;;
        provider-config.yaml) definition="#ProviderConfig" ;;
        *)                    definition="#ModelConfig" ;;
    esac

    cat "$file" | cue vet "$MODEL_SCHEMA" "$MODEL_RULES" yaml: - -d "$definition" 2>&1
}

if [ "$#" -gt 0 ]; then
    # Validate specific file(s) passed as arguments
    EXIT_CODE=0
    for file in "$@"; do
        if ! output=$(validate_file "$file"); then
            echo "FAIL $file"
            echo "$output"
            EXIT_CODE=1
        fi
    done
    exit $EXIT_CODE
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
