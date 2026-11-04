"""Gmail XOAUTH2: token refresh/caching and SMTP/IMAP auth, fully offline."""
import base64
import imaplib
import json
import shutil
import smtplib
import sys
import threading
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from outreach import google_oauth, mailbox, mailer, replies
from outreach.config import ConfigError, settings
from outreach.google_oauth import access_token, clear_cache, xoauth2_b64, xoauth2_bytes

WORK = Path(__file__).resolve().parent / "_gmail_xoauth_work"
shutil.rmtree(WORK, ignore_errors=True)
WORK.mkdir()

STATE = {"calls": [], "mode": "ok", "n": 0}


class TokenHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0)).decode()
        form = {k: v[0] for k, v in parse_qs(body).items()}
        STATE["calls"].append(form)
        if STATE["mode"] == "invalid_grant":
            code, payload = 400, {"error": "invalid_grant",
                                  "error_description": "Token has been expired or revoked."}
        else:
            STATE["n"] += 1
            code, payload = 200, {"access_token": f"tok{STATE['n']}", "expires_in": 3599,
                                  "token_type": "Bearer"}
        data = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *_args):
        pass


server = HTTPServer(("127.0.0.1", 0), TokenHandler)
threading.Thread(target=server.serve_forever, daemon=True).start()
TOKEN_URI = f"http://127.0.0.1:{server.server_port}/token"

token_file = WORK / "gmail_token.json"
token_file.write_text(json.dumps({
    "client_id": "cid.apps.googleusercontent.com", "client_secret": "csecret",
    "refresh_token": "1//refresh", "token_uri": TOKEN_URI}), encoding="utf-8")

