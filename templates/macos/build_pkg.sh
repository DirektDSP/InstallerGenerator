#!/usr/bin/env bash
# Build a flat macOS product archive (.pkg) from CI-built plugin bundles.
# Uses pkgbuild + productbuild. GENERATED/OWNED by InstallerGenerator — generalized
# from Polygraph's packaging/macos/build_pkg.sh to be format-adaptive: it packages
# whatever bundles are present (VST3 required; AU/CLAP/app optional) and generates
# the productbuild Distribution.xml dynamically, so it works for plugins with no
# Standalone target (e.g. Chasm) without a per-plugin template edit.
set -euo pipefail

VERSION="${VERSION:?set VERSION}"
ARTIFACTS_DIR="${ARTIFACTS_DIR:?set ARTIFACTS_DIR}"
OUTDIR="${OUTDIR:?set OUTDIR}"
PRODUCT_NAME="${PRODUCT_NAME:?set PRODUCT_NAME}"
BUNDLE_ID="${BUNDLE_ID:?set BUNDLE_ID}"
COMPANY_NAME="${COMPANY_NAME:-DirektDSP}"
# Filename-safe product name for the final .pkg (spaces -> none). Internal
# sub-package names still use PRODUCT_NAME. Defaults to PRODUCT_NAME when unset.
PRODUCT_SLUG="${PRODUCT_SLUG:-${PRODUCT_NAME// /}}"

# --- Signing / notarization (all optional; unset = unsigned build, as before) --
# MACOS_SIGN_IDENTITY_APP        "Developer ID Application: Name (TEAMID)"
# MACOS_INSTALLER_SIGN_IDENTITY  "Developer ID Installer: Name (TEAMID)"
# NOTARY_KEY_PATH/KEY_ID/ISSUER_ID   App Store Connect API key for notarytool
# MACOS_ENTITLEMENTS             plist applied to the Standalone .app only
# See docs/SIGNING.md in the plugin repos for how these are produced.
MACOS_SIGN_IDENTITY_APP="${MACOS_SIGN_IDENTITY_APP:-}"
MACOS_INSTALLER_SIGN_IDENTITY="${MACOS_INSTALLER_SIGN_IDENTITY:-}"
NOTARY_KEY_PATH="${NOTARY_KEY_PATH:-}"
NOTARY_KEY_ID="${NOTARY_KEY_ID:-}"
NOTARY_ISSUER_ID="${NOTARY_ISSUER_ID:-}"
MACOS_ENTITLEMENTS="${MACOS_ENTITLEMENTS:-}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKDIR="$(mktemp -d)"
PKGS="$WORKDIR/pkgs"
RES="$WORKDIR/resources"
trap 'rm -rf "$WORKDIR"' EXIT

mkdir -p "$PKGS" "$RES" "$OUTDIR"
cp -f "$SCRIPT_DIR/resources/EULA" "$RES/EULA"
cp -f "$SCRIPT_DIR/resources/README" "$RES/README"

