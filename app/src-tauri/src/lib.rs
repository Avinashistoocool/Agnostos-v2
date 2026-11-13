mod log;
pub mod protocol;

use protocol::{Incoming, LineBuffer, Router};
use serde_json::{json, Value};
use std::io::{BufRead, BufReader, Read, Write};
use std::path::PathBuf;
use std::process::{Child, ChildStdin, Command, Stdio};
use std::sync::{Arc, Mutex};
use tauri::{AppHandle, Emitter, Manager, RunEvent, State, WindowEvent};
use tauri_plugin_shell::process::{CommandChild, CommandEvent};
use tauri_plugin_shell::ShellExt;

pub const EVENT_NAME: &str = "engine://event";
const SIDECAR_NAME: &str = "agnostos-engine";
const DEV_CMD_ENV: &str = "AGNOSTOS_ENGINE_CMD";
const DEV_CWD_ENV: &str = "AGNOSTOS_ENGINE_CWD";

enum ChildHandle {
    Sidecar(CommandChild),
    Dev { child: Child, stdin: ChildStdin },
}

impl ChildHandle {
    fn write_line(&mut self, line: &str) -> Result<(), String> {
        match self {
            ChildHandle::Sidecar(c) => c.write(line.as_bytes()).map_err(|e| e.to_string()),
            ChildHandle::Dev { stdin, .. } => stdin
                .write_all(line.as_bytes())
                .and_then(|_| stdin.flush())
                .map_err(|e| e.to_string()),
        }
    }

    fn kill(self) {
        match self {
            ChildHandle::Sidecar(c) => {
                let _ = c.kill();
            }
            ChildHandle::Dev { mut child, stdin } => {
                drop(stdin);
                let _ = child.kill();
                let _ = child.wait();
            }
        }
    }
}

#[derive(Default)]
struct Inner {
    child: Option<ChildHandle>,
    generation: u64,
}

#[derive(Clone, Default)]
pub struct Engine {
    inner: Arc<Mutex<Inner>>,
    router: Arc<Mutex<Router>>,
    log: Arc<log::RotatingLog>,
}

impl Engine {
    fn new(log_dir: Option<PathBuf>) -> Self {
        Self { log: Arc::new(log::RotatingLog::new(log_dir)), ..Default::default() }
    }

    fn handle_stdout_line(&self, app: &AppHandle, line: &str) {
        match protocol::parse_line(line) {
            Incoming::Response { id, reply } => {
                if !self.router.lock().unwrap().resolve(id, reply) {
                    self.log.line(&format!("[shell] response for unknown/expired id {id}"));
                }
            }
            Incoming::Event(payload) => {
                let _ = app.emit(EVENT_NAME, payload);
            }
            Incoming::Invalid(raw) if raw.is_empty() => {}
            Incoming::Invalid(raw) => self.log.line(&format!("[stdout] {raw}")),
        }
    }

    fn on_terminated(&self, app: &AppHandle, generation: u64, code: Option<i32>) {
        let mut inner = self.inner.lock().unwrap();
        if inner.generation != generation {
            return;
        }
        if let Some(ChildHandle::Dev { mut child, .. }) = inner.child.take() {
            let _ = child.wait();
        }
        drop(inner);
        self.log.line(&format!("[shell] engine exited (code {code:?})"));
        self.router
            .lock()
            .unwrap()
            .fail_all(protocol::unavailable("The engine process exited"));
        let _ = app.emit(EVENT_NAME, json!({ "event": "engine.exited", "data": { "code": code } }));
    }

    fn start(&self, app: &AppHandle) -> Result<(), String> {
        let mut inner = self.inner.lock().unwrap();
        if let Some(old) = inner.child.take() {
            old.kill();
        }
        inner.generation += 1;
        let generation = inner.generation;
        self.router
            .lock()
            .unwrap()
            .fail_all(protocol::unavailable("The engine was restarted"));

        let handle = match std::env::var(DEV_CMD_ENV).ok().filter(|s| !s.trim().is_empty()) {
            Some(cmd) => self.spawn_dev(app, &cmd, generation)?,
            None => self.spawn_sidecar(app, generation)?,
        };
        inner.child = Some(handle);
        Ok(())
    }

