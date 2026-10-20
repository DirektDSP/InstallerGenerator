# macOS signing + notarization

Every DirektDSP plugin currently ships **unsigned and un-notarized**. On any Mac
since Catalina a downloaded unsigned `.pkg` is blocked by Gatekeeper: the user
sees *"cannot be opened because it is from an unidentified developer"*, and the
plugins inside may be quarantined even if they force the installer through. For
a paid product this is the single biggest install-time blocker.

**You do this once for the whole catalogue.** The certificates are per-account,
not per-plugin, and the pipeline is shared: `templates/macos/build_pkg.sh` is
copied into every plugin's working tree by `tools/render_installer.py` at build
time, so signing added there reaches all of them. Store the credentials as
**organization** secrets and every plugin repo inherits them with no per-repo
work.

This document is the manual half — the parts that need your Apple login and
cannot be automated. `.github/workflows/build-plugin.yml` is the automated half
and reads the secrets produced here.

---

## What signing and notarization actually are

Two separate things, both required:

| | What it does | Needs |
|---|---|---|
| **Code signing** | Stamps each bundle with your identity | Developer ID certificates |
| **Notarization** | Apple scans the build and issues a ticket | App Store Connect API key |
| **Stapling** | Attaches the ticket to the `.pkg` so it validates offline | `xcrun stapler` |

Notarization is a *scan*, not a review — it is automated and usually takes a
couple of minutes. It will reject anything not signed with the **hardened
runtime**, which is why the two steps are coupled.

---

## Step 1 — Confirm the membership tier

<https://developer.apple.com/account>

You need a paid **Apple Developer Program** membership ($99/year). A free Apple
developer account cannot create Developer ID certificates — that is the one
hard prerequisite here. If the page shows an enrolment prompt rather than a
membership with a Team ID, start there; enrolment can take 24–48 hours.

Note your **Team ID** (10 characters, e.g. `ABCDE12345`) — it appears in the
membership details and inside every certificate name.

---

## Step 2 — Create two certificates

You need **both**. They are not interchangeable:

- **Developer ID Application** — signs `.vst3`, `.component`, `.clap`, `.app`
- **Developer ID Installer** — signs the `.pkg`

### Easiest path (Xcode)

1. Xcode → Settings → Accounts → add your Apple ID
2. Select the team → **Manage Certificates…**
3. **+** → *Developer ID Application*
4. **+** again → *Developer ID Installer*

Both land in your login keychain with their private keys.

### Manual path (no Xcode)

1. Keychain Access → Certificate Assistant → **Request a Certificate From a
   Certificate Authority**
   - Fill in your email and a common name
   - Select **Saved to disk**, key size 2048, algorithm RSA
2. <https://developer.apple.com/account/resources/certificates> → **+**
3. Choose *Developer ID Application*, upload the CSR, download the `.cer`
4. Double-click the `.cer` to install it
5. Repeat from step 1 for *Developer ID Installer* (use a fresh CSR)

> Apple limits you to a small number of Developer ID certificates per account
> and they are awkward to revoke. Create one of each and keep the `.p12`
> backups somewhere safe rather than regenerating later.

### Confirm they are installed

```sh
security find-identity -v -p codesigning
```

You want two lines like:

```
1) A1B2... "Developer ID Application: Your Name (ABCDE12345)"
2) C3D4... "Developer ID Installer: Your Name (ABCDE12345)"
```

Copy those quoted strings verbatim — they become two of the secrets below.

---

## Step 3 — Export both certificates as `.p12`

CI cannot use your keychain, so each certificate has to travel as an encrypted
`.p12` containing **the certificate and its private key**.

1. Keychain Access → **My Certificates** (this category matters — it only lists
   certificates that have their private key)
2. Right-click *Developer ID Application: …* → **Export…**
3. Format: *Personal Information Exchange (.p12)*, save as
   `DeveloperIDApplication.p12`
