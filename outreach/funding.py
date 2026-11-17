"""Funding-likelihood factor: how plausible is it that this host can PAY for (or
route funding to) a visiting Indian undergraduate?

Evidence used (all local, no network):
  * a curated table of institutions/labs/companies with KNOWN paid summer schemes
    open to Indian undergrads (stipend-bearing programmes, industry research labs);
  * country-level funded routes for Indian students (Charpak FR, DAAD DE, Mitacs CA...);
  * negative evidence: replies saying "no funding" (no_cold_email.json + reply text);
  * host type: industry research lab > national lab/facility > university.

Score is 0..1. It's a ranking signal, not a promise. `funding_note` explains the
best route, so drafts can name the right programme instead of asking for money.
"""
from __future__ import annotations

import re

# (pattern on institution/company name, score, route note)
KNOWN_FUNDED_HOSTS: list[tuple[str, float, str]] = [
    # Industry / company research labs that pay student researchers
    (r"\bgoogle\b|deepmind", 0.95, "Google Student Researcher / DeepMind student programmes (paid)"),
    (r"\bmicrosoft research|\bmicrosoft\b", 0.9, "Microsoft Research internship (paid)"),
    (r"\bmeta\b|facebook ai|fair\b", 0.85, "Meta AI research internship (paid)"),
    (r"\bnvidia\b", 0.85, "NVIDIA Research internship (paid)"),
    (r"\bibm research|\bibm\b", 0.8, "IBM Research internship (paid)"),
    (r"\bamazon\b|\baws\b", 0.8, "Amazon Science internship (paid)"),
    (r"\badobe research|\badobe\b", 0.8, "Adobe Research internship (paid)"),
    (r"\bsamsung\b", 0.75, "Samsung Research (PRISM / internships, paid)"),
    (r"\bqualcomm\b|\bintel\b|\bapple\b|\bsony\b|\bbosch\b|\bsiemens\b", 0.7,
     "industry research internship (paid)"),
    (r"allen institute for ai|\bai2\b|allenai", 0.85, "Ai2 research internship (paid, visa sponsored)"),
    # Facilities / national labs with paid summer programmes
    (r"\bcern\b|european organization for nuclear", 0.8,
     "CERN Summer Student / Technical Student (paid stipend)"),
    (r"\bdesy\b|deutsches elektronen", 0.75, "DESY Summer Student Programme (paid)"),
    (r"paul scherrer|\bpsi\b", 0.7, "PSI Summer Student (paid)"),
    (r"\biter\b", 0.6, "ITER internship (allowance)"),
    (r"max planck", 0.75, "Max Planck internships / IMPRS (often funded)"),
    (r"helmholtz|forschungszentrum|\bkit\b|karlsruhe institute", 0.6, "Helmholtz/KIT guest stays (often funded)"),
    (r"\bepfl\b|lausanne", 0.75, "Summer@EPFL (CHF 1,800/month + travel)"),
    (r"\beth z", 0.75, "ETH SSRF (funded)"),
    (r"weizmann", 0.75, "Weizmann Kupcinet-Getz (funded)"),
    (r"\boist\b|okinawa institute", 0.75, "OIST research internship (funded)"),
    (r"university of tokyo|\butokyo\b", 0.7, "UTRIP (allowance + housing)"),
    (r"caltech|california institute of technology", 0.7, "Caltech SURF ($ stipend, mentor needed)"),
    (r"\bkaust\b|king abdullah university", 0.75, "KAUST VSRP ($1,000/month + housing + flights)"),
    (r"\bista\b|institute of science and technology austria", 0.7, "ISTA scientific internship (paid)"),
    (r"perimeter institute", 0.6, "Perimeter undergraduate programme"),
]

