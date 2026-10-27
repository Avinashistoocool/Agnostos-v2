"""Keep outreach on the student's field: physics / HEP / CERN-adjacent work.

A row is "in focus" when its research area, institution, department or recent
papers match FOCUS_KEYWORDS. Off-focus rows are left in the workbook but are
not drafted or sent while FOCUS is on.
"""
from __future__ import annotations

import re

DEFAULT_FOCUS = (
    "physic;particle;hadron;collider;lhc;cern;jet tagging;jets;quark;gluon;neutrino;"
    "detector;calorimet;trigger;cosmolog;astro;gravitation;gravitational wave;quantum;"
    "nuclear;plasma;fusion;lattice;qcd;higgs;boson;dark matter;accelerat;beam;"
    "condensed matter;many-body;string theory;field theory;high energy;high-energy;"
    "atlas;cms;lhcb;alice experiment;desy;fermilab;infn;in2p3;psi;gsi;cosmic ray"
)

# Strong signals that a row is NOT physics even if a keyword slips in.
OFF_FOCUS = (r"clinical|patient|cancer|tumou?r|medical|surgery|radiolog|pathology|cell image|"
             r"platelet|genom|protein|drug|vehicular|intrusion|software-defined|"
             r"photovoltaic|seism|gesture|pose and action|activity recognition|marketing")


def focus_pattern(spec: str) -> re.Pattern:
    words = [w.strip() for w in (spec or DEFAULT_FOCUS).split(";") if w.strip()]
    return re.compile("|".join(re.escape(w) for w in words), re.I)


def row_text(p) -> str:
    get = (lambda k: getattr(p, k, "")) if not isinstance(p, dict) else (lambda k: p.get(k, ""))
    parts = [get("research_area"), get("institution"), get("department"),
             " ".join(get("recent_works") or []) if not isinstance(p, dict) else
             str(p.get("recent_works") or ""),
             " ".join(get("openalex_concepts") or []) if not isinstance(p, dict) else ""]
    return " ".join(str(x or "") for x in parts)


def in_focus(p, spec: str = "") -> bool:
    text = row_text(p)
    hits = len(set(m.group(0).lower() for m in focus_pattern(spec).finditer(text)))
    if not hits:
        return False
    # A single weak hit next to clearly-other-field topics doesn't count.
    if hits < 2 and re.search(OFF_FOCUS, text, re.I):
        return False
    return True