    fn spawn_sidecar(&self, app: &AppHandle, generation: u64) -> Result<ChildHandle, String> {
        let (mut rx, child) = app
            .shell()
            .sidecar(SIDECAR_NAME)
            .map_err(|e| e.to_string())?
            .env("PYTHONIOENCODING", "utf-8")
            .env("PYTHONUNBUFFERED", "1")
            .set_raw_out(true)
            .spawn()
            .map_err(|e| format!("could not start {SIDECAR_NAME}: {e}"))?;
        self.log.line(&format!("[shell] started sidecar pid {}", child.pid()));
        let engine = self.clone();
        let app = app.clone();
        tauri::async_runtime::spawn(async move {
            let mut out = LineBuffer::default();
            let mut err = LineBuffer::default();
            let mut code = None;
            while let Some(event) = rx.recv().await {
                match event {
                    CommandEvent::Stdout(bytes) => {
                        for line in out.push(&bytes) {
                            engine.handle_stdout_line(&app, &line);
                        }
                    }
                    CommandEvent::Stderr(bytes) => {
                        for line in err.push(&bytes) {
                            engine.log.line(&line);
                        }
                    }
                    CommandEvent::Error(e) => engine.log.line(&format!("[shell] {e}")),
                    CommandEvent::Terminated(payload) => {
                        code = payload.code;
                        break;
                    }
                    _ => {}
                }
            }
            if let Some(line) = out.finish() {
                engine.handle_stdout_line(&app, &line);
            }
            if let Some(line) = err.finish() {
                engine.log.line(&line);
            }
            engine.on_terminated(&app, generation, code);
        });
        Ok(ChildHandle::Sidecar(child))
    }

    fn spawn_dev(&self, app: &AppHandle, cmdline: &str, generation: u64) -> Result<ChildHandle, String> {
        let parts = protocol::split_command(cmdline);
        let (program, args) = parts.split_first().ok_or("AGNOSTOS_ENGINE_CMD is empty")?;
        let cwd = std::env::var(DEV_CWD_ENV).map(PathBuf::from).unwrap_or_else(|_| default_dev_cwd());
        let mut cmd = Command::new(program);
        cmd.args(args)
            .current_dir(&cwd)
            .env("PYTHONIOENCODING", "utf-8")
            .env("PYTHONUNBUFFERED", "1")
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped());
        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            const CREATE_NO_WINDOW: u32 = 0x0800_0000;
            cmd.creation_flags(CREATE_NO_WINDOW);
        }
        let mut child = cmd
            .spawn()
            .map_err(|e| format!("could not start `{cmdline}` in {}: {e}", cwd.display()))?;
        self.log.line(&format!(
            "[shell] started dev engine `{cmdline}` (cwd {}) pid {}",
            cwd.display(),
            child.id()
        ));
        let stdin = child.stdin.take().ok_or("no stdin")?;
        let stdout = child.stdout.take().ok_or("no stdout")?;
        let stderr = child.stderr.take().ok_or("no stderr")?;

        let log = self.log.clone();
        std::thread::spawn(move || {
            let mut reader = BufReader::new(stderr);
            let mut buf = Vec::new();
            while matches!(reader.read_until(b'\n', &mut buf), Ok(n) if n > 0) {
                let line = String::from_utf8_lossy(&buf);
                log.line(line.trim_end_matches(['\r', '\n']));
                buf.clear();
            }
        });

        let engine = self.clone();
        let app = app.clone();
        std::thread::spawn(move || {
            let mut stdout = stdout;
            let mut lines = LineBuffer::default();
            let mut chunk = [0u8; 8192];
            loop {
                match stdout.read(&mut chunk) {
                    Ok(0) | Err(_) => break,
                    Ok(n) => {
                        for line in lines.push(&chunk[..n]) {
                            engine.handle_stdout_line(&app, &line);
                        }
                    }
                }
            }
            if let Some(line) = lines.finish() {
                engine.handle_stdout_line(&app, &line);
            }
            engine.on_terminated(&app, generation, None);
        });
        Ok(ChildHandle::Dev { child, stdin })
    }

    fn stop(&self) {
        let mut inner = self.inner.lock().unwrap();
        inner.generation += 1;
        if let Some(child) = inner.child.take() {
            child.kill();
            self.log.line("[shell] engine stopped");
        }
        drop(inner);
        self.router
            .lock()
            .unwrap()
            .fail_all(protocol::unavailable("The engine was stopped"));
    }

    async fn call(&self, method: String, params: Value) -> Result<Value, Value> {
        let (id, rx) = {
            let mut inner = self.inner.lock().unwrap();
            let Some(child) = inner.child.as_mut() else {
                return Err(protocol::unavailable("The engine is not running"));
            };
            let (id, rx) = self.router.lock().unwrap().register();
            if let Err(e) = child.write_line(&protocol::encode_request(id, &method, &params)) {
                self.router.lock().unwrap().cancel(id);
                return Err(protocol::unavailable(format!("Could not reach the engine: {e}")));
            }
            (id, rx)
        };
        let limit = protocol::timeout_for(&method);
        match tokio::time::timeout(limit, rx).await {
            Ok(Ok(reply)) => reply,
            Ok(Err(_)) => Err(protocol::unavailable("The engine closed the request")),
            Err(_) => {
                self.router.lock().unwrap().cancel(id);
                Err(protocol::unavailable(format!(
                    "The engine did not answer {method} within {}s",
                    limit.as_secs()
                )))
            }
        }
    }
}

