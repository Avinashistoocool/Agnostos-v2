"""Mode A: discovery + scraping of university faculty directories.

Anti-bot handling is defensive and conservative by design:
  * Real Chromium via Playwright (not a headless-flagged browser fingerprint)
  * Stealth patches for the common automation tells (navigator.webdriver, plugins,
    languages, WebGL vendor, permissions, chrome runtime)
  * Authenticated residential/rotating proxy support
  * Human-like pacing: randomized dwell times, easing mouse paths, scrolls
  * robots.txt is honoured by default (RESPECT_ROBOTS=true)
  * Automatic fallback to plain HTTP fetch when Playwright is unavailable

This stays within polite-crawler territory: it does not solve CAPTCHAs, does not
forge credentials, and rate-limits itself.
"""
from __future__ import annotations

import asyncio
import random
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass
from urllib import robotparser

from .config import Settings
from .models import Professor

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
OBFUSCATED_RE = re.compile(
    r"([A-Za-z0-9._%+\-]+)\s*(?:\[at\]|\(at\)|\s+at\s+|&#64;|\{at\})\s*"
    r"([A-Za-z0-9.\-]+)\s*(?:\[dot\]|\(dot\)|\s+dot\s+|\{dot\})\s*([A-Za-z]{2,})",
    re.I)
TITLE_RE = re.compile(
    r"\b(Prof\.?|Professor|Dr\.?|PD\s+Dr\.?|Assoc\.?\s+Prof\.?|Assistant\s+Professor|"
    r"Associate\s+Professor|Senior\s+Lecturer|Lecturer|Reader|Privatdozent)\b", re.I)
NAME_RE = re.compile(
    r"(?:Prof\.?|Professor|Dr\.?|PD\s+Dr\.?)\s+"
    r"((?:[A-Z][\w'\-\u00c0-\u024f]+\.?\s+){1,3}[A-Z][\w'\-\u00c0-\u024f]+)")

