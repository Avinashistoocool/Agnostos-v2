"""Humanizing layer: strip the tells that make a draft read as machine-written.

Three stages, cheapest first:

  1. `deslop()`  — deterministic and free, but deliberately CONSERVATIVE. It only
     makes substitutions that cannot break grammar: single words with identical
     part of speech, em dashes, markdown. Anything requiring sentence surgery is
     left alone and caught by stage 2 instead, because a mangled sentence is
     worse than a formal one.
  2. `score()`   — free. Rates how machine-written a draft still reads, 0-100,
     and flags unverifiable result claims.
  3. LLM rewrite — only for drafts above the threshold, so the paid stage touches
     a minority of rows.
"""
from __future__ import annotations

import re

# Single-word swaps with the same part of speech. Safe in any sentence position.
WORD_SWAPS = {
    r"\butilise\b": "use",
    r"\butilize\b": "use",
    r"\butilised\b": "used",
    r"\butilized\b": "used",
    r"\butilising\b": "using",
    r"\butilizing\b": "using",
    r"\bleverage\b": "use",
    r"\bleveraged\b": "used",
    r"\bleveraging\b": "using",
    r"\bcommence\b": "start",
    r"\bcommenced\b": "started",
    r"\bregarding\b": "about",
    r"\bconcerning\b": "about",
    r"\bnumerous\b": "many",
    r"\bprior to\b": "before",
    r"\bsubsequently\b": "later",
    r"\bthus\b": "so",
    r"\bhence\b": "so",
    r"\bmoreover\b": "also",
    r"\bfurthermore\b": "also",
    r"\badditionally\b": "also",
    r"\bin order to\b": "to",
    r"\brobust\b": "solid",
    r"\bcutting[- ]edge\b": "recent",
    r"\bstate[- ]of[- ]the[- ]art\b": "recent",
    r"\bpivotal\b": "important",
    r"\binvaluable\b": "useful",
    r"\bcomprehensive\b": "full",
    r"\bmeticulously\b": "carefully",
    r"\bseamlessly\b": "",
    r"\bseamless\b": "",
    r"\bsuccessfully\b": "",
    r"\bsignificantly\b": "",
    r"\bnovel\b": "",
    r"\bgroundbreaking\b": "",
    r"\brealm\b": "area",
}

# Whole clauses that can be deleted or swapped without leaving a fragment.
PHRASE_SWAPS = {
    r"I hope this e-?mail finds you well[.!,]?\s*": "",
    r"I hope this message finds you well[.!,]?\s*": "",
    r"\bI am writing to enquire\b": "I wanted to ask",
    r"\bI am writing to inquire\b": "I wanted to ask",
    r"\bI am writing to ask\b": "I wanted to ask",
    r"\bI am writing to express my interest in\b": "I'm interested in",
    r"\bI am writing to express my interest\b": "I'm interested in your group's work",
    r"\bI am writing to introduce myself\b": "I'm a student writing to you",
    r"\bI am writing to\b": "I wanted to",
    r"\bI am writing regarding\b": "I'm writing about",
    r"\bI am reaching out to enquire about\b": "I wanted to ask about",
    r"\bI am reaching out to you\b": "I'm writing",
    r"\bI am reaching out\b": "I'm writing",
    r"\bI would be thrilled\b": "I'd be glad",
    r"\bI would be honou?red\b": "I'd be glad",
    r"\bit is worth noting that\b": "",
    r"\bneedless to say,?\s*": "",
    r"\bI am deeply passionate about\b": "I'm interested in",
    r"\bI am passionate about\b": "I'm interested in",
    r"\bperfectly aligns with\b": "lines up with",
    r"\baligns closely with\b": "lines up with",
    r"\baligns with\b": "lines up with",
    r"\bserves as a testament to\b": "shows",
    r"\ba deep dive into\b": "a closer look at",
    r"\bat your earliest convenience\b": "",
    r"\bPlease do not hesitate to\b": "Feel free to",
}

