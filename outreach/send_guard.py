"""Send-time gate for cold first emails (send, resend, legacy).

Every check here is about WHO receives a cold email, never about its wording:

  * bounce blocklist   - any address that bounced on either account
                         (professors.xlsx Reply Status, send_log.csv, FAILURES.json)
  * no-cold-email list - groups/institutions that told us they never host ad-hoc
                         interns (output/no_cold_email.json)
  * mailbox type       - student, alumni and shared/role mailboxes
  * identity           - first initial + surname must both be in the address,
                         and the address must not name a different given name
  * email status       - "invalid" and "suspect" addresses are not cold-mailed
  * domain cap         - at most MAX_PER_DOMAIN_WEEK cold emails per institution
                         domain in any rolling 7 days (counted from send_log.csv)
"""
from __future__ import annotations

import csv
import json
import re
import unicodedata
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

COLD_MODES = {"live", "resend", "legacy"}
BOUNCED = "skipped: bounced before"
WRONG_PERSON = "skipped: wrong person before"

# Second-level labels that sit under a country code: ox.ac.uk, unimelb.edu.au.
_SLD = {"ac", "co", "edu", "gov", "org", "net", "or", "ne", "go", "uni", "res"}

_STUDENT_DOMAIN_RE = re.compile(
    r"(?:^|\.)(?:student|students|stud|studenti|studium|postgrad|pgr|alumni|alum|etu|etud"
    r"|campus|sms)\.", re.I)
_STUDENT_FULL_DOMAINS = {"g.harvard.edu", "college.harvard.edu", "alumni.harvard.edu",
                         "my.uu.nl", "student.uu.nl", "live.ucl.ac.uk"}
_SHARED_LOCAL_RE = re.compile(
    r"^(?:lehre|lst|office|sekretariat|secretariat|secretary|sekr|info|admin|contact|"
    r"enquiries|inquiries|studienberatung|dekanat|postmaster|webmaster|noreply|no-reply|"
    r"roma\d*)(?:[._\-]|$)", re.I)


def _fold(text: str) -> str:
    norm = unicodedata.normalize("NFKD", str(text or ""))
    return "".join(c for c in norm if not unicodedata.combining(c)).lower().strip()


def domain_of(email: str) -> str:
    return _fold(email).rpartition("@")[2]


def org_domain(email: str) -> str:
    """Institution-level domain: physics.ox.ac.uk -> ox.ac.uk, cfa.harvard.edu -> harvard.edu."""
    labels = [l for l in domain_of(email).split(".") if l]
    if len(labels) >= 3 and len(labels[-1]) == 2 and labels[-2] in _SLD:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


def mailbox_problem(email: str) -> str:
    """Why this is a student or shared mailbox, or ''."""
    email = _fold(email)
    if "@" not in email:
        return "no address"
    local, _, domain = email.rpartition("@")
    if domain in _STUDENT_FULL_DOMAINS or _STUDENT_DOMAIN_RE.search(domain + "."):
        return "student/alumni mailbox"
    # UCL/Imperial student style: f.wang.20@ucl.ac.uk, abc21@imperial.ac.uk
    if re.search(r"\.\d{2}$", local):
        return "numbered (student-style) mailbox"
    if re.fullmatch(r"[a-z]+\d{2}", local) and domain.endswith(("imperial.ac.uk", "ic.ac.uk")):
        return "numbered (student-style) mailbox"
    if _SHARED_LOCAL_RE.match(local):
        return "shared/role mailbox"
    if domain.split(".")[0] == "pec" or ".pec." in f".{domain}.":
        return "shared/role mailbox (PEC certified mail)"
    return ""


def _name_words(name: str) -> list[str]:
    from .verify import TITLE_RE
    clean = str(name or "")
    while True:
        stripped = TITLE_RE.sub("", clean)
        if stripped == clean:
            break
        clean = stripped
    clean = _fold(re.sub(r"\([^)]*\)", " ", clean))
    return [w for w in re.split(r"[^a-z]+", clean) if w]


