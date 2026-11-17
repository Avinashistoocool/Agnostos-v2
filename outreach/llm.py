"""Token-optimized LLM evaluation + email drafting.

Works against any OpenAI-compatible endpoint (OpenAI, Groq, or a proxy) and
negotiates capabilities at runtime, because gateways differ in what they accept.

Design for cost control:
  * A single call per professor returns BOTH the probability score and the email draft.
  * Shared instructions sit in a stable system-prompt prefix, so providers with
    automatic prompt caching discount it on every call after the first.
  * Per-professor user messages carry only the minimal context block.
  * Structured Outputs are used when supported, with graceful downgrade to
    json_object and then to prompt-only JSON.
  * Estimation gate runs before any paid call.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass

from pathlib import Path

from .config import CACHE_MIN_PREFIX_TOKENS, Settings

# gpt-5 / o-series replies include hidden reasoning tokens (~1-2k here).
REASONING_MIN_TOKENS = 4000
MAX_TOKEN_BUDGET = 16000
from .humanize import REWRITE_SYSTEM, build_rewrite_request, deslop, has_hard_claims
from .humanize import (allowed_links, allowed_metrics, confirmed_facts_text,
                       fix_unverified_links, strip_unverified_numbers, validate_first_email)
from .humanize import score as ai_score
from .models import Professor
from .resume_parser import ResumeProfile
from .tls import http_client

SYSTEM_TEMPLATE = """You are an expert academic outreach strategist advising a student seeking a {position} in {geography}.

APPLICANT PROFILE (background only; quote facts and numbers only from CONFIRMED FACTS below)
{profile}

Availability: {availability}
Funding (context for scoring only; NEVER mention money in a first email): {funding}
For each professor given, do two things:

1. SCORE the realistic probability (1-100) that this professor would accept this student for a {position}. Calibrate honestly and use the full range:
   - 80-100: near-perfect subfield overlap, funded route exists, group known to take interns
   - 60-79: strong overlap, plausible funding, realistic
   - 40-59: adjacent field or unclear funding
   - 20-39: weak overlap or strong competition
   - 1-19: wrong field, no route, or unrealistic
   Penalize: generic topic overlap, no funding route, very senior/large groups, missed deadlines.
   Reward: specific technical overlap with the student's actual projects, named funding programmes, explicit eligibility for non-EU undergraduates.

2. DRAFT a cold FIRST email to that professor.

CONFIRMED FACTS (user-verified; the only facts and numbers you may state about the student)
{confirmed_facts}

HONESTY AND FRAMING — THIS MATTERS MOST
The student is a second-year undergraduate. Be exactly as strong as the confirmed facts, no stronger and no weaker:
- Numbers: you may quote numbers from CONFIRMED FACTS verbatim. Never invent, round or alter a number, and never quote any other number (no GPA, no ranks, no percentages that are not listed).
- Lead with the confirmed result most relevant to THIS professor's field (CONFIRMED FACTS groups results by field and says which to lead with). Use only facts relevant to their field; one project, not a list.
- Never compare against other models, never claim novelty, never say "outperformed", "state of the art" or "beat".
- Never describe the work as "a small subset", "basic", "mostly to understand", "just to see", and never say you had trouble following, got stuck on or didn't follow their work.
- Nothing in the email should embarrass the student if the professor asked them to defend it in a five-minute conversation.

VOICE — WRITE LIKE A PERSON, NOT A LANGUAGE MODEL
- Vary sentence length. Mix a long sentence with a short one.
- Use plain words: "used" not "utilised", "so" not "thus", "about" not "regarding".
- Contractions are fine: I'm, I've, it's, don't.
- BANNED phrases: "I am writing to", "I am reaching out", "delve", "leverage", "utilise", "robust", "cutting-edge", "passionate about", "align with", "resonates", "moreover", "furthermore", "in conclusion", "I would be thrilled", "invaluable", "testament to", "deep dive", "landscape", "realm", "pivotal", "underscore", "showcase", "seamless", "comprehensive", "it is worth noting", "I read your", "caught my eye", "wrap my head around", "get a feel for", "Thanks for reading", "mostly".
- No three-item lists ("X, Y, and Z").
- Do not restate the professor's work back to them as a compliment.