# Overclaiming: the honesty net. Verb-for-verb only, so grammar survives.
CLAIM_SWAPS = {
    r"\bachieved\b": "got",
    r"\bachieving\b": "getting",
    r"\bdemonstrated\b": "showed",
    r"\bdemonstrating\b": "showing",
    r"\bdemonstrates\b": "shows",
    r"\bproved\b": "suggested",
    r"\bproves\b": "suggests",
    r"\boutperformed\b": "was compared against",
    r"\boutperforms\b": "is compared against",
    r"\bsuperior\b": "different",
}

# Claims that cannot be softened safely. These force an LLM rewrite.
HARD_CLAIM_RE = re.compile(
    r"\b\d+(\.\d+)?\s*%"
    r"|\b(improv|enhanc|boost)(ed|ing|es)?\s+(the\s+)?(accuracy|performance|results?|discrimination)"
    r"|\bbeat(s|ing)?\s+(the\s+)?(baseline|state)"
    r"|\bbest[- ]in[- ]class\b"
    r"|\bresulted in (enhanced|improved|superior|better)\b", re.I)

AI_TELLS = [
    (r"\u2014", 3, "em dash"),
    (r"\*\*|^\s*[-*\u2022]\s+", 3, "markdown"),
    (r"\b(delve|leverag|utilis|utiliz|robust|cutting-edge|seamless|pivotal|invaluable)", 4,
     "LLM vocabulary"),
    (r"\b(moreover|furthermore|additionally|thus|hence|therefore)\b", 2, "connective formality"),
    (r"\bI am writing to\b|\bI am reaching out\b", 4, "form-letter opener"),
    (r"\bI hope this (e-?mail|message) finds you well\b", 5, "boilerplate greeting"),
    (r"\b(passionate|thrilled|honou?red) (about|to)\b", 3, "performed enthusiasm"),
    (r"\balign(s|ed|ing)? (closely |perfectly )?with\b", 3, "alignment cliche"),
    (r"\w+,\s+\w+,\s+and\s+\w+", 3, "three-item list"),
    (HARD_CLAIM_RE.pattern, 6, "unverifiable result claim"),
    (r"\b(achieved|demonstrated|outperformed|novel|groundbreaking|superior)\b", 4, "overclaiming"),
]


def _apply(pattern_map: dict, text: str) -> str:
    for pattern, repl in pattern_map.items():
        text = re.sub(pattern, repl, text, flags=re.I)
    return text


def _break_triads(text: str) -> str:
    """'X, Y, and Z' is the most recognizable LLM rhythm. Drop one item."""
    return re.sub(
        r"\b(\w+(?:\s\w+){0,2}),\s+(\w+(?:\s\w+){0,2}),\s+and\s+(\w+(?:\s\w+){0,2})\b",
        lambda m: f"{m.group(1)} and {m.group(3)}", text, count=1)


