"""OpenAlex enrichment: fetch recent publications and topic concepts per professor.

Free API, no key. Adds high-value personalization context at zero LLM cost.
"""
from __future__ import annotations

import json
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

from .models import Professor
from .tls import urlopen as tls_urlopen

API = "https://api.openalex.org"
_CACHE_VERSION = 1


class OpenAlexClient:
    def __init__(self, mailto: str = "", cache_path: str | Path | None = None,
                 works_per_author: int = 4, timeout: float = 15.0,
                 min_interval: float = 0.12, max_authors: int = 15,
                 api_key: str = ""):
        self.mailto = mailto
        self.api_key = api_key
        self.works_per_author = works_per_author
        self.max_authors = max_authors
        self.timeout = timeout
        self.min_interval = min_interval
        self._last_call = 0.0
        self.rate_limited = False
        self.last_error = ""
        self.cache_path = Path(cache_path) if cache_path else None
        self.cache: dict = {}
        if self.cache_path and self.cache_path.exists():
            try:
                data = json.loads(self.cache_path.read_text(encoding="utf-8"))
                if data.get("_v") == _CACHE_VERSION:
                    self.cache = data
            except (json.JSONDecodeError, OSError):
                self.cache = {}
        self.cache.setdefault("_v", _CACHE_VERSION)

    # --- low level ---
    def _get(self, path: str, params: dict) -> dict | None:
        if self.rate_limited:
            return None
        self.last_error = ""
        if self.mailto:
            params["mailto"] = self.mailto
        if self.api_key:
            params["api_key"] = self.api_key
        url = f"{API}{path}?{urllib.parse.urlencode(params)}"
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
            if exc.code == 429:
                # The free pool is shared per-IP; hammering it further is pointless.
                self.rate_limited = True
                self.last_error = (
                    "OpenAlex rate limit hit (shared free IP budget). "
                    "Set OPENALEX_API_KEY in .env for a free, higher quota."
                )
            else:
                self.last_error = f"HTTP {exc.code}"
            return None
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            return None
        finally:
            self._last_call = time.monotonic()

    # --- helpers ---
    @staticmethod
    def _clean_name(name: str) -> str:
        return re.sub(r"^(Prof\.?|Professor|Dr\.?|PD|Assoc\.?|Asst\.?)\s+", "", name, flags=re.I).strip()

    @staticmethod
    def _reconstruct_abstract(inverted: dict | None, limit: int = 240) -> str:
        if not inverted:
            return ""
        positions: list[tuple[int, str]] = []
        for word, idxs in inverted.items():
            positions.extend((i, word) for i in idxs)
        text = " ".join(w for _, w in sorted(positions))
        return text[:limit]

    def find_author(self, prof: Professor, strict: bool = False) -> dict | None:
        """Best OpenAlex author record for `prof`.

        With `strict`, only a record whose affiliations match the stated
        institution is returned; otherwise the top name hit is used as a
        fallback. Fallbacks are never cached, so a later strict lookup can't
        be fed a namesake at another university.
        """
        name = self._clean_name(prof.name)
        if not name:
            return None
        key = f"author::{name.lower()}::{prof.institution.lower()}"
        if self.cache.get(key):
            return self.cache[key]
        data = self._get("/authors", {"search": name, "per-page": 5})
        best = None
        matched = False
        if data and data.get("results"):
            inst_low = prof.institution.lower()
            for cand in data["results"]:
                affs = " ".join(
                    (a.get("institution") or {}).get("display_name", "")
                    for a in (cand.get("affiliations") or [])
                ).lower()
                last_known = " ".join(
                    i.get("display_name", "")
                    for i in (cand.get("last_known_institutions") or [])
                ).lower()
                blob = affs + " " + last_known
                inst_tokens = [t for t in re.findall(r"[a-z]{4,}", inst_low)
                               if t not in {"university", "institute", "college"}]
                if inst_tokens and any(t in blob for t in inst_tokens):
                    best = cand
                    matched = True
                    break
            if best is None and not strict:
                best = data["results"][0]
        if matched:              # a miss may be a rate limit; retry next time
            self.cache[key] = best
        return best

    def enrich(self, prof: Professor) -> Professor:
        author = self.find_author(prof)
        if not author:
            return prof
        prof.openalex_id = author.get("id", "")
        prof.openalex_concepts = [
            t.get("display_name", "") for t in (author.get("topics") or [])[:8]
            if t.get("display_name")
        ] or [
            c.get("display_name", "") for c in (author.get("x_concepts") or [])[:8]
            if c.get("display_name")
        ]
        if not prof.institution:
            insts = author.get("last_known_institutions") or []
            if insts:
                prof.institution = insts[0].get("display_name", "")

        wkey = f"works::{prof.openalex_id}::{self.works_per_author}::{self.max_authors}"
        if wkey in self.cache:
            prof.recent_works = self.cache[wkey]
            return prof
        works = self._get("/works", {
            "filter": f"author.id:{prof.openalex_id}",
            "sort": "publication_date:desc",
            "per-page": max(self.works_per_author * 6, 25),
            "select": "title,publication_year,abstract_inverted_index,authorships",
        })
        candidates = []
        for w in (works or {}).get("results", []):
            title = (w.get("title") or "").strip()
            if not title:
                continue
            authorships = w.get("authorships") or []
            n_authors = len(authorships)
            # Mega-collaboration papers (ATLAS/CMS) say nothing about the PI's own work.
            if n_authors > self.max_authors:
                continue
            position = next(
                (a.get("author_position") for a in authorships
                 if (a.get("author") or {}).get("id") == prof.openalex_id),
                "middle",
            )
            year = w.get("publication_year", 0) or 0
            abstract = self._reconstruct_abstract(w.get("abstract_inverted_index"), 180)
            entry = f"{title} ({year})"
            if abstract:
                entry += f" - {abstract}"
            lead_bonus = 1 if position in ("first", "last") else 0
            candidates.append((lead_bonus, year, entry))
        candidates.sort(key=lambda c: (-c[0], -c[1]))
        titles, seen_titles = [], set()
        for _, _, entry in candidates:
            norm_title = re.sub(r"\W+", "", entry.split(" (")[0]).lower()[:80]
            if norm_title in seen_titles:
                continue
            seen_titles.add(norm_title)
            titles.append(entry)
            if len(titles) >= self.works_per_author:
                break
        prof.recent_works = titles
        self.cache[wkey] = titles
        return prof

    def enrich_all(self, professors: list[Professor], progress=None) -> list[Professor]:
        for i, p in enumerate(professors, 1):
            if self.rate_limited:
                break
            try:
                self.enrich(p)
            except Exception as exc:
                self.last_error = f"{type(exc).__name__}: {exc}"
            if progress:
                progress(i, len(professors), p)
        self.save_cache()
        return professors

    def save_cache(self) -> None:
        if not self.cache_path:
            return
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.cache_path.write_text(json.dumps(self.cache), encoding="utf-8")
        except OSError:
            pass
