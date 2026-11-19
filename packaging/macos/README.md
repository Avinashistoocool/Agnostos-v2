# Agnostos for macOS - 2.3.0 beta

macOS installers have to be built on a Mac; they cannot be cross-compiled from Windows.

## Build (once, on any Mac)

1. Install the Xcode Command Line Tools (`xcode-select --install`), Python 3.12+, Node 20+ and Rust (`https://rustup.rs`).
2. Copy the repository to the Mac (a ZIP is fine) and run:

   ```
   chmod +x build-mac.sh
   ./build-mac.sh
   ```

3. The output is `app/src-tauri/target/release/bundle/dmg/Agnostos_2.3.0_<arch>.dmg`. It is built for the Mac's own architecture: arm64 on Apple Silicon, x64 on Intel.

## Install

Open the `.dmg` and drag **Agnostos** to Applications. The build is unsigned, so the first time you open it, right-click the app, choose **Open**, then confirm.

## Differences from Windows

- App data lives in `~/Library/Application Support/Agnostos` instead of `%LOCALAPPDATA%\Agnostos`.
- Sign-in tokens are stored in the macOS login Keychain (service "Agnostos") instead of Windows DPAPI.
- Scheduled background sending uses Windows Task Scheduler on Windows. On a Mac, run jobs from the app. You can also use `launchd` or `cron` with `python -m outreach.cli ...`.

Every feature, policy and option in `../windows/USAGE.md` works the same way. That includes discovery with the funding factor and company search, senior-researcher (legacy) letters, replies, coordinators and programme reminders.