# download-artifact often nests: <dest>/<artifact-name>/*.clap (not <dest>/*.clap)
resolve_bundle_dir() {
  local root="${1:?}"
  shopt -s nullglob
  local hits=( "$root"/*.vst3 )
  if [[ ${#hits[@]} -ge 1 ]]; then printf '%s' "$root"; return; fi
  local sub
  for sub in "$root"/*/; do
    [[ -d "$sub" ]] || continue
    hits=( "${sub}"*.vst3 )
    if [[ ${#hits[@]} -ge 1 ]]; then printf '%s' "${sub%/}"; return; fi
  done
  printf '%s' "$root"
}

resolved="$(resolve_bundle_dir "$ARTIFACTS_DIR")"
if [[ "$resolved" != "$ARTIFACTS_DIR" ]]; then
  echo "Resolved plugin bundles under: $resolved"
fi
ARTIFACTS_DIR="$resolved"

shopt -s nullglob
vst3s=( "$ARTIFACTS_DIR"/*.vst3 )
aus=( "$ARTIFACTS_DIR"/*.component )
claps=( "$ARTIFACTS_DIR"/*.clap )
apps=( "$ARTIFACTS_DIR"/*.app )

# VST3 is the one format every DirektDSP plugin ships — hard requirement.
if [[ ${#vst3s[@]} -ne 1 ]]; then
  echo "Expected exactly one .vst3 in $ARTIFACTS_DIR, got: ${vst3s[*]-}"
  exit 1
fi

# --- Code signing -------------------------------------------------------------
# Runs before anything is staged into a component pkg: pkgbuild copies bundles
# verbatim, so a bundle signed after staging would ship unsigned inside the pkg.
# A secure timestamp needs a real identity; the ad-hoc "-" identity (local
# dry runs) has none, and codesign refuses the combination.
SIGN_FLAGS=(--options runtime)
if [[ "$MACOS_SIGN_IDENTITY_APP" != "-" ]]; then
  SIGN_FLAGS+=(--timestamp)
fi

sign_bundle() {
  local target="$1"
  local extra=()
  # The Standalone opens an input device, so under the hardened runtime it needs
  # the audio-input entitlement or macOS denies it the microphone. Plug-in
  # formats never ask for one — the host owns the device. The file is checked
  # for existence, not just the variable: a plugin tree with a stale vendored
  # packaging/ would otherwise fail codesign with an unhelpful error.
  if [[ "$target" == *.app ]]; then
    if [[ -n "$MACOS_ENTITLEMENTS" && -f "$MACOS_ENTITLEMENTS" ]]; then
      extra=(--entitlements "$MACOS_ENTITLEMENTS")
    elif [[ -n "$MACOS_ENTITLEMENTS" ]]; then
      echo "::warning::MACOS_ENTITLEMENTS=$MACOS_ENTITLEMENTS does not exist; signing $(basename "$target") without entitlements"
    fi
  fi

  # Inside-out: codesign seals a bundle around whatever it already contains, so
  # signing the outer bundle first leaves nested binaries unsigned and
  # notarization rejects the whole submission. Everything that can carry code
  # is covered — frameworks, dylibs, bundles, helper apps/XPC services and any
  # extra Mach-O in Contents/MacOS (a shipped runtime such as ONNX Runtime
  # arrives signed by its vendor and is re-signed with our identity here) —
  # deepest paths first so a nested bundle's own contents are sealed before it.
  local main_exe=""
  if [[ -f "$target/Contents/Info.plist" ]]; then
    main_exe="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleExecutable' "$target/Contents/Info.plist" 2>/dev/null || true)"
  fi
  local nested
  while IFS= read -r nested; do
    [[ -n "$nested" ]] || continue
    # Skip the bundle's own main executable: it is sealed with the bundle below.
    [[ -n "$main_exe" && "$nested" == "$target/Contents/MacOS/$main_exe" ]] && continue
    codesign --force --sign "$MACOS_SIGN_IDENTITY_APP" "${SIGN_FLAGS[@]}" "$nested"
  done < <(
    {
      find "$target" -mindepth 1 \( -name '*.framework' -o -name '*.dylib' -o -name '*.so' \
        -o -name '*.bundle' -o -name '*.app' -o -name '*.xpc' -o -name '*.appex' \) -print 2>/dev/null
      # Loose Mach-O files next to the main executable (helpers, CLIs)
      if [[ -d "$target/Contents/MacOS" ]]; then
        find "$target/Contents/MacOS" -type f -perm -u+x -print 2>/dev/null
      fi
    } | awk '{ print gsub("/", "/") "\t" $0 }' | sort -rn -k1,1 | cut -f2- | awk '!seen[$0]++'
  )

  # --options runtime is mandatory: notarization rejects anything built without
  # the hardened runtime. --timestamp is what keeps already-shipped signatures
  # valid after the certificate itself expires.
  codesign --force --sign "$MACOS_SIGN_IDENTITY_APP" "${SIGN_FLAGS[@]}" \
    "${extra[@]+"${extra[@]}"}" "$target"
  codesign --verify --strict --deep --verbose=2 "$target"
}

if [[ -n "$MACOS_SIGN_IDENTITY_APP" ]]; then
  echo "Signing bundles as: $MACOS_SIGN_IDENTITY_APP"
  for bundle in "${vst3s[@]}" "${aus[@]}" "${claps[@]}" "${apps[@]}"; do
    echo "  codesign $(basename "$bundle")"
    sign_bundle "$bundle"
  done
else
  echo "::warning::MACOS_SIGN_IDENTITY_APP unset — bundles will be unsigned and Gatekeeper will block them"
fi

# ---------------------------------------------------------------------------
# Clear stale per-user copies of the plug-in (postinstall scripts)
#
# Why: DAWs such as Ableton Live scan the *user* plug-in folders
# (~/Library/Audio/Plug-Ins/{VST3,Components,CLAP}) in addition to /Library, and a
# same-named bundle in the user folder shadows the system-wide one. A leftover
# developer build there means users keep loading the stale copy even after
# installing this pkg. Each format's component package therefore carries a
# postinstall that removes ONLY the same-named bundle of its own format from the
# console user's folder, so the /Library install is the only one. Nothing else is
# deleted and nothing is written into the user folder. The script never fails the
# install (always exit 0). Installer scripts run as root, so the console user's home
# is resolved explicitly rather than trusting $HOME.
# ---------------------------------------------------------------------------
# $1 = format dir under Plug-Ins, $2 = bundle extension, $3 = "au" to also reset the AU cache.
# Output: path of a scripts dir holding an executable "postinstall".
# PRODUCT_NAME is embedded via printf %q so names with spaces/quotes stay one safe word.
make_scripts() {
  local kind="$1" fmtdir="$2" ext="$3"
  local dir="$WORKDIR/scripts_${kind}"
  rm -rf "$dir"; mkdir -p "$dir"
  local bundle="${PRODUCT_NAME}.${ext}"
  {
    echo '#!/bin/bash'
    echo '# Generated by InstallerGenerator build_pkg.sh. Removes a stale per-user copy that'
    echo '# would shadow the /Library install in DAWs. Never fails the install.'
    echo 'set -u'
    printf 'bundle=%q\n' "$bundle"
    printf 'fmtdir=%q\n' "$fmtdir"
    cat <<'BODY'
u=$(stat -f %Su /dev/console 2>/dev/null || true)
if [ -z "$u" ] || [ "$u" = "root" ]; then u="${USER:-}"; fi
if [ -z "$u" ] || [ "$u" = "root" ]; then
  echo "postinstall: no console user, not clearing user-folder copy"
  exit 0
fi
home=$(dscl . -read "/Users/$u" NFSHomeDirectory 2>/dev/null | awk '{print $2}')
if [ -z "$home" ]; then home="/Users/$u"; fi
target="$home/Library/Audio/Plug-Ins/$fmtdir/$bundle"
if [ -e "$target" ] || [ -L "$target" ]; then
  echo "postinstall: removing stale user copy: $target"
  rm -rf "$target"
else
  echo "postinstall: no user copy at $target"
fi
BODY
    if [[ "$kind" == "au" ]]; then
      echo '# Make the AudioComponent cache pick up the new component.'
      echo 'killall -9 AudioComponentRegistrar 2>/dev/null || true'
    fi
    echo 'exit 0'
  } > "$dir/postinstall"
  chmod 755 "$dir/postinstall"
  printf '%s' "$dir"
}

stage_pkg() {
  local kind="$1" identifier="$2" outfile="$3"
  local root="$WORKDIR/root_${kind}"
  rm -rf "$root"; mkdir -p "$root"
  case "$kind" in
    vst3)
      mkdir -p "$root/Library/Audio/Plug-Ins/VST3"
      cp -R "${vst3s[0]}" "$root/Library/Audio/Plug-Ins/VST3/" ;;
    au)
      mkdir -p "$root/Library/Audio/Plug-Ins/Components"
      for c in "${aus[@]}"; do cp -R "$c" "$root/Library/Audio/Plug-Ins/Components/"; done ;;
    clap)
      mkdir -p "$root/Library/Audio/Plug-Ins/CLAP"
      cp -R "${claps[0]}" "$root/Library/Audio/Plug-Ins/CLAP/" ;;
    app)
      mkdir -p "$root/Applications"
      cp -R "${apps[0]}" "$root/Applications/" ;;
    *) echo "Unknown kind: $kind"; exit 1 ;;
  esac
  # Plug-in formats (not the app) get a postinstall that clears the user-folder copy.
  local -a script_args=()
  case "$kind" in
    vst3) script_args=( --scripts "$(make_scripts vst3 VST3 vst3)" ) ;;
    au)   script_args=( --scripts "$(make_scripts au Components component)" ) ;;
    clap) script_args=( --scripts "$(make_scripts clap CLAP clap)" ) ;;
  esac
  pkgbuild --root "$root" --identifier "$identifier" --version "$VERSION" --install-location / \
    ${script_args[@]+"${script_args[@]}"} "$PKGS/$outfile"
}

# Build a component pkg + accumulate an outline/choice/ref line only for the
# formats that are actually present. This is what makes the script plugin-agnostic.
OUTLINE=""
CHOICES=""
REFS=""

add_choice() {
  local id="$1" title="$2" desc="$3" pkgid="$4" pkgfile="$5"
  OUTLINE+="        <line choice=\"${id}\" />
"
  CHOICES+="    <choice id=\"${id}\" visible=\"true\" start_selected=\"true\" title=\"${title}\" description=\"${desc}\">
        <pkg-ref id=\"${pkgid}\" />
    </choice>
"
  REFS+="    <pkg-ref id=\"${pkgid}\" version=\"${VERSION}\" onConclusion=\"None\">${pkgfile}</pkg-ref>
"
}

stage_pkg vst3 "${BUNDLE_ID}.vst3" "${PRODUCT_NAME}.vst3.pkg"
add_choice vst3 "${PRODUCT_NAME} VST3" "VST3 plug-in (system Library, all users)." "${BUNDLE_ID}.vst3" "${PRODUCT_NAME}.vst3.pkg"

if [[ ${#aus[@]} -ge 1 ]]; then
  stage_pkg au "${BUNDLE_ID}.au" "${PRODUCT_NAME}.au.pkg"
  add_choice au "${PRODUCT_NAME} AU" "Audio Unit component (system Library, all users)." "${BUNDLE_ID}.au" "${PRODUCT_NAME}.au.pkg"
fi
if [[ ${#claps[@]} -ge 1 ]]; then
  stage_pkg clap "${BUNDLE_ID}.clap" "${PRODUCT_NAME}.clap.pkg"
  add_choice clap "${PRODUCT_NAME} CLAP" "CLAP plug-in (system Library, all users)." "${BUNDLE_ID}.clap" "${PRODUCT_NAME}.clap.pkg"
fi
if [[ ${#apps[@]} -ge 1 ]]; then
  stage_pkg app "${BUNDLE_ID}.app" "${PRODUCT_NAME}.app.pkg"
  add_choice standalone "${PRODUCT_NAME} Standalone" "Standalone application in /Applications." "${BUNDLE_ID}.app" "${PRODUCT_NAME}.app.pkg"
fi

# Factory presets — staged by render_installer.py into packaging/presets/ (a
# sibling of this script's dir). Installed to the shared Documents location so
# every user sees them: /Users/Shared/<Company>/<Product>/Presets.
PRESETS_SRC="$SCRIPT_DIR/../presets"
if [[ -d "$PRESETS_SRC" ]] && compgen -G "$PRESETS_SRC/*" > /dev/null; then
  proot="$WORKDIR/root_presets"
  mkdir -p "$proot/Users/Shared/${COMPANY_NAME}/${PRODUCT_NAME}/Presets"
  cp -R "$PRESETS_SRC"/* "$proot/Users/Shared/${COMPANY_NAME}/${PRODUCT_NAME}/Presets/"
  pkgbuild --root "$proot" --identifier "${BUNDLE_ID}.presets" --version "$VERSION" \
    --install-location / "$PKGS/${PRODUCT_NAME}.presets.pkg"
  add_choice presets "${PRODUCT_NAME} Factory Presets" "Factory preset library (all users)." "${BUNDLE_ID}.presets" "${PRODUCT_NAME}.presets.pkg"
fi

# require-scripts: the vst3/au/clap component packages now carry postinstall scripts.
# Component-package scripts are embedded by pkgbuild and run regardless of this
# attribute, but it also tells Installer the product relies on scripting; the
# default is true, so the previous explicit "false" is removed rather than inverted.
DIST_OUT="$WORKDIR/Distribution.xml"
cat > "$DIST_OUT" <<EOF
<?xml version="1.0" encoding="utf-8"?>
<installer-gui-script minSpecVersion="2">
    <title>${PRODUCT_NAME} ${VERSION}</title>
    <allowed-os-versions>
        <os-version min="10.13" />
    </allowed-os-versions>
    <license file="EULA" mime-type="text/plain" />
    <readme file="README" mime-type="text/plain" />
    <options customize="always" rootVolumeOnly="true" hostArchitectures="x86_64,arm64" />
    <domains enable_anywhere="false" enable_currentUserHome="false" enable_localSystem="true" />

    <choices-outline>
${OUTLINE}    </choices-outline>

${CHOICES}${REFS}</installer-gui-script>
EOF

OUT_PKG="$OUTDIR/${COMPANY_NAME}-${PRODUCT_SLUG}-${VERSION}-macOS.pkg"
# Do not use "${SIGN_ARGS[@]}" when empty: set -u + bash 4.4+ treats it as unbound.
if [[ -n "${MACOS_INSTALLER_SIGN_IDENTITY:-}" ]]; then
  productbuild --sign "$MACOS_INSTALLER_SIGN_IDENTITY" \
    --distribution "$DIST_OUT" --package-path "$PKGS" --resources "$RES" "$OUT_PKG"
else
  productbuild \
    --distribution "$DIST_OUT" --package-path "$PKGS" --resources "$RES" "$OUT_PKG"
fi

echo "Built $OUT_PKG"

# --- Notarization -------------------------------------------------------------
# The .pkg is what gets submitted, not the individual bundles: one ticket covers
# everything inside it, and stapling to the pkg is what makes the installer
# validate on a machine with no network.
if [[ -n "$NOTARY_KEY_PATH" && -n "$NOTARY_KEY_ID" && -n "$NOTARY_ISSUER_ID" ]]; then
  if [[ -z "$MACOS_INSTALLER_SIGN_IDENTITY" ]]; then
    echo "::error::Notarization requires a signed pkg — set MACOS_INSTALLER_SIGN_IDENTITY"
    exit 1
  fi

  echo "Submitting $OUT_PKG to the notary service (this usually takes a couple of minutes)"
  if ! xcrun notarytool submit "$OUT_PKG" \
      --key "$NOTARY_KEY_PATH" --key-id "$NOTARY_KEY_ID" --issuer "$NOTARY_ISSUER_ID" \
      --wait --timeout 30m; then
    echo "::error::Notarization failed. Fetch the reason with:"
    echo "  xcrun notarytool log <submission-id> --key <p8> --key-id <id> --issuer <uuid>"
    exit 1
  fi

  xcrun stapler staple "$OUT_PKG"
  xcrun stapler validate "$OUT_PKG"
  # Gatekeeper's own verdict, as the installer daemon would see it
  spctl --assess --type install --verbose=4 "$OUT_PKG"
  echo "Notarized + stapled $OUT_PKG"
elif [[ -n "$MACOS_INSTALLER_SIGN_IDENTITY" ]]; then
  echo "::warning::pkg is signed but NOT notarized — Gatekeeper still blocks it on download"
else
  echo "::warning::pkg is unsigned and un-notarized — for local/dev use only"
fi