EMAIL RULES
- 110-150 words in the body, in exactly 4 short paragraphs separated by blank lines, after ONE salutation line ("Dear Prof. <Surname>,"; "Dr." if the context says they are not a professor). Never write a second greeting line.
- Paragraph 1 (who + proof, 1-2 sentences): {intro} plus the single strongest confirmed result for their field, with its code link.
- Paragraph 2 (why them, 1-2 sentences): name ONE supplied publication, method or topic of theirs (never invent a title) and say in ONE sentence how the student's work connects to it, as something the student wants to work on. A statement, not a confession of confusion.
- Paragraph 3 (the ask, one sentence, the only question mark in the email): "Could I spend 8-10 weeks in summer 2027 working on <a specific thing in their group>?" then the fallback "If that isn't possible, could you point me to someone who might be a good fit?" may follow as a clause or short sentence.
- Paragraph 4: {cv_paragraph}a short sign-off with the first name only; the signature block is appended automatically.
- NEVER use the words "capacity", "space for", "room for" or "any chance". Never ask "May I send my CV" and never say the CV is attached.
- MONEY: a first email never mentions funding, stipends, salary, payment, costs, travel, visa, unpaid work or self-funding. Not even to say the student needs funding. Funding is discussed only after the professor replies.
- PROGRAMME: if the context has a "Likely funded route" naming a specific programme (e.g. CERN Summer Student, Summer@EPFL, Google Student Researcher), you may say once that the student would apply through that programme. Use only the programme's name; drop anything in brackets and any word about pay, stipend or money. Skip it if the route is generic ("university group", "ask host").
- Plain text, no markdown, no em dashes, no bullet points. British/neutral English.
- Subject: "<their topic> / <student's matching result>{subject_tag}", under 70 characters, e.g. "Belle II GNN background sim / graph-network jet tagger{subject_tag}". Never use "inquiry", "enquiry", "internship", "opportunity" or "Application".

OUTPUT
Return a JSON object with exactly these fields: probability, justification, subject, body.
Return only that JSON object, with no prose and no code fences."""

RESPONSE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["probability", "justification", "subject", "body"],
    "properties": {
        "probability": {
            "type": "integer",
            "description": "Realistic acceptance probability from 1 to 100.",
        },
        "justification": {
            "type": "string",
            "description": "Two to three sentences citing specific evidence for the score.",
        },
        "subject": {
            "type": "string",
            "description": "Email subject line, under 70 characters.",
        },
        "body": {
            "type": "string",
            "description": ("Email body, 110-150 words. Plain text starting with ONE "
                            "salutation line, then 4 short paragraphs separated by "
                            "blank lines, then a sign-off. Use \\n for line breaks."),
        },
    },
}

USER_TEMPLATE = """Evaluate and draft for this professor.

{context}"""

REDRAFT_NOTE = """

Your previous draft was REJECTED for: {problems}.
Previous subject: {subject}
Previous body:
{body}

