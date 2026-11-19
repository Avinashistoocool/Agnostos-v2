# Building the Agnostos desktop app

Agnostos ships as a native Windows desktop app: a Tauri 2 shell (`app/src-tauri`, Rust), a React UI
(`app/src`) and the Python engine (`desktop_engine`), which is frozen into `agnostos-engine.exe` and
bundled as a Tauri **sidecar**. Nothing is hosted, and the app does not run in a browser. The shell talks to the
engine over stdin/stdout as described in [engine-protocol.md](engine-protocol.md).

## Prerequisites (Windows 10/11 x64)

| Tool | Notes |
|---|---|
| Visual Studio Build Tools (C++ workload, Windows SDK) | MSVC linker for Rust |
| Rust (stable, MSVC) | `winget install Rustlang.Rustup`, then `rustup default stable-msvc` |
| Node.js 20+ and npm | `cd app; npm install` (pulls `@tauri-apps/cli`) |
| Python 3.11+ | Engine. PyInstaller is used for release builds |
| WebView2 runtime | Already present on Windows 11. The installer downloads it if missing |

The first `tauri build` downloads NSIS and WiX automatically into the Tauri cache.

## Dev workflow

In dev mode the shell runs the engine straight from source. The env var only needs to be set in the
shell that launches Tauri:

```powershell
cd app
$env:AGNOSTOS_ENGINE_CMD = "python -m desktop_engine"   # run with cwd = repo root
# optional: $env:AGNOSTOS_ENGINE_CWD = "C:\path\to\repo"  (default: the repo containing app/)
npm run tauri dev                                        # starts Vite on :1420 + the Rust shell
```

- To test the shell without the real engine, use `$env:AGNOSTOS_ENGINE_CMD = "python tests\fake_engine.py"`.
- If `AGNOSTOS_ENGINE_CMD` is not set, the shell starts the bundled sidecar
  `binaries/agnostos-engine-x86_64-pc-windows-msvc.exe`. For dev builds `build.rs` creates an empty
  placeholder there if it is missing, so the sidecar fails to start and calls reject with `unavailable`.
- Engine stderr and shell diagnostics go to `%LOCALAPPDATA%\app.agnostos.desktop\logs\engine.log`.
  The file rotates at 2 MB and keeps `engine.1..3.log`.
- Rust tests: `cd app\src-tauri; cargo test`. These cover the protocol parser and router, plus a
  round trip through `tests\fake_engine.py`.

## Release build

```powershell
.\build-app.ps1                    # engine + Tauri release build with build-machine paths remapped
```

or step by step:

```powershell
.\build-engine.ps1                 # PyInstaller -> app\src-tauri\binaries\agnostos-engine-x86_64-pc-windows-msvc.exe
cd app
npm run tauri build                # runs `npm run build` (Vite -> app/dist), compiles Rust, bundles
```

A release build fails early if the sidecar exe is missing or is the empty dev placeholder.

Outputs, under `app\src-tauri\target\release\bundle\`:

| File | Notes |
|---|---|
| `nsis\Agnostos_<ver>_x64-setup.exe` | Per-user install (no admin needed). Recommended download |
| `msi\Agnostos_<ver>_x64_en-US.msi` | Per-machine MSI for managed or enterprise installs |

Each bundle is about 11 MB plus the size of the engine. The app version comes from
`app/src-tauri/tauri.conf.json` (`version`) and `Cargo.toml`. Keep both in sync with
`outreach/__init__.py` (`__version__`, currently 2.3.0) when you release.

## Publishing a download

1. Package the installer with docs: `Agnostos-<ver>-Windows-Setup.zip` containing the setup `.exe`, `packaging/windows/README.md`, `USAGE.md` and `LICENSE`.
2. Tag the release (`git tag v<ver>`; push the tag) and create a GitHub Release with the ZIP attached. The README's **Download** link points at `releases/latest`.

## macOS build

Run `./build-mac.sh` on a Mac with the Xcode Command Line Tools, Python 3.12+, Node 20+ and Rust. It freezes the engine for the host target triple (`agnostos-engine-aarch64-apple-darwin` or `-x86_64-apple-darwin`), copies it into `app/src-tauri/binaries/`, and runs `tauri build`. `tauri.macos.conf.json` switches the bundle targets to `app` and `dmg`. The output is `bundle/dmg/Agnostos_<ver>_<arch>.dmg`. It is unsigned: the first time, right-click the app and choose **Open**. On macOS the engine keeps data in `~/Library/Application Support/Agnostos` and stores tokens in the login Keychain (service `Agnostos`). See `packaging/macos/README.md`.

## Code signing

Builds are unsigned, so SmartScreen will warn ("Windows protected your PC"). To sign them, set
`bundle.windows.certificateThumbprint` (with `digestAlgorithm: "sha256"` and a `timestampUrl`) in
`tauri.conf.json`, or use `bundle.windows.signCommand` for Azure Trusted Signing or a cloud HSM.
Sign `agnostos-engine.exe` **before** bundling, because Tauri only signs the main exe and the installers.

## Auto-update

Auto-update is not enabled. To add it, use `tauri-plugin-updater`: generate a key pair with
`npx tauri signer generate`, set `bundle.createUpdaterArtifacts: true`, and set
`plugins.updater.pubkey` and `endpoints` (for example a `latest.json` on GitHub Releases). Then sign
release builds with `TAURI_SIGNING_PRIVATE_KEY`. Until then, users update by running the new
installer, which upgrades in place and keeps per-user data in `%LOCALAPPDATA%\Agnostos`.