4. Set a strong export password — you will store it as a secret
5. Repeat for *Developer ID Installer: …* → `DeveloperIDInstaller.p12`

If the Export option is greyed out or the resulting file is tiny, you exported
the certificate without its key — go back to **My Certificates** and expand the
disclosure triangle to confirm a private key is attached.

---

## Step 4 — Create an App Store Connect API key for notarytool

This is what `notarytool` authenticates with. Preferred over an Apple ID +
app-specific password because it is not tied to a person and does not break
when 2FA state changes.

1. <https://appstoreconnect.apple.com> → **Users and Access**
2. **Integrations** tab → **App Store Connect API** → **Team Keys**
3. **+**, name it something like `churn-notary`, access role **Developer**
4. Download `AuthKey_XXXXXXXXXX.p8`

> **The `.p8` downloads exactly once.** If you lose it you must revoke the key
> and make a new one. Back it up before leaving the page.

Record three values:

- **Issuer ID** — the UUID shown above the key list
- **Key ID** — the 10-character `XXXXXXXXXX` from the filename
- The `.p8` file itself

---

## Step 5 — Load everything into GitHub secrets

### Fast path: one script

`tools/macos_signing_secrets.sh` does this whole step. It reads the identity
names out of the two `.p12` files (so they cannot be mistyped), checks each
carries its private key, generates the keychain password, and uploads all ten
organization secrets with `gh`:

```sh
gh auth refresh -h github.com -s admin:org     # once; org secrets need this scope
tools/macos_signing_secrets.sh \
  --app-p12 ~/certs/DeveloperIDApplication.p12 \
  --installer-p12 ~/certs/DeveloperIDInstaller.p12 \
  --notary-key ~/certs/AuthKey_XXXXXXXXXX.p8 \
  --notary-key-id XXXXXXXXXX \
  --notary-issuer <issuer UUID>
```

It prompts for the two export passwords. Add `--dry-run` to see what it would
set. By default the secrets are visible to **InstallerGenerator only**: it is
the one workflow that signs, and several DirektDSP repos are public. Keep it
that way; `--visibility all` would let any workflow in any org repo read the
certificates. The manual equivalent follows.

### Manual path

Base64-encode the three binary files:

```sh
base64 -i DeveloperIDApplication.p12 | pbcopy   # paste, then next
base64 -i DeveloperIDInstaller.p12   | pbcopy
base64 -i AuthKey_XXXXXXXXXX.p8      | pbcopy
```

These belong at **organization** level, not on a single repo: the same
certificate signs every plugin, and `build-all.yml` passes `secrets: inherit`
down to each `build-plugin.yml` call.

GitHub org → **Settings** → **Secrets and variables** → **Actions** → *New
organization secret*. Set repository access to all DirektDSP plugin repos (or
"All repositories" if that matches your policy).

Mirror the same values into `secrets/org.yaml` in the `secrets` repo, which is
sops+age encrypted and is the source of truth for what the org secrets should
contain:

```sh
export SOPS_AGE_KEY_FILE=~/.config/sops/age/keys.txt
sops org.yaml    # add macos_sign_identity_app, macos_cert_application_p12, ...
```

For each row:

| Secret | Value |
|---|---|
| `MACOS_CERT_APPLICATION_P12` | base64 of `DeveloperIDApplication.p12` |
| `MACOS_CERT_APPLICATION_PASSWORD` | its export password from Step 3 |
| `MACOS_CERT_INSTALLER_P12` | base64 of `DeveloperIDInstaller.p12` |
| `MACOS_CERT_INSTALLER_PASSWORD` | its export password from Step 3 |
| `MACOS_SIGN_IDENTITY_APP` | `Developer ID Application: Your Name (ABCDE12345)` |
| `MACOS_INSTALLER_SIGN_IDENTITY` | `Developer ID Installer: Your Name (ABCDE12345)` |
| `MACOS_NOTARY_ISSUER_ID` | issuer UUID from Step 4 |
| `MACOS_NOTARY_KEY_ID` | 10-character key ID from Step 4 |
| `MACOS_NOTARY_KEY_P8` | base64 of the `.p8` |
| `MACOS_KEYCHAIN_PASSWORD` | any random string (`openssl rand -base64 24`) |

