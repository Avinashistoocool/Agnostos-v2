"""IMAP sessions may be closed mid-scan without losing the folder or row."""
import imaplib
from pathlib import Path
import socket
import sys
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _isolate  # noqa: F401,E402  (must precede outreach imports)

from outreach.replies import ReplyChecker


class FakeConnection:
    def __init__(self, fail_on=None):
        self.fail_on = fail_on
        self.selected = None
        self.closed = False

    def select(self, folder, readonly=True):
        if self.fail_on == "select":
            self.fail_on = None
            raise imaplib.IMAP4.abort("connection closed")
        self.selected = folder
        return "OK", [b"1"]

    def search(self, *args):
        if self.fail_on == "search":
            self.fail_on = None
            raise imaplib.IMAP4.abort("socket error: EOF")
        assert self.selected == '"INBOX"'
        return "OK", [b"12"]

    def fetch(self, *args):
        if self.fail_on == "fetch":
            self.fail_on = None
            raise OSError("socket error: EOF")
        assert self.selected == '"INBOX"'
        return "OK", [(b"12", b"From: professor@example.org\r\nSubject: Re: test\r\n\r\nHello")]

    def logout(self):
        self.closed = True


class Checker(ReplyChecker):
    def __init__(self, connections):
        super().__init__(SimpleNamespace(
            imap_host="example.org", smtp_host="example.org", imap_user="me",
            smtp_user="me", imap_password="test", smtp_password="test"))
        self.connections = iter(connections)

    def __enter__(self):
        self.conn = next(self.connections)
        self.folders = ["INBOX"]
        return self


for failed in ("select", "search", "fetch"):
    old, new = FakeConnection(failed), FakeConnection()
    checker = Checker([old, new])
    with checker:
        checker._select("INBOX")
        assert checker._search("FROM", '"professor@example.org"') == [b"12"]
        assert checker._fetch(b"12")["Subject"] == "Re: test"
    assert old.closed and new.closed, failed

old, new = FakeConnection("search"), FakeConnection()
checker = Checker([old, new])
checker.__enter__()
checker._select("INBOX")
enter = checker.__enter__
attempts = 0


def temporary_dns_error():
    global attempts
    attempts += 1
    if attempts == 1:
        raise socket.gaierror("temporary DNS failure")
    return enter()


with patch.object(checker, "__enter__", side_effect=temporary_dns_error), \
        patch("outreach.replies.time.sleep"):
    assert checker._search("FROM", '"professor@example.org"') == [b"12"]
assert attempts == 2 and old.closed
checker.__exit__(None, None, None)
print("IMAP reconnection tests passed")