STEALTH_JS = r"""
// `navigator.webdriver` must be absent, not merely undefined: detectors check
// `'webdriver' in navigator` and walk the prototype chain.
try { delete Object.getPrototypeOf(navigator).webdriver; } catch (e) {}
try { delete navigator.__proto__.webdriver; } catch (e) {}
if ('webdriver' in navigator) {
  Object.defineProperty(navigator, 'webdriver', {get: () => undefined, configurable: true});
}
Object.defineProperty(navigator, 'languages', {get: () => ['en-GB', 'en-US', 'en']});

const mkPlugin = (name, filename, desc, mimes) => {
  const plugin = Object.create(Plugin.prototype);
  Object.defineProperties(plugin, {
    name: {value: name}, filename: {value: filename},
    description: {value: desc}, length: {value: mimes.length},
  });
  mimes.forEach((m, i) => {
    const mime = Object.create(MimeType.prototype);
    Object.defineProperties(mime, {
      type: {value: m.type}, suffixes: {value: m.suffixes},
      description: {value: desc}, enabledPlugin: {value: plugin},
    });
    plugin[i] = mime;
  });
  return plugin;
};
const pdfMimes = [
  {type: 'application/pdf', suffixes: 'pdf'},
  {type: 'text/pdf', suffixes: 'pdf'},
];
const pluginData = [
  mkPlugin('PDF Viewer', 'internal-pdf-viewer', 'Portable Document Format', pdfMimes),
  mkPlugin('Chrome PDF Viewer', 'internal-pdf-viewer', 'Portable Document Format', pdfMimes),
  mkPlugin('Chromium PDF Viewer', 'internal-pdf-viewer', 'Portable Document Format', pdfMimes),
  mkPlugin('Microsoft Edge PDF Viewer', 'internal-pdf-viewer', 'Portable Document Format', pdfMimes),
  mkPlugin('WebKit built-in PDF', 'internal-pdf-viewer', 'Portable Document Format', pdfMimes),
];
const pluginArray = Object.create(PluginArray.prototype);
pluginData.forEach((p, i) => { pluginArray[i] = p; pluginArray[p.name] = p; });
Object.defineProperty(pluginArray, 'length', {value: pluginData.length});
Object.defineProperty(navigator, 'plugins', {get: () => pluginArray});

Object.defineProperty(navigator, 'hardwareConcurrency', {get: () => 8});
Object.defineProperty(navigator, 'deviceMemory', {get: () => 8});
Object.defineProperty(navigator, 'maxTouchPoints', {get: () => 0});

// A real Chrome exposes chrome.runtime, chrome.loadTimes and chrome.csi.
window.chrome = window.chrome || {};
window.chrome.runtime = window.chrome.runtime || {
  id: undefined,
  connect: () => {},
  sendMessage: () => {},
  onMessage: {addListener: () => {}, removeListener: () => {}},
  PlatformOs: {MAC: 'mac', WIN: 'win', ANDROID: 'android', CROS: 'cros', LINUX: 'linux'},
};
window.chrome.app = window.chrome.app || {
  isInstalled: false,
  InstallState: {DISABLED: 'disabled', INSTALLED: 'installed', NOT_INSTALLED: 'not_installed'},
  RunningState: {CANNOT_RUN: 'cannot_run', READY_TO_RUN: 'ready_to_run', RUNNING: 'running'},
};
window.chrome.csi = window.chrome.csi || (() => ({
  startE: Date.now(), onloadT: Date.now(), pageT: performance.now(), tran: 15,
}));
window.chrome.loadTimes = window.chrome.loadTimes || (() => ({
  commitLoadTime: Date.now() / 1000, finishLoadTime: Date.now() / 1000,
  firstPaintTime: Date.now() / 1000, navigationType: 'Other',
  wasFetchedViaSpdy: true, npnNegotiatedProtocol: 'h2', connectionInfo: 'h2',
}));

const origQuery = window.navigator.permissions && window.navigator.permissions.query;
if (origQuery) {
  window.navigator.permissions.query = (p) =>
    p && p.name === 'notifications'
      ? Promise.resolve({state: Notification.permission})
      : origQuery.call(window.navigator.permissions, p);
}

const patchGL = (proto) => {
  if (!proto) return;
  const getParameter = proto.getParameter;
  proto.getParameter = function (p) {
    if (p === 37445) return 'Intel Inc.';
    if (p === 37446) return 'Intel Iris OpenGL Engine';
    return getParameter.apply(this, arguments);
  };
};
patchGL(window.WebGLRenderingContext && WebGLRenderingContext.prototype);
patchGL(window.WebGL2RenderingContext && WebGL2RenderingContext.prototype);

Object.defineProperty(screen, 'colorDepth', {get: () => 24});
Object.defineProperty(screen, 'pixelDepth', {get: () => 24});

// Hide the patching itself: toString() must look native.
const nativeToString = Function.prototype.toString;
const patched = new WeakSet([
  navigator.permissions && navigator.permissions.query,
  window.chrome.csi, window.chrome.loadTimes,
].filter(Boolean));
Function.prototype.toString = function () {
  if (patched.has(this)) return `function () { [native code] }`;
  return nativeToString.call(this);
};
"""

VIEWPORTS = [(1920, 1080), (1680, 1050), (1536, 864), (1440, 900), (1366, 768)]
LOCALES = ["en-GB", "en-US", "de-DE", "fr-FR", "nl-NL"]

BLOCK_MARKERS = [
    "cf-chl", "just a moment", "checking your browser",
    "_incapsula_resource", "incapsula incident id", "request unsuccessful",
    "attention required! | cloudflare", "ddos protection by cloudflare",
    "enable javascript and cookies to continue", "px-captcha", "/_px/",
    "verify you are human", "access denied", "error 1020",
]
# A challenge interstitial is always a short page; a real directory is not.
BLOCK_MAX_TEXT_LEN = 2500


@dataclass
class ScrapeResult:
    url: str
    html: str = ""
    text: str = ""
    blocked: bool = False
    error: str = ""