def _tidy_spacing(text: str) -> str:
    text = text.replace("\u2014", ", ").replace("\u2013", "-")
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"(?m)^\s*[-*\u2022]\s+", "", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\s+([,.;:?!])", r"\1", text)
    text = re.sub(r"([,.;:?!])(?=[A-Za-z])", r"\1 ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"(?m)^(.)", lambda m: m.group(1).upper(), text)
    text = re.sub(r"([.!?]\s+)([a-z])", lambda m: m.group(1) + m.group(2).upper(), text)
    return text.strip()


_SELF_FUND_RE = re.compile(
    r"(?:\b(?:can|could|will|would|happy to|able to|willing to|prepared to|plan to|"
    r"ready to|i'?ll|i'?d)\b[^.!?\n]{0,40}"
    r"\b(?:cover|pay|fund|finance|self-fund|support)\b[^.!?\n]{0,50}"
    r"\b(?:travel|visa|living|accommodation|expenses|costs|stay|own|myself)\b)"
    r"|\bbe self-?funded\b|\bself-?fund(?:ing|ed)?\b|\bmy own (?:funding|expenses|costs)\b",
    re.I)
_NEGATED_RE = re.compile(r"\b(?:not|n't|unable|cannot|can't|won't|no)\b", re.I)


def offers_self_funding(text: str) -> list[str]:
    """Sentences that offer to pay one's own way (negated statements are fine)."""
    hits = []
    for s in re.split(r"(?<=[.!?])\s+|\n+", text or ""):
        if _SELF_FUND_RE.search(s) and not _NEGATED_RE.search(s):
            hits.append(s.strip())
    return hits


def strip_self_funding(text: str) -> str:
    """Remove self-funding offers; rewrite 'X and can cover travel' clauses."""
    out = []
    for para in (text or "").split("\n"):
        sents = re.split(r"(?<=[.!?])\s+", para)
        kept = []
        for s in sents:
            if not _SELF_FUND_RE.search(s) or _NEGATED_RE.search(s):
                kept.append(s)
                continue
            # "I'm available May-July for 8-12 weeks and can cover travel..." -> keep availability.
            m = re.match(r"(.*?\b(?:weeks|2027|months|summer)\b[^,;]*?)\s*(?:,|;|\band\b)", s, re.I)
            if m and len(m.group(1)) > 20:
                kept.append(m.group(1).rstrip(" ,;") + ".")
        out.append(" ".join(k for k in kept if k))
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()


def deslop(text: str) -> str:
    """Conservative deterministic pass. Never attempts sentence surgery."""
    if not text:
        return text
    out = _apply(PHRASE_SWAPS, text)
    out = _apply(CLAIM_SWAPS, out)
    out = _apply(WORD_SWAPS, out)
    out = _break_triads(out)
    return _tidy_spacing(out)


def score(text: str) -> tuple[int, list[str]]:
    """How machine-written does this still read? 0 = human, 100 = obvious AI."""
    if not text:
        return 0, []
    total, reasons = 0, []
    for pattern, weight, label in AI_TELLS:
        hits = len(re.findall(pattern, text, flags=re.I | re.M))
        if hits:
            total += weight * hits
            reasons.append(f"{label} x{hits}")

    sentences = [s for s in re.split(r"(?<=[.?!])\s+", text) if s.strip()]
    if len(sentences) >= 4:
        lengths = [len(s.split()) for s in sentences]
        mean = sum(lengths) / len(lengths)
        variance = sum((l - mean) ** 2 for l in lengths) / len(lengths)
        # Human writing varies; uniform sentence length is a strong tell.
        if variance < 12:
            total += 8
            reasons.append("uniform sentence length")
        if mean > 26:
            total += 5
            reasons.append("long average sentence")
    return min(total, 100), reasons


def has_hard_claims(text: str) -> bool:
    return bool(HARD_CLAIM_RE.search(text or ""))


REWRITE_SYSTEM = """You rewrite cold emails so they read as if a real second-year undergraduate typed them.

Rules:
- Keep every fact, name, date and the overall structure. Change only the voice.
- Shorten. Vary sentence length sharply: follow a long sentence with a very short one.
- Use contractions (I'm, I've, it's). Use plain words.
- Remove any claim of results, metrics, novelty or superiority. The student's projects are coursework; they built and tried things, they did not achieve or prove anything. If a sentence claims a result, rewrite it as what they attempted or wanted to understand.
- Never use: delve, leverage, utilise, robust, cutting-edge, seamless, pivotal, invaluable, passionate, thrilled, align with, resonate, moreover, furthermore, therefore, showcase, underscore, "I am writing to", "I hope this email finds you well".
- No em dashes, no markdown, no bullet points, no three-item lists.
- Keep the salutation line and the sign-off exactly as they are.
- Stay between 120 and 180 words.

Return ONLY the rewritten email body as plain text. No JSON, no commentary, no quotes around it."""


def build_rewrite_request(body: str) -> list[dict]:
    return [
        {"role": "system", "content": REWRITE_SYSTEM},
        {"role": "user", "content": f"Rewrite this email body:\n\n{body}"},
    ]
