"""Scale `discover` to a target headcount, in resumable batches.

One OpenAlex query stops being useful after a few hundred papers: relevance
falls off, and the same people keep reappearing. Reaching "a thousand of the
right professors" therefore needs the work split up:

* The total (`count`) is divided evenly over `batches`.
* Each batch owns one query. With fewer queries than batches the queries are
  reused, and a reused query *continues from the page the last batch reached*
  instead of starting over - so batch 3 on the same topic finds new people.
* A batch pages through results until it has its quota of senior
  researchers (checked against OpenAlex's own citation data as it goes), its
  query runs dry, or it hits the page cap. A shortfall is carried forward to
  the next batch so the total is still met where the literature allows.
* Nobody is counted twice: every batch skips authors any earlier batch took,
  and anyone already in the output workbook.
* Progress is saved after every batch. Re-running the same command picks up
  at the first unfinished batch, so an interrupted 1000-row run loses at most
  one batch of work.

Nothing here knows anything about particular institutions or fields; the
only inputs are the queries and the seniority gate.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .discover import (Candidate, Discoverer, home_fields, resolve_countries,
                       to_professor, work_field)
from .models import Professor


@dataclass
class BatchSpec:
    index: int
    query: str
    quota: int


@dataclass
class BatchResult:
    index: int
    query: str
    quota: int
    found: int = 0
    pages: int = 0
    works: int = 0
    exhausted: bool = False
    error: str = ""


@dataclass
class BatchState:
    """Everything needed to resume a run exactly where it stopped."""
    fingerprint: str = ""
    cursors: dict[str, str] = field(default_factory=dict)
    exhausted: list[str] = field(default_factory=list)
    taken: list[str] = field(default_factory=list)
    done: list[dict] = field(default_factory=list)
    # Per query: best relevance score seen and the fields it is "about".
    anchors: dict[str, dict] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path, fingerprint: str) -> "BatchState":
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if data.get("fingerprint") == fingerprint:
                return cls(**data)
        except (OSError, ValueError, TypeError):
            pass
        return cls(fingerprint=fingerprint)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=1), encoding="utf-8")


def name_key(name: str) -> str:
    """Order- and accent-insensitive name key: 'Plehn, Tilman' == 'Tilman PLEHN'."""
    import unicodedata
    folded = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode()
    words = [w for w in re.findall(r"[a-z]+", folded.lower()) if len(w) > 1]
    return " ".join(sorted(words))


def split_queries(text: str) -> list[str]:
    """'a; b | c' or one per line -> ['a', 'b', 'c']."""
    return [q.strip() for q in re.split(r"[;|\n]+", text or "") if q.strip()]


def plan_batches(queries: list[str], count: int, batches: int) -> list[BatchSpec]:
    """Divide `count` over `batches`, assigning queries round-robin."""
    if not queries:
        raise ValueError("at least one query is required")
    batches = max(1, batches)
    count = max(1, count)
    base, extra = divmod(count, batches)
    return [BatchSpec(index=i + 1, query=queries[i % len(queries)],
                      quota=base + (1 if i < extra else 0))
            for i in range(batches)]


def fingerprint(queries: list[str], count: int, batches: int, countries: list[str],
                since_year: int, min_h_index: int, min_works: int) -> str:
    """Identifies a run, so a changed command never resumes a stale state."""
    raw = json.dumps([queries, count, batches, sorted(countries), since_year,
                      min_h_index, min_works])
    return hashlib.sha1(raw.encode()).hexdigest()[:12]


def run_batch(disc: Discoverer, spec: BatchSpec, state: BatchState,
              countries: list[str], since_year: int, min_h_index: int,
              min_works: int, max_pages: int, skip_ids: set[str],
              skip_names: set[str] | None = None,
              inst_types: list[str] | None = None,
              resolve_domains: bool = True, min_relevance: float = 0.1,
              on_page=None) -> tuple[list[Professor], BatchResult]:
    """Page through one query until `spec.quota` senior researchers are found."""
    result = BatchResult(index=spec.index, query=spec.query, quota=spec.quota)
    if spec.query in state.exhausted:
        result.exhausted = True
        return [], result

    people: dict[str, Candidate] = {}
    checked: set[str] = set()
    senior: dict[str, Candidate] = {}
    cursor = state.cursors.get(spec.query, "*")

    while result.pages < max_pages and len(senior) < spec.quota:
        works, next_cursor, total = disc.fetch_page(
            spec.query, countries, since_year, cursor=cursor, inst_types=inst_types)
        if not works:
            if not disc.last_error:
                result.exhausted = True
            break
        result.pages += 1
        result.works += len(works)
        anchor = state.anchors.get(spec.query)
        if anchor is None:
            anchor = state.anchors[spec.query] = {
                "top": max((w.get("relevance_score") or 0) for w in works),
                "fields": home_fields(works)}
        floor = anchor["top"] * min_relevance
        kept = [w for w in works
                if (w.get("relevance_score") or 0) >= floor
                and (not anchor["fields"] or work_field(w) in anchor["fields"])]
        for work in kept:
            disc.fold(work, people, countries)
        # Results come best-first; once a whole page is below the floor the
        # rest of the query is noise, however many "matches" it claims.
        if floor and all((w.get("relevance_score") or 0) < floor for w in works):
            result.exhausted = True

        # Seniority is only knowable from the author record, so check each
        # newcomer once - 50 per request - before deciding whether to page on.
        fresh = [c for aid, c in people.items()
                 if aid not in checked and aid not in skip_ids]
        disc.hydrate(fresh)
        for c in fresh:
            checked.add(c.author_id)
            if skip_names and name_key(c.name) in skip_names:
                continue
            if c.h_index >= min_h_index and c.works_count >= min_works:
                senior[c.author_id] = c
        if on_page:
            on_page(spec, result.pages, len(works), total, len(senior))

        cursor = next_cursor
        state.cursors[spec.query] = cursor or ""
        if result.exhausted:
            break
        if not cursor:
            result.exhausted = True
            break

    if result.exhausted and spec.query not in state.exhausted:
        state.exhausted.append(spec.query)

    # OpenAlex sometimes splits one person over several author ids, so the
    # same name can surface twice within a batch; keep the stronger record.
    if skip_names is None:
        skip_names = set()
    professors = []
    for cand in sorted(senior.values(), key=lambda c: -c.score):
        if len(professors) >= spec.quota:
            break
        if name_key(cand.name) in skip_names:
            continue
        homepage = disc.ror_domains(cand.ror)[1] if resolve_domains else ""
        professors.append(to_professor(cand, homepage))
        skip_ids.add(cand.author_id)
        skip_names.add(name_key(cand.name))
    result.found = len(professors)
    result.error = disc.last_error
    disc.save_cache()
    return professors, result


def run_batches(queries: list[str], count: int = 1000, batches: int = 4,
                countries: str = "europe", since_year: int = 2021,
                min_h_index: int = 8, min_works: int = 20,
                max_pages_per_batch: int = 40, existing: list[Professor] | None = None,
                state_path: Path | None = None, mailto: str = "", api_key: str = "",
                cache_path: Path | None = None, carry_shortfall: bool = True,
                inst_types: list[str] | None = None, resolve_domains: bool = True,
                min_relevance: float = 0.1, on_batch_start=None, on_page=None, on_batch_done=None):
    """Run (or resume) the whole plan. Yields `(professors, BatchResult)` per batch.

    A generator, so the caller can persist each batch to disk the moment it
    finishes - the point of batching is not losing an hour of work to a
    dropped connection in batch four.
    """
    codes = resolve_countries(countries)
    fp = fingerprint(queries, count, batches, codes, since_year, min_h_index, min_works)
    state = BatchState.load(state_path, fp) if state_path else BatchState(fingerprint=fp)
    disc = Discoverer(mailto=mailto, api_key=api_key, cache_path=cache_path)

    skip_ids = set(state.taken)
    skip_names: set[str] = set()
    for p in existing or []:
        if p.openalex_id:
            skip_ids.add(p.openalex_id)
        if p.name:
            skip_names.add(name_key(p.name))

    done_idx = {d["index"] for d in state.done}
    carry = 0
    for spec in plan_batches(queries, count, batches):
        if spec.index in done_idx:
            prev = next(d for d in state.done if d["index"] == spec.index)
            carry = max(0, prev["quota"] - prev["found"]) if carry_shortfall else 0
            continue
        if carry_shortfall and carry:
            spec.quota += carry
        if on_batch_start:
            on_batch_start(spec)
        before = set(skip_ids)
        profs, res = run_batch(disc, spec, state, codes, since_year, min_h_index,
                               min_works, max_pages_per_batch, skip_ids,
                               skip_names=skip_names, inst_types=inst_types,
                               resolve_domains=resolve_domains,
                               min_relevance=min_relevance, on_page=on_page)
        carry = max(0, spec.quota - res.found) if carry_shortfall else 0
        yield profs, res
        # Only mark done once the caller has had the chance to save the rows.
        state.taken.extend(sorted(skip_ids - before))
        state.done.append(asdict(res))
        if state_path:
            state.save(state_path)
        if on_batch_done:
            on_batch_done(res)
