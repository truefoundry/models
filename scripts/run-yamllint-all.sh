#!/usr/bin/env bash
# Run yamllint on all YAML under providers/.
# Writes lint_failed=true|false to GITHUB_OUTPUT when set; exits with yamllint's code.

set -e
yamllint -c .yamllint.yml providers/
code=$?
[ -n "${GITHUB_OUTPUT:-}" ] && echo "lint_failed=$([ "$code" -ne 0 ] && echo true || echo false)" >> "$GITHUB_OUTPUT"
exit $code
