//! Size-rotated log file for engine stderr (`<app log dir>/engine.log`, keeps engine.1..3.log).

use std::fs::{self, File, OpenOptions};
use std::io::Write;
use std::path::PathBuf;
use std::sync::Mutex;
use std::time::{SystemTime, UNIX_EPOCH};

const MAX_BYTES: u64 = 2 * 1024 * 1024;
const KEEP: u32 = 3;

#[derive(Default)]
pub struct RotatingLog {
    dir: Option<PathBuf>,
    state: Mutex<Option<(File, u64)>>,
}

impl RotatingLog {
    pub fn new(dir: Option<PathBuf>) -> Self {
        Self { dir, state: Mutex::new(None) }
    }

    fn path(&self, n: u32) -> Option<PathBuf> {
        let name = if n == 0 { "engine.log".to_string() } else { format!("engine.{n}.log") };
        self.dir.as_ref().map(|d| d.join(name))
    }

    fn open(&self) -> Option<(File, u64)> {
        let path = self.path(0)?;
        fs::create_dir_all(path.parent()?).ok()?;
        let file = OpenOptions::new().create(true).append(true).open(&path).ok()?;
        let size = file.metadata().map(|m| m.len()).unwrap_or(0);
        Some((file, size))
    }

    fn rotate(&self) {
        for n in (1..KEEP).rev() {
            if let (Some(from), Some(to)) = (self.path(n), self.path(n + 1)) {
                let _ = fs::rename(from, to);
            }
        }
        if let (Some(from), Some(to)) = (self.path(0), self.path(1)) {
            let _ = fs::rename(from, to);
        }
    }

    pub fn line(&self, text: &str) {
        if self.dir.is_none() {
            eprintln!("{text}");
            return;
        }
        let mut state = self.state.lock().unwrap();
        if state.as_ref().map_or(false, |(_, size)| *size >= MAX_BYTES) {
            *state = None;
            self.rotate();
        }
        if state.is_none() {
            *state = self.open();
        }
        if let Some((file, size)) = state.as_mut() {
            let secs = SystemTime::now().duration_since(UNIX_EPOCH).map(|d| d.as_secs()).unwrap_or(0);
            let entry = format!("{secs} {text}\n");
            if file.write_all(entry.as_bytes()).is_ok() {
                *size += entry.len() as u64;
            }
        }
    }
}