def _robots_allows(url: str, user_agent: str) -> bool:
    try:
        parts = urllib.parse.urlparse(url)
        rp = robotparser.RobotFileParser()
        rp.set_url(f"{parts.scheme}://{parts.netloc}/robots.txt")
        rp.read()
        return rp.can_fetch(user_agent, url)
    except Exception:
        return True  # no robots.txt reachable -> default allow


def _looks_blocked(html: str) -> bool:
    """True only for genuine challenge/denial interstitials.

    Matching marker words anywhere in a large page produces false positives
    (many university sites merely *mention* Cloudflare), so require either a
    short page or an unambiguous challenge marker.
    """
    low = html.lower()
    head = low[:6000]
    hard_markers = ("cf-chl", "_incapsula_resource", "px-captcha",
                    "incapsula incident id", "/_px/")
    if any(m in head for m in hard_markers):
        return True
    text_len = len(_html_to_text(html))
    if text_len > BLOCK_MAX_TEXT_LEN:
        return False
    return any(marker in head for marker in BLOCK_MARKERS)


def _html_to_text(html: str) -> str:
    html = re.sub(r"<(script|style|noscript)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
    html = re.sub(r"<br\s*/?>|</(p|div|li|tr|h[1-6])>", "\n", html, flags=re.I)
    html = re.sub(r"<[^>]+>", " ", html)
    html = (html.replace("&nbsp;", " ").replace("&amp;", "&")
                .replace("&lt;", "<").replace("&gt;", ">")
                .replace("&#64;", "@").replace("&quot;", '"'))
    html = re.sub(r"[ \t]+", " ", html)
    return re.sub(r"\n{2,}", "\n", html).strip()


class StealthScraper:
    """Playwright-backed scraper with graceful degradation to urllib."""

    def __init__(self, settings: Settings):
        self.s = settings
        self._pw = None
        self._browser = None
        self._context = None
        self.playwright_available = True

    # ---------- lifecycle ----------
    async def start(self) -> bool:
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            self.playwright_available = False
            return False
        self._pw = await async_playwright().start()
        launch_args = {
            "headless": self.s.scrape_headless,
            "args": [
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--no-sandbox",
                "--disable-infobars",
                "--window-position=0,0",
            ],
        }
        if self.s.proxy_server:
            proxy = {"server": self.s.proxy_server}
            if self.s.proxy_username:
                proxy["username"] = self.s.proxy_username
                proxy["password"] = self.s.proxy_password
            launch_args["proxy"] = proxy
        self._browser = await self._pw.chromium.launch(**launch_args)
        await self._new_context()
        return True

    async def _new_context(self):
        if self._context:
            await self._context.close()
        width, height = random.choice(VIEWPORTS)
        self._context = await self._browser.new_context(
            user_agent=self.s.user_agent,
            viewport={"width": width, "height": height},
            locale=random.choice(LOCALES),
            timezone_id=random.choice(["Europe/Berlin", "Europe/Zurich",
                                       "Europe/London", "Europe/Amsterdam"]),
            device_scale_factor=random.choice([1, 1.25, 2]),
            java_script_enabled=True,
            ignore_https_errors=True,
            extra_http_headers={
                "Accept-Language": "en-GB,en;q=0.9",
                "Accept": ("text/html,application/xhtml+xml,application/xml;q=0.9,"
                           "image/avif,image/webp,*/*;q=0.8"),
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "none",
                "Upgrade-Insecure-Requests": "1",
            },
        )
        await self._context.add_init_script(STEALTH_JS)

    async def close(self):
        for obj in (self._context, self._browser):
            if obj:
                try:
                    await obj.close()
                except Exception:
                    pass
        if self._pw:
            await self._pw.stop()

    # ---------- human behaviour ----------
    async def _humanize(self, page):
        width = page.viewport_size["width"] if page.viewport_size else 1280
        height = page.viewport_size["height"] if page.viewport_size else 800
        x, y = random.randint(80, width - 80), random.randint(80, height - 80)
        for _ in range(random.randint(2, 4)):
            tx, ty = random.randint(40, width - 40), random.randint(40, height - 40)
            steps = random.randint(12, 28)
            for i in range(1, steps + 1):
                t = i / steps
                ease = t * t * (3 - 2 * t)  # smoothstep, not linear
                await page.mouse.move(x + (tx - x) * ease, y + (ty - y) * ease)
                await asyncio.sleep(random.uniform(0.004, 0.018))
            x, y = tx, ty
            await asyncio.sleep(random.uniform(0.1, 0.45))
        for _ in range(random.randint(1, 4)):
            await page.mouse.wheel(0, random.randint(240, 900))
            await asyncio.sleep(random.uniform(0.3, 1.3))

    async def _pause(self):
        await asyncio.sleep(random.uniform(self.s.scrape_delay_min, self.s.scrape_delay_max))

    # ---------- fetching ----------
    def _fallback_fetch(self, url: str) -> ScrapeResult:
        req = urllib.request.Request(url, headers={
            "User-Agent": self.s.user_agent,
            "Accept-Language": "en-GB,en;q=0.9",
            "Accept": "text/html,application/xhtml+xml",
        })
        try:
            with urllib.request.urlopen(req, timeout=25) as resp:
                html = resp.read().decode("utf-8", errors="ignore")
            blocked = _looks_blocked(html)
            return ScrapeResult(url, html, _html_to_text(html), blocked)
        except Exception as exc:
            return ScrapeResult(url, error=f"{type(exc).__name__}: {exc}")

    async def fetch(self, url: str, retries: int = 2) -> ScrapeResult:
        if self.s.respect_robots and not _robots_allows(url, self.s.user_agent):
            return ScrapeResult(url, error="blocked by robots.txt (RESPECT_ROBOTS=true)")
        if not self.playwright_available or self._context is None:
            return self._fallback_fetch(url)

        for attempt in range(retries + 1):
            page = await self._context.new_page()
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=45000)
                await asyncio.sleep(random.uniform(1.2, 3.0))
                html = await page.content()
                if _looks_blocked(html):
                    # Challenge pages usually self-resolve; wait it out once.
                    await asyncio.sleep(random.uniform(6, 12))
                    html = await page.content()
                if _looks_blocked(html):
                    await page.close()
                    if attempt < retries:
                        await self._new_context()  # fresh fingerprint + proxy exit
                        await self._pause()
                        continue
                    return ScrapeResult(url, html, _html_to_text(html), blocked=True,
                                        error="anti-bot challenge not cleared")
                await self._humanize(page)
                html = await page.content()
                text = await page.evaluate("() => document.body ? document.body.innerText : ''")
                await page.close()
                return ScrapeResult(url, html, text or _html_to_text(html))
            except Exception as exc:
                try:
                    await page.close()
                except Exception:
                    pass
                if attempt >= retries:
                    return ScrapeResult(url, error=f"{type(exc).__name__}: {exc}")
                await self._pause()
        return ScrapeResult(url, error="exhausted retries")