`MACOS_INSTALLER_SIGN_IDENTITY` was already wired up; the rest are new.

Each is independently gated. Setting none leaves the pipeline building unsigned
`.pkg`s exactly as before, so nothing breaks while you work through this. The
useful intermediate states are:

| Secrets present | Result |
|---|---|
| none | unsigned pkg, warning in the log |
| `MACOS_CERT_APPLICATION_P12` + `MACOS_SIGN_IDENTITY_APP` + `MACOS_KEYCHAIN_PASSWORD` | bundles signed, pkg unsigned |
| + `MACOS_CERT_INSTALLER_P12` + `MACOS_INSTALLER_SIGN_IDENTITY` | pkg signed, `pkgutil` check becomes a hard gate |
| + the three `MACOS_NOTARY_*` | notarized + stapled; `stapler validate` and `spctl` become hard gates |

---

## Step 6 — What CI already does with them

This half is implemented. `build-plugin.yml` handles the keychain and the notary
key; `templates/macos/build_pkg.sh` does the signing, notarization and stapling.
Every step is gated on its secret being non-empty, so the workflow stays green
before the certificates exist and switches on the moment they land.

Reference only — you do not need to run any of this by hand.

**Import into a throwaway keychain** (never the runner's login keychain):

```sh
security create-keychain -p "$KEYCHAIN_PASSWORD" build.keychain
security set-keychain-settings -lut 21600 build.keychain
security unlock-keychain -p "$KEYCHAIN_PASSWORD" build.keychain
security import app.p12 -k build.keychain -P "$P12_PASSWORD" -T /usr/bin/codesign
security import installer.p12 -k build.keychain -P "$P12_PASSWORD" -T /usr/bin/productbuild
security set-key-partition-list -S apple-tool:,apple:,codesign: \
  -s -k "$KEYCHAIN_PASSWORD" build.keychain
security list-keychains -d user -s build.keychain login.keychain
```

The `set-key-partition-list` line is the one everyone forgets — without it
`codesign` blocks on an interactive keychain prompt and the job hangs until it
times out.

**Sign each bundle**, hardened runtime and secure timestamp, deepest nested
component first:

```sh
codesign --force --sign "$MACOS_SIGN_IDENTITY_APP" \
         --options runtime --timestamp --verbose \
         Churn.vst3 Churn.component Churn.clap Churn.app
```

`--options runtime` is mandatory: notarization rejects anything without the
hardened runtime. `--timestamp` is what keeps signatures valid after the
certificate eventually expires.

**Sign the installer** — `packaging/macos/build_pkg.sh` already does this when
`MACOS_INSTALLER_SIGN_IDENTITY` is set.

**Notarize and staple the `.pkg`** (not the individual bundles — the ticket
covers everything inside):

```sh
xcrun notarytool submit "DirektDSP-Churn-$VERSION-macOS.pkg" \
  --key AuthKey.p8 --key-id "$KEY_ID" --issuer "$ISSUER_ID" --wait
xcrun stapler staple "DirektDSP-Churn-$VERSION-macOS.pkg"
```

**Verify** — these replace the current `pkgutil` warning in the smoke test:

```sh
xcrun stapler validate "DirektDSP-Churn-$VERSION-macOS.pkg"
spctl -a -vvv -t install "DirektDSP-Churn-$VERSION-macOS.pkg"
```

If notarization fails, the log says exactly why:

```sh
xcrun notarytool log <submission-id> \
  --key AuthKey.p8 --key-id "$KEY_ID" --issuer "$ISSUER_ID"
```

---

## Gotchas

- **Hardened runtime is not optional.** Missing `--options runtime` on any
  executable fails notarization for the whole submission.
- **Sign after the universal build.** Churn builds `arm64;x86_64`; signing a
  slice then `lipo`-ing invalidates it. Sign the finished bundle.
- **The Standalone may need an entitlement.** If `Churn.app` ever records
  audio input it needs `com.apple.security.device.audio-input`; the plugin
  formats do not, since the host owns the device.
- **First submission is slow.** Usually ~2 minutes, occasionally 30. `--wait`
  blocks, so give the job a generous `timeout-minutes`.
- **Certificates expire in 5 years**, but `--timestamp` means already-shipped
  builds keep validating past that date.
- **Do not commit the `.p12` or `.p8` files.** They belong in a password
  manager. `assets/moonbase_api_config.json` is already gitignored for the same
  reason; these should never reach the repo at all.

---

## Windows

Unsigned Windows plugins are not just a SmartScreen warning. On Windows 11,
**Smart App Control** refuses to load an unsigned DLL it has no cloud
reputation for, so a host shows an error such as *"Polygraph.vst3 is either
not designed to run on Windows or it contains an error. Error status
0xc0e90002"* and the plugin never loads. Smart App Control is on by default on
fresh Windows 11 installs. Authenticode signing with a publicly trusted
certificate fixes it, and also removes the SmartScreen warning on the
installer.

**Route: SSL.com code signing with eSigner (cloud key).** Since June 2023 a
code signing key cannot be exported to a file; it has to live in hardware or a
cloud HSM, so CI needs a provider whose cloud signing runs on a GitHub runner.
eSigner does, through SSL.com's CodeSignTool, which build-plugin.yml pins by
version and SHA-256 (it bundles its own Java). Azure Artifact Signing is
cheaper but takes individuals only in the USA and Canada, and organisations
elsewhere.

### What to buy and verify

1. An OV (or IV, for an individual) **code signing certificate** from SSL.com,
   1 year. The short term is deliberate while incorporation is open: the
   certificate is reissued to a company if one is formed.
2. The **eSigner** plan for it. Tier 1 is 240 signings a year. A release signs
   five files: the VST3 binary, the .clap, the standalone .exe, the installer
   and its uninstaller. Microsoft's onnxruntime.dll is already signed and is
   skipped.
3. Validation by SSL.com: photo ID and, for a business name, the CRO
   business-name registration, a matching address and usually a phone call.
4. In the eSigner dashboard, enable automation and copy the **TOTP secret**
   (the text behind the QR code), and note the order's **signing credential
   ID**.

### Secrets

```sh
gh auth refresh -h github.com -s admin:org
tools/windows_signing_secrets.sh             # --sandbox first, to try a free eSigner sandbox account
```

The script prompts for the four values and stores `WINDOWS_ESIGNER_USERNAME`,
`WINDOWS_ESIGNER_PASSWORD`, `WINDOWS_ESIGNER_CREDENTIAL_ID` and
`WINDOWS_ESIGNER_TOTP_SECRET` as organisation secrets visible to
InstallerGenerator only (plus `WINDOWS_ESIGNER_ENVIRONMENT=TEST` with
`--sandbox`).

### What CI does with them

Signing runs only when a build asks for it (`sign_windows: true`) and all four
secrets exist. The nightly build-all never asks, so it cannot spend the yearly
signings; Polygraph's release job asks for every release tag. When signing is
on:

- every PE file in the Windows artefacts is signed before validation and
  packaging (files that already carry a valid signature are left alone);
- NSIS signs the installer and the uninstaller it writes (`!finalize` and
  `!uninstfinalize`, which need NSIS 3.08 or newer);
- the smoke test installs the result and fails the build if the installer, the
  uninstaller or any installed binary is unsigned.

Without signing the build is unchanged apart from a warning that Smart App
Control will block the plugins.