# Country-level routes Indian undergrads can use (score bump + note).
COUNTRY_ROUTES = {
    "FR": (0.55, "Charpak Lab Scholarship (EUR 700/month, needs a French host)"),
    "DE": (0.45, "DAAD-funded / institute guest stay (ask host)"),
    "CA": (0.3, "Mitacs Globalink (check IIT eligibility)"),
    "JP": (0.45, "JASSO / institute summer programmes"),
    "CH": (0.45, "Swiss summer fellowships (EPFL/ETH/PSI)"),
    "SG": (0.45, "A*STAR / NUS / NTU summer programmes"),
    "KR": (0.4, "KAIST / SNU summer programmes"),
    "TW": (0.4, "TEEP (Taiwan Experience Education Programme)"),
    "IL": (0.35, "Israeli summer programmes (e.g. Weizmann, Technion)"),
    "SA": (0.5, "KAUST VSRP"),
    "AT": (0.4, "Austrian summer internships (e.g. ISTA)"),
    "US": (0.25, "SURF-type programmes (most need a host who funds)"),
    "GB": (0.1, "UK rarely funds external undergrads (UKRI schemes are domestic)"),
}

INDUSTRY_RE = re.compile(
    r"\b(inc|corp|corporation|ltd|llc|gmbh|research lab|labs?)\b|google|microsoft|\bmeta\b|nvidia|"
    r"ibm|amazon|adobe|samsung|qualcomm|intel|apple|sony|bosch|siemens", re.I)
FACILITY_RE = re.compile(r"national lab|laboratory|institute|centre|center|cern|desy|max planck|"
                         r"helmholtz|forschungszentrum", re.I)
NO_FUNDING_RE = re.compile(
    r"no (funds?|funding)|not (have|any) (funds?|funding)|cannot (fund|support|pay)|"
    r"unable to (fund|pay|support)|self-?fund|cover your own|own funding|unpaid", re.I)


COUNTRY_NAMES = {
    "france": "FR", "germany": "DE", "canada": "CA", "japan": "JP", "switzerland": "CH",
    "singapore": "SG", "south korea": "KR", "korea": "KR", "republic of korea": "KR",
    "taiwan": "TW", "israel": "IL", "saudi arabia": "SA", "austria": "AT",
    "united states": "US", "usa": "US", "united states of america": "US",
    "united kingdom": "GB", "uk": "GB", "great britain": "GB", "england": "GB",
}


def _country_code(country: str) -> str:
    c = (country or "").strip()
    if len(c) == 2:
        return {"UK": "GB"}.get(c.upper(), c.upper())
    return COUNTRY_NAMES.get(c.lower(), "")


def funding_score(institution: str, country: str = "", reply_text: str = "",
                  notes: str = "") -> tuple[float, str]:
    """0..1 funding likelihood and the best route note."""
    inst = f"{institution or ''} {notes or ''}"
    if reply_text and NO_FUNDING_RE.search(reply_text):
        return 0.0, "said no funding"
    best, note = 0.0, ""
    for pat, score, route in KNOWN_FUNDED_HOSTS:
        if re.search(pat, inst, re.I) and score > best:
            best, note = score, route
    c = _country_code(country)
    if c in COUNTRY_ROUTES:
        cs, cn = COUNTRY_ROUTES[c]
        if cs > best:
            best, note = cs, cn
        elif not note:
            note = cn
    if not note:
        if INDUSTRY_RE.search(inst):
            best, note = max(best, 0.6), "industry research internship (usually paid)"
        elif FACILITY_RE.search(inst):
            best, note = max(best, 0.35), "facility/institute guest stay (ask about funding)"
        else:
            best, note = max(best, 0.15), "university group (funding uncertain)"
    return round(best, 3), note


def blended(fit: float, funding: float, weight: float) -> float:
    """Combine topic fit (0..1) with funding (0..1). weight=0 -> fit only;
    weight=1 -> equal; weight=2 -> funding counts double."""
    weight = max(0.0, weight)
    return (fit + weight * funding) / (1.0 + weight)
