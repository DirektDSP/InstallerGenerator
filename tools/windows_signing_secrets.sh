#!/usr/bin/env bash
# Upload the Windows (SSL.com eSigner) signing secrets to the DirektDSP GitHub
# organization, visible to InstallerGenerator only (several org repos are
# public). Prompts for everything secret; nothing is echoed or written to disk.
#
#   tools/windows_signing_secrets.sh [--sandbox] [--repos InstallerGenerator] [--org DirektDSP] [--dry-run]
#
# Where the values come from (eSigner dashboard at https://secure.ssl.com):
#   username / password  your SSL.com account login
#   credential id        Orders > your code signing order > "Signing Credential ID"
#   TOTP secret          shown once when you enable eSigner automation (the text
#                        secret behind the QR code); this lets CI produce the
#                        one-time codes itself
# --sandbox stores WINDOWS_ESIGNER_ENVIRONMENT=TEST to try the pipeline with a
# free eSigner sandbox account first; without it any TEST marker is removed.
# Needs `gh auth refresh -h github.com -s admin:org` once beforehand.
set -euo pipefail

ORG="DirektDSP"; REPOS="InstallerGenerator"; SANDBOX=0; DRY_RUN=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --sandbox) SANDBOX=1; shift ;;
    --repos) REPOS="$2"; shift 2 ;;
    --org) ORG="$2"; shift 2 ;;
    --dry-run) DRY_RUN=1; shift ;;
    -h|--help) sed -n '2,17p' "$0"; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

read -r -p "eSigner username (SSL.com account): " U
read -r -s -p "eSigner password: " P; echo
read -r -p "Signing credential ID: " C
read -r -s -p "TOTP secret (automation key): " T; echo
for v in U P C T; do [[ -n "${!v}" ]] || { echo "all four values are required" >&2; exit 2; }; done
[[ "$C" =~ ^[0-9a-fA-F-]{8,}$ ]] || { echo "the credential ID looks wrong (expected a UUID-like id from the eSigner order page)" >&2; exit 2; }

set_secret() {
  if [[ $DRY_RUN -eq 1 ]]; then echo "  [dry-run] gh secret set $1 --org $ORG --visibility selected --repos $REPOS"; return; fi
  printf '%s' "$2" | gh secret set "$1" --org "$ORG" --visibility selected --repos "$REPOS"
}
echo "Organization $ORG, visible to: $REPOS$([[ $SANDBOX -eq 1 ]] && echo '  (SANDBOX)')"
set_secret WINDOWS_ESIGNER_USERNAME "$U"
set_secret WINDOWS_ESIGNER_PASSWORD "$P"
set_secret WINDOWS_ESIGNER_CREDENTIAL_ID "$C"
set_secret WINDOWS_ESIGNER_TOTP_SECRET "$T"
if [[ $SANDBOX -eq 1 ]]; then
  set_secret WINDOWS_ESIGNER_ENVIRONMENT "TEST"
elif [[ $DRY_RUN -eq 0 ]]; then
  gh secret delete WINDOWS_ESIGNER_ENVIRONMENT --org "$ORG" >/dev/null 2>&1 || true
fi
echo "done. Builds sign only when asked: dispatch build-plugin.yml with sign_windows=true"
echo "(release tags pushed through Polygraph's release job ask for it automatically)."