Write a new draft that follows every EMAIL RULE and fixes each problem above."""


GREETING_RE = re.compile(r"^(dear|hello|hi|good (morning|afternoon)|sehr geehrte)", re.I)
SECOND_GREETING_RE = re.compile(
    r"^\s*(?:(?:dear|hello|hi|good (?:morning|afternoon)|sehr geehrte)\b[^\n]{0,60}"
    r"|(?:prof\.?|professor|dr\.?)\s+[^\s,]+(?:\s+[^\s,]+)?\s*[,:!])\s*$", re.I)
TITLE_PREFIX_RE = re.compile(r"^(Prof\.?|Professor|Dr\.?|PD|Mr\.?|Ms\.?|Mrs\.?)\s+", re.I)


def _salutation(professor_name: str) -> str:
    bare = TITLE_PREFIX_RE.sub("", professor_name).strip()
    while TITLE_PREFIX_RE.match(bare):  # e.g. "Prof. Dr. Anna Schmidt"
        bare = TITLE_PREFIX_RE.sub("", bare).strip()
    if not bare:
        return "Dear Professor,"
    surname = bare.split()[-1]
    title = "Prof." if re.match(r"\s*(Prof|Professor)", professor_name, re.I) else "Dr."
    return f"Dear {title} {surname},"


def _split_paragraphs(text: str, target_chunks: int = 3) -> str:
    sentences = [s for s in re.split(r"(?<=[.?!])\s+", text.strip()) if s]
    if len(sentences) < 4:
        return text.strip()
    per = max(2, -(-len(sentences) // target_chunks))
    chunks = [" ".join(sentences[i:i + per]) for i in range(0, len(sentences), per)]
    return "\n\n".join(c for c in chunks if c)


def tidy_body(body: str, professor_name: str) -> str:
    """Repair the two formatting faults models still produce occasionally:
    a missing salutation, and paragraphs run together into one block."""
    text = body.strip().replace("\\n", "\n").replace("\r\n", "\n")
    text = "\n".join(ln.strip() for ln in text.split("\n")).strip()

    greeting = ""
    if GREETING_RE.match(text):
        greeting, _, text = text.partition("\n")
        text = text.strip()
    else:
        greeting = _salutation(professor_name)
    # Models sometimes add their own salutation under the one above.
    while True:
        first, _, rest = text.partition("\n")
        if first and SECOND_GREETING_RE.match(first) and rest.strip():
            text = rest.strip()
        else:
            break

    # Peel off a trailing sign-off so it is never merged into a paragraph.
    signoff = ""
    parts = text.rsplit("\n\n", 1)
    if len(parts) == 2 and len(parts[1]) < 80:
        text, signoff = parts[0].strip(), parts[1].strip()

    if "\n\n" not in text:
        text = _split_paragraphs(text)

    out = f"{greeting}\n\n{text}"
    if signoff:
        out += f"\n\n{signoff}"
    return out


@dataclass
class Estimate:
    n_calls: int
    system_tokens: int
    input_tokens: int
    output_tokens: int
    cached_input_tokens: int
    cost_usd: float
    model: str
    cache_eligible: bool = True
    free_tier: bool = False

    def render(self) -> str:
        cache_line = (
            f"   of which cached   : ~{self.cached_input_tokens:,} (billed at the cached rate)"
            if self.cache_eligible else
            f"   cache             : inactive (prompt prefix under "
            f"{CACHE_MIN_PREFIX_TOKENS:,} tokens)"
        )
        cost_line = (" ESTIMATED COST       : $0.0000 (provider free tier)"
                     if self.free_tier else
                     f" ESTIMATED COST       : ${self.cost_usd:.4f}")
        lines = [
            "",
            "=" * 62,
            " TOKEN & COST ESTIMATE (pre-flight)",
            "=" * 62,
            f" Model                : {self.model}",
            f" Professors to call   : {self.n_calls}",
            f" System prompt        : ~{self.system_tokens:,} tokens (identical prefix each call)",
            f" Input tokens  (total): ~{self.input_tokens:,}",
            cache_line,
            f" Output tokens (total): ~{self.output_tokens:,}",
            cost_line,
            "=" * 62,
        ]
        return "\n".join(lines)


def estimate_tokens(text: str) -> int:
    """Approximate OpenAI tokenization: ~4 chars/token for English prose."""
    if not text:
        return 0
    return max(1, int(len(text) / 4) + text.count("\n"))


def _intro_sentence(settings, profile: ResumeProfile) -> str:
    """Opening self-introduction: STUDENT_INTRO from .env, else built from the resume."""
    intro = str(getattr(settings, "student_intro", "") or "").strip()
    if intro:
        return f'"{intro}"'
    degree = (profile.degree or "").strip()
    inst = (profile.institution or "").strip()
    if degree and inst:
        return f'one sentence saying the student is a {degree} student at {inst}'
    return "one sentence saying who the student is (year, programme, institution from the profile)"


class LLMEvaluator:
    def __init__(self, settings: Settings, profile: ResumeProfile):
        self.settings = settings
        self.profile = profile
        self._client = None
        self.system_prompt = SYSTEM_TEMPLATE.format(
            position=settings.position,
            geography=settings.geography,
            profile=re.sub(r",?\s*GPA[^),\n]*", "", profile.summary_block()),
            availability=settings.availability,
            funding=settings.funding_stance,
            confirmed_facts=confirmed_facts_text(
                getattr(settings, "confirmed_facts_file", "")
                or Path(settings.output_dir) / "confirmed_facts.md"),
            intro=_intro_sentence(settings, profile),
            cv_paragraph=(f'"My CV is linked here: {cv_url}" then ' if (cv_url := str(
                getattr(settings, "cv_url", "") or "").strip()) else ""),
            subject_tag=(f" ({tag})" if (tag := str(
                getattr(settings, "subject_tag", "") or "").strip()) else ""),
        )
        self.allowed_numbers = allowed_metrics(confirmed_facts_text(
            getattr(settings, "confirmed_facts_file", "")
            or Path(settings.output_dir) / "confirmed_facts.md"))
        self.allowed_links = allowed_links(confirmed_facts_text(
            getattr(settings, "confirmed_facts_file", "")
            or Path(settings.output_dir) / "confirmed_facts.md"))
        self.usage = {"input": 0, "output": 0, "cached": 0, "calls": 0, "rewrites": 0}
        # Capabilities are optimistic, then downgraded on the first rejection.
        self.caps = {
            "json_schema": True,
            "json_object": True,
            "max_completion_tokens": True,
            "temperature": True,
        }
        # Reasoning models spend hidden tokens before writing anything; a cap
        # sized for the visible JSON alone yields empty, truncated replies.
        self.token_floor = settings.max_output_tokens

    def _budget(self, model: str) -> int:
        floor = self.token_floor
        if self._is_reasoning(model):
            floor = max(floor, REASONING_MIN_TOKENS)
        return floor

    # --- client ---
    @property
    def client(self):
        if self._client is None:
            self.settings.require_api_key()
            from openai import OpenAI
            kwargs = {"api_key": self.settings.api_key}
            client = http_client()
            if client is not None:
                kwargs["http_client"] = client
            if self.settings.base_url:
                kwargs["base_url"] = self.settings.base_url
            self._client = OpenAI(**kwargs)
        return self._client

    # --- estimation ---
    def estimate(self, professors: list[Professor], model: str | None = None) -> Estimate:
        model = model or self.settings.draft_model
        sys_tokens = estimate_tokens(self.system_prompt)
        per_user = [estimate_tokens(USER_TEMPLATE.format(context=p.context_block()))
                    for p in professors]
        n = len(professors)
        in_price, cached_price, out_price = self.settings.price(model)

        # Prompt caching is automatic, but only for sufficiently long prefixes,
        # only from the second call onwards, and only on some providers.
        cache_eligible = (self.settings.supports_prompt_cache
                          and sys_tokens >= CACHE_MIN_PREFIX_TOKENS)
        if cache_eligible:
            cached = sys_tokens * max(n - 1, 0)
            fresh = sys_tokens + sum(per_user)
        else:
            cached = 0
            fresh = sys_tokens * n + sum(per_user)
        out = n * int(self._budget(model) * 0.55)
        if self.settings.humanize_rewrite:
            # Roughly a third of drafts trip the humanizer and get rewritten.
            rewrites = max(1, n // 3)
            fresh += rewrites * (estimate_tokens(REWRITE_SYSTEM) + 260)
            out += rewrites * 230

        cost = (fresh / 1e6 * in_price
                + cached / 1e6 * cached_price
                + out / 1e6 * out_price)
        return Estimate(n, sys_tokens, fresh + cached, out, cached,
                        round(cost, 4), model, cache_eligible,
                        free_tier=self.settings.is_free_tier)

    # --- parsing ---
    @staticmethod
    def _parse(text: str) -> dict:
        text = text.strip()
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text).strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        match = re.search(r"\{.*\}", text, re.S)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass
        raise ValueError(f"Unparseable LLM response: {text[:200]}")

    # --- single call ---
    @staticmethod
    def _is_reasoning(model: str) -> bool:
        name = (model or "").rpartition("/")[2]
        return name.startswith("o") or name.startswith("gpt-5")

    def _supports_temperature(self, model: str) -> bool:
        # Reasoning models (o-series, gpt-5) reject an explicit temperature.
        return not self._is_reasoning(model)

    def _build_request(self, model: str, message: str) -> dict:
        """Assemble a request using only the fields this endpoint has accepted.

        Gateways and proxies vary: some reject `max_completion_tokens`, some
        reject `response_format` entirely. Unsupported fields are learned once
        (see `_downgrade`) and then omitted for the rest of the run.
        """
        kwargs = {
            "model": model,
            "messages": [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": message},
            ],
        }
        if self.caps["max_completion_tokens"]:
            kwargs["max_completion_tokens"] = self._budget(model)
        else:
            kwargs["max_tokens"] = self._budget(model)

        if self.caps["json_schema"]:
            kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "professor_evaluation", "strict": True,
                                "schema": RESPONSE_SCHEMA},
            }
        elif self.caps["json_object"]:
            kwargs["response_format"] = {"type": "json_object"}

        if self.caps["temperature"] and self._supports_temperature(model):
            kwargs["temperature"] = 0.4
        return kwargs

    def _downgrade(self) -> str | None:
        """Turn off the most likely unsupported capability. Returns what changed."""
        for cap, label in (
            ("json_schema", "structured outputs (json_schema)"),
            ("json_object", "JSON response_format"),
            ("max_completion_tokens", "max_completion_tokens (using max_tokens)"),
            ("temperature", "temperature"),
        ):
            if self.caps[cap]:
                self.caps[cap] = False
                return label
        return None

    def evaluate_one(self, prof: Professor, model: str | None = None,
                     max_retries: int = 3) -> Professor:
        model = model or self.settings.draft_model
        message = base_message = USER_TEMPLATE.format(context=prof.context_block())
        redrafted = False

        last_error = ""
        attempt = 0
        # Downgrades do not consume a retry: they are negotiation, not failure.
        while attempt < max_retries:
            try:
                resp = self.client.chat.completions.create(
                    **self._build_request(model, message))
                choice = resp.choices[0]
                if choice.finish_reason == "length":
                    budget = self._budget(model)
                    if budget < MAX_TOKEN_BUDGET:
                        # Learned once per run, like the capability downgrades.
                        self.token_floor = min(budget * 2, MAX_TOKEN_BUDGET)
                        print(f"  ~ reply truncated; raising output budget to "
                              f"{self.token_floor} tokens and retrying")
                        continue
                    raise ValueError("response truncated; raise MAX_OUTPUT_TOKENS")
                data = self._parse(choice.message.content or "")

                u = resp.usage
                cached = 0
                details = getattr(u, "prompt_tokens_details", None)
                if details is not None:
                    cached = getattr(details, "cached_tokens", 0) or 0
                self.usage["input"] += (getattr(u, "prompt_tokens", 0) or 0) - cached
                self.usage["cached"] += cached
                self.usage["output"] += getattr(u, "completion_tokens", 0) or 0
                self.usage["calls"] += 1

                prob = int(float(data.get("probability", 0)))
                prof.probability = max(1, min(100, prob))
                prof.justification = str(data.get("justification", "")).strip()
                prof.email_subject = str(data.get("subject", "")).strip()
                prof.email_body = tidy_body(str(data.get("body", "")), prof.name)
                self._humanize(prof, model)
                problems = self.validate(prof)
                if problems and not redrafted:
                    # One redraft with the reasons; a second failure is flagged instead.
                    redrafted = True
                    message = base_message + REDRAFT_NOTE.format(
                        problems="; ".join(problems), subject=prof.email_subject,
                        body=prof.email_body)
                    continue
                if problems:
                    prof.ai_flags = ("REJECTED DRAFT: " + "; ".join(problems) + " | "
                                     + prof.ai_flags).strip(" |")
                prof.llm_status = f"ok ({model})" + (" +redraft" if redrafted else "")
                return prof
            except Exception as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                name = type(exc).__name__
                if name == "BadRequestError":
                    dropped = self._downgrade()
                    if dropped:
                        print(f"  ~ endpoint rejected {dropped}; retrying without it")
                        continue
                if name in ("AuthenticationError", "PermissionDeniedError",
                            "NotFoundError", "BadRequestError", "RuntimeError"):
                    break
                attempt += 1
                if attempt < max_retries:
                    time.sleep(2 ** attempt)
        prof.llm_status = f"failed: {last_error[:180]}"
        return prof

    # --- humanizing layer ---
    def _humanize(self, prof: Professor, model: str) -> None:
        """Free deterministic cleanup, then an LLM rewrite only if still needed."""
        body = deslop(prof.email_body)
        penalty, reasons = ai_score(body)
        needs_rewrite = (penalty >= self.settings.humanize_threshold
                         or has_hard_claims(body))

        if needs_rewrite and self.settings.humanize_rewrite:
            rewritten = self._rewrite(body, model)
            if rewritten:
                candidate = deslop(tidy_body(rewritten, prof.name))
                new_penalty, new_reasons = ai_score(candidate)
                # Keep the rewrite only if it is genuinely less robotic.
                if new_penalty <= penalty:
                    body, penalty, reasons = candidate, new_penalty, new_reasons
                    prof.llm_status += " +rewrite"

        if not self.settings.can_self_fund in {"1", "true", "yes", "y", "on"}:
            # Hard guard: the student can't pay their own way, whatever the model wrote.
            from .humanize import offers_self_funding, strip_self_funding
            if offers_self_funding(body):
                body = strip_self_funding(body)
                reasons = list(reasons) + ["removed self-funding offer"]
        # Only numbers from the confirmed facts may stay.
        body, removed = strip_unverified_numbers(body, self.allowed_numbers)
        if removed:
            reasons = list(reasons) + ["removed unverified number(s): " + ", ".join(removed[:3])]
        body, bad_links = fix_unverified_links(body, self.allowed_links)
        if bad_links:
            reasons = list(reasons) + ["replaced unverified link(s): " + ", ".join(bad_links[:2])]
        body = re.sub(r"(?m)^(My CV is linked here:[^\n]*)\n(?=\S)", r"\1\n\n", body)
        prof.email_body = body
        prof.ai_score = penalty
        prof.ai_flags = "; ".join(reasons)
        if has_hard_claims(body):
            prof.ai_flags = ("UNVERIFIED CLAIM - review before sending; "
                             + prof.ai_flags).strip("; ")

    def validate(self, prof: Professor) -> list[str]:
        """Rules a cold first email must pass (see humanize.validate_first_email)."""
        problems = validate_first_email(prof.email_subject, prof.email_body,
                                        allowed=self.allowed_numbers)
        if len(prof.email_subject or "") > 70:
            problems.append("subject over 70 characters")
        return problems

    def _rewrite(self, body: str, model: str) -> str:
        kwargs = {
            "model": model,
            "messages": build_rewrite_request(body),
        }
        if self.caps["max_completion_tokens"]:
            kwargs["max_completion_tokens"] = self._budget(model)
        else:
            kwargs["max_tokens"] = self._budget(model)
        if self.caps["temperature"] and self._supports_temperature(model):
            kwargs["temperature"] = 0.8  # higher temperature reads less uniform
        try:
            resp = self.client.chat.completions.create(**kwargs)
            u = resp.usage
            cached = getattr(getattr(u, "prompt_tokens_details", None), "cached_tokens", 0) or 0
            self.usage["input"] += (getattr(u, "prompt_tokens", 0) or 0) - cached
            self.usage["cached"] += cached
            self.usage["output"] += getattr(u, "completion_tokens", 0) or 0
            self.usage["rewrites"] += 1
            text = (resp.choices[0].message.content or "").strip()
            return re.sub(r"^```\w*\s*|\s*```$", "", text).strip('"\n ')
        except Exception:
            return ""  # a failed rewrite is never fatal; the deslopped body stands

    def chat_json(self, system: str, user: str, model: str | None = None,
                  max_retries: int = 3) -> dict:
        """One JSON-returning call with the same capability negotiation as drafting."""
        model = model or self.settings.draft_model
        attempt, last_error = 0, ""
        while attempt < max_retries:
            kwargs = {"model": model,
                      "messages": [{"role": "system", "content": system},
                                   {"role": "user", "content": user}]}
            key = "max_completion_tokens" if self.caps["max_completion_tokens"] else "max_tokens"
            kwargs[key] = self._budget(model)
            if self.caps["json_object"]:
                kwargs["response_format"] = {"type": "json_object"}
            if self.caps["temperature"] and self._supports_temperature(model):
                kwargs["temperature"] = 0.5
            try:
                resp = self.client.chat.completions.create(**kwargs)
                choice = resp.choices[0]
                if choice.finish_reason == "length" and self._budget(model) < MAX_TOKEN_BUDGET:
                    self.token_floor = min(self._budget(model) * 2, MAX_TOKEN_BUDGET)
                    continue
                u = resp.usage
                cached = getattr(getattr(u, "prompt_tokens_details", None), "cached_tokens", 0) or 0
                self.usage["input"] += (getattr(u, "prompt_tokens", 0) or 0) - cached
                self.usage["cached"] += cached
                self.usage["output"] += getattr(u, "completion_tokens", 0) or 0
                self.usage["calls"] += 1
                return self._parse(choice.message.content or "")
            except Exception as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                if type(exc).__name__ == "BadRequestError":
                    self.caps["json_schema"] = False
                    for cap in ("json_object", "max_completion_tokens", "temperature"):
                        if self.caps[cap]:
                            self.caps[cap] = False
                            break
                    else:
                        break
                    continue
                attempt += 1
                if attempt < max_retries:
                    time.sleep(2 ** attempt)
        raise RuntimeError(last_error or "LLM call failed")

    def evaluate_all(self, professors: list[Professor], model: str | None = None,
                     progress=None, budget_usd: float | None = None) -> list[Professor]:
        model = model or self.settings.draft_model
        consecutive_failures = 0
        for i, prof in enumerate(professors, 1):
            if budget_usd is not None and self.actual_cost(model) >= budget_usd:
                prof.llm_status = "skipped: budget exhausted"
                continue
            self.evaluate_one(prof, model=model)
            if progress:
                progress(i, len(professors), prof)
            ok = prof.llm_status.startswith("ok")
            consecutive_failures = 0 if ok else consecutive_failures + 1
            if consecutive_failures >= 3:
                for rest in professors[i:]:
                    rest.llm_status = "skipped: aborted after repeated failures"
                print("  ! Three consecutive failures; aborting to avoid wasted spend.")
                break
        return professors

    def actual_cost(self, model: str | None = None) -> float:
        model = model or self.settings.draft_model
        in_price, cached_price, out_price = self.settings.price(model)
        u = self.usage
        return (u["input"] / 1e6 * in_price
                + u["cached"] / 1e6 * cached_price
                + u["output"] / 1e6 * out_price)

    def usage_report(self, model: str | None = None) -> str:
        u = self.usage
        extra = f" | rewrites {u['rewrites']}" if u.get("rewrites") else ""
        cost = ("$0.0000 (free tier)" if self.settings.is_free_tier
                else f"${self.actual_cost(model):.4f}")
        return (
            f"LLM calls: {u['calls']}{extra} | input {u['input']:,} | "
            f"cached {u['cached']:,} | output {u['output']:,} | "
            f"actual cost {cost}"
        )


def confirm_gate(estimate: Estimate, budget_usd: float, assume_yes: bool = False) -> bool:
    """Display the estimate and require explicit [Y/N] confirmation."""
    print(estimate.render())
    if estimate.free_tier:
        print(" This provider's free tier covers the run; nothing will be billed.")
    elif estimate.cost_usd > budget_usd:
        print(f" !! Estimate ${estimate.cost_usd:.4f} EXCEEDS your budget cap of ${budget_usd:.2f}.")
        print("    Lower --max-professors, raise BUDGET_USD, or switch to "
              "--provider groq (free).")
    if assume_yes:
        print(" --yes supplied; proceeding without prompt.\n")
        return True
    try:
        answer = input(" Proceed with the LLM calls? [Y/N]: ").strip().lower()
    except EOFError:
        return False
    return answer in {"y", "yes"}


def list_models(settings: Settings) -> list[str]:
    """Live model list from whichever provider is configured."""
    settings.require_api_key()
    from openai import OpenAI
    kwargs = {"api_key": settings.api_key}
    client = http_client()
    if client is not None:
        kwargs["http_client"] = client
    if settings.base_url:
        kwargs["base_url"] = settings.base_url
    return sorted(m.id for m in OpenAI(**kwargs).models.list().data)
