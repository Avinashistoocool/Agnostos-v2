"""Build a large professor list automatically, from research topic alone.

Scraping faculty directories (Mode A) only reaches the pages you already
thought to list, and a hand-curated spreadsheet (Mode B) caps out at however
many rows you had the patience to type. Neither scales to "mail a few hundred
of the right people".

This module works the other way round: start from *the research*, not from a
university. It asks OpenAlex for recent papers matching your interests,
written in the countries you can actually go to, and keeps the people in the
position that matters - first or last author, i.e. the student who did the
work and the PI who funded it. Group-leader-shaped authors are kept; the
thousand-author ATLAS/CMS papers that name everybody are discarded, because
being author #817 says nothing about what someone works on.

What comes out is a ranked list of real, currently-publishing researchers with
their institution, their topics and their actual recent titles - everything the
matcher and the drafting prompt need. What does *not* come out is an email
address: OpenAlex has none. That is `verify --repair`'s job, which goes and
reads each person's own page. The intended flow is

    discover  ->  verify --repair --apply  ->  run --mode list  ->  send

Free, no API key, no scraping, no rate-limit roulette.
"""
from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .models import Professor
from .tls import urlopen as tls_urlopen

API = "https://api.openalex.org"
ROR_API = "https://api.ror.org/organizations/"

# ISO-3166 alpha-2 for the regions people actually ask for, so `--countries
# europe` beats typing twenty-six codes. Not an attempt at geopolitics.
COUNTRY_GROUPS = {
    "europe": ["at", "be", "bg", "ch", "cy", "cz", "de", "dk", "ee", "es", "fi",
               "fr", "gb", "gr", "hr", "hu", "ie", "is", "it", "lt", "lu", "lv",
               "mt", "nl", "no", "pl", "pt", "ro", "rs", "se", "si", "sk"],
    "eu": ["at", "be", "bg", "cy", "cz", "de", "dk", "ee", "es", "fi", "fr",
           "gr", "hr", "hu", "ie", "it", "lt", "lu", "lv", "mt", "nl", "pl",
           "pt", "ro", "se", "si", "sk"],
    "dach": ["de", "at", "ch"],
    "nordics": ["dk", "fi", "is", "no", "se"],
    "uk": ["gb"],
    "usa": ["us"],
    "northamerica": ["us", "ca"],
    "asia": ["cn", "jp", "kr", "sg", "hk", "tw", "in", "il"],
    "anz": ["au", "nz"],
}

# Institution types that can host a visiting student. Companies and hospitals
# occasionally can too, but they do not run the application routes this tool
# writes to, so they are noise by default.
DEFAULT_INST_TYPES = ["education", "facility"]


def _this_year() -> int:
    return datetime.now().year


_INITIAL_RE = re.compile(r"^[A-Z]\.?$")
_TITLE_RE = re.compile(r"^(dr|prof|professor|priv|doz|dipl|ing|mr|ms|mrs|phd)\b\.?\s*",
                       re.IGNORECASE)
# Trailing degrees and stray ids that some records append: "Jane Doe PhD", "X (12345)".
_SUFFIX_RE = re.compile(r"(\s*\([^)]*\)|[\s,]+(phd|ph\.d\.?|md|msc|dr|jr|sr)\.?)+\s*$",
                        re.IGNORECASE)


def _clean_name(raw: str) -> str:
    name = _SUFFIX_RE.sub("", _TITLE_RE.sub("", (raw or "").strip())).strip()
    if not name or "," in name:              # "Golling, T." - bibliography form
        return ""
    # Some records shout: "TOBIAS GOLLING". Nobody writes a greeting that way.
    words = [w.title() if len(w) > 3 and w.isupper() else w for w in name.split()]
    out: list[str] = []
    for w in words:                          # "Faruk Bulut Bulut"
        if not out or out[-1].lower() != w.lower():
            out.append(w)
    return " ".join(out)


def _fold(text: str) -> str:
    import unicodedata
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()


