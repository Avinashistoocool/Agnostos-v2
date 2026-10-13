"""Resume parsing: PDF/DOCX -> structured applicant profile."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, asdict, field
from pathlib import Path

SECTION_PATTERNS = {
    "education": r"academic\s*profile|education|academic\s*background",
    "interests": r"research\s*interests?",
    "projects": r"research\s*&?\s*technical\s*projects?|projects?|publications?",
    "skills": r"technical\s*skills?|skills?\s*&?\s*tools?|computer\s*skills|skills",
    "achievements": r"scholastic\s*achievements?|achievements?|awards?|honou?rs",
    "experience": r"experience|internships?|positions?",
}

# Domain vocabulary used for keyword extraction + local similarity.
DOMAIN_TERMS = [
    "machine learning", "deep learning", "neural network", "transformer", "attention",
    "graph neural network", "geometric deep learning", "equivariant", "gnn", "cnn",
    "generative model", "diffusion model", "normalizing flow", "variational autoencoder",
    "reinforcement learning", "representation learning", "self-supervised", "foundation model",
    "anomaly detection", "classification", "regression", "surrogate model", "emulator",
    "uncertainty quantification", "bayesian", "inference", "simulation-based inference",
    "high-energy physics", "particle physics", "collider", "jet tagging", "jet classification",
    "lhc", "cern", "atlas", "cms", "lattice qcd", "quantum chromodynamics", "hadron",
    "quantum computing", "quantum machine learning", "quantum information", "condensed matter",
    "astrophysics", "cosmology", "gravitational wave", "astronomy", "remote sensing",
    "computational physics", "scientific machine learning", "sciml", "physics-informed",
    "pde", "differential equation", "molecular dynamics", "materials discovery", "chemistry",
    "fluid dynamics", "turbulence", "plasma", "photonics", "optics", "nanoscience",
    "biophysics", "neuroscience", "medical imaging", "computer vision", "image processing",
    "nlp", "natural language processing", "robotics", "autonomous navigation", "path planning",
    "slam", "control", "edge computing", "iot", "embedded", "fpga", "gpu", "hpc",
    "distributed computing", "optimization", "numerical methods", "differential geometry",
    "topology", "statistics", "data analysis", "signal processing", "time series",
    "pytorch", "tensorflow", "jax", "numpy", "scipy", "scikit-learn", "opencv", "root",
    "c++", "python", "cuda", "linux", "git",
]

STOPWORDS = set("""a an and are as at be but by for from has have he her his i if in into is it its
me my of on or our ours she so such than that the their them then there these they this to was we
were what when where which while who will with would you your within using use used based towards
toward via able also been being can could did do does each how most much new non not now off one
only other out over own same some too very will about after all any because before both during
further here more no nor once other same under until up down again against between through""".split())

TOKEN_RE = re.compile(r"[a-z][a-z0-9+#\-\.]{1,}")


@dataclass
class ResumeProfile:
    name: str = ""
    email: str = ""
    phone: str = ""
    institution: str = ""
    degree: str = ""
    graduation_year: str = ""
    gpa: str = ""
    research_interests: list[str] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    projects: list[dict] = field(default_factory=list)
    achievements: list[str] = field(default_factory=list)
    raw_text: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    def summary_block(self, max_projects: int = 4, max_chars: int = 2400) -> str:
        """Compact, token-cheap profile summary for LLM prompts."""
        lines = [
            f"Name: {self.name}",
            f"Program: {self.degree} at {self.institution}"
            + (f" (expected {self.graduation_year}, GPA {self.gpa})" if self.graduation_year else ""),
            f"Research interests: {', '.join(self.research_interests) or ', '.join(self.keywords[:10])}",
            f"Core skills: {', '.join(self.skills[:18])}",
        ]
        if self.projects:
            lines.append("Key projects:")
            for p in self.projects[:max_projects]:
                detail = " ".join(p.get("bullets", []))[:420]
                advisor = f" [advisor: {p['advisor']}]" if p.get("advisor") else ""
                lines.append(f"  - {p['title']}{advisor}: {detail}")
        if self.achievements:
            lines.append("Achievements: " + " | ".join(a[:160] for a in self.achievements[:3]))
        text = "\n".join(lines)
        return text[:max_chars]

    def profile_text(self) -> str:
        """Text blob used for local lexical matching."""
        parts = self.research_interests + self.skills + self.keywords
        parts += [p["title"] + " " + " ".join(p.get("bullets", [])) for p in self.projects]
        return " ".join(parts).lower()


def _read_pdf(path: Path) -> str:
    try:
        import pdfplumber
    except ImportError as exc:
        raise RuntimeError("pdfplumber required for PDF resumes: pip install pdfplumber") from exc
    chunks = []
    with pdfplumber.open(str(path)) as pdf:
        for page in pdf.pages:
            chunks.append(page.extract_text(x_tolerance=1) or "")
    return "\n".join(chunks)


def _read_docx(path: Path) -> str:
    try:
        import docx
    except ImportError as exc:
        raise RuntimeError("python-docx required for DOCX resumes: pip install python-docx") from exc
    document = docx.Document(str(path))
    return "\n".join(p.text for p in document.paragraphs)


JOINERS = r"in|of|at|and|for|the|with|from|on|to"

TOP_BULLETS = "\u25a0\u25cf\u25e6\u25aa\u2756\u2022\ufffd"
SUB_BULLETS = "-\u2013\u2014*"
BULLET_CHARS = TOP_BULLETS + SUB_BULLETS + " \t"

DEGREE_RE = re.compile(
    r"\b(B\.?\s?Tech|B\.?\s?E\b|B\.?\s?Sc|B\.?\s?S\b|M\.?\s?Tech|M\.?\s?Sc|M\.?\s?S\b|"
    r"Integrated\s*M\.?\s?Sc|Dual\s*Degree|Ph\.?\s?D)\b", re.I)
INSTITUTION_RE = re.compile(
    r"(Indian Institute of Technology[A-Za-z ]*|[A-Z][A-Za-z\.]*\s*(?:University|Institute|College|"
    r"Universit[a-z]*|Polytechnic)[A-Za-z ]{0,30})")


def _parse_education(sections: dict, profile: "ResumeProfile") -> None:
    """Pick the education line describing the highest-level current degree."""
    best = None
    for line in sections.get("education", []):
        if DEGREE_RE.search(line) and INSTITUTION_RE.search(line):
            best = line
            break
    if best is None:
        for line in sections.get("education", []):
            if INSTITUTION_RE.search(line):
                best = line
                break
    if not best:
        return
    inst = INSTITUTION_RE.search(best)
    if inst:
        profile.institution = inst.group(1).strip(" ,.")
    deg_match = DEGREE_RE.search(best)
    if deg_match:
        end = inst.start() if inst and inst.start() > deg_match.start() else len(best)
        profile.degree = re.sub(r"\s+", " ", best[deg_match.start():end]).strip(" ,.-")
    year = re.search(r"\b(20[2-9]\d)\b", best)
    if year:
        profile.graduation_year = year.group(1)
    gpa = re.search(r"\b(\d{1,2}\.\d{1,2})\b", best)
    if gpa:
        profile.gpa = gpa.group(1)


def _despace(text: str) -> str:
    """Some PDF extractors drop spaces (e.g. 'DeepLearning').

    Repair only when the text genuinely looks glued. A space-ratio test alone
    sits too close to the value of ordinary prose, so the decisive signal is
    mean word length: glued extractions produce very long pseudo-words, while
    normal English averages roughly 5-7 characters per token.
    """
    words = text.split()
    letters = sum(c.isalpha() for c in text)
    spaces = text.count(" ")
    mean_word = (sum(len(w) for w in words) / len(words)) if words else 0.0
    looks_glued = (letters and spaces / letters < 0.10) or mean_word > 11
    if not looks_glued:
        return re.sub(r"[ \t]+", " ", text)
    text = re.sub(rf"(?<=[a-z])({JOINERS})(?=[A-Z])", r" \1 ", text)
    text = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", text)
    text = re.sub(r"(?<=[a-z]{2})(?=\d)", " ", text)
    text = re.sub(r"(?<=[.,;:])(?=[A-Za-z])", " ", text)
    return re.sub(r"[ \t]+", " ", text)


def _split_sections(lines: list[str]) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {}
    current = "header"
    sections[current] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        compact = re.sub(r"[^a-z& ]", "", stripped.lower())
        is_heading = (
            len(stripped) < 60
            and (stripped.isupper() or stripped.replace(" ", "").isupper())
        )
        matched = None
        for key, pattern in SECTION_PATTERNS.items():
            if re.fullmatch(rf"\s*({pattern})\s*", compact):
                matched = key
                break
        if matched and (is_heading or len(stripped) < 45):
            current = matched
            sections.setdefault(current, [])
            continue
        if is_heading and len(stripped.split()) <= 6 and stripped[0].isupper():
            current = "other:" + compact.strip()
            sections.setdefault(current, [])
            continue
        sections.setdefault(current, []).append(stripped)
    return sections


def _extract_keywords(text: str, top_n: int = 45) -> list[str]:
    low = text.lower()
    found = [t for t in DOMAIN_TERMS if t in low]
    tokens = [t for t in TOKEN_RE.findall(low) if t not in STOPWORDS and len(t) > 3]
    freq: dict[str, int] = {}
    for t in tokens:
        freq[t] = freq.get(t, 0) + 1
    extra = [w for w, c in sorted(freq.items(), key=lambda kv: -kv[1]) if c >= 2]
    out, seen = [], set()
    for term in found + extra:
        if term not in seen:
            seen.add(term)
            out.append(term)
    return out[:top_n]


def _extract_projects(section_lines: list[str]) -> list[dict]:
    projects: list[dict] = []
    for line in section_lines:
        raw = line.strip()
        if not raw:
            continue
        first = raw[0]
        clean = raw.lstrip(BULLET_CHARS).strip()
        if not clean:
            continue
        if first in TOP_BULLETS:
            title = re.split(r"\s*\|\s*", clean)[0]
            title = re.sub(r"\(([^)]*['\u2019]?\d{2}[^)]*)\)\s*$", "", title).strip(" .,-")
            advisor = re.search(r"Advised by ([^|(]+)", clean)
            projects.append({
                "title": title,
                "advisor": advisor.group(1).strip() if advisor else "",
                "bullets": [],
            })
        elif projects:
            projects[-1]["bullets"].append(clean)
    if not projects:
        projects = _extract_projects_unbulleted(section_lines)
    return [p for p in projects if len(p["title"]) > 3]


def _is_title_case(text: str) -> bool:
    """Headings capitalise most words; sentences capitalise only the first."""
    words = [w for w in re.findall(r"[A-Za-z][\w\-]*", text) if len(w) > 3]
    if len(words) < 2:
        return True
    capitalised = sum(1 for w in words if w[0].isupper())
    return capitalised / len(words) >= 0.6


def _extract_projects_unbulleted(section_lines: list[str]) -> list[dict]:
    """Fallback for resumes that use no bullet glyphs at all.

    A project title is a short line that reads like a heading: it starts with a
    capital, carries no terminal punctuation, and is followed by longer prose.
    """
    projects: list[dict] = []
    for line in section_lines:
        clean = line.strip().lstrip(BULLET_CHARS).strip()
        if not clean:
            continue
        looks_like_title = (
            len(clean) <= 80
            and clean[0].isupper()
            and not clean.endswith((".", ",", ";", ":"))
            and len(clean.split()) <= 12
            and _is_title_case(clean)
        )
        if looks_like_title:
            title = re.split(r"\s*\|\s*", clean)[0].strip(" .,-")
            advisor = re.search(r"Advised by ([^|(]+)", clean)
            projects.append({
                "title": title,
                "advisor": advisor.group(1).strip() if advisor else "",
                "bullets": [],
            })
        elif projects:
            projects[-1]["bullets"].append(clean)
    return projects


def parse_resume(path: str | Path) -> ResumeProfile:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Resume not found: {path}")
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        raw = _read_pdf(path)
    elif suffix in {".docx", ".doc"}:
        raw = _read_docx(path)
    elif suffix in {".txt", ".md"}:
        raw = path.read_text(encoding="utf-8", errors="ignore")
    else:
        raise ValueError(f"Unsupported resume format: {suffix}")

    text = _despace(raw)
    lines = [ln.strip() for ln in text.splitlines()]
    sections = _split_sections(lines)
    profile = ResumeProfile(raw_text=text)

    header = sections.get("header", [])
    non_empty = [ln for ln in lines if ln.strip()]
    if header:
        profile.name = header[0].strip()
    elif non_empty:
        profile.name = non_empty[0].strip()
    if profile.name.isupper():
        profile.name = profile.name.title()
    email = re.search(r"[\w\.\-+]+@[\w\.\-]+\.\w+", text)
    if email:
        profile.email = email.group(0)
    phone = re.search(r"(\+\d{1,3}[\s-]?)?\d{10}", text.replace(" ", ""))
    if phone:
        profile.phone = phone.group(0)

    edu_lines = sections.get("education", [])
    if not edu_lines:
        sections["education"] = edu_lines = [ln for ln in lines if INSTITUTION_RE.search(ln)]
    _parse_education(sections, profile)

    interest_text = " ".join(sections.get("interests", []))
    if not interest_text:
        m = re.search(r"Research\s*Interests?\s*:?(.{0,300})", text, re.I | re.S)
        interest_text = m.group(1) if m else ""
    interest_text = re.split(r"Relevant\s*Coursework|Coursework|SCHOLASTIC|EDUCATION", interest_text, 1, re.I)[0]
    profile.research_interests = [
        s.strip(" .;") for s in re.split(r"[,;\n]", interest_text.replace(":", "")) if 3 < len(s.strip()) < 70
    ][:10]

    profile.projects = _extract_projects(sections.get("projects", []) + sections.get("experience", []))
    profile.achievements = [
        a.lstrip(BULLET_CHARS).strip()
        for a in sections.get("achievements", []) if len(a) > 30
    ][:5]

    profile.keywords = _extract_keywords(text)
    low = text.lower()
    profile.skills = [t for t in DOMAIN_TERMS if t in low][:30]
    return profile


def save_profile(profile: ResumeProfile, path: str | Path) -> None:
    Path(path).write_text(json.dumps(profile.to_dict(), indent=2), encoding="utf-8")
