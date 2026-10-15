"""One TLS context for every outbound connection (HTTPS, SMTP, IMAP).

python.org builds on macOS ship with no CA store at all (the
"Install Certificates.command" step is usually skipped), so
`ssl.create_default_context()` fails with
"CERTIFICATE_VERIFY_FAILED ... (_ssl.c:1144)" on perfectly valid hosts.
Python on Windows has the same gap for many institutional chains.

Order of preference, never disabling verification:
  1. SSL_CERT_FILE / REQUESTS_CA_BUNDLE if they point at a real file
  2. truststore - the OS store itself (macOS Keychain, Windows CertStore),
     which also picks up university / corporate root CAs
  3. certifi's Mozilla bundle
  4. Python's default
"""
from __future__ import annotations

import os
import ssl
import urllib.request
from functools import lru_cache


def _env_bundle() -> str | None:
    for var in ("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE"):
        path = os.getenv(var, "").strip()
        if path and os.path.isfile(path):
            return path
    return None


def ca_file() -> str | None:
    """A CA bundle path, for libraries that only accept a file."""
    env = _env_bundle()
    if env:
        return env
    try:
        import certifi
        return certifi.where()
    except ImportError:
        return None


@lru_cache(maxsize=1)
def context() -> ssl.SSLContext:
    env = _env_bundle()
    if env:
        return ssl.create_default_context(cafile=env)
    try:
        import truststore
        return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    except Exception:
        pass
    return ssl.create_default_context(cafile=ca_file())


def describe() -> str:
    env = _env_bundle()
    if env:
        return f"env bundle {env}"
    try:
        import truststore  # noqa: F401
        return "OS trust store (truststore)"
    except ImportError:
        pass
    return f"certifi {ca_file()}" if ca_file() else "Python default (no CA bundle!)"


def urlopen(req, timeout: float = 30):
    return urllib.request.urlopen(req, timeout=timeout, context=context())


def http_client():
    """httpx client for the OpenAI SDK using the same trust store, or None
    to let the SDK use its own transport when httpx isn't installed."""
    try:
        import httpx
    except ImportError:
        return None
    return httpx.Client(verify=context(), timeout=httpx.Timeout(600, connect=30))
