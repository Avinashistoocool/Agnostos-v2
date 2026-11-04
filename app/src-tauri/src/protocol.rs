//! Pure newline-delimited JSON protocol helpers (no Tauri runtime), see docs/engine-protocol.md.

use serde_json::{json, Map, Value};
use std::collections::HashMap;
use std::time::Duration;
use tokio::sync::oneshot;

pub const DEFAULT_TIMEOUT: Duration = Duration::from_secs(120);
pub const GOOGLE_AUTH_TIMEOUT: Duration = Duration::from_secs(330);

pub type Reply = Result<Value, Value>;

/// One parsed stdout line from the engine.
#[derive(Debug, Clone, PartialEq)]
pub enum Incoming {
    Response { id: u64, reply: Reply },
    /// Already shaped as the `engine://event` payload: `{event, data}`.
    Event(Value),
    Invalid(String),
}

pub fn engine_error(code: &str, message: impl Into<String>) -> Value {
    json!({ "code": code, "message": message.into() })
}

pub fn unavailable(message: impl Into<String>) -> Value {
    engine_error("unavailable", message)
}

pub fn timeout_for(method: &str) -> Duration {
    if method.starts_with("auth.google") {
        GOOGLE_AUTH_TIMEOUT
    } else {
        DEFAULT_TIMEOUT
    }
}

/// Encode a request as a single JSON line terminated by `\n`.
pub fn encode_request(id: u64, method: &str, params: &Value) -> String {
    let params = if params.is_null() { Value::Object(Map::new()) } else { params.clone() };
    let mut line = json!({ "id": id, "method": method, "params": params }).to_string();
    line.push('\n');
    line
}

fn normalize_error(err: &Value) -> Value {
    match err {
        Value::Object(map) => {
            let code = map.get("code").and_then(Value::as_str).unwrap_or("internal");
            let message = map
                .get("message")
                .and_then(Value::as_str)
                .unwrap_or("engine error");
            let mut out = map.clone();
            out.insert("code".into(), Value::String(code.into()));
            out.insert("message".into(), Value::String(message.into()));
            Value::Object(out)
        }
        Value::String(s) => engine_error("internal", s.clone()),
        other => engine_error("internal", other.to_string()),
    }
}

pub fn parse_line(line: &str) -> Incoming {
    let trimmed = line.trim_start_matches('\u{feff}').trim();
    if trimmed.is_empty() {
        return Incoming::Invalid(String::new());
    }
    let value: Value = match serde_json::from_str(trimmed) {
        Ok(v) => v,
        Err(_) => return Incoming::Invalid(trimmed.to_string()),
    };
    let Value::Object(obj) = &value else {
        return Incoming::Invalid(trimmed.to_string());
    };
    if let Some(event) = obj.get("event") {
        if obj.get("id").map_or(true, Value::is_null) {
            if let Some(name) = event.as_str() {
                let data = obj.get("data").cloned().unwrap_or(Value::Null);
                return Incoming::Event(json!({ "event": name, "data": data }));
            }
        }
    }
    if let Some(id) = obj.get("id").and_then(Value::as_u64) {
        if let Some(err) = obj.get("error").filter(|e| !e.is_null()) {
            return Incoming::Response { id, reply: Err(normalize_error(err)) };
        }
        if obj.contains_key("result") {
            let result = obj.get("result").cloned().unwrap_or(Value::Null);
            return Incoming::Response { id, reply: Ok(result) };
        }
    }
    Incoming::Invalid(trimmed.to_string())
}

/// Tracks in-flight requests (id -> oneshot sender).
#[derive(Default)]
pub struct Router {
    next_id: u64,
    pending: HashMap<u64, oneshot::Sender<Reply>>,
}

impl Router {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn register(&mut self) -> (u64, oneshot::Receiver<Reply>) {
        self.next_id += 1;
        let id = self.next_id;
        let (tx, rx) = oneshot::channel();
        self.pending.insert(id, tx);
        (id, rx)
    }

    pub fn cancel(&mut self, id: u64) -> bool {
        self.pending.remove(&id).is_some()
    }

    pub fn pending_count(&self) -> usize {
        self.pending.len()
    }

    /// Resolve a response. Returns false if no request with that id was waiting.
    pub fn resolve(&mut self, id: u64, reply: Reply) -> bool {
        match self.pending.remove(&id) {
            Some(tx) => {
                let _ = tx.send(reply);
                true
            }
            None => false,
        }
    }

    pub fn fail_all(&mut self, err: Value) {
        for (_, tx) in self.pending.drain() {
            let _ = tx.send(Err(err.clone()));
        }
    }
}

/// Splits an arbitrary byte stream into lines (handles `\n` and `\r\n`).
#[derive(Default)]
pub struct LineBuffer {
    buf: Vec<u8>,
}

impl LineBuffer {
    pub fn push(&mut self, chunk: &[u8]) -> Vec<String> {
        self.buf.extend_from_slice(chunk);
        let mut lines = Vec::new();
        while let Some(pos) = self.buf.iter().position(|b| *b == b'\n') {
            let mut line: Vec<u8> = self.buf.drain(..=pos).collect();
            line.pop();
            if line.last() == Some(&b'\r') {
                line.pop();
            }
            lines.push(String::from_utf8_lossy(&line).into_owned());
        }
        lines
    }

