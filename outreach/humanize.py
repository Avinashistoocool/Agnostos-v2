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
from pathlib import Path
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

# Claims that cannot be softened safely. These force an LLM rewrite. Numbers are
# handled separately (see `unverified_numbers`): verified ones may stay.
HARD_CLAIM_RE = re.compile(
    r"\b(improv|enhanc|boost)(ed|ing|es)?\s+(the\s+)?(accuracy|performance|results?|discrimination)"
    r"|\bbeat(s|ing)?\s+(the\s+)?(baseline|state)"
    r"|\bbest[- ]in[- ]class\b"
    r"|\b(?:outperform\w*|state[- ]of[- ]the[- ]art|sota)\b"
    r"|\bresulted in (enhanced|improved|superior|better)\b", re.I)

# A metric: 84.84%, 0.9853, 10M, 4.5x, ~256 KB, 10 million. Plain integers
# (8-10 weeks, 2027, 10 classes) are not metrics.
METRIC_RE = re.compile(
    r"(?<![\w.])(\d+(?:\.\d+)?)(?:\s*(%|percent\b|million\b|kb\b|mb\b|gb\b)|(x\b|\u00d7|m\b|k\b))"
    r"|(?<![\w.\-])(\d+\.\d+)(?![\w.]*\.\w)", re.I)

# Fallback when output/confirmed_facts.md is absent: the user-verified numbers.
DEFAULT_CONFIRMED_FACTS = """
GDS-ParT: 84.84% accuracy and 0.9853 macro AUC on 1M JetClass test jets (10 classes).
Trained 2.07M parameters on 10M jets on a single 6 GB GPU; cache cut from ~256 KB to ~1.9 KB.
GDS-ParT-MoE: NMI 0.45/0.43; one expert showed 4.5x muon enrichment.
NIDAR: 100% simulated coverage. AnaTele: 20 rules.
"""

_UNIT_ALIASES = {"percent": "%", "\u00d7": "x", "million": "m"}


def _metric_key(value: str, unit: str) -> tuple[str, str]:
    unit = (unit or "").lower()
    return value, _UNIT_ALIASES.get(unit, unit)


def metric_tokens(text: str) -> list[tuple[str, tuple[str, str]]]:
    """(matched text, (value, unit)) for every metric-looking number."""
    out = []
    for m in METRIC_RE.finditer(text or ""):
        if m.group(1):
            out.append((m.group(0), _metric_key(m.group(1), m.group(2) or m.group(3))))
        else:
            out.append((m.group(0), _metric_key(m.group(4), "")))
    return out


def allowed_metrics(facts_text: str) -> set[tuple[str, str]]:
    return {key for _, key in metric_tokens(facts_text)}


_FACTS_CACHE: dict[str, str] = {}


def confirmed_facts_text(path: str | Path | None = None) -> str:
    """The user-verified facts block (output/confirmed_facts.md), comments stripped."""
    if path is None:
        try:
            from .config import settings
            path = settings.confirmed_facts_file or (Path(settings.output_dir) / "confirmed_facts.md")
        except Exception:
            path = ""
    key = str(path or "")
    if key not in _FACTS_CACHE:
        text = ""
        if key and Path(key).is_file():
            lines = Path(key).read_text(encoding="utf-8").splitlines()
            text = "\n".join(l for l in lines if not l.lstrip().startswith("# ")).strip()
        _FACTS_CACHE[key] = text or DEFAULT_CONFIRMED_FACTS.strip()
    return _FACTS_CACHE[key]


def default_allowed() -> set[tuple[str, str]]:
    return allowed_metrics(confirmed_facts_text())


def unverified_numbers(text: str, allowed: set | None = None) -> list[str]:
    allowed = default_allowed() if allowed is None else allowed
    return [raw.strip() for raw, key in metric_tokens(text) if key not in allowed]


_REPO_RE = re.compile(r"(?:https?://)?(?:www\.)?github\.com/([\w.\-]+)(/[\w.\-]+)?/?", re.I)


def allowed_links(facts_text: str) -> set[str]:
    return {m.group(0).lower().rstrip("/.").removeprefix("https://").removeprefix("http://")
            .removeprefix("www.") for m in _REPO_RE.finditer(facts_text or "")}