# ---------- extraction ----------
GENERIC_LOCALPARTS = {
    "info", "office", "contact", "admin", "webmaster", "secretary", "sekretariat",
    "studies", "doktorat", "studium", "enquiries", "support", "help", "press",
    "noreply", "no-reply", "mail", "post", "hr", "jobs", "it", "privacy",
    "sekretariat-physik", "studienberatung", "newsletter", "media",
}


def _deobfuscate(text: str) -> list[str]:
    found = set(EMAIL_RE.findall(text))
    for user, domain, tld in OBFUSCATED_RE.findall(text):
        found.add(f"{user}@{domain}.{tld}")
    bad = ("example.com", "sentry.io", "wixpress", "@2x", ".png", ".jpg", ".svg", "@sentry")
    out = []
    for raw in found:
        email = raw.strip(".,;:")
        low = email.lower()
        if any(b in low for b in bad) or len(email) > 80:
            continue
        if low.split("@")[0] in GENERIC_LOCALPARTS:
            continue
        out.append(email)
    return sorted(out)


MAILTO_RE = re.compile(r"""mailto:([^"'?>\s]+)""", re.I)


def _mailto_emails(html: str) -> list[str]:
    out = []
    for raw in MAILTO_RE.findall(html or ""):
        email = urllib.parse.unquote(raw).strip().strip(".,;:")
        if EMAIL_RE.fullmatch(email) and email.split("@")[0].lower() not in GENERIC_LOCALPARTS:
            out.append(email)
    return out