def name_email_problem(name: str, email: str) -> str:
    """'' when the address holds this person's first initial AND surname."""
    from .verify import NAME_PARTICLES, given_name_conflict
    words = _name_words(name)
    if not words or "@" not in str(email):
        return "name or address missing"
    if given_name_conflict(name, email):
        return "address names a different given name"
    local = re.sub(r"[^a-z]", "", _fold(email).rpartition("@")[0])
    initial = words[0][0]
    full = [w for w in words if len(w) > 1]
    surnames = [w for w in full[1:] if w not in NAME_PARTICLES] or full[-1:]
    candidates = set(surnames)
    if len(surnames) > 1:
        candidates.add("".join(surnames))
    for s in sorted(candidates, key=len, reverse=True):
        if len(s) < 3:
            continue
        hit = s if s in local else (s[:6] if len(s) > 7 and s[:6] in local else "")
        if not hit:
            continue
        rest = local.replace(hit, " ", 1).split()
        rest = "".join(rest)
        if not rest:
            return ""  # surname-only addresses are standard for faculty (darve@stanford.edu)
        if rest[0] == initial or rest[-1] == initial or any(
                g in rest for g in full[:-1] if len(g) >= 3):
            return ""
        return "address does not start with the first initial"
    # University NetIDs: initials + digits (jc3633@cornell.edu, yy2664@columbia.edu)
    netid = re.fullmatch(r"([a-z]{2,3})\d{3,5}", re.sub(r"[^a-z0-9]", "", _fold(email).rpartition("@")[0]))
    if netid:
        inits = netid.group(1)
        if inits[0] == initial and inits[-1] == (surnames[-1][0] if surnames else ""):
            return ""
    return "surname not in address"


def _name_key(name: str) -> str:
    return " ".join(w for w in _name_words(name) if len(w) > 1)


class ColdGuard:
    """Decides, row by row, whether a cold email may go out."""

    def __init__(self, blocked: dict[str, str] | None = None,
                 no_cold: dict | None = None, domain_counts: Counter | None = None,
                 max_per_domain: int = 3, strict_names: bool = True):
        self.blocked = {k.lower(): v for k, v in (blocked or {}).items()}
        no_cold = no_cold or {}
        self.no_cold_emails = {}
        self.no_cold_names = {}
        for p in no_cold.get("people", []):
            reason = p.get("reason", "said they do not host interns")
            if p.get("email"):
                self.no_cold_emails[p["email"].strip().lower()] = reason
            if p.get("name"):
                self.no_cold_names[_name_key(p["name"])] = reason
        self.no_cold_domains = {d["domain"].strip().lower().lstrip("@."): d.get("reason", "")
                                for d in no_cold.get("domains", []) if d.get("domain")}
        self.domain_counts = Counter(domain_counts or {})
        self.max_per_domain = max_per_domain
        self.strict_names = strict_names

    # ---- construction from the operator's files ----
    @classmethod
    def from_settings(cls, settings, xlsx: str | Path | None = None) -> "ColdGuard":
        out = Path(settings.output_dir)
        blocked = load_blocklist(out, xlsx or getattr(settings, "target_xlsx", "") or None)
        no_cold_path = Path(getattr(settings, "no_cold_email_file", "") or out / "no_cold_email.json")
        return cls(blocked=blocked, no_cold=load_no_cold(no_cold_path),
                   domain_counts=domain_counts(out / "send_log.csv"),
                   max_per_domain=getattr(settings, "max_per_domain_week", 3),
                   strict_names=getattr(settings, "name_match_strict", True))

    # ---- checks ----
    def permanent_reason(self, row: dict, allow_unverified: bool = False) -> str:
        """Reasons that will not change by waiting (everything but the domain cap)."""
        email = str(row.get("email") or "").strip().lower()
        if not email:
            return "skipped: no address"
        if email in self.blocked:
            return self.blocked[email]
        why = self.no_cold_emails.get(email) or self.no_cold_names.get(_name_key(row.get("name", "")))
        if why:
            return f"skipped: no cold email ({why})"[:160]
        dom = domain_of(email)
        for d, reason in self.no_cold_domains.items():
            if dom == d or dom.endswith("." + d):
                return f"skipped: no cold email ({d}: {reason})"[:160]
        problem = mailbox_problem(email)
        if problem:
            return f"skipped: {problem}"
        status = str(row.get("email_status") or "").strip().lower()
        if status == "suspect" and not allow_unverified:
            return "skipped: suspect address"
        if str(row.get("review_flags") or "").upper().startswith("REJECTED DRAFT"):
            return "skipped: draft failed validation"
        if self.strict_names and row.get("name"):
            problem = name_email_problem(row.get("name", ""), email)
            if problem:
                return f"skipped: name/email mismatch ({problem})"
        return ""

    def domain_reason(self, row: dict) -> str:
        if self.max_per_domain <= 0:
            return ""
        dom = org_domain(row.get("email", ""))
        if self.domain_counts[dom] >= self.max_per_domain:
            return (f"skipped: domain cap ({self.domain_counts[dom]} cold emails to "
                    f"{dom} in 7 days, max {self.max_per_domain})")
        return ""

    def check(self, row: dict, allow_unverified: bool = False) -> str:
        return self.permanent_reason(row, allow_unverified) or self.domain_reason(row)

    def record(self, row: dict) -> None:
        """Count a cold email that just went out (or would, in a dry run)."""
        self.domain_counts[org_domain(row.get("email", ""))] += 1


