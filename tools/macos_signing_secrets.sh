#!/usr/bin/env bash
# Upload the macOS signing + notarization secrets to the DirektDSP GitHub
# organization in one go, so every plugin repo inherits them through
# build-all.yml's `secrets: inherit` and build-plugin.yml's gated steps.
#
# Run this on the Mac that holds the Developer ID certificates after following
# docs/SIGNING.md steps 1-4. It never writes the files anywhere; it only
# base64-encodes them into `gh secret set`.
#
#   tools/macos_signing_secrets.sh \
#     --app-p12 ~/certs/DeveloperIDApplication.p12 \
#     --installer-p12 ~/certs/DeveloperIDInstaller.p12 \
#     --notary-key ~/certs/AuthKey_ABCDE12345.p8 \
#     --notary-key-id ABCDE12345 \
#     --notary-issuer 12345678-1234-1234-1234-123456789abc \
#     [--visibility all|private|selected] [--org DirektDSP] [--dry-run]
#
# Prompts for the two .p12 export passwords (not echoed). The identity strings
# are read from the certificates themselves, so they cannot be mistyped.
# Needs `gh auth refresh -h github.com -s admin:org` once beforehand.
set -euo pipefail

ORG="DirektDSP"
VISIBILITY="all"
DRY_RUN=0
APP_P12="" INSTALLER_P12="" NOTARY_KEY="" NOTARY_KEY_ID="" NOTARY_ISSUER=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --app-p12) APP_P12="$2"; shift 2 ;;
    --installer-p12) INSTALLER_P12="$2"; shift 2 ;;
    --notary-key) NOTARY_KEY="$2"; shift 2 ;;
    --notary-key-id) NOTARY_KEY_ID="$2"; shift 2 ;;
    --notary-issuer) NOTARY_ISSUER="$2"; shift 2 ;;
    --visibility) VISIBILITY="$2"; shift 2 ;;
    --org) ORG="$2"; shift 2 ;;
    --dry-run) DRY_RUN=1; shift ;;
    -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

for v in APP_P12 INSTALLER_P12 NOTARY_KEY NOTARY_KEY_ID NOTARY_ISSUER; do
  [[ -n "${!v}" ]] || { echo "missing --$(echo "$v" | tr '[:upper:]_' '[:lower:]-')" >&2; exit 2; }
done
for f in "$APP_P12" "$INSTALLER_P12" "$NOTARY_KEY"; do
  [[ -f "$f" ]] || { echo "not a file: $f" >&2; exit 2; }
done
[[ "$NOTARY_KEY_ID" =~ ^[A-Z0-9]{10}$ ]] || { echo "--notary-key-id should be the 10-character key id (from AuthKey_<ID>.p8)" >&2; exit 2; }
[[ "$NOTARY_ISSUER" =~ ^[0-9a-fA-F-]{36}$ ]] || { echo "--notary-issuer should be the issuer UUID from App Store Connect" >&2; exit 2; }

read -r -s -p "Export password for $(basename "$APP_P12"): " APP_PW; echo
read -r -s -p "Export password for $(basename "$INSTALLER_P12"): " INSTALLER_PW; echo

# Read the identity common names straight out of the .p12 files so the secret
# matches what `security find-identity` will report on the runner.
identity_of() {
  local p12="$1" pw="$2"
  openssl pkcs12 -in "$p12" -clcerts -nokeys -passin "pass:$pw" 2>/dev/null \
    | openssl x509 -noout -subject -nameopt sep_multiline,utf8 2>/dev/null \
    | awk -F'CN=' '/CN=/{print $2}'
}
APP_ID="$(identity_of "$APP_P12" "$APP_PW")"
INSTALLER_ID="$(identity_of "$INSTALLER_P12" "$INSTALLER_PW")"
[[ "$APP_ID" == "Developer ID Application:"* ]] || {
  echo "the application .p12 does not contain a 'Developer ID Application' certificate (got '${APP_ID:-nothing}'); check the file and password" >&2; exit 1; }
[[ "$INSTALLER_ID" == "Developer ID Installer:"* ]] || {
  echo "the installer .p12 does not contain a 'Developer ID Installer' certificate (got '${INSTALLER_ID:-nothing}'); check the file and password" >&2; exit 1; }
# The private key must travel with the certificate or CI cannot sign.
for pair in "$APP_P12|$APP_PW" "$INSTALLER_P12|$INSTALLER_PW"; do
  openssl pkcs12 -in "${pair%%|*}" -nocerts -nodes -passin "pass:${pair#*|}" 2>/dev/null | grep -q "PRIVATE KEY" \
    || { echo "${pair%%|*} carries no private key; re-export from Keychain Access > My Certificates" >&2; exit 1; }
done

KEYCHAIN_PW="$(openssl rand -base64 24)"

echo "Organization: $ORG   visibility: $VISIBILITY"
echo "  MACOS_SIGN_IDENTITY_APP        = $APP_ID"
echo "  MACOS_INSTALLER_SIGN_IDENTITY  = $INSTALLER_ID"
echo "  MACOS_NOTARY_KEY_ID            = $NOTARY_KEY_ID"
echo "  MACOS_NOTARY_ISSUER_ID         = $NOTARY_ISSUER"
echo "  + MACOS_CERT_APPLICATION_P12 / _PASSWORD, MACOS_CERT_INSTALLER_P12 / _PASSWORD,"
echo "    MACOS_NOTARY_KEY_P8, MACOS_KEYCHAIN_PASSWORD (random)"

set_secret() {
  local name="$1" value="$2"
  if [[ $DRY_RUN -eq 1 ]]; then echo "  [dry-run] gh secret set $name --org $ORG --visibility $VISIBILITY"; return; fi
  printf '%s' "$value" | gh secret set "$name" --org "$ORG" --visibility "$VISIBILITY"
}

set_secret MACOS_CERT_APPLICATION_P12      "$(base64 < "$APP_P12" | tr -d '\n')"
set_secret MACOS_CERT_APPLICATION_PASSWORD "$APP_PW"
set_secret MACOS_CERT_INSTALLER_P12        "$(base64 < "$INSTALLER_P12" | tr -d '\n')"
set_secret MACOS_CERT_INSTALLER_PASSWORD   "$INSTALLER_PW"
set_secret MACOS_SIGN_IDENTITY_APP         "$APP_ID"
set_secret MACOS_INSTALLER_SIGN_IDENTITY   "$INSTALLER_ID"
set_secret MACOS_NOTARY_KEY_P8             "$(base64 < "$NOTARY_KEY" | tr -d '\n')"
set_secret MACOS_NOTARY_KEY_ID             "$NOTARY_KEY_ID"
set_secret MACOS_NOTARY_ISSUER_ID          "$NOTARY_ISSUER"
set_secret MACOS_KEYCHAIN_PASSWORD         "$KEYCHAIN_PW"

echo "done. Next: dispatch build-plugin.yml for one plugin (fuzzboy first) and check the"
echo "macOS job's 'Smoke test' step reports a signed, stapled pkg."