    pub fn finish(&mut self) -> Option<String> {
        if self.buf.is_empty() {
            return None;
        }
        let rest = std::mem::take(&mut self.buf);
        Some(String::from_utf8_lossy(&rest).trim_end_matches('\r').to_string())
    }
}

/// Split a dev command line such as `python -m desktop_engine` (supports "double quotes").
pub fn split_command(cmd: &str) -> Vec<String> {
    let mut out = Vec::new();
    let mut cur = String::new();
    let mut in_quotes = false;
    let mut has_token = false;
    for ch in cmd.chars() {
        match ch {
            '"' => {
                in_quotes = !in_quotes;
                has_token = true;
            }
            c if c.is_whitespace() && !in_quotes => {
                if has_token {
                    out.push(std::mem::take(&mut cur));
                    has_token = false;
                }
            }
            c => {
                cur.push(c);
                has_token = true;
            }
        }
    }
    if has_token {
        out.push(cur);
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn encodes_request_line() {
        let line = encode_request(7, "settings.get", &Value::Null);
        assert!(line.ends_with('\n'));
        let v: Value = serde_json::from_str(line.trim()).unwrap();
        assert_eq!(v, json!({"id": 7, "method": "settings.get", "params": {}}));
    }

    #[test]
    fn parses_result_error_event() {
        assert_eq!(
            parse_line("{\"id\": 7, \"result\": {\"a\": 1}}\r\n"),
            Incoming::Response { id: 7, reply: Ok(json!({"a": 1})) }
        );
        assert_eq!(
            parse_line(r#"{"id": 3, "result": null}"#),
            Incoming::Response { id: 3, reply: Ok(Value::Null) }
        );
        assert_eq!(
            parse_line(r#"{"id": 8, "error": {"code": "not_signed_in", "message": "Sign in first"}}"#),
            Incoming::Response {
                id: 8,
                reply: Err(json!({"code": "not_signed_in", "message": "Sign in first"}))
            }
        );
        assert_eq!(
            parse_line(r#"{"id": 9, "error": "boom"}"#),
            Incoming::Response { id: 9, reply: Err(json!({"code": "internal", "message": "boom"})) }
        );
        assert_eq!(
            parse_line(r#"{"event": "job.log", "data": {"job_id": "j3", "line": "x"}}"#),
            Incoming::Event(json!({"event": "job.log", "data": {"job_id": "j3", "line": "x"}}))
        );
        assert_eq!(
            parse_line(r#"{"event": "auth.progress"}"#),
            Incoming::Event(json!({"event": "auth.progress", "data": null}))
        );
    }

    #[test]
    fn rejects_garbage() {
        assert!(matches!(parse_line("Traceback (most recent call last):"), Incoming::Invalid(_)));
        assert!(matches!(parse_line("[1,2]"), Incoming::Invalid(_)));
        assert!(matches!(parse_line(r#"{"id": 1}"#), Incoming::Invalid(_)));
        assert!(matches!(parse_line(""), Incoming::Invalid(_)));
    }

    #[test]
    fn timeouts() {
        assert_eq!(timeout_for("auth.google"), GOOGLE_AUTH_TIMEOUT);
        assert_eq!(timeout_for("auth.github.poll"), DEFAULT_TIMEOUT);
        assert_eq!(timeout_for("jobs.start"), DEFAULT_TIMEOUT);
    }

    #[test]
    fn router_resolves_and_fails() {
        let mut r = Router::new();
        let (a, mut rx_a) = r.register();
        let (b, mut rx_b) = r.register();
        assert_ne!(a, b);
        assert!(r.resolve(a, Ok(json!(1))));
        assert!(!r.resolve(a, Ok(json!(2))));
        assert!(!r.resolve(999, Ok(json!(2))));
        assert_eq!(rx_a.try_recv().unwrap(), Ok(json!(1)));
        r.fail_all(unavailable("gone"));
        assert_eq!(rx_b.try_recv().unwrap().unwrap_err()["code"], "unavailable");
        assert_eq!(r.pending_count(), 0);
    }

    #[test]
    fn line_buffer_splits_chunks() {
        let mut lb = LineBuffer::default();
        assert!(lb.push(b"{\"id\":1,").is_empty());
        assert_eq!(lb.push(b"\"result\":1}\r\n{\"ev"), vec!["{\"id\":1,\"result\":1}"]);
        assert_eq!(lb.push(b"ent\":\"x\"}\n\n"), vec!["{\"event\":\"x\"}", ""]);
        assert_eq!(lb.finish(), None);
        lb.push("caf\u{e9}".as_bytes());
        assert_eq!(lb.finish().as_deref(), Some("caf\u{e9}"));
    }

    #[test]
    fn splits_commands() {
        assert_eq!(split_command("python -m desktop_engine"), vec!["python", "-m", "desktop_engine"]);
        assert_eq!(
            split_command(r#""C:\Program Files\Python\python.exe"  -m  x """#),
            vec![r"C:\Program Files\Python\python.exe", "-m", "x", ""]
        );
    }
}
