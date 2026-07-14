#!/usr/bin/env bash
# Run clap-validator on .clap bundles under ARTIFACT_DIR.
# Exits non-zero if any plugin fails validation.
#
# Usage: run_clapval.sh <clap-validator-bin> <artifact-dir> [output-dir]
#
# clap-validator runs tests out-of-process by default, which is safer and
# avoids the in-process hang that occurred when using pluginval with CLAP.
# Tests run in parallel per-plugin (clap-validator default).
set -euo pipefail

CLAPVAL_BIN="${1:?clap-validator binary path}"
ARTIFACT_DIR="${2:?directory to search for .clap bundles}"
OUT_DIR="${3:-clapval_logs}"

mkdir -p "$OUT_DIR"

plugins=()
while IFS= read -r line; do
    plugins+=("$line")
done < <(find "$ARTIFACT_DIR" -name '*.clap')

if [[ ${#plugins[@]} -eq 0 ]]; then
    echo "ERROR: No .clap bundles found under $ARTIFACT_DIR"
    exit 1
fi

# Skip tests broken by known clap-validator 0.3.2 bugs:
# - process-note-*, param-fuzz-basic: validator queries output note ports with
#   is_input=true, causing a bounds-check failure when plugin has no input ports
#   (free-audio/clap-validator#28).
SKIP_FILTER="process-note-inconsistent|process-note-out-of-place-basic|param-fuzz-basic"

failed=0
for plugin in "${plugins[@]}"; do
    echo "=== clap-validator: $plugin ==="
    log="$OUT_DIR/$(basename "$plugin" .clap).json"
    if ! "$CLAPVAL_BIN" validate --json \
        --test-filter "$SKIP_FILTER" --invert-filter \
        "$plugin" > "$log" 2>&1; then
        failed=1
        echo "FAILED: $plugin — see $log"
    else
        echo "PASSED: $plugin"
    fi
done

exit "$failed"
