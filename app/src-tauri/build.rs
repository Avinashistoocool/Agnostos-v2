use std::path::Path;

fn main() {
    // tauri-build requires every externalBin to exist. Dev builds (AGNOSTOS_ENGINE_CMD) get an
    // empty placeholder; release builds refuse to bundle a missing/placeholder engine.
    let target = std::env::var("TARGET").unwrap_or_default();
    let sidecar = format!("binaries/agnostos-engine-{target}.exe");
    let path = Path::new(&sidecar);
    let release = std::env::var("PROFILE").as_deref() == Ok("release");
    let size = std::fs::metadata(path).map(|m| m.len()).unwrap_or(0);
    if size == 0 {
        if release {
            panic!("{sidecar} is missing or empty: run build-engine.ps1 before `npm run tauri build`");
        }
        let _ = std::fs::create_dir_all("binaries");
        let _ = std::fs::write(path, b"");
        println!("cargo:warning={sidecar} not found; using an empty dev placeholder (set AGNOSTOS_ENGINE_CMD)");
    }
    println!("cargo:rerun-if-changed={sidecar}");
    tauri_build::build()
}