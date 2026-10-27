"""Email address verification and repair.

An outreach list is only as good as its addresses. LLM-assembled or
hand-copied lists routinely contain addresses that are plausible but wrong:
the right person at the wrong university, a guessed `first.last@` pattern, or
a domain that does not accept mail at all. Sending to those burns the sender
reputation and silently loses the contact.

This module runs three cheap local checks and, with `--repair`, goes and
reads the professor's own pages to find the address they currently publish.

  1. Syntax        - RFC-ish shape, no obvious junk.
  2. Deliverability- the domain actually publishes MX (or at least A) records.
  3. Name match    - the local part plausibly derives from the person's name.
  4. Current page  - the address printed on their own institutional page wins
                     over whatever the spreadsheet says.

There is deliberately no table of "which domain belongs to which university".
Institution text in a scraped list is unreliable and domains rarely spell
their institution out; the only dependable answer is the one the person
publishes themselves.

Nothing here sends mail or requires an API key. An optional SMTP RCPT probe
(`--probe-smtp`) is available but off by default: many servers accept every
recipient or blacklist probers, so it is advisory only.
"""
from __future__ import annotations

import contextlib
import html as htmllib
import json
import os
import re
import smtplib
import socket
import ssl
import subprocess
import sys
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from .models import Professor


_QUIET_LOCK = threading.Lock()
_QUIET = {"depth": 0, "saved": None, "devnull": None}


@contextlib.contextmanager
def _quiet_stderr():
    """Mute stderr for the duration of the block.

    The search library's HTTP core is a native extension that prints its own
    connection errors straight to file descriptor 2, so they cannot be caught
    or filtered in Python. They are noise - the failure is already handled by
    moving to the next backend - but they bury the progress report.

    fd 2 is process-wide and verification runs in threads, so the redirect is
    reference-counted: the first thread in mutes it, the last one out restores
    it. Without that, overlapping threads restore each other's devnull and
    stderr stays muted for the rest of the run.
    """
    try:
        fd = sys.stderr.fileno()
    except (AttributeError, ValueError, OSError):
        yield                      # already redirected somewhere unusual
        return
    with _QUIET_LOCK:
        if _QUIET["depth"] == 0:
            saved = devnull = None
            try:
                sys.stderr.flush()
                saved = os.dup(fd)
                devnull = os.open(os.devnull, os.O_WRONLY)
                os.dup2(devnull, fd)
            except OSError:
                # Some Windows consoles/pipes refuse dup2 ("Incorrect function").
                # Muting is cosmetic; never let it fail the search itself.
                for h in (saved, devnull):
                    if h is not None:
                        os.close(h)
                saved = None
            if saved is None:
                muted = False
            else:
                _QUIET["saved"], _QUIET["devnull"] = saved, devnull
                muted = True
        else:
            muted = True
        if muted:
            _QUIET["depth"] += 1
    if not muted:
        yield
        return
    try:
        yield
    finally:
        with _QUIET_LOCK:
            _QUIET["depth"] -= 1
            if _QUIET["depth"] == 0:
                try:
                    sys.stderr.flush()
                    os.dup2(_QUIET["saved"], fd)
                except OSError:
                    pass
                os.close(_QUIET["saved"])
                os.close(_QUIET["devnull"])


def _ssl_context():
    """A CA bundle that covers European university hosts on every OS (see tls.py)."""
    from .tls import context
    return context()


_SSL = _ssl_context()


EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")
FIND_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
OBFUSCATED_RE = re.compile(
    r"([A-Za-z0-9._%+\-]+)\s*(?:\[at\]|\(at\)|&#64;|\sat\s)\s*"
    r"([A-Za-z0-9.\-]+)\s*(?:\[dot\]|\(dot\)|\sdot\s)\s*([A-Za-z]{2,})", re.I)
# `name "AT" uni-x.de`, `name [at] uni-x.de`, `name (at) uni-x (dot) de`, run
# on the page's visible text, where markup has already been stripped out.
AT_TEXT_RE = re.compile(
    r"([A-Za-z0-9._%+\-]+)\s*"
    r"(?:[\"'\[\(\{<]\s*(?:at|@)\s*[\"'\]\)\}>]|\s(?:at|AT)\s)\s*"
    r"([A-Za-z0-9\-]+(?:(?:\.|\s*(?:\[dot\]|\(dot\)|\{dot\})\s*|\s+dot\s+)[A-Za-z0-9\-]+)+)", re.I)
_DOT_TOKEN_RE = re.compile(r"\s*(?:\[dot\]|\(dot\)|\{dot\})\s*|\s+dot\s+", re.I)


