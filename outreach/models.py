"""Professor target record shared by both modes."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict


@dataclass
class Professor:
    name: str = ""
    email: str = ""
    institution: str = ""
    country: str = ""
    department: str = ""
    research_area: str = ""
    profile_url: str = ""
    notes: str = ""

    # Existing-sheet metadata (Mode B)
    rank: str = ""
    fit_note: str = ""
    funding_status: str = ""
    eligibility: str = ""
    application_route: str = ""
    deadline: str = ""
    prior_probability: str = ""

    # Enrichment
    recent_works: list[str] = field(default_factory=list)
    openalex_id: str = ""
    openalex_concepts: list[str] = field(default_factory=list)

    # Pipeline results
    local_score: float = 0.0
    matched_terms: list[str] = field(default_factory=list)
    probability: int = 0
    justification: str = ""
    email_subject: str = ""
    email_body: str = ""
    llm_status: str = ""
    ai_score: int = 0
    ai_flags: str = ""

    # Bookkeeping
    source_sheet: str = ""
    source_row: int = 0

    def to_dict(self) -> dict:
        return asdict(self)

    def match_text(self) -> str:
        """Everything a local matcher should look at."""
        return " ".join([
            self.research_area, self.department, self.notes, self.fit_note,
            " ".join(self.recent_works), " ".join(self.openalex_concepts),
        ]).lower()

    def personal_text(self) -> str:
        """Only signal specific to this professor.

        Excludes `department`, which in Mode A is a constant inherited from the
        source entry and would otherwise give every scraped person the same score.
        """
        return " ".join([
            self.research_area, self.notes, self.fit_note,
            " ".join(self.recent_works), " ".join(self.openalex_concepts),
        ]).lower()

    def context_block(self, max_chars: int = 900) -> str:
        """Minimal, token-cheap context sent to the LLM."""
        lines = [
            f"Professor: {self.name}",
            f"Institution: {self.institution}" + (f", {self.country}" if self.country else ""),
        ]
        if self.department:
            lines.append(f"Department/Group: {self.department}")
        if self.research_area:
            lines.append(f"Research area: {self.research_area}")
        if self.recent_works:
            lines.append("Recent publications: " + "; ".join(self.recent_works[:4]))
        if self.openalex_concepts:
            lines.append("Topics: " + ", ".join(self.openalex_concepts[:8]))
        if self.funding_status:
            lines.append(f"Funding: {self.funding_status}")
        if self.eligibility:
            lines.append(f"Eligibility: {self.eligibility}")
        if self.application_route:
            lines.append(f"Application route: {self.application_route}")
        if self.deadline:
            lines.append(f"Deadline: {self.deadline}")
        if self.matched_terms:
            lines.append("Local keyword overlap: " + ", ".join(self.matched_terms[:10]))
        return "\n".join(lines)[:max_chars]