def _best_name(names: list[str]) -> str:
    """Pick the most spelled-out form of the *same* name.

    Papers routinely credit "T. Golling", but an email greeting needs "Dear
    Professor Golling" and the address finder needs "Tobias" to recognise
    `tobias.golling@`. OpenAlex lists the alternatives it has seen; prefer one
    that expands initials of the primary name. Alternatives are also polluted
    with co-authors' names merged in, so an alternative must keep the same
    surname and must not add more than one word.
    """
    cleaned = [c for c in (_clean_name(n) for n in names) if c]
    if not cleaned:
        return names[0] if names else ""
    primary = cleaned[0]
    p_words = primary.split()
    surname = _fold(p_words[-1])

    def key(name: str):
        words = name.split()
        full = sum(1 for w in words if not _INITIAL_RE.match(w) and len(w) > 1)
        return (full, -sum(1 for w in words if _INITIAL_RE.match(w)), -len(words))

    best = primary
    for alt in cleaned[1:]:
        words = alt.split()
        if _fold(words[-1]) != surname or len(words) > len(p_words) + 1:
            continue
        if key(alt) > key(best):
            best = alt
    return best


def work_field(work: dict) -> str:
    """The broad field (e.g. 'Physics and Astronomy') OpenAlex filed a work under."""
    return (((work.get("primary_topic") or {}).get("field") or {})
            .get("display_name") or "")


def home_fields(works: list[dict], top: int = 30, share: float = 0.15) -> list[str]:
    """Fields that make up a real share of a query's best-matching papers.

    Free-text search matches words, not meaning: "geometric deep learning"
    also returns dentistry papers that mention geometry. The query's own top
    results say what it is actually about, so keep only works from those
    fields - learned per query, no subject list needed.
    """
    best = sorted(works, key=lambda w: -(w.get("relevance_score") or 0))[:top]
    counts: dict[str, int] = {}
    for w in best:
        f = work_field(w)
        if f:
            counts[f] = counts.get(f, 0) + 1
    n = sum(counts.values())
    return [f for f, c in counts.items() if n and c / n >= share]


def resolve_countries(spec: str) -> list[str]:
    """'europe', 'de,ch,uk' or 'dach,fr' -> a flat list of alpha-2 codes."""
    out: list[str] = []
    for part in re.split(r"[,\s]+", (spec or "").strip().lower()):
        if not part:
            continue
        if part in COUNTRY_GROUPS:
            out.extend(COUNTRY_GROUPS[part])
        else:
            # OpenAlex wants ISO-3166; people write "uk" for "gb".
            out.append({"uk": "gb", "en": "gb", "eu": "eu"}.get(part, part))
    seen, uniq = set(), []
    for c in out:
        if len(c) == 2 and c not in seen:
            seen.add(c)
            uniq.append(c)
    return uniq


@dataclass
class Candidate:
    """One researcher accumulated across however many papers matched."""
    author_id: str
    name: str = ""
    orcid: str = ""
    institution: str = ""
    country: str = ""
    ror: str = ""
    hits: int = 0
    lead_hits: int = 0
    newest_year: int = 0
    relevance: float = 0.0
    titles: list[str] = field(default_factory=list)
    topics: list[str] = field(default_factory=list)
    works_count: int = 0
    cited_by_count: int = 0
    h_index: int = 0

    @property
    def score(self) -> float:
        """How strongly this person is a *current PI in this topic*.

        Repeat appearances dominate (someone who shows up in four matching
        papers is working on it, not passing through), last-author position
        is worth more than first, and recency decays over five years.
        """
        recency = (max(0.0, 1.0 - (_this_year() - self.newest_year) / 5.0)
                   if self.newest_year else 0.0)
        return (self.hits * 1.0 + self.lead_hits * 0.6 + recency * 2.0
                + min(self.h_index, 60) / 60.0)


