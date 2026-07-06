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
  pkgbuild --root "$root" --identifier "$identifier" --version "$VERSION" --install-location / \
    "$PKGS/$outfile"
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
    <options customize="always" rootVolumeOnly="true" hostArchitectures="x86_64,arm64" require-scripts="false" />
    <domains enable_anywhere="false" enable_currentUserHome="false" enable_localSystem="true" />

    <choices-outline>
${OUTLINE}    </choices-outline>

${CHOICES}${REFS}</installer-gui-script>
EOF

OUT_PKG="$OUTDIR/${COMPANY_NAME}-${PRODUCT_NAME}-${VERSION}-macOS.pkg"
# Do not use "${SIGN_ARGS[@]}" when empty: set -u + bash 4.4+ treats it as unbound.
if [[ -n "${MACOS_INSTALLER_SIGN_IDENTITY:-}" ]]; then
  productbuild --sign "$MACOS_INSTALLER_SIGN_IDENTITY" \
    --distribution "$DIST_OUT" --package-path "$PKGS" --resources "$RES" "$OUT_PKG"
else
  productbuild \
    --distribution "$DIST_OUT" --package-path "$PKGS" --resources "$RES" "$OUT_PKG"
fi

echo "Built $OUT_PKG"
