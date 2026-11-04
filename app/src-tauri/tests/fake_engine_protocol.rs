//! Drives tests/fake_engine.py through the pure protocol layer (skipped if Python is missing).

use agnostos_lib::protocol::{self, Incoming, LineBuffer, Router};
use serde_json::json;
use std::io::{Read, Write};
use std::path::PathBuf;
use std::process::{Command, Stdio};

fn python() -> Option<String> {
    let candidates = std::env::var("PYTHON").into_iter().chain(["python".into(), "python3".into()]);
    candidates.into_iter().find(|p| {
        Command::new(p)
            .arg("--version")
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .status()
            .map(|s| s.success())
            .unwrap_or(false)
    })
}

#[test]
fn round_trip_with_fake_engine() {
    let Some(py) = python() else {
        eprintln!("python not found; skipping");
        return;
    };
    let script = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../tests/fake_engine.py");
    let mut child = Command::new(py)
        .arg(script)
        .env("PYTHONIOENCODING", "utf-8")
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .spawn()
        .expect("spawn fake engine");
    let mut stdin = child.stdin.take().unwrap();
    let mut router = Router::new();
    let (id_info, mut rx_info) = router.register();
    let (id_echo, mut rx_echo) = router.register();
    let (id_bad, mut rx_bad) = router.register();
    stdin.write_all(protocol::encode_request(id_info, "app.info", &json!(null)).as_bytes()).unwrap();
    stdin
        .write_all(protocol::encode_request(id_echo, "echo", &json!({"x": "café"})).as_bytes())
        .unwrap();
    stdin.write_all(protocol::encode_request(id_bad, "nope", &json!({})).as_bytes()).unwrap();
    drop(stdin);

    let mut raw = Vec::new();
    child.stdout.take().unwrap().read_to_end(&mut raw).unwrap();
    child.wait().unwrap();

    let mut lb = LineBuffer::default();
    let mut events = Vec::new();
    // Feed in small chunks to exercise reassembly.
    for chunk in raw.chunks(5) {
        for line in lb.push(chunk) {
            match protocol::parse_line(&line) {
                Incoming::Response { id, reply } => assert!(router.resolve(id, reply)),
                Incoming::Event(e) => events.push(e),
                Incoming::Invalid(l) => assert!(l.is_empty(), "unexpected line {l}"),
            }
        }
    }
    assert_eq!(router.pending_count(), 0);
    assert_eq!(rx_info.try_recv().unwrap().unwrap()["engine_version"], "fake-1");
    assert_eq!(rx_echo.try_recv().unwrap().unwrap(), json!({"x": "café"}));
    assert_eq!(rx_bad.try_recv().unwrap().unwrap_err()["code"], "not_found");
    assert_eq!(events, vec![json!({"event": "fake.echo", "data": {"x": "café"}})]);
}