def _page_text(html: str) -> str:
    """Visible text with tags removed and entities decoded."""
    text = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", html or "")
    text = re.sub(r"<[^>]+>", " ", text)
    return htmllib.unescape(text)


def _typo3_decrypt(enc: str, offset: int) -> str:
    out = []
    for ch in enc:
        n = ord(ch)
        for lo, hi in ((0x2B, 0x3A), (0x40, 0x5A), (0x61, 0x7A)):
            if lo <= n <= hi:
                n += offset
                if n > hi:
                    n = lo + (n - hi - 1)
                elif n < lo:
                    n = hi - (lo - n - 1)
                break
        out.append(chr(n))
    return "".join(out)


def _typo3_emails(html: str) -> list[str]:
    """TYPO3 (common on German/Austrian/Swiss university sites) ships mailto
    links Caesar-shifted and decodes them in JavaScript on click."""
    tokens = re.findall(r"linkTo_UnCryptMailto\(\s*['\"]([^'\"]+)['\"]", html or "")
    tokens += re.findall(r"data-mailto-token=['\"]([^'\"]+)['\"]", html or "")
    out = []
    for tok in tokens:
        tok = htmllib.unescape(tok)
        for off in range(-15, 16):
            dec = _typo3_decrypt(tok, off)
            if dec.lower().startswith("mailto:"):
                out.append(urllib.parse.unquote(dec[7:]).split("?")[0])
                break
    return out


def _cloudflare_emails(html: str) -> list[str]:
    out = []
    for hexstr in re.findall(r"data-cfemail=['\"]([0-9a-fA-F]+)['\"]", html or ""):
        try:
            data = bytes.fromhex(hexstr)
            out.append(bytes(b ^ data[0] for b in data[1:]).decode("utf-8"))
        except (ValueError, IndexError, UnicodeDecodeError):
            continue
    return out

# Mailbox names that belong to an office, not a person.
GENERIC_LOCALPARTS = {
    "info", "office", "contact", "admin", "webmaster", "secretary", "sekretariat",
    "enquiries", "enquiry", "support", "help", "press", "noreply", "no-reply",
    "mail", "post", "hr", "jobs", "it", "privacy", "newsletter", "media",
    "studies", "studium", "studienberatung", "admissions", "registry", "library",
}


# Common free-mail hosts: valid, but never evidence of an affiliation.
FREEMAIL = {"gmail.com", "googlemail.com", "yahoo.com", "outlook.com",
            "hotmail.com", "proton.me", "protonmail.com", "icloud.com",
            "web.de", "gmx.de", "gmx.net", "mail.ru", "qq.com", "163.com"}

OK, SUSPECT, INVALID, UNKNOWN = "ok", "suspect", "invalid", "unknown"

# Nobiliary particles; universities usually drop them from the local part.
NAME_PARTICLES = {"van", "von", "de", "del", "della", "der", "den", "di", "da",
                  "do", "dos", "das", "la", "le", "el", "al", "bin", "ibn",
                  "ter", "ten", "af", "av", "zu", "mac", "mc", "st"}

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")


# ----------------------------------------------------------------- helpers
def _ascii_fold(text: str) -> str:
    """Muller -> muller, Romao -> romao, so accents never break a match."""
    norm = unicodedata.normalize("NFKD", text or "")
    return "".join(c for c in norm if not unicodedata.combining(c)).lower()


TITLE_RE = re.compile(
    r"^\s*(prof\.?|professor|dr\.?|dr\.?rer\.?nat\.?|phd|pd|priv\.?-?doz\.?|"
    r"assoc\.?|assist\.?|asst\.?|mr\.?|ms\.?|mrs\.?|sir|dame)\s+", re.I)


def name_tokens(name: str) -> list[str]:
    """Given-name/surname word list, titles and initials removed."""
    clean = name or ""
    while True:
        stripped = TITLE_RE.sub("", clean)
        if stripped == clean:
            break
        clean = stripped
    clean = re.sub(r"\([^)]*\)", " ", clean)
    clean = _ascii_fold(clean)
    words = [w for w in re.split(r"[^a-z]+", clean) if len(w) > 1]
    return words