fn default_dev_cwd() -> PathBuf {
    // Dev runs only: release binaries must not embed the build machine's path.
    #[cfg(debug_assertions)]
    let repo = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("..").join("..");
    #[cfg(not(debug_assertions))]
    let repo = std::env::current_dir().unwrap_or_default();
    if repo.join("outreach").is_dir() {
        match repo.canonicalize() {
            Ok(p) => PathBuf::from(p.to_string_lossy().trim_start_matches(r"\\?\")),
            Err(_) => repo,
        }
    } else {
        std::env::current_dir().unwrap_or_default()
    }
}

#[tauri::command]
async fn engine_call(
    engine: State<'_, Engine>,
    method: String,
    params: Option<Value>,
) -> Result<Value, Value> {
    let engine = engine.inner().clone();
    engine.call(method, params.unwrap_or(Value::Null)).await
}

#[tauri::command]
async fn engine_restart(app: AppHandle, engine: State<'_, Engine>) -> Result<(), Value> {
    let engine = engine.inner().clone();
    tauri::async_runtime::spawn_blocking(move || engine.start(&app))
        .await
        .map_err(|e| protocol::engine_error("internal", e.to_string()))?
        .map_err(protocol::unavailable)
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            if let Some(w) = app.get_webview_window("main") {
                let _ = w.unminimize();
                let _ = w.show();
                let _ = w.set_focus();
            }
        }))
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_opener::init())
        .invoke_handler(tauri::generate_handler![engine_call, engine_restart])
        .setup(|app| {
            let engine = Engine::new(app.path().app_log_dir().ok());
            if let Err(e) = engine.start(app.handle()) {
                engine.log.line(&format!("[shell] {e}"));
                eprintln!("agnostos: {e}");
            }
            app.manage(engine);
            Ok(())
        })
        .on_window_event(|window, event| {
            if matches!(event, WindowEvent::CloseRequested { .. } | WindowEvent::Destroyed)
                && window.label() == "main"
            {
                if let Some(engine) = window.try_state::<Engine>() {
                    engine.stop();
                }
            }
        })
        .build(tauri::generate_context!())
        .expect("error while building Agnostos");

    app.run(|handle, event| {
        if matches!(event, RunEvent::Exit | RunEvent::ExitRequested { .. }) {
            if let Some(engine) = handle.try_state::<Engine>() {
                engine.stop();
            }
        }
    });
}