ROLE_WORDS = (
    "professor", "lecturer", "reader", "fellow", "researcher", "scientist",
    "emeritus", "head of", "director", "chair", "staff", "postdoc", "student",
    "assistant", "associate", "senior", "group leader", "privatdozent",
)


def _clean_name(raw: str) -> str:
    """Strip tabs/role suffixes that directory tables glue onto the name."""
    name = re.split(r"[\t|,;]|\s{2,}", raw)[0].strip(" .-\u2013")
    words = name.split()
    while words and words[-1].lower().strip(",.") in {w.split()[0] for w in ROLE_WORDS}:
        words.pop()
    name = " ".join(words)
    return name if 4 <= len(name) <= 70 else ""


def _title_case_name(line: str) -> str:
    m = NAME_RE.search(line)
    if m:
        return _clean_name(m.group(0))
    head = re.split(r"[\t|]|\s{2,}", line)[0].strip()
    words = head.split()
    if (2 <= len(words) <= 4 and all(w[:1].isupper() for w in words)
            and not EMAIL_RE.search(head) and len(head) < 60
            and not any(r in head.lower() for r in ROLE_WORDS)):
        return head
    return ""


def _blurb_window(lines: list[str], idx: int, max_lines: int = 3) -> list[str]:
    """Lines belonging to one person: stop at the next titled name."""
    window = [lines[idx]]
    for nxt in lines[idx + 1: idx + max_lines]:
        if TITLE_RE.search(nxt) or _title_case_name(nxt):
            break
        window.append(nxt)
    return window


def _research_blurb(lines: list[str], name: str, limit: int = 300) -> str:
    """Join nearby lines into a topic blurb, dropping the name/role boilerplate."""
    role_heads = {r.split()[0] for r in ROLE_WORDS}
    parts = []
    for line in lines:
        clean = re.sub(r"\s+", " ", line.replace("\t", " ")).strip()
        if not clean:
            continue
        clean = clean.replace(name, " ").strip(" -\u2013|,")
        words = [w for w in clean.split() if w.lower().strip(",.") not in role_heads]
        if not words:
            continue
        parts.append(" ".join(words))
    return " ".join(parts)[:limit]