def _variants(tokens: list[str]) -> set[str]:
    """Local parts a university might plausibly assign to this person."""
    if not tokens:
        return set()
    out: set[str] = set()
    first = tokens[0]
    # Try every trailing token as the surname, plus the full compound, so
    # "van Vulpen" and "Ruiz de Austri" both produce the forms in real use.
    surname_forms = {tokens[-1], "".join(tokens[1:]), ".".join(tokens[1:]),
                     "-".join(tokens[1:]),
                     "".join(t for t in tokens[1:] if t not in NAME_PARTICLES)}
    surname_forms |= {t for t in tokens[1:] if t not in NAME_PARTICLES}
    for last in {s for s in surname_forms if len(s) >= 2}:
        middles = [t for t in tokens[1:-1] if t not in NAME_PARTICLES]
        out |= {
            last, first,
            f"{first}.{last}", f"{first}{last}", f"{first}-{last}", f"{first}_{last}",
            f"{last}.{first}", f"{last}{first}", f"{last}-{first}", f"{last}_{first}",
            f"{first[0]}.{last}", f"{first[0]}{last}", f"{first[0]}-{last}",
            f"{first[0]}_{last}", f"{last}.{first[0]}", f"{last}{first[0]}",
            f"{first}.{last[0]}", f"{first}{last[0]}",
            first[:3] + last[:3], last[:3] + first[:3],
            (first[0] + last)[:8], last[:8],
        }
        for m in middles:
            out |= {f"{first}.{m}.{last}", f"{first[0]}{m[0]}{last}",
                    f"{first[0]}.{m[0]}.{last}", f"{first}{m[0]}{last}"}
    return {v for v in out if len(v) >= 2}


def given_name_conflict(name: str, email: str) -> bool:
    """True when the address names a DIFFERENT given name than this person's.

    francesco.vicentini for Filippo Vicentini, alberto.pardo for C. Domingo-Pardo,
    cengiz.tuysuz for Cenk Tuysuz: the surname matches, so name_match() scores
    them 0.75, but they are other people at the same institution.
    """
    if "@" not in email:
        return False
    local = _ascii_fold(email.split("@")[0])
    parts = [re.sub(r"\d+", "", p) for p in re.split(r"[._\-+]", local)]
    parts = [p for p in parts if p]
    if len(parts) < 2:
        return False
    raw = _ascii_fold(re.sub(r"[()]", " ", name or ""))
    words = [w for w in re.split(r"[^a-z]+", raw) if w]
    full = [w for w in words if len(w) > 1]
    initials = {w[0] for w in words}
    surnames = set(full[1:]) | ({full[-1]} if full else set())
    for g in parts:
        if len(g) < 3 or any(g == s or (len(s) >= 4 and s in g) for s in surnames):
            continue
        if any(t.startswith(g) or g.startswith(t) for t in full):
            continue
        # Name given only as initials ("R.A. Cooper"): richard.cooper is fine.
        if g[0] in initials and any(len(w) == 1 for w in words):
            continue
        return True
    return False


_GENERIC_TLDS = {"com", "org", "net", "edu", "eu", "int", "gov", "info", "io", "ai"}


def country_mismatch(country: str, email: str) -> bool:
    """Address on another country's domain (cengiz@usak.edu.tr for a DESY row)."""
    tld = domain_of(email).rsplit(".", 1)[-1].lower()
    want = (country or "").strip().lower()
    want = {"gb": "uk"}.get(want, want)
    return bool(len(want) == 2 and len(tld) == 2 and tld not in _GENERIC_TLDS and tld != want)


def name_match(name: str, email: str) -> float:
    """0..1 confidence that this local part belongs to this person.

    1.0 exact pattern, 0.75 the surname appears intact, 0.5 a plausible
    initialism, 0.0 no relationship at all.
    """
    tokens = name_tokens(name)
    if not tokens or "@" not in email:
        return 0.0
    local = _ascii_fold(email.split("@")[0])
    local_norm = re.sub(r"[^a-z0-9]", "", local)
    if local in GENERIC_LOCALPARTS or local_norm in GENERIC_LOCALPARTS:
        return 0.0
    variants = _variants(tokens)
    if local in variants or local_norm in {re.sub(r"[^a-z0-9]", "", v) for v in variants}:
        return 1.0
    first = tokens[0]
    # "Ruiz de Austri", "van Vulpen", "Crispim Romao": any trailing token can
    # be the one the university used.
    surnames = [t for t in tokens[1:] if t not in NAME_PARTICLES] or [tokens[-1]]
    for last in surnames:
        if len(last) >= 4 and last in local_norm:
            return 1.0 if local_norm in {last, first[0] + last} else 0.75
        # Truncated surnames: Voloshynovskiy -> svolos, Mieskolainen -> mieskol.
        stem = local_norm[1:] if local_norm.startswith(first[0]) else local_norm
        if len(stem) >= 4 and last.startswith(stem):
            return 0.9
        if len(local_norm) >= 5 and last.startswith(local_norm):
            return 0.9
    if len(first) >= 4 and first in local_norm:
        return 0.6
    # Initials plus a numeric id (Cambridge CRSid mc2281, mx123): the digits
    # carry no signal, so judge on the letters alone.
    m = re.fullmatch(r"([a-z]{1,4})(\d{1,6})", local_norm)
    if m:
        letters = m.group(1)
        initials = "".join(t[0] for t in tokens)
        if letters == initials or letters in initials or initials.startswith(letters):
            return 0.9
        if letters[0] == first[0] and any(letters[-1] == s[0] for s in surnames):
            return 0.9
        return 0.3
    if len(local_norm) <= 4 and all(
            c in local_norm for c in (first[0], surnames[-1][0])):
        return 0.5
    return 0.0


