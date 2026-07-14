#!/usr/bin/env bash
# Run pluginval on plugin bundles under ARTIFACT_DIR. Exits non-zero if any run fails.
#
# Compatibility notes:
#   - macOS GitHub runners ship bash 3.2 in /usr/bin; use POSIX-friendly array fill
#     (no `mapfile -d`) so the same script works there.
#   - Linux runners are headless. Editor lifecycle tests instantiate a
#     juce::Component-backed editor that needs a display server — wrap with
#     `xvfb-run` when on Linux without DISPLAY set.
#   --timeout-ms is a hard cap per test. GUI tests are enabled; the editor timer
#     is gated on !isPluginvalHost() so the repaint/message-loop hang is avoided.
set -euo pipefail

PLUGINVAL_BIN="${1:?pluginval binary path}"
ARTIFACT_DIR="${2:?directory to search for plugins}"
OUT_DIR="${3:-pluginval_logs}"
STRICTNESS="${4:-7}"

mkdir -p "$OUT_DIR"

# Portable plugin-bundle discovery — works with bash 3.2.
# .clap excluded — pluginval doesn't support CLAP; use run_clapval.sh instead.
# .component (AU) included on macOS if present. The caller (CI workflow) must
# register them with the system audio component registry first.
# -prune: a modern .vst3 is a bundle DIRECTORY whose Contents/ nests a .vst3
# module file — without pruning the same plugin gets validated twice.
plugins=()
while IFS= read -r line; do
    plugins+=("$line")
done < <(find "$ARTIFACT_DIR" -name '*.vst3' -prune)

# On macOS, also pick up AU .component bundles.
if [[ "$(uname -s)" == "Darwin" ]]; then
    while IFS= read -r line; do
        plugins+=("$line")
    done < <(find "$ARTIFACT_DIR" -name '*.component')
fi

if [[ ${#plugins[@]} -eq 0 ]]; then
  echo "ERROR: No plugin bundles found under $ARTIFACT_DIR"
  exit 1
fi

# Linux headless workaround: xvfb-run wraps pluginval with a transient virtual
# framebuffer so any GUI-touching code (state thread sync, etc) has a display.
WRAPPER=()
if [[ "$(uname -s)" == "Linux" && -z "${DISPLAY:-}" ]] && command -v xvfb-run >/dev/null 2>&1; then
    WRAPPER=(xvfb-run -a --server-args="-screen 0 1280x720x24")
fi

PLUGINVAL_ARGS=(
  --validate-in-process
  --verbose
  --timeout-ms 30000
  --strictness-level "$STRICTNESS"
  --output-dir "$OUT_DIR"
)

failed=0
for plugin in "${plugins[@]}"; do
  echo "=== pluginval: $plugin ==="
  # Bash 3.2 (macos runner) treats `${WRAPPER[@]}` on an empty array as unbound under
  # `set -u`. Branch on length to avoid the unbound expansion.
  if [[ ${#WRAPPER[@]} -gt 0 ]]; then
    if ! "${WRAPPER[@]}" "$PLUGINVAL_BIN" "${PLUGINVAL_ARGS[@]}" "$plugin"; then
      failed=1
    fi
  else
    if ! "$PLUGINVAL_BIN" "${PLUGINVAL_ARGS[@]}" "$plugin"; then
      failed=1
    fi
  fi
done

exit "$failed"
