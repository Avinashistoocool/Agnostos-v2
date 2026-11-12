# Building the Agnostos desktop app

Agnostos is available as a native Windows desktop app. The app has these parts:

- a Tauri 2 shell (`app/src-tauri`, Rust)
- a React UI (`app/src`)
- the Python engine (`desktop_engine`). The build freezes the engine into `agnostos-engine.exe` and bundles it as a Tauri **sidecar**.

Nothing is hosted, and the app does not run in a browser. The shell communicates with the
engine over stdin/stdout, as [engine-protocol.md](engine-protocol.md) describes.

## Prerequisites (Windows 10/11 x64)

| Tool | Notes |
|---|---|
| Visual Studio Build Tools (C++ workload, Windows SDK) | MSVC linker for Rust |
| Rust (stable, MSVC) | `winget install Rustlang.Rustup`, then `rustup default stable-msvc` |
| Node.js 20+ and npm | `cd app; npm install` (installs `@tauri-apps/cli`) |
| Python 3.11+ | Engine. Release builds use PyInstaller |
| WebView2 runtime | Windows 11 already has it. If it is missing, the installer downloads it |

The first `tauri build` downloads NSIS and WiX automatically into the Tauri cache.

## Dev workflow

In dev mode, the shell runs the engine directly from the source. Set the environment variable only in the
shell that starts Tauri:

```powershell
cd app
$env:AGNOSTOS_ENGINE_CMD = "python -m desktop_engine"   # run with cwd = repo root
# optional: $env:AGNOSTOS_ENGINE_CWD = "C:\path\to\repo"  (default: the repo containing app/)
npm run tauri dev                                        # starts Vite on :1420 + the Rust shell
```

- To test the shell without the real engine, use `$env:AGNOSTOS_ENGINE_CMD = "python tests\fake_engine.py"`.
- If `AGNOSTOS_ENGINE_CMD` is not set, the shell starts the bundled sidecar
  `binaries/agnostos-engine-x86_64-pc-windows-msvc.exe`. For dev builds, if that file is missing, `build.rs` makes an empty
  placeholder there. Thus, the sidecar does not start, and calls fail with `unavailable`.
- Engine stderr and shell diagnostics go to `%LOCALAPPDATA%\app.agnostos.desktop\logs\engine.log`.
  The file rotates at 2 MB and keeps `engine.1..3.log`.
- Rust tests: `cd app\src-tauri; cargo test`. These tests examine the protocol parser and router. They also do a
  round trip through `tests\fake_engine.py`.

## Release build

```powershell
.\build-engine.ps1                 # PyInstaller -> app\src-tauri\binaries\agnostos-engine-x86_64-pc-windows-msvc.exe
cd app
npm run tauri build                # runs `npm run build` (Vite -> app/dist), compiles Rust, bundles
```

A release build fails early if the sidecar exe is missing, or if it is the empty dev placeholder.

The outputs are in `app\src-tauri\target\release\bundle\`:

| File | Notes |
|---|---|
| `nsis\Agnostos_<ver>_x64-setup.exe` | Installation for one user (no admin necessary). Recommended download |
| `msi\Agnostos_<ver>_x64_en-US.msi` | MSI for each machine, for managed or enterprise installations |

Each bundle is about 11 MB plus the size of the engine. The app version comes from
`app/src-tauri/tauri.conf.json` (`version`) and `Cargo.toml`. When you make a release, keep the two values the same as
`outreach/__init__.py` (`__version__`, at this time 2.2.0).

## Code signing

The builds are not signed. Thus, SmartScreen shows a warning ("Windows protected your PC"). To sign them, set
`bundle.windows.certificateThumbprint` (with `digestAlgorithm: "sha256"` and a `timestampUrl`) in
`tauri.conf.json`. Alternatively, use `bundle.windows.signCommand` for Azure Trusted Signing or a cloud HSM.
Sign `agnostos-engine.exe` **before** you bundle it, because Tauri signs only the main exe and the installers.

## Auto-update

Auto-update is not enabled. To add it, use `tauri-plugin-updater`:

1. Make a key pair with `npx tauri signer generate`.
2. Set `bundle.createUpdaterArtifacts: true`.
3. Set `plugins.updater.pubkey` and `endpoints` (for example, a `latest.json` on GitHub Releases).
4. Sign the release builds with `TAURI_SIGNING_PRIVATE_KEY`.

Until then, users update when they run the new installer. The installer upgrades in place, and it keeps the
data of each user in `%LOCALAPPDATA%\Agnostos`.