def domain_of(email: str) -> str:
    return email.split("@")[-1].strip().lower() if "@" in email else ""


def is_academic(domain: str) -> bool:
    """True for a domain that looks like a research institution, not webmail.

    Deliberately shallow: `.edu`, `.ac.<cc>`, `.edu.<cc>` and anything that is
    simply not a known free-mail host. Guessing *which* university a domain
    belongs to from its spelling never worked - that is what the web lookup is
    for.
    """
    domain = (domain or "").lower().lstrip(".")
    if not domain or domain in FREEMAIL:
        return False
    parts = domain.split(".")
    return not (len(parts) < 2 or domain in FREEMAIL)


def same_site(a: str, b: str) -> bool:
    """True if two domains belong to the same organisation.

    `thphys.uni-heidelberg.de` and `uni-heidelberg.de` are the same place;
    `kit.edu` and `durham.ac.uk` are not.
    """
    a, b = (a or "").lower().lstrip("."), (b or "").lower().lstrip(".")
    if not a or not b:
        return False
    return a == b or a.endswith("." + b) or b.endswith("." + a)


# ------------------------------------------------------------ DNS / SMTP
_mx_cache: dict[str, bool | None] = {}


def has_mail_records(domain: str, timeout: float = 6.0) -> bool | None:
    """True if the domain can receive mail, False if it demonstrably cannot.

    None means the lookup itself failed (offline, DNS blocked) - never treat
    that as a bad address.
    """
    if not domain:
        return False
    if domain in _mx_cache:
        return _mx_cache[domain]
    result: bool | None = None
    try:
        import dns.resolver  # optional dependency
        try:
            answers = dns.resolver.resolve(domain, "MX", lifetime=timeout)
            result = len(answers) > 0
        except dns.resolver.NoAnswer:
            result = None          # no MX, but the zone exists -> check A below
        except (dns.resolver.NXDOMAIN, dns.resolver.NoNameservers):
            result = False
        except Exception:
            result = None
    except ImportError:
        result = _nslookup_mx(domain, timeout)
    if result is None:
        # A domain with an A/AAAA record but no MX still accepts mail there.
        try:
            socket.setdefaulttimeout(timeout)
            socket.getaddrinfo(domain, None)
            result = True
        except socket.gaierror:
            result = False
        except Exception:
            result = None
    _mx_cache[domain] = result
    return result