# ---------------------------------------------------------------- loaders
def _header_map(ws, max_scan: int = 10) -> tuple[int, dict]:
    for r, row in enumerate(ws.iter_rows(min_row=1, max_row=max_scan, values_only=True), 1):
        names = {str(v).strip().lower(): i for i, v in enumerate(row) if v is not None}
        if "reply status" in names and ({"email address", "email"} & set(names)):
            return r, names
    return 0, {}


def bounced_from_workbook(path: str | Path) -> set[str]:
    path = Path(path)
    if not path.is_file():
        return set()
    from openpyxl import load_workbook
    out = set()
    wb = load_workbook(path, read_only=True, data_only=True)
    try:
        for ws in wb.worksheets:
            hdr, cols = _header_map(ws)
            if not hdr:
                continue
            ecol = cols.get("email address", cols.get("email"))
            rcol = cols["reply status"]
            for row in ws.iter_rows(min_row=hdr + 1, values_only=True):
                status = str(row[rcol] if rcol < len(row) and row[rcol] else "").strip().lower()
                email = str(row[ecol] if ecol < len(row) and row[ecol] else "").strip().lower()
                if email and status.startswith("bounced"):
                    out.add(email)
    finally:
        wb.close()
    return out


def bounced_from_log(path: str | Path) -> set[str]:
    path = Path(path)
    if not path.is_file():
        return set()
    out = set()
    with path.open(newline="", encoding="utf-8", errors="replace") as fh:
        for rec in csv.DictReader(fh):
            text = f"{rec.get('status', '')} {rec.get('detail', '')}".lower()
            if "bounce" in text and rec.get("email"):
                out.add(rec["email"].strip().lower())
    return out


def failures_from_json(path: str | Path) -> dict[str, str]:
    path = Path(path)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    items = data.get("failures", []) if isinstance(data, dict) else data
    out = {}
    for f in items or []:
        email = str(f.get("email") or "").strip().lower()
        if not email:
            continue
        kind = str(f.get("failure") or "").lower()
        cause = str(f.get("root_cause") or "").upper()
        if kind == "bounce" and cause != "DELAYED_NOT_FAILED":
            out[email] = BOUNCED
        elif kind == "wrong_person":
            out.setdefault(email, WRONG_PERSON)
    return out


def load_blocklist(output_dir: str | Path, xlsx: str | Path | None = None) -> dict[str, str]:
    """address -> skip reason, from every record of a bounce on either account."""
    out_dir = Path(output_dir)
    blocked = failures_from_json(out_dir / "FAILURES.json")
    for email in bounced_from_log(out_dir / "send_log.csv"):
        blocked[email] = BOUNCED
    workbook = Path(xlsx) if xlsx and str(xlsx) not in ("", ".") else out_dir / "professors.xlsx"
    for email in bounced_from_workbook(workbook):
        blocked[email] = BOUNCED
    return blocked


def load_no_cold(path: str | Path) -> dict:
    path = Path(path)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def domain_counts(log_path: str | Path, days: int = 7, now: datetime | None = None) -> Counter:
    """Cold emails (live, resend, legacy) per institution domain in the last `days` days."""
    log_path = Path(log_path)
    counts = Counter()
    if not log_path.is_file():
        return counts
    cutoff = (now or datetime.now()) - timedelta(days=days)
    with log_path.open(newline="", encoding="utf-8", errors="replace") as fh:
        for rec in csv.DictReader(fh):
            if rec.get("mode") not in COLD_MODES or rec.get("status") != "sent":
                continue
            try:
                when = datetime.strptime(str(rec.get("time", ""))[:19], "%Y-%m-%d %H:%M:%S")
            except ValueError:
                continue
            if when >= cutoff and rec.get("email"):
                counts[org_domain(rec["email"])] += 1
    return counts