def fix_unverified_links(text: str, allowed: set[str] | None = None) -> tuple[str, list[str]]:
    """Replace GitHub repo links that are not in the confirmed facts with the profile link."""
    allowed = allowed_links(confirmed_facts_text()) if allowed is None else allowed
    fixed = []

    def _sub(m):
        key = m.group(0).lower().rstrip("/.").removeprefix("https://").removeprefix("http://") \
            .removeprefix("www.")
        if key in allowed or not m.group(2):
            return m.group(0)
        fixed.append(m.group(0))
        return f"github.com/{m.group(1)}" + ("." if m.group(0).endswith(".") else "")

    return _REPO_RE.sub(_sub, text or ""), fixed


def strip_unverified_numbers(text: str, allowed: set | None = None) -> tuple[str, list[str]]:
    """Drop every sentence quoting a number outside the confirmed facts."""
    allowed = default_allowed() if allowed is None else allowed
    removed = []
    paras = []
    for para in (text or "").split("\n"):
        kept = []
        for s in re.split(r"(?<=[.!?])\s+(?=[A-Z])", para):
            bad = unverified_numbers(s, allowed)
            if bad:
                removed.extend(bad)
                continue
            kept.append(s)
        paras.append(" ".join(kept))
    out = re.sub(r"\n{3,}", "\n\n", "\n".join(paras)).strip()
    return out, removed

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


_URL_RE = re.compile(
    r"https?://\S+|www\.\S+|\S+@[\w\-]+(?:\.[\w\-]+)+"
    r"|\b[\w\-]+(?:\.[\w\-]+)*\.(?:com|org|io|net|edu|in|de|ch|uk|eu)(?:/[^\s,;)]*)?",
    re.I)