def _nslookup_mx(domain: str, timeout: float) -> bool | None:
    try:
        proc = subprocess.run(["nslookup", "-type=mx", domain],
                              capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None
    out = (proc.stdout or "").lower()
    if "mail exchanger" in out:
        return True
    if "non-existent domain" in out or "nxdomain" in out:
        return False
    return None


def smtp_probe(email: str, mail_from: str, timeout: float = 10.0) -> bool | None:
    """Ask the recipient's server whether the mailbox exists.

    Advisory only: catch-all servers accept everything and some providers
    blacklist probers, so a True here is weak evidence and a None is common.
    """
    domain = domain_of(email)
    if not domain:
        return False
    try:
        import dns.resolver
        hosts = sorted(((r.preference, str(r.exchange).rstrip("."))
                        for r in dns.resolver.resolve(domain, "MX", lifetime=timeout)))
        host = hosts[0][1] if hosts else domain
    except Exception:
        host = domain
    try:
        with smtplib.SMTP(host, 25, timeout=timeout) as server:
            server.ehlo_or_helo_if_needed()
            server.mail(mail_from or f"verify@{domain}")
            code, _ = server.rcpt(email)
    except Exception:
        return None
    if code in (250, 251):
        return True
    if code in (550, 551, 553):
        return False
    return None


# -------------------------------------------------------------- the check
@dataclass
class EmailCheck:
    email: str = ""
    status: str = UNKNOWN
    confidence: int = 0
    reasons: list[str] = field(default_factory=list)
    suggestion: str = ""
    source: str = ""

    @property
    def sendable(self) -> bool:
        return self.status in (OK, SUSPECT, UNKNOWN)

    def summary(self) -> str:
        return "; ".join(self.reasons) if self.reasons else "looks fine"


def check_email(name: str, email: str, institution: str = "",
                known_domains: tuple[str, ...] = (), check_dns: bool = True,
                probe: bool = False, mail_from: str = "") -> EmailCheck:
    """Score one address. Pure-local except for the optional DNS/SMTP steps."""
    email = (email or "").strip()
    res = EmailCheck(email=email)
    if not email:
        res.status, res.reasons = INVALID, ["no address on this row"]
        return res
    if not EMAIL_RE.match(email):
        res.status, res.reasons = INVALID, ["not a valid address shape"]
        return res

    score, reasons = 100, []
    domain = domain_of(email)

    if check_dns:
        mx = has_mail_records(domain)
        if mx is False:
            res.status = INVALID
            res.reasons = [f"{domain} does not resolve or accept mail"]
            return res
        if mx is None:
            reasons.append("could not verify DNS for the domain")
            score -= 10

    nm = name_match(name, email)
    if nm >= 1.0:
        pass
    elif nm >= 0.75:
        score -= 10
        reasons.append("local part contains the surname but is not a usual pattern")
    elif nm >= 0.5:
        score -= 25
        reasons.append("local part only loosely matches the name")
    elif nm > 0:
        score -= 35
        reasons.append("local part barely matches the name")
    else:
        score -= 55
        reasons.append(f"local part does not match '{name}'")

    if known_domains and not any(same_site(domain, d) for d in known_domains):
        score -= 20
        reasons.append(f"their current page is on {known_domains[0]}, not {domain}")
    elif domain in FREEMAIL:
        score -= 30
        reasons.append("personal webmail rather than an institutional address")

    if probe:
        hit = smtp_probe(email, mail_from)
        if hit is False:
            res.status = INVALID
            res.reasons = reasons + ["the mail server says this mailbox does not exist"]
            res.confidence = 0
            return res
        if hit is True:
            score = min(100, score + 10)
            reasons.append("mail server accepted the recipient")

    res.confidence = max(0, min(100, score))
    res.reasons = reasons
    res.status = OK if res.confidence >= 70 else SUSPECT
    return res


# ------------------------------------------------------- finding the truth
class EmailFinder:
    """Find the professor's current address by reading their own web pages.

    The row's profile URL first, then a plain web search for the person. An
    address is accepted when its local part matches their name and the page
    that published it belongs to the same domain - no assumptions about how a
    university's domain ought to be spelled.
    """

    SEARCH = "https://html.duckduckgo.com/html/?q="

    # Tried in order; the first that answers wins. Public search endpoints
    # block scrapers aggressively and the one that works changes month to
    # month, so there is no single backend to rely on.
    BACKENDS = ("mullvad_google", "bing", "yandex", "mullvad_brave")

    def __init__(self, timeout: float = 15.0, delay: float = 1.5,
                 max_pages: int = 4, openalex=None):
        self.timeout = timeout
        self.delay = delay
        self.max_pages = max_pages
        self.openalex = openalex
        self.search_error = ""
        self._good_backend = ""
        self._page_cache: dict[str, str] = {}
        self._search_cache: dict[str, list[str]] = {}

    # Shared by every finder (one per worker thread), so N workers still
    # space their requests to any one host by `delay`, rather than hitting the
    # same university or search engine N times at once.
    _host_lock = threading.Lock()
    _host_next: dict[str, float] = {}

    def _pace(self, host: str) -> None:
        with EmailFinder._host_lock:
            now = time.monotonic()
            slot = max(now, EmailFinder._host_next.get(host, 0.0))
            EmailFinder._host_next[host] = slot + self.delay
        if slot > now:
            time.sleep(slot - now)

    def _fetch(self, url: str) -> str:
        if url in self._page_cache:
            return self._page_cache[url]
        self._pace(urllib.parse.urlparse(url).netloc.lower())
        req = urllib.request.Request(url, headers={
            "User-Agent": _UA,
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en-GB,en;q=0.9",
        })
        text = ""
        try:
            with urllib.request.urlopen(req, timeout=self.timeout,
                                        context=_SSL) as resp:
                raw = resp.read(600_000)
                charset = resp.headers.get_content_charset() or "utf-8"
                text = raw.decode(charset, errors="replace")
        except Exception:
            text = ""
        self._page_cache[url] = text
        return text

    # Labels people insert into a published address to defeat harvesters.
    # Removing them is reconstructing the address the person actually wrote.
    ANTISPAM_LABELS = ("spamnot", "nospam", "nospamplease", "removethis",
                       "remove", "deletethis", "spam", "xxx", "nospam1")

    @classmethod
    def _unobfuscate(cls, email: str) -> str:
        local, _, domain = email.partition("@")
        labels = [p for p in domain.split(".")
                  if p.lower() not in cls.ANTISPAM_LABELS]
        return f"{local}@{'.'.join(labels)}" if len(labels) >= 2 else email

    @classmethod
    def _emails_in(cls, html: str) -> list[str]:
        found = set()
        for raw in FIND_EMAIL_RE.findall(html or ""):
            found.add(raw.strip(".,;:"))
        for user, dom, tld in OBFUSCATED_RE.findall(html or ""):
            found.add(f"{user}@{dom}.{tld}")
        for raw in re.findall(r"mailto:([^\"'?>\s]+)", html or "", re.I):
            cand = urllib.parse.unquote(raw).strip().strip(".,;:")
            if EMAIL_RE.match(cand):
                found.add(cand)
        for cand in _typo3_emails(html) + _cloudflare_emails(html):
            if EMAIL_RE.match(cand.strip()):
                found.add(cand.strip())
        for user, dom in AT_TEXT_RE.findall(_page_text(html)):
            cand = f"{user.strip('.')}@{_DOT_TOKEN_RE.sub('.', dom).strip('.')}"
            if EMAIL_RE.match(cand):
                found.add(cand)
        out = []
        for email in found:
            email = cls._unobfuscate(email)
            low = email.lower()
            if any(b in low for b in (".png", ".jpg", ".jpeg", ".gif", ".svg", "@2x",
                                      "example.com", "sentry", "wixpress", "u002f")):
                continue
            if low.split("@")[0] in GENERIC_LOCALPARTS or len(email) > 80:
                continue
            out.append(email)
        return out

    SKIP_HOSTS = ("duckduckgo", "google.", "bing.", "facebook", "twitter",
                  "linkedin", "youtube", "wikipedia", "researchgate",
                  "semanticscholar", "x.com", "github.io", "rocketreach",
                  "zoominfo", "signalhire", "contactout", "academia.edu",
                  "web.archive.org", "scholar.google")

    def _keep(self, href: str) -> bool:
        if not href.startswith("http"):
            return False
        host = urllib.parse.urlparse(href).netloc.lower()
        return not any(bad in host for bad in self.SKIP_HOSTS)

    def _search_ddgs(self, query: str, limit: int) -> list[str]:
        """Metasearch via the `ddgs` package, if it is installed.

        Each backend is tried on its own and the first that answers wins.
        Handing the whole list to one call looks tidier but fails as a unit
        whenever the rotation lands on a blocked engine, which is often. The
        backend that last worked is tried first, so a run does not pay for the
        same dead engine on every row.
        """
        try:
            from ddgs import DDGS
        except ImportError:
            return []
        order = list(self.BACKENDS)
        if self._good_backend in order:
            order.remove(self._good_backend)
            order.insert(0, self._good_backend)
        for backend in order:
            self._pace("search:" + backend)
            try:
                with _quiet_stderr():
                    rows = DDGS(timeout=int(self.timeout)).text(
                        query, backend=backend, max_results=limit * 2)
            except Exception as exc:
                self.search_error = f"{type(exc).__name__}: {exc}"
                continue
            hrefs = [r.get("href", "") for r in rows if r.get("href")]
            if hrefs:
                self.search_error = ""
                self._good_backend = backend
                return hrefs
        return []

    def _search_html(self, query: str, limit: int) -> list[str]:
        """Last resort: scrape DuckDuckGo's HTML endpoint directly."""
        html = self._fetch(self.SEARCH + urllib.parse.quote_plus(query))
        if "anomaly-modal" in html or "anomaly_modal" in html:
            self.search_error = "search engine served an anti-bot page"
            return []
        # Results are wrapped in //duckduckgo.com/l/?uddg=<percent-encoded url>.
        out = [urllib.parse.unquote(u) for u in re.findall(r"uddg=([^\"&'<>]+)", html)]
        return out + re.findall(r'href="(https?://[^"]+)"', html)

    def _search_urls(self, query: str, limit: int = 5) -> list[str]:
        if query in self._search_cache:
            return self._search_cache[query]
        candidates = self._search_ddgs(query, limit) or self._search_html(query, limit)
        urls, seen = [], set()
        for href in candidates:
            if not self._keep(href) or href in seen:
                continue
            seen.add(href)
            urls.append(href)
            if len(urls) >= limit:
                break
        self._search_cache[query] = urls
        return urls

    def _queries(self, prof: Professor) -> list[str]:
        """Search phrasings most likely to surface a current contact page."""
        name = prof.name.strip()
        inst = (prof.institution or "").strip()
        base = f"{name} {inst}".strip()
        out = [f"{base} email", f"{base} contact"]
        # When the institution's own domain is known, ask the engine for that
        # site specifically - it is the one place the address is authoritative.
        host = urllib.parse.urlparse(prof.profile_url or "").netloc.lower()
        host = host.removeprefix("www.")
        if host:
            out.insert(0, f"{name} email site:{host}")
        out.append(f"{name} professor email address")
        return out

    @staticmethod
    def _is_profile_page(url: str) -> bool:
        """A person's page, not an institution's front door.

        Discovery fills Profile URL with the university homepage, which is a
        fine search seed but a terrible source of personal addresses.
        """
        path = urllib.parse.urlparse(url or "").path.strip("/")
        return bool(path) and path not in ("index.html", "index.php", "home", "en", "de")

    def find(self, prof: Professor) -> tuple[str, str, float]:
        """Find the professor's current address. Returns (email, source, score).

        The only question asked is "whose address is this, and did it come from
        a page that owns the domain" - not "does this domain spell out the
        institution written in the spreadsheet", which is never reliable.
        """
        if not prof.name.strip():
            return "", "", 0.0
        pages: list[tuple[str, str]] = []
        if prof.profile_url and self._is_profile_page(prof.profile_url):
            pages.append(("profile page", prof.profile_url))

        seen_urls = {u for _, u in pages}
        for query in self._queries(prof):
            for url in self._search_urls(query, limit=self.max_pages):
                if url not in seen_urls:
                    seen_urls.add(url)
                    pages.append(("web search", url))
            if len(pages) >= self.max_pages + 1:
                break

        best: tuple[float, str, str] = (0.0, "", "")
        # The row's profile URL, when discovery filled it in, is the
        # institution's own domain as published by ROR - real data about this
        # person's employer, not a guess about how a university spells itself.
        inst_host = urllib.parse.urlparse(prof.profile_url or "").netloc.lower()
        inst_host = inst_host.removeprefix("www.")
        for label, url in pages[: self.max_pages + 2]:
            host = urllib.parse.urlparse(url).netloc.lower().removeprefix("www.")
            for email in self._emails_in(self._fetch(url)):
                nm = name_match(prof.name, email)
                if nm < 0.75 or given_name_conflict(prof.name, email):
                    continue
                # A surname-only match on another country's domain is someone else.
                if nm < 1.0 and country_mismatch(prof.country, email):
                    continue
                dom = domain_of(email)
                score = nm
                if same_site(dom, host):
                    score += 1.0          # published on the site that owns it
                elif inst_host and same_site(dom, inst_host):
                    score += 0.75         # their employer's domain, seen elsewhere
                if is_academic(dom):
                    score += 0.5
                if label == "profile page":
                    score += 0.25
                if score > best[0]:
                    best = (score, email, f"{label}: {host}")
            if best[0] >= 2.0:            # name + own domain + academic: done
                break
        return best[1], best[2], best[0]


_CACHE_LOCK = threading.Lock()


def verify_professor(prof: Professor, finder: EmailFinder | None = None,
                     check_dns: bool = True, probe: bool = False,
                     mail_from: str = "", repair: bool = False,
                     cache: dict | None = None) -> EmailCheck:
    """Full check for one row, optionally hunting for the current address.

    When `repair` is on the web lookup runs for *every* row, not just the ones
    that fail the cheap checks - a wrong address usually looks perfectly well
    formed, so the only way to catch it is to go and read the real page.
    """
    found = source = ""
    score = 0.0
    key = f"{prof.name.strip().lower()}|{(prof.institution or '').strip().lower()}"
    if repair and finder:
        with _CACHE_LOCK:
            hit = (cache or {}).get(key)
        if hit and hit.get("score", 0.0) >= 1.75:
            found, source, score = hit.get("email", ""), hit.get("source", ""), hit.get("score", 0.0)
        else:
            # Weak cached matches are rejected below anyway; search again
            # rather than letting an old near-miss block the row forever.
            found, source, score = finder.find(prof)
            if hit and hit.get("score", 0.0) > score:
                found, source, score = hit.get("email", ""), hit.get("source", ""), hit.get("score", 0.0)
            if cache is not None and found:
                # A miss is usually a blocked search engine, not a settled
                # answer - caching it would make the next run miss too.
                with _CACHE_LOCK:
                    cache[key] = {"email": found, "source": source, "score": score}

    known = (domain_of(found),) if found else ()
    res = check_email(prof.name, prof.email, prof.institution, known,
                      check_dns=check_dns, probe=probe, mail_from=mail_from)
    if repair and finder and not found and not (prof.email or "").strip():
        res.reasons = ["no address on this row, and none published on the pages searched"
                       + (f" ({finder.search_error[:60]})" if finder.search_error else "")]
    elif found and score < 1.75 and not (prof.email or "").strip():
        res.reasons = [f"no address on this row; only a weak match found ({found} on "
                       f"{source}), not adopted"]
    if found and score >= 1.75:
        if not (prof.email or "").strip():
            # Rows from `discover` arrive with no address at all; the found
            # one is not a correction, it is the only candidate there is.
            res.suggestion, res.source = found, source
            res.status = SUSPECT
            res.confidence = min(90, int(55 + score * 15))
            res.reasons = [f"no address on the row; their page lists {found}"]
        elif found.lower() != (prof.email or "").lower():
            res.suggestion, res.source = found, source
            if not same_site(domain_of(found), domain_of(prof.email)):
                res.confidence = min(res.confidence, 45)
                res.status = SUSPECT
                res.reasons.append(f"their current page lists {found}")
            else:
                res.reasons.append(f"their page spells it {found}")
        else:
            res.confidence = max(res.confidence, 95)
            res.status = OK
            res.reasons = [f"confirmed on {source}"] if source else res.reasons
    return res


def verify_many(professors: list[Professor], workers: int = 4,
                check_dns: bool = True, probe: bool = False,
                mail_from: str = "", repair: bool = False,
                cache: dict | None = None, apply: bool = False,
                on_result=None) -> dict[str, int]:
    """Verify many rows concurrently; each worker gets its own EmailFinder.

    The finder is I/O-bound (search engines and university pages), so a few
    threads cut a thousand-row recheck from hours to a fraction of that. Each
    finder shares one per-host politeness schedule, so no site is hammered.
    `on_result(index, prof, res)` is called from the main thread, in
    completion order.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    local = threading.local()

    def finder() -> EmailFinder:
        if not hasattr(local, "finder"):
            local.finder = EmailFinder()
        return local.finder

    def work(prof: Professor) -> EmailCheck:
        res = verify_professor(prof, finder=finder(), check_dns=check_dns,
                               probe=probe, mail_from=mail_from,
                               repair=repair, cache=cache)
        old = (prof.email or "").strip()
        # Only replace an address that is missing or failed its checks. An
        # address that passed (same site, name matches) is left alone and the
        # alternative spelling stays in Suggested Email for a human to judge.
        if apply and res.suggestion and (not old or res.status != OK):
            prof.email = res.suggestion
            # Re-check so the row gets the status of the address it now holds.
            res = verify_professor(prof, finder=finder(), check_dns=check_dns,
                                   probe=probe, mail_from=mail_from,
                                   repair=repair, cache=cache)
            if old:
                res.reasons.append(f"replaced {old}")
            if not res.suggestion:
                res.suggestion, res.source = prof.email, "adopted"
        return res

    counts = {OK: 0, SUSPECT: 0, INVALID: 0, UNKNOWN: 0}
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = {pool.submit(work, p): i for i, p in enumerate(professors)}
        for fut in as_completed(futures):
            i = futures[fut]
            prof = professors[i]
            try:
                res = fut.result()
            except Exception as exc:  # one bad page must not sink the batch
                res = EmailCheck(email=prof.email, status=UNKNOWN,
                                 reasons=[f"lookup failed: {type(exc).__name__}"])
            prof.email_status = res.status
            prof.email_confidence = res.confidence
            prof.email_notes = res.summary()
            prof.email_suggestion = (f"{res.suggestion}  ({res.source})"
                                     if res.suggestion else "")
            counts[res.status] = counts.get(res.status, 0) + 1
            if on_result:
                on_result(i, prof, res)
    return counts


def load_cache(path: Path) -> dict:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_cache(path: Path, data: dict) -> None:
    with _CACHE_LOCK:
        snapshot = dict(data)       # workers may still be writing to `data`
    try:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps(snapshot, indent=1), encoding="utf-8")
    except (OSError, TypeError, ValueError):
        pass
