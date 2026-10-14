"""Recheck that each professor on the list is still who and where the row says.

Email verification answers "is this the right address"; this answers the
question before it - "is this person still publishing, and still at this
institution". People move, retire, and go quiet, and an internship request
to someone who left three years ago is wasted.

Everything comes from the person's OpenAlex author record (by id when the
row has one, by name otherwise): their last known institutions and their
publication counts per year. No institution tables, no keyword lists.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime

from .enrich import OpenAlexClient
from .models import Professor

ACTIVE = "active"
MOVED = "moved"
INACTIVE = "inactive"
NOT_FOUND = "not found"

_STOP = {"university", "universitat", "universite", "universita", "universidad",
         "institute", "institut", "instituto", "istituto", "college", "school",
         "of", "the", "and", "for", "de", "di", "der", "des", "la", "le", "fur",
         "national", "technical", "technology", "sciences", "science", "research",
         "center", "centre", "zentrum", "and", "di", "degli", "studi"}


def _tokens(text: str) -> set[str]:
    folded = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    return {w for w in re.findall(r"[a-z]{3,}", folded.lower()) if w not in _STOP}


def _fold(text: str) -> str:
    return unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().lower()


def _acronyms(name: str) -> set[str]:
    """'Karlsruhe Institute of Technology' -> {'kit', 'kiot'}."""
    words = re.findall(r"[a-z]+", _fold(name))
    small = {"of", "the", "and", "for", "de", "di", "der", "des", "la", "le",
             "van", "von", "fur", "du", "del", "degli"}
    out = {"".join(w[0] for w in words if w not in small),
           "".join(w[0] for w in words)}
    return {a for a in out if len(a) >= 2}


def _one_match(a: str, b: str) -> bool:
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return True                      # nothing to compare - do not cry wolf
    if ta & tb:
        return True
    # 'ULiege' vs 'University of Liege', 'Uni-Hamburg' vs 'Hamburg'
    if any(x in y or y in x for x in ta for y in tb if min(len(x), len(y)) >= 4):
        return True
    # 'KIT' vs 'Karlsruhe Institute of Technology', 'EPFL', 'UvA'
    short_a = {w for w in re.findall(r"[a-z]+", _fold(a)) if 2 <= len(w) <= 6}
    short_b = {w for w in re.findall(r"[a-z]+", _fold(b)) if 2 <= len(w) <= 6}
    return bool(short_a & _acronyms(b) or short_b & _acronyms(a))


def same_institution(a: str, b: str) -> bool:
    """Loose match of two institution names ('Uni Heidelberg' vs 'Heidelberg University').

    Rows often list two places ('Nikhef / UvA'); any one matching is enough.
    """
    parts_a = [x for x in re.split(r"[/;&]|\band\b", a or "") if x.strip()] or [a]
    return any(_one_match(x, b) for x in parts_a)


def _author_record(client: OpenAlexClient, prof: Professor) -> dict | None:
    if prof.openalex_id:
        aid = prof.openalex_id.rstrip("/").rsplit("/", 1)[-1]
        key = f"author_id::{aid}"
        if key in client.cache:
            return client.cache[key]
        data = client._get(f"/authors/{aid}", {})
        if data:
            client.cache[key] = data
        return data
    return client.find_author(prof)


def _aliases(client: OpenAlexClient, inst: dict) -> list[str]:
    """Display name plus the acronyms/alternatives OpenAlex knows ('CERN', 'Nikhef')."""
    name = inst.get("display_name") or ""
    iid = (inst.get("id") or "").rstrip("/").rsplit("/", 1)[-1]
    if not iid:
        return [name]
    key = f"inst_alias::{iid}"
    if key not in client.cache:
        data = client._get(f"/institutions/{iid}",
                           {"select": "display_name_acronyms,display_name_alternatives"})
        if data is None:
            return [name]
        client.cache[key] = (list(data.get("display_name_acronyms") or [])
                             + list(data.get("display_name_alternatives") or []))
    return [name] + client.cache[key]


def recheck_professor(client: OpenAlexClient, prof: Professor,
                      inactive_after: int = 3) -> tuple[str, str]:
    """-> (status, human-readable note). Fills institution/OpenAlex id if blank."""
    author = _author_record(client, prof)
    if not author:
        if client.last_error:
            return "", f"could not check: {client.last_error}"
        return NOT_FOUND, "no OpenAlex author record for this name"
    if not prof.openalex_id and author.get("id"):
        prof.openalex_id = author["id"]

    insts = [i.get("display_name", "") for i in
             (author.get("last_known_institutions") or []) if i.get("display_name")]
    years = [c.get("year", 0) for c in (author.get("counts_by_year") or [])
             if (c.get("works_count") or 0) > 0]
    latest = max(years) if years else 0
    this_year = datetime.now().year
    # Every place the person has published from in the last few years; one
    # stray co-affiliation in last_known_institutions is not a move.
    recent_insts = [a.get("institution") or {} for a in (author.get("affiliations") or [])
                    if max(a.get("years") or [0]) >= this_year - 2]
    known = list(author.get("last_known_institutions") or []) + recent_insts

    if not prof.institution and insts:
        prof.institution = insts[0]

    parts = []
    if latest:
        parts.append(f"latest paper {latest}")
    if insts:
        parts.append("OpenAlex: " + "; ".join(insts[:2]))

    if latest and this_year - latest >= inactive_after:
        return INACTIVE, f"no publications since {latest}; " + "; ".join(parts[1:])
    if insts and prof.institution and not any(
            same_institution(prof.institution, alias)
            for inst in known for alias in _aliases(client, inst)):
        return MOVED, f"row says {prof.institution}, now at {insts[0]}" + (
            f" ({parts[0]})" if latest else "")
    return ACTIVE, ", ".join(parts) or "found"


def recheck_all(professors: list[Professor], client: OpenAlexClient,
                on_result=None) -> dict[str, int]:
    counts = {ACTIVE: 0, MOVED: 0, INACTIVE: 0, NOT_FOUND: 0, "": 0}
    for i, prof in enumerate(professors):
        status, note = recheck_professor(client, prof)
        prof.profile_status = f"{status}: {note}" if status else note
        counts[status] = counts.get(status, 0) + 1
        if on_result:
            on_result(i, prof, status, note)
    client.save_cache()
    return counts