def _tidy_spacing(text: str) -> str:
    # Links and addresses must survive the punctuation-spacing rules below.
    links = []

    def _mask(m):
        links.append(m.group(0))
        return f"\x00{len(links) - 1}\x00"

    text = _URL_RE.sub(_mask, text)
    text = text.replace("\u2014", ", ").replace("\u2013", "-")
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"(?m)^\s*[-*\u2022]\s+", "", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\s+([,.;:?!])", r"\1", text)
    text = re.sub(r"([,.;:?!])(?=[A-Za-z])", r"\1 ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"(?m)^(.)", lambda m: m.group(1).upper(), text)
    text = re.sub(r"([.!?]\s+)([a-z])", lambda m: m.group(1) + m.group(2).upper(), text)
    text = re.sub(r"\x00(\d+)\x00", lambda m: links[int(m.group(1))], text)
    return text.strip()


_SELF_FUND_RE = re.compile(
    r"(?:\b(?:can|could|will|would|happy to|able to|willing to|prepared to|plan to|"
    r"ready to|i'?ll|i'?d)\b[^.!?\n]{0,40}"
    r"\b(?:cover|pay|fund|finance|self-fund|support)\b[^.!?\n]{0,50}"
    r"\b(?:travel|visa|living|accommodation|expenses|costs|stay|own|myself)\b)"
    r"|\bbe self-?funded\b|\bself-?fund(?:ing|ed)?\b|\bmy own (?:funding|expenses|costs)\b"
    r"|\bunpaid\b|\bwithout (?:pay|payment|a stipend|a salary|funding)\b"
    r"|\bcontribut\w*\s+(?:to|towards?)\s+(?:the\s+|my\s+|any\s+)?(?:costs?|expenses|travel)",
    re.I)
# Offers phrased with a negation ("no stipend needed") are still offers.
_NEGATED_OFFER_RE = re.compile(
    r"\bno\s+(?:stipend|salary|payment|pay|funding)\s+(?:is\s+)?(?:needed|required|necessary)\b"
    r"|\b(?:don'?t|do not|won'?t|will not)\s+(?:need|require|expect)\s+"
    r"(?:a\s+|any\s+)?(?:stipend|salary|payment|funding|to be paid)\b", re.I)
_NEGATED_RE = re.compile(r"\b(?:not|n't|unable|cannot|can't|won't|no)\b", re.I)


def _is_offer(sentence: str) -> bool:
    if _NEGATED_OFFER_RE.search(sentence):
        return True
    return bool(_SELF_FUND_RE.search(sentence)) and not _NEGATED_RE.search(sentence)


def offers_self_funding(text: str) -> list[str]:
    """Sentences that offer to pay one's own way (negated statements are fine)."""
    hits = []
    for s in re.split(r"(?<=[.!?])\s+|\n+", text or ""):
        if _is_offer(s):
            hits.append(s.strip())
    return hits


def strip_self_funding(text: str) -> str:
    """Remove self-funding offers; rewrite 'X and can cover travel' clauses."""
    out = []
    for para in (text or "").split("\n"):
        sents = re.split(r"(?<=[.!?])\s+", para)
        kept = []
        for s in sents:
            if not _is_offer(s):
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
    return bool(HARD_CLAIM_RE.search(text or "")) or bool(unverified_numbers(text or ""))


# --- first-email validation -------------------------------------------------
MONEY_RE = re.compile(
    r"\b(?:fund(?:s|ed|ing)?|stipend\w*|salar(?:y|ies)|paid|unpaid|payment|"
    r"costs?(?!\s*(?:map|function|field|matrix|term|surface))|expenses?|money|financ\w*|"
    r"scholarships?|grants?|travel (?:support|grant)|self-?fund\w*|afford\w*)\b", re.I)
FIRST_EMAIL_BANNED = [
    (re.compile(r"\bcapacity\b", re.I), "says 'capacity'"),
    (re.compile(r"\btrouble following\b|\bgot stuck\b|\bdidn.?t (?:fully |quite )?follow\b|"
                r"\bwrap my head\b", re.I), "opens with confusion ('trouble following')"),
    (re.compile(r"\bsmall subset\b", re.I), "says 'small subset'"),
    (re.compile(r"\bGPA\b|\bCGPA\b", re.I), "mentions GPA"),
    (re.compile(r"\bmay I send\b[^.?!]{0,30}\b(?:cv|resume|r\u00e9sum\u00e9)\b", re.I),
     "asks 'May I send my CV' (link it instead)"),
]
SUBJECT_BANNED = re.compile(r"\b(?:inquiry|enquiry)\b", re.I)
_GREETING_LINE_RE = re.compile(
    r"^\s*(?:dear\b|hello\b|hi\b|good (?:morning|afternoon)\b|sehr geehrte|"
    r"(?:prof\.?|professor|dr\.?)\s+[^\s,]+(?:\s+[^\s,]+)?\s*,\s*$)", re.I)


def validate_first_email(subject: str, body: str, allow_money: bool = False,
                         allowed: set | None = None) -> list[str]:
    """Reasons this cold first email must not go out as drafted ([] = fine)."""
    problems = []
    body = body or ""
    for rx, label in FIRST_EMAIL_BANNED:
        if rx.search(body):
            problems.append(label)
    lines = [l for l in body.splitlines() if l.strip()]
    greetings = [l for l in lines[:4] if _GREETING_LINE_RE.match(l)]
    if len(greetings) >= 2:
        problems.append("two greeting lines")
    if SUBJECT_BANNED.search(subject or ""):
        problems.append("'inquiry/enquiry' in subject")
    if not allow_money:
        hit = MONEY_RE.search(body)
        if hit:
            problems.append(f"mentions money/funding ('{hit.group(0)}')")
    if offers_self_funding(body):
        problems.append("offers self-funding")
    bad = unverified_numbers(body, allowed)
    if bad:
        problems.append("unverified number(s): " + ", ".join(bad[:3]))
    return problems


REWRITE_SYSTEM = """You rewrite cold emails so they read as if a real second-year undergraduate typed them.

Rules:
- Keep every fact, name, date, link and the overall structure. Change only the voice.
- Keep the verified numbers EXACTLY as written (84.84%, 0.9853 macro AUC, 1M test jets, 10M training jets, 2.07M parameters, and any other number from the confirmed facts). Do not round, drop or add numbers.
- Remove any OTHER metric, and any claim of novelty or superiority ("outperformed", "state of the art", "beat").
- Never add "small subset", "mostly", "basic", "just to see", "capacity", "trouble following", or anything about money, funding, costs or GPA.
- Shorten. Vary sentence length: follow a long sentence with a short one.
- Use contractions (I'm, I've, it's). Use plain words.
- Never use: delve, leverage, utilise, robust, cutting-edge, seamless, pivotal, invaluable, passionate, thrilled, align with, resonate, moreover, furthermore, therefore, showcase, underscore, "I am writing to", "I hope this email finds you well".
- No em dashes, no markdown, no bullet points, no three-item lists.
- Keep the single salutation line and the sign-off exactly as they are. Never add a second greeting.
- Stay between 110 and 150 words, in 4 short paragraphs.

Return ONLY the rewritten email body as plain text. No JSON, no commentary, no quotes around it."""


def build_rewrite_request(body: str) -> list[dict]:
    return [
        {"role": "system", "content": REWRITE_SYSTEM},
        {"role": "user", "content": f"Rewrite this email body:\n\n{body}"},
    ]