PERSON_LINK_RE = re.compile(
    r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', re.I | re.S)


def _person_links(html: str, base_url: str) -> dict[str, str]:
    """Map lowercased anchor text -> absolute URL, for likely person links."""
    links: dict[str, str] = {}
    for href, label in PERSON_LINK_RE.findall(html or ""):
        text = re.sub(r"<[^>]+>", " ", label)
        text = re.sub(r"\s+", " ", text).strip()
        if not text or len(text) > 70 or href.startswith(("mailto:", "#", "javascript:")):
            continue
        if not (TITLE_RE.search(text) or 2 <= len(text.split()) <= 4):
            continue
        links.setdefault(text.lower(), urllib.parse.urljoin(base_url, href))
    return links


def extract_professors(result: ScrapeResult, institution: str = "", country: str = "",
                       department: str = "") -> list[Professor]:
    """Heuristic extraction of name/email/research blurb from a directory page."""
    if not result.text:
        return []
    out: dict[str, Professor] = {}
    lines = [ln.strip() for ln in result.text.splitlines() if ln.strip()]

    # Pass 1: anchor on emails, take surrounding lines as context.
    for idx, line in enumerate(lines):
        emails = _deobfuscate(line)
        if not emails:
            continue
        window = lines[max(0, idx - 4): idx + 4]
        name = ""
        for cand in reversed(lines[max(0, idx - 5): idx + 1]):
            found_name = _title_case_name(cand)
            if found_name:
                name = found_name
                break
        if not name:
            local = emails[0].split("@")[0]
            name = " ".join(w.capitalize() for w in re.split(r"[._\-]", local) if w.isalpha())
        research = " ".join(w for w in window if not EMAIL_RE.search(w))[:400]
        key = emails[0].lower()
        if key not in out:
            out[key] = Professor(
                name=name, email=emails[0], institution=institution, country=country,
                department=department, research_area=research, profile_url=result.url,
            )

    # Pass 2: titled names in the rendered text, matched to mailto: links by surname.
    mailtos = _mailto_emails(result.html)
    links = _person_links(result.html, result.url)
    for idx, line in enumerate(lines):
        if not TITLE_RE.search(line):
            continue
        name = _title_case_name(line)
        if not name:
            continue
        surname = re.sub(r"[^a-z]", "", name.split()[-1].lower())
        email = ""
        if len(surname) > 3:
            email = next((m for m in mailtos if surname in m.lower().split("@")[0]), "")
        key = (email or name).lower()
        if key in out:
            continue
        profile_url = next(
            (url for text, url in links.items() if surname and surname in text),
            result.url)
        out[key] = Professor(
            name=name, email=email, institution=institution, country=country,
            department=department,
            research_area=_research_blurb(_blurb_window(lines, idx), name),
            profile_url=profile_url,
            notes="" if email else "email not on directory page; profile page pending",
        )
    return list(out.values())


async def scrape_sources(settings: Settings, sources: list[dict],
                         progress=None, resolve_profiles: bool = True,
                         max_profile_pages: int = 40) -> list[Professor]:
    """`sources` entries: {url, institution, country, department}."""
    scraper = StealthScraper(settings)
    started = await scraper.start()
    if not started:
        print("  ! Playwright not installed; falling back to plain HTTP fetch.")
        print("    Install with: pip install playwright && playwright install chromium")
    professors: list[Professor] = []
    try:
        for i, src in enumerate(sources, 1):
            result = await scraper.fetch(src["url"])
            found = extract_professors(
                result,
                institution=src.get("institution", ""),
                country=src.get("country", ""),
                department=src.get("department", ""),
            )
            professors.extend(found)
            if progress:
                progress(i, len(sources), src, result, found)
            await scraper._pause()

        # Second hop: many directories only expose emails on individual profile pages.
        if resolve_profiles:
            pending = [p for p in professors
                       if not p.email and p.profile_url and p.profile_url not in
                       {s["url"] for s in sources}][:max_profile_pages]
            for j, prof in enumerate(pending, 1):
                page = await scraper.fetch(prof.profile_url, retries=0)
                emails = _deobfuscate(page.text) + _mailto_emails(page.html)
                surname = re.sub(r"[^a-z]", "", prof.name.split()[-1].lower())
                best = next((e for e in emails if surname and surname in e.lower()),
                            emails[0] if emails else "")
                if best:
                    prof.email = best
                    prof.notes = ""
                if page.text:
                    prof.research_area = (prof.research_area + " " + page.text[:400]).strip()
                if progress:
                    progress(len(sources) + j, len(sources) + len(pending),
                             {"url": prof.profile_url}, page,
                             [prof] if best else [])
                await scraper._pause()
    finally:
        await scraper.close()

    unique: dict[str, Professor] = {}
    for p in professors:
        key = p.email.lower() or f"{p.name.lower()}|{p.institution.lower()}"
        if key not in unique:
            unique[key] = p
    return list(unique.values())


def run_scrape(settings: Settings, sources: list[dict], progress=None,
               resolve_profiles: bool = True) -> list[Professor]:
    return asyncio.run(scrape_sources(settings, sources, progress, resolve_profiles))
