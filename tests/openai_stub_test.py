"""Verify the real OpenAI SDK path, provider switching, and capability
negotiation against a local stub server (no API key, no spend)."""
from __future__ import annotations

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from outreach.config import settings
from outreach.excel_io import load_targets
from outreach.llm import LLMEvaluator
from outreach.resume_parser import parse_resume

import _paths

settings.resume_path = _paths.resume_path(settings)
settings.target_xlsx = _paths.target_xlsx(settings)

RECEIVED: list[dict] = []


class Handler(BaseHTTPRequestHandler):
    truncate = False
    reject_fields: set = set()

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")
        RECEIVED.append({"path": self.path, "body": body})

        if Handler.reject_fields & set(body):
            err = json.dumps({"error": {
                "message": "The request contains invalid or unsupported fields.",
                "type": "invalid_request_error", "code": "invalid_request"}}).encode()
            self.send_response(400)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(err)))
            self.end_headers()
            self.wfile.write(err)
            return

        payload = {
            "id": "chatcmpl-stub",
            "object": "chat.completion",
            "created": 0,
            "model": body.get("model", "gpt-4.1"),
            "choices": [{
                "index": 0,
                "finish_reason": "length" if Handler.truncate else "stop",
                "message": {
                    "role": "assistant",
                    "content": json.dumps({
                        "probability": 73,
                        "justification": "Direct overlap on transformer-based jet tagging.",
                        "subject": "Summer internship enquiry: jet tagging with transformers",
                        "body": "Dear Professor,\n\nYour recent work caught my eye.\n\nBest,\nAlex",
                    }),
                },
            }],
            "usage": {
                "prompt_tokens": 1500,
                "completion_tokens": 260,
                "total_tokens": 1760,
                "prompt_tokens_details": {"cached_tokens": 1024},
            },
        }
        data = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *_a):
        pass


def main() -> int:
    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = server.server_address[1]

    settings.openai_api_key = "sk-stub-key"
    settings.openai_base_url = f"http://127.0.0.1:{port}/v1"
    settings.provider = "openai"

    profile = parse_resume(settings.resume_path)
    prof = load_targets(settings.target_xlsx)[0]
    ev = LLMEvaluator(settings, profile)

    print("[1] real SDK call against stub")
    ev.evaluate_one(prof, model="gpt-4.1")
    assert prof.llm_status.startswith("ok"), prof.llm_status
    assert prof.probability == 73, prof.probability
    assert prof.email_subject.startswith("Summer internship"), prof.email_subject
    assert "\n" in prof.email_body
    print(f"    ok: {prof.probability}% | {prof.email_subject}")

    print("[2] request shape accepted by the SDK")
    req = RECEIVED[0]
    assert req["path"].endswith("/chat/completions"), req["path"]
    body = req["body"]
    assert body["model"] == "gpt-4.1"
    assert body["messages"][0]["role"] == "system"
    assert body["messages"][1]["role"] == "user"
    assert "Professor:" in body["messages"][1]["content"]
    assert body["response_format"]["type"] == "json_schema"
    schema = body["response_format"]["json_schema"]
    assert schema["strict"] is True
    assert sorted(schema["schema"]["required"]) == \
        ["body", "justification", "probability", "subject"]
    assert body["max_completion_tokens"] == settings.max_output_tokens
    assert body["temperature"] == 0.4
    print(f"    ok: strict json_schema, {len(body['messages'])} messages, "
          f"max_completion_tokens={body['max_completion_tokens']}")

    print("[3] usage accounting splits cached tokens")
    assert ev.usage["cached"] == 1024, ev.usage
    assert ev.usage["input"] == 1500 - 1024, ev.usage
    assert ev.usage["output"] == 260
    expected = (476 / 1e6 * 2.00) + (1024 / 1e6 * 0.50) + (260 / 1e6 * 8.00)
    assert abs(ev.actual_cost("gpt-4.1") - expected) < 1e-9
    print(f"    ok: {ev.usage_report('gpt-4.1')}")

    print("[4] reasoning models omit temperature")
    RECEIVED.clear()
    prof2 = load_targets(settings.target_xlsx)[1]
    ev.evaluate_one(prof2, model="gpt-5-mini")
    assert "temperature" not in RECEIVED[0]["body"], RECEIVED[0]["body"].keys()
    assert prof2.llm_status.startswith("ok")
    print("    ok: gpt-5-mini request sent without temperature")

    print("[5] truncated response (finish_reason=length) is treated as a failure")
    RECEIVED.clear()
    Handler.truncate = True
    prof3 = load_targets(settings.target_xlsx)[2]
    ev.evaluate_one(prof3, model="gpt-4.1", max_retries=1)
    assert prof3.probability == 0, prof3.probability
    assert "truncated" in prof3.llm_status, prof3.llm_status
    Handler.truncate = False
    print(f"    ok: {prof3.llm_status[:60]}")

    print("[6] capability downgrade against a restrictive gateway")
    RECEIVED.clear()
    # Mimic a proxy that rejects structured outputs and max_completion_tokens.
    Handler.reject_fields = {"response_format", "max_completion_tokens"}
    ev2 = LLMEvaluator(settings, profile)
    prof4 = load_targets(settings.target_xlsx)[3]
    ev2.evaluate_one(prof4, model="gpt-4.1")
    assert prof4.llm_status.startswith("ok"), prof4.llm_status
    assert ev2.caps["json_schema"] is False and ev2.caps["json_object"] is False
    assert ev2.caps["max_completion_tokens"] is False
    final = RECEIVED[-1]["body"]
    assert "response_format" not in final and "max_completion_tokens" not in final
    assert final["max_tokens"] == settings.max_output_tokens
    Handler.reject_fields = set()
    print(f"    ok: negotiated down over {len(RECEIVED)} attempts, then succeeded")

    print("[7] groq provider wiring")
    settings.provider = "groq"
    settings.groq_api_key = "gsk-stub"
    settings.groq_base_url = f"http://127.0.0.1:{port}/v1"
    assert settings.api_key == "gsk-stub"
    assert settings.key_env_name == "GROQ_API_KEY"
    assert settings.supports_prompt_cache is False
    ev3 = LLMEvaluator(settings, profile)
    prof5 = load_targets(settings.target_xlsx)[4]
    ev3.evaluate_one(prof5, model="openai/gpt-oss-120b")
    assert prof5.llm_status.startswith("ok"), prof5.llm_status
    est = ev3.estimate([prof5], "openai/gpt-oss-120b")
    assert est.cache_eligible is False and est.cached_input_tokens == 0
    print(f"    ok: groq key/base_url used, no cache assumed, est ${est.cost_usd:.4f}")

    server.shutdown()
    print("\nPROVIDER INTEGRATION TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
