#!/usr/bin/env bash
# macOS release build: frozen engine sidecar + Tauri .app/.dmg.
# Run on a Mac with Xcode Command Line Tools, Python 3.12+, Node 20+ and Rust installed:
#   ./build-mac.sh            # native architecture
# Output: app/src-tauri/target/release/bundle/dmg/Agnostos_<version>_<arch>.dmg
set -euo pipefail
cd "$(dirname "$0")"

PY="${PYTHON:-python3}"
"$PY" -m pip install --quiet "pyinstaller>=6.10" -r requirements.txt \
    google-api-python-client google-auth-oauthlib

"$PY" -m PyInstaller --noconfirm --clean --distpath dist/engine --workpath build/engine-pyi \
    desktop_engine/agnostos-engine.spec

exe=dist/engine/agnostos-engine
probe=$(echo '{"id":1,"method":"ping","params":{}}' | "$exe" 2>/dev/null || true)
echo "$probe" | grep -q '"ok":true' || { echo "Engine smoke test failed: $probe"; exit 1; }

triple=$(rustc -vV | sed -n 's/^host: //p')
mkdir -p app/src-tauri/binaries
cp "$exe" "app/src-tauri/binaries/agnostos-engine-$triple"
chmod +x "app/src-tauri/binaries/agnostos-engine-$triple"

export RUSTFLAGS="${RUSTFLAGS:-} --remap-path-prefix=$PWD=agnostos --remap-path-prefix=$HOME=home"
cd app
[ -d node_modules ] || npm ci --no-audit --no-fund
npm run tauri build

find src-tauri/target/release/bundle -maxdepth 2 \( -name '*.dmg' -o -name '*.app' \) -print