class Discoverer:
    """Topic -> ranked list of real researchers, via the OpenAlex works index."""

    def __init__(self, mailto: str = "", api_key: str = "",
                 cache_path: str | Path | None = None, timeout: float = 30.0,
                 min_interval: float = 0.15, max_authors_per_work: int = 15):
        self.mailto = mailto
        self.api_key = api_key
        self.timeout = timeout
        self.min_interval = min_interval
        self.max_authors_per_work = max_authors_per_work
        self.last_error = ""
        self.pages_read = 0
        self.works_seen = 0
        self._last_call = 0.0
        self.cache_path = Path(cache_path) if cache_path else None
        self.cache: dict = {}
        if self.cache_path and self.cache_path.exists():
            try:
                self.cache = json.loads(self.cache_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                self.cache = {}

    # ---------------------------------------------------------- transport
    def _get(self, url: str) -> dict | None:
        # Describes the most recent request only; a stale error would make a
        # genuinely finished topic look like a failure for the rest of the run.
        self.last_error = ""
        wait = self.min_interval - (time.monotonic() - self._last_call)
        if wait > 0:
            time.sleep(wait)
        req = urllib.request.Request(url, headers={
            "User-Agent": f"academic-outreach-tool (mailto:{self.mailto or 'anonymous'})",
            "Accept": "application/json",
        })
        try:
            with tls_urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            self.last_error = (
                "OpenAlex rate limit hit; set OPENALEX_API_KEY in .env for a "
                "free higher quota." if exc.code == 429 else f"HTTP {exc.code}")
            return None
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            return None
        finally:
            self._last_call = time.monotonic()

    def _api(self, path: str, params: dict) -> dict | None:
        if self.mailto:
            params["mailto"] = self.mailto
        if self.api_key:
            params["api_key"] = self.api_key
        return self._get(f"{API}{path}?{urllib.parse.urlencode(params)}")

    # ------------------------------------------------------------ domains
    def ror_domains(self, ror: str) -> tuple[str, str]:
        """ROR id -> (primary mail domain, homepage). Authoritative and free.

        OpenAlex institution records carry a `ror` but their `homepage_url` is
        always null, so this is the only way to learn that Durham University
        is `durham.ac.uk` without hardcoding a table of universities.
        """
        if not ror:
            return "", ""
        rid = ror.rstrip("/").rsplit("/", 1)[-1]
        key = f"ror::{rid}"
        if key in self.cache:
            hit = self.cache[key]
            return hit.get("domain", ""), hit.get("homepage", "")
        data = self._get(ROR_API + rid) or {}
        domain = (data.get("domains") or [""])[0]
        homepage = next((l.get("value", "") for l in (data.get("links") or [])
                         if l.get("type") == "website"), "")
        self.cache[key] = {"domain": domain, "homepage": homepage}
        return domain, homepage

    # ------------------------------------------------------------- search
    def _work_filter(self, countries: list[str], since_year: int,
                     inst_types: list[str]) -> str:
        # `has_doi` drops preprint duplicates and conference junk entries.
        parts = [f"from_publication_date:{since_year}-01-01",
                 "type:article", "has_doi:true"]
        if countries:
            parts.append("authorships.countries:" + "|".join(countries))
        if inst_types:
            parts.append("authorships.institutions.type:" + "|".join(inst_types))
        return ",".join(parts)

    def fetch_page(self, query: str, countries: list[str], since_year: int,
                   cursor: str = "*", per_page: int = 100,
                   inst_types: list[str] | None = None) -> tuple[list[dict], str, int]:
        """One page of matching works -> (works, next_cursor, total_matches).

        Exposed separately so batched discovery can stop and resume a query
        at exactly the page it reached.
        """
        flt = self._work_filter(countries, since_year,
                                inst_types if inst_types is not None else DEFAULT_INST_TYPES)
        data = self._api("/works", {
            "search": query,
            "filter": flt,
            "per-page": per_page,
            "cursor": cursor,
            "select": "id,title,publication_year,authorships,topics,cited_by_count,"
                      "relevance_score,primary_topic",
        })
        if not data or not data.get("results"):
            return [], "", 0
        self.pages_read += 1
        self.works_seen += len(data["results"])
        meta = data.get("meta") or {}
        return data["results"], meta.get("next_cursor") or "", meta.get("count", 0)

    def fold(self, work: dict, people: dict[str, Candidate],
             countries: list[str]) -> None:
        """Credit one work to its first and last authors."""
        authorships = work.get("authorships") or []
        # Mega-collaboration papers list every member of ATLAS. Nobody on
        # them chose to be there, so they carry no topical signal.
        if not authorships or len(authorships) > self.max_authors_per_work:
            return
        year = work.get("publication_year") or 0
        title = (work.get("title") or "").strip()
        topics = [t.get("display_name", "") for t in (work.get("topics") or [])[:4]]
        for a in authorships:
            position = a.get("author_position")
            if position not in ("first", "last"):
                continue
            author = a.get("author") or {}
            aid = author.get("id") or ""
            insts = [i for i in (a.get("institutions") or []) if i.get("ror")]
            if not aid or not insts:
                continue
            if countries and not any(
                    (i.get("country_code") or "").lower() in countries for i in insts):
                continue
            inst = insts[0]
            cand = people.get(aid)
            if cand is None:
                cand = people[aid] = Candidate(author_id=aid)
            cand.name = cand.name or (author.get("display_name") or "")
            cand.orcid = cand.orcid or (author.get("orcid") or "")
            if not cand.institution or year >= cand.newest_year:
                cand.institution = inst.get("display_name", "") or cand.institution
                cand.country = (inst.get("country_code") or "").upper() or cand.country
                cand.ror = inst.get("ror", "") or cand.ror
            cand.hits += 1
            if position == "last":
                cand.lead_hits += 1
            cand.newest_year = max(cand.newest_year, year)
            if title and len(cand.titles) < 6 and not any(
                    t.startswith(title) for t in cand.titles):
                cand.titles.append(f"{title} ({year})" if year else title)
            for t in topics:
                if t and t not in cand.topics:
                    cand.topics.append(t)

    def hydrate(self, candidates: list[Candidate], progress=None) -> None:
        """Fill in works/citation counts, 50 authors per request.

        Citation history is what separates a group leader from a postdoc with
        one good paper, and a batch filter costs one call per fifty people.
        """
        ids = [c.author_id.rsplit("/", 1)[-1] for c in candidates if c.author_id]
        by_id = {c.author_id.rsplit("/", 1)[-1]: c for c in candidates}
        for start in range(0, len(ids), 50):
            chunk = ids[start:start + 50]
            data = self._api("/authors", {
                "filter": "openalex:" + "|".join(chunk),
                "per-page": 50,
                "select": "id,display_name,display_name_alternatives,works_count,"
                          "cited_by_count,summary_stats,topics",
            })
            if progress:
                progress(min(start + 50, len(ids)), len(ids))
            for row in (data or {}).get("results", []):
                cand = by_id.get((row.get("id") or "").rsplit("/", 1)[-1])
                if not cand:
                    continue
                cand.name = _best_name(
                    [cand.name, row.get("display_name") or ""]
                    + list(row.get("display_name_alternatives") or []))
                cand.works_count = row.get("works_count") or 0
                cand.cited_by_count = row.get("cited_by_count") or 0
                cand.h_index = (row.get("summary_stats") or {}).get("h_index") or 0
                for t in (row.get("topics") or [])[:6]:
                    name = t.get("display_name", "")
                    if name and name not in cand.topics:
                        cand.topics.append(name)

    def save_cache(self) -> None:
        if not self.cache_path:
            return
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            self.cache_path.write_text(json.dumps(self.cache, indent=1), encoding="utf-8")
        except OSError:
            pass


def to_professor(cand: Candidate, homepage: str = "") -> Professor:
    """Candidate -> the record the rest of the pipeline already understands."""
    return Professor(
        name=cand.name,
        email="",                       # verify --repair fills this in
        institution=cand.institution,
        country=cand.country,
        research_area="; ".join(cand.topics[:6]),
        profile_url=homepage,
        notes=(f"{cand.hits} recent matching paper(s), "
               f"{cand.lead_hits} as senior author; "
               f"h-index {cand.h_index}, {cand.works_count} works."),
        recent_works=cand.titles[:4],
        openalex_id=cand.author_id,
        openalex_concepts=cand.topics[:8],
        prior_probability="",
    )
