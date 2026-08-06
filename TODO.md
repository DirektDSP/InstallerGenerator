# TODO — macOS signing + notarization

Tracking the remaining work on `feat/macos-signing-notarization` (PR #6).

**Status as of 2026-08-06:** branch rebased onto `main` (head `ae289cf`, 0 behind /
1 ahead), force-pushed, PR `MERGEABLE`, `tools/selftest.py` passing including
main's embargo suite. The CI half is implemented and gated — with no secrets set
the pipeline builds unsigned `.pkg`s exactly as before, and each tier switches on
as its secrets land. What remains is the Apple-account half plus four code gaps
found in review.

See [`docs/SIGNING.md`](docs/SIGNING.md) for the full walkthrough of the manual steps.

---

## Summary

| ID | Task | Effort | After | Status |
|---|---|---|---|---|
| — | Rebase onto main, resolve embargo overlap, force-push PR #6 | — | — | done |
| A1 | Apple Developer Program membership confirmed | — | — | done |
| B8 | Verify `CHASM_CONFIG_B64` org secret name | 5m | — | ready |
| D12 | `-f` guard on `MACOS_ENTITLEMENTS` | 30m | — | ready |
| D13 | Notary all-or-nothing gate | 30m | — | ready |
| D14 | Widen `sign_bundle` nested find | 30m | — | ready |
| D15 | Selftest: assert entitlements staged | 30m | — | ready |
| A2 | Developer ID **Application** cert | 15m | A1 | needs Apple login |
| A3 | Developer ID **Installer** cert | 15m | A1 | needs Apple login |
| A5 | App Store Connect API key (`.p8`) | 15m | A1 | needs Apple login |
| A4 | Export both `.p12` with private keys | 15m | A2, A3 | needs Apple login |
| B6 | 10 organization secrets | 30m | A4, A5 | blocked |
| B7 | Mirror into sops `org.yaml` | 15m | B6 | blocked |
| C9 | Staged rollout: fuzzboy → standalone → chasm | ~3h | B6 | blocked |
| C11 | Quarantined download test on a clean Mac | 30m | C9 | blocked |
| E16 | Windows / NSIS signing | — | — | deferred |

Critical path from the start of the Apple session ≈ 5h, most of it CI waiting.
D12–D15 should land before C9 so validation exercises the fixed code.

---

## Ready now — no Apple dependency

- [ ] **B8 · Verify `CHASM_CONFIG_B64` exists as an org secret under that exact
      name.** The rename from `CONFIG_JSON_B64` survived the rebase, and
      `secrets: inherit` deleted the old explicit per-plugin mapping in
      `build-all.yml`. `build-plugin.yml` falls back to
      `secrets[needs.manifest.outputs.config_secret]`, so a wrong name means
      chasm's Moonbase config injection fails silently.

- [ ] **D12 · Add an existence check to the entitlements guard.**
      `templates/macos/build_pkg.sh:85` tests `MACOS_ENTITLEMENTS` for
      non-emptiness but not that the file exists, while
      `.github/workflows/build-plugin.yml:745` sets the path unconditionally. A
      plugin repo with a stale vendored `packaging/` fails `codesign` with a
      confusing error. Use `-f`.

- [ ] **D13 · Make the notarization gate all-or-nothing.** `build_pkg.sh`
      notarizes only when all three `NOTARY_*` vars are set, but the smoke test
      hard-fails on `MACOS_NOTARY_KEY_P8 != ''` alone. Setting `KEY_P8` without
      `KEY_ID` / `ISSUER_ID` silently skips notarization and then fails
      `stapler validate`. Loud, but misleading — check the three together.

- [ ] **D14 · Widen (or document) the nested-bundle signing find.**
      `sign_bundle` only finds `*.framework`, `*.dylib`, `*.so`. Correct for the
      current JUCE bundles; a future helper executable or nested `.app` would go
      unsigned and fail notarization for the whole submission.

- [ ] **D15 · Assert the entitlements file is staged.** `tools/selftest.py` has
      no check that `render_installer.py` writes
      `packaging/macos/standalone.entitlements`.

## Apple account — manual, needs an Apple login

- [x] **A1 · Confirm paid Apple Developer Program membership.** Note the Team ID.
- [ ] **A2 · Create the Developer ID _Application_ certificate.** Signs `.vst3`,
      `.component`, `.clap`, `.app`.
- [ ] **A3 · Create the Developer ID _Installer_ certificate.** Signs the `.pkg`.
      Not interchangeable with A2 — both are required.
- [ ] **A5 · Create an App Store Connect API key**, Team Keys, role Developer.
      The `.p8` downloads **exactly once** — back it up before leaving the page.
      Record the Issuer ID and the Key ID.
- [ ] **A4 · Export both certificates as `.p12` with their private keys.**
      Keychain Access → **My Certificates** (not *Certificates* — that category
      exports the cert without its key). Use strong export passwords.

## Secrets wiring

- [ ] **B6 · Add ten organization secrets.** Organization level, not repo level —
      `build-all.yml` uses `secrets: inherit`, so repo-level secrets will not fan
      out to the called workflow. Grant access to every plugin repo.

      | Secret | Value |
      |---|---|
      | `MACOS_CERT_APPLICATION_P12` | base64 of `DeveloperIDApplication.p12` |
      | `MACOS_CERT_APPLICATION_PASSWORD` | its export password |
      | `MACOS_CERT_INSTALLER_P12` | base64 of `DeveloperIDInstaller.p12` |
      | `MACOS_CERT_INSTALLER_PASSWORD` | its export password |
      | `MACOS_SIGN_IDENTITY_APP` | `Developer ID Application: Name (TEAMID)` |
      | `MACOS_INSTALLER_SIGN_IDENTITY` | `Developer ID Installer: Name (TEAMID)` |
      | `MACOS_NOTARY_ISSUER_ID` | issuer UUID |
      | `MACOS_NOTARY_KEY_ID` | 10-character key ID |
      | `MACOS_NOTARY_KEY_P8` | base64 of the `.p8` |
      | `MACOS_KEYCHAIN_PASSWORD` | any random string (`openssl rand -base64 24`) |

- [ ] **B7 · Mirror the same values into `secrets/org.yaml`** in the `secrets`
      repo (sops + age), which is the source of truth for what the org secrets
      should contain.

## Validation — after B6

The three tiers are independently gated, so each can be verified on its own:

| Secrets present | Expected result |
|---|---|
| none | unsigned pkg, warning in the log |
| `MACOS_CERT_APPLICATION_P12` + `MACOS_SIGN_IDENTITY_APP` + `MACOS_KEYCHAIN_PASSWORD` | bundles signed, pkg unsigned |
| + `MACOS_CERT_INSTALLER_P12` + `MACOS_INSTALLER_SIGN_IDENTITY` | pkg signed, `pkgutil` becomes a hard gate |
| + the three `MACOS_NOTARY_*` | notarized + stapled, `stapler validate` and `spctl` become hard gates |

- [ ] **C9 · Staged `workflow_dispatch` rollout at `level: full`,** one plugin at
      a time, in this order:
      1. **fuzzboy** — free, no Moonbase config, so a failure isolates signing
         from secret injection
      2. a **Standalone-bearing** plugin — exercises `standalone.entitlements`
         and the hardened-runtime audio-input entitlement
      3. **chasm** — no Standalone target, exercises the format-adaptive path

- [ ] **C11 · Download a built `.pkg` on a clean Mac via a browser** and confirm
      it installs with no Gatekeeper prompt. CI's `spctl` check does not prove
      this — only a download that carries the quarantine bit does.

## Deferred

- [ ] **E16 · Windows / NSIS installer signing.** Still unsigned, so SmartScreen
      shows *"Windows protected your PC"* until the binary builds reputation.
      Azure Trusted Signing (~$10/month, no hardware token) is the cheap option
      but requires a verified organisation or three years of individual trading
      history. Traditional OV/EV certificates run $200–600/year and EV needs a
      hardware token, which does not work on hosted CI runners.