try:
    # --- refresh + caching ---
    clear_cache()
    assert access_token(token_file) == "tok1"
    assert STATE["calls"][0] == {"grant_type": "refresh_token",
                                 "client_id": "cid.apps.googleusercontent.com",
                                 "client_secret": "csecret", "refresh_token": "1//refresh"}
    assert access_token(token_file) == "tok1" and len(STATE["calls"]) == 1, "should be cached"

    # Within the 60s margin of expiry -> refresh.
    key = next(iter(google_oauth._cache))
    tok, _exp = google_oauth._cache[key]
    google_oauth._cache[key] = (tok, google_oauth.time.monotonic() + 30)
    assert access_token(token_file) == "tok2" and len(STATE["calls"]) == 2
    assert access_token(token_file) == "tok2" and len(STATE["calls"]) == 2
    assert access_token(token_file, force=True) == "tok3"

    # Thread safety: concurrent callers share one refresh.
    clear_cache()
    before = len(STATE["calls"])
    results = []
    threads = [threading.Thread(target=lambda: results.append(access_token(token_file)))
               for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(STATE["calls"]) == before + 1 and len(set(results)) == 1, results

    # --- invalid_grant ---
    clear_cache()
    STATE["mode"] = "invalid_grant"
    try:
        access_token(token_file)
        raise AssertionError("invalid_grant should raise")
    except ConfigError as exc:
        assert "invalid_grant" in str(exc) and "reconnect Gmail" in str(exc), exc
    STATE["mode"] = "ok"

    # --- bad token files ---
    for content, needle in (("{not json", "not valid JSON"),
                            (json.dumps({"client_id": "x"}), "client_secret, refresh_token")):
        bad = WORK / "bad.json"
        bad.write_text(content, encoding="utf-8")
        try:
            access_token(bad)
            raise AssertionError("bad token file should raise")
        except ConfigError as exc:
            assert needle in str(exc), exc
    for missing in ("", WORK / "nope.json"):
        try:
            access_token(missing)
            raise AssertionError("missing token file should raise")
        except ConfigError as exc:
            assert "GOOGLE_OAUTH_TOKEN_FILE" in str(exc), exc

    # --- XOAUTH2 string ---
    assert xoauth2_bytes("me@gmail.com", "abc") == b"user=me@gmail.com\x01auth=Bearer abc\x01\x01"
    assert base64.b64decode(xoauth2_b64("me@gmail.com", "abc")) == \
        b"user=me@gmail.com\x01auth=Bearer abc\x01\x01"

    # --- SMTP ---
    class FakeSMTP:
        instances = []
        reply = (235, b"2.7.0 Accepted")

        def __init__(self, host, port, context=None, timeout=None):
            self.host, self.port = host, port
            self.commands, self.logins, self.sent = [], [], []
            FakeSMTP.instances.append(self)

        def ehlo(self):
            self.commands.append(("EHLO",))

        def starttls(self, context=None):
            self.commands.append(("STARTTLS",))

        def docmd(self, cmd, args=""):
            self.commands.append((cmd, args))
            if cmd == "AUTH":
                return FakeSMTP.reply
            return (535, b"5.7.8 Username and Password not accepted")

        def login(self, user, password):
            self.logins.append((user, password))

        def send_message(self, msg):
            if len(self.sent) == 0 and getattr(self, "drop_first", False):
                raise smtplib.SMTPServerDisconnected("gone")
            self.sent.append(msg)

        def quit(self):
            pass

    oauth = replace(settings, smtp_host="smtp.gmail.com", smtp_port=465, smtp_security="ssl",
                    smtp_user="me@gmail.com", smtp_password="", smtp_from="me@gmail.com",
                    smtp_auth="xoauth2", google_oauth_token_file=str(token_file),
                    imap_host="", imap_user="", imap_password="", imap_port=993)
    clear_cache()
    with patch.object(mailer.smtplib, "SMTP_SSL", FakeSMTP):
        m = mailer.Mailer(oauth, None, dry_run=False)
        m.connect()
        srv = FakeSMTP.instances[-1]
        expected = "XOAUTH2 " + base64.b64encode(
            b"user=me@gmail.com\x01auth=Bearer tok5\x01\x01").decode()
        assert srv.commands == [("AUTH", expected)], srv.commands
        assert srv.logins == []

        # Reconnect after a dropped socket re-authenticates (expired token is refreshed).
        key = next(iter(google_oauth._cache))
        google_oauth._cache[key] = ("tok5", google_oauth.time.monotonic() - 1)
        srv.send_message = lambda msg: (_ for _ in ()).throw(smtplib.SMTPServerDisconnected("x"))
        from email.message import EmailMessage
        m._deliver(EmailMessage())
        srv2 = FakeSMTP.instances[-1]
        assert srv2 is not srv and len(srv2.sent) == 1
        assert srv2.commands == [("AUTH", "XOAUTH2 " + xoauth2_b64("me@gmail.com", "tok6"))]
        m.close()

        # 334 challenge -> empty line -> error with Gmail's detail.
        FakeSMTP.reply = (334, base64.b64encode(b'{"status":"400","schemes":"Bearer"}'))
        try:
            mailer.Mailer(oauth, None, dry_run=False)._open()
            raise AssertionError("334 should fail")
        except smtplib.SMTPAuthenticationError as exc:
            srv3 = FakeSMTP.instances[-1]
            assert srv3.commands[-1] == ("", ""), srv3.commands
            assert exc.smtp_code == 535 and '"status":"400"' in str(exc), exc
            assert "reconnect Gmail" in str(exc)
        assert not google_oauth._cache, "failed auth should drop cached token"
        FakeSMTP.reply = (235, b"ok")

    # STARTTLS path authenticates after EHLO/STARTTLS/EHLO.
    with patch.object(mailer.smtplib, "SMTP", FakeSMTP):
        mailer.Mailer(replace(oauth, smtp_port=587, smtp_security="starttls"), None, dry_run=False)._open()
        cmds = FakeSMTP.instances[-1].commands
        assert [c[0] for c in cmds] == ["EHLO", "STARTTLS", "EHLO", "AUTH"], cmds

    # Missing token file -> ConfigError before any connection attempt.
    n = len(FakeSMTP.instances)
    try:
        mailer.Mailer(replace(oauth, google_oauth_token_file=""), None, dry_run=False).connect()
        raise AssertionError("missing token file should raise")
    except ConfigError:
        assert len(FakeSMTP.instances) == n

    # Password path unchanged.
    pw = replace(oauth, smtp_auth="password", smtp_password="app-pass")
    with patch.object(mailer.smtplib, "SMTP_SSL", FakeSMTP):
        mailer.Mailer(pw, None, dry_run=False).connect()
        srv = FakeSMTP.instances[-1]
        assert srv.logins == [("me@gmail.com", "app-pass")] and srv.commands == []

    # --- IMAP ---
    class FakeIMAP:
        instances = []

        def __init__(self, host, port, ssl_context=None, timeout=None):
            self.host, self.auth, self.logins = host, [], []
            FakeIMAP.instances.append(self)

        def authenticate(self, mech, callback):
            self.auth.append((mech, callback(b"")))
            return "OK", [b"Success"]

        def login(self, user, password):
            self.logins.append((user, password))
            return "OK", [b""]

        def list(self):
            return "OK", [b'(\\HasNoChildren) "/" "INBOX"',
                          b'(\\HasNoChildren \\Sent) "/" "[Gmail]/Sent Mail"']

        def select(self, *a, **k):
            return "OK", [b"0"]

        def logout(self):
            pass

    clear_cache()
    with patch.object(imaplib, "IMAP4_SSL", FakeIMAP):
        with replies.ReplyChecker(oauth) as rc:
            assert rc.folders == ["INBOX"]
        conn = FakeIMAP.instances[-1]
        assert conn.host == "imap.gmail.com"
        assert conn.auth == [("XOAUTH2", xoauth2_bytes("me@gmail.com", f"tok{STATE['n']}"))]
        assert conn.logins == []

        rc = replies.ReplyChecker(oauth)
        rc.__enter__()
        rc._reconnect()
        assert FakeIMAP.instances[-1].auth[0][0] == "XOAUTH2"

        with mailbox.SentArchiver(oauth) as arc:
            assert arc.folder == "[Gmail]/Sent Mail"
        assert FakeIMAP.instances[-1].auth and not FakeIMAP.instances[-1].logins

        from outreach.replier import ThreadReader
        with ThreadReader(oauth):
            pass
        assert FakeIMAP.instances[-1].auth[0][0] == "XOAUTH2"

        with replies.ReplyChecker(pw):
            pass
        conn = FakeIMAP.instances[-1]
        assert conn.logins == [("me@gmail.com", "app-pass")] and conn.auth == []

    # Gmail error challenge: second callback answers with an empty line.
    class ChallengeIMAP(FakeIMAP):
        def authenticate(self, mech, callback):
            self.auth.append(callback(b""))
            self.auth.append(callback(b'{"status":"400"}'))
            raise imaplib.IMAP4.error("AUTHENTICATE failed.")

    with patch.object(imaplib, "IMAP4_SSL", ChallengeIMAP):
        try:
            replies.ReplyChecker(oauth).__enter__()
            raise AssertionError("IMAP auth failure should raise")
        except imaplib.IMAP4.error as exc:
            assert "reconnect Gmail" in str(exc)
            assert FakeIMAP.instances[-1].auth[1] == b""

    # Settings validation.
    try:
        replace(settings, smtp_auth="oauth")
        raise AssertionError("unknown SMTP_AUTH should raise")
    except ValueError:
        pass
finally:
    server.shutdown()
    server.server_close()
    clear_cache()
    shutil.rmtree(WORK, ignore_errors=True)

print("gmail xoauth tests passed")
