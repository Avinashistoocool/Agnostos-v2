"""Dependency-free local lexical matching (TF-IDF cosine + domain-term overlap).

Purpose: cheaply rank/filter professors so only strong candidates ever reach the LLM.
"""
from __future__ import annotations

import math
import re
from collections import Counter

from .models import Professor
from .resume_parser import DOMAIN_TERMS, STOPWORDS, ResumeProfile

TOKEN_RE = re.compile(r"[a-z][a-z0-9+#\-]{2,}")

# Terms whose presence signals a genuine subfield hit rather than generic overlap.
HIGH_SIGNAL_WEIGHT = 2.5

SYNONYMS = {
    r"\bhep\b": "high-energy physics",
    r"\bparticle physics\b": "high-energy physics",
    r"\bcollider\b": "high-energy physics",
    r"\blhc\b": "high-energy physics",
    r"\batlas\b": "high-energy physics",
    r"\bcms\b": "high-energy physics",
    r"\bqcd\b": "lattice qcd",
    r"\bml\b": "machine learning",
    r"\bai\b": "machine learning",
    r"\bdl\b": "deep learning",
    r"\bnns?\b": "neural network",
    r"\bgnns?\b": "graph neural network",
    r"\bgeometric deep learning\b": "graph neural network",
    r"\bsciml\b": "scientific machine learning",
    r"\bphysics-?(informed|enhanced)\b": "scientific machine learning",
    r"\bpinns?\b": "scientific machine learning",
    r"\bjets?\b": "jet classification",
    r"\btagging\b": "jet classification",
    r"\btransformers?\b": "transformer",
    r"\bgenerative\b": "generative model",
    r"\bsimulation-based inference\b": "inference",
    r"\bsbi\b": "inference",
    r"\bfoundation models?\b": "foundation model",
    r"\banomal(y|ies|ous)\b": "anomaly detection",
    r"\bquantum (computing|information|machine learning)\b": "quantum computing",
}


def normalize(text: str) -> str:
    low = text.lower()
    for pattern, dst in SYNONYMS.items():
        low = re.sub(pattern, dst, low)
    return low


def tokenize(text: str) -> list[str]:
    return [t for t in TOKEN_RE.findall(normalize(text)) if t not in STOPWORDS]


def _ngrams(tokens: list[str], n: int = 2) -> list[str]:
    return [" ".join(tokens[i:i + n]) for i in range(len(tokens) - n + 1)]


def _features(text: str) -> Counter:
    toks = tokenize(text)
    return Counter(toks + _ngrams(toks, 2))


class LocalMatcher:
    """TF-IDF cosine similarity against the applicant profile, boosted by domain-term overlap."""

    def __init__(self, profile: ResumeProfile):
        self.profile = profile
        profile_text = profile.profile_text()
        self.profile_features = _features(profile_text)
        normalized_profile = normalize(profile_text)
        self.profile_terms = {t for t in DOMAIN_TERMS if t in normalized_profile}
        self._idf: dict[str, float] = {}

    def fit(self, professors: list[Professor]) -> None:
        """Compute IDF over the corpus so generic words (e.g. 'physics') carry less weight."""
        docs = [_features(p.personal_text()) for p in professors]
        docs.append(self.profile_features)
        n = len(docs)
        df: Counter = Counter()
        for d in docs:
            df.update(d.keys())
        self._idf = {term: math.log((n + 1) / (count + 1)) + 1.0 for term, count in df.items()}

    def _idf_of(self, term: str) -> float:
        return self._idf.get(term, 2.0)

    def _vector(self, features: Counter) -> dict[str, float]:
        if not features:
            return {}
        total = sum(features.values())
        vec = {}
        for term, count in features.items():
            weight = (count / total) * self._idf_of(term)
            if term in DOMAIN_TERMS:
                weight *= HIGH_SIGNAL_WEIGHT
            vec[term] = weight
        norm = math.sqrt(sum(v * v for v in vec.values())) or 1.0
        return {k: v / norm for k, v in vec.items()}

    def score(self, prof: Professor) -> tuple[float, list[str]]:
        personal = prof.personal_text()
        prof_text = normalize(personal)
        if len(prof_text.strip()) < 12:
            return 0.0, []
        a = self._vector(self.profile_features)
        b = self._vector(_features(personal))
        cosine = sum(a.get(t, 0.0) * w for t, w in b.items())

        matched = sorted({t for t in self.profile_terms if t in prof_text}, key=lambda t: -len(t))
        # Professor entries are often one-line topics, so reward absolute hits
        # (saturating) instead of coverage of the full resume vocabulary.
        weighted_hits = sum(1.6 if " " in t else 1.0 for t in matched)
        term_signal = 1.0 - math.exp(-0.5 * weighted_hits)
        combined = 0.45 * min(cosine * 2.5, 1.0) + 0.55 * term_signal
        return round(combined, 4), matched

    def rank(self, professors: list[Professor]) -> list[Professor]:
        self.fit(professors)
        for p in professors:
            p.local_score, p.matched_terms = self.score(p)
        return sorted(professors, key=lambda p: -p.local_score)


MIN_CONTEXT_CHARS = 30


def filter_candidates(professors: list[Professor], profile: ResumeProfile,
                      min_score: float, max_count: int) -> tuple[list[Professor], list[Professor]]:
    """Return (selected, rejected) after local ranking + threshold + cap.

    Professors with no usable research signal are rejected regardless of score:
    drafting a "personalized" email from a directory stub such as
    "Research Associate, CMS, Room 511b" produces generic text and wastes tokens.
    Publications always count as signal; otherwise there must be enough topic text
    to say something specific.
    """
    matcher = LocalMatcher(profile)
    ranked = matcher.rank(professors)
    selected, rejected = [], []
    for p in ranked:
        has_signal = (bool(p.recent_works)
                      or len(p.personal_text().strip()) >= MIN_CONTEXT_CHARS)
        if not p.email:
            p.llm_status = "skipped: no email"
        elif p.local_score < min_score:
            p.llm_status = f"skipped: local score {p.local_score} < {min_score}"
        elif not has_signal:
            p.llm_status = "skipped: too little research context to personalize"
        elif len(selected) >= max_count:
            p.llm_status = "skipped: over max-professors cap"
        else:
            selected.append(p)
            continue
        rejected.append(p)
    return selected, rejected
